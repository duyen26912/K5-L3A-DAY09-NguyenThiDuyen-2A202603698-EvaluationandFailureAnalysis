"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)
    Also: duplicated (item, seed) rows, evaluator failures on a green run, and headline metrics
    that do not follow from the report's own rows (hand-edited numbers)."""
    problems: list[str] = []
    rows, brows = pr.get("rows") or [], base.get("rows") or []
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. headline numbers must be finite
    for name, rep in (("PR", pr), ("baseline", base)):
        for k, v in (rep.get("metrics") or {}).items():
            if _num_bad(v):
                problems.append(f"{name} metric {k} is {v} (crashed grader or hand edit)")

    # 2. graders must not have crashed, on a red OR a green run
    if pr.get("evaluator_failures"):
        problems.append(f"PR has {len(pr['evaluator_failures'])} evaluator failure(s): {pr['evaluator_failures'][0]}")
    if base.get("evaluator_failures"):
        problems.append(f"baseline has {len(base['evaluator_failures'])} evaluator failure(s)")

    # 3. coverage: items x seeds rows, no duplicates, same (item, seed) set as the baseline
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"PR has {len(rows)} rows, manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"PR has duplicated (item, seed) rows: {dups[:3]}")
    bkeys = {(r.get("item_id"), r.get("seed")) for r in brows}
    if set(keys) != bkeys:
        miss, extra = sorted(bkeys - set(keys), key=str), sorted(set(keys) - bkeys, key=str)
        problems.append(f"(item, seed) set differs from baseline: {len(miss)} missing {miss[:3]}, "
                        f"{len(extra)} extra {extra[:3]}")
    if list(man.get("seeds") or []) != list(bman.get("seeds") or []):
        problems.append(f"seeds {man.get('seeds')} differ from baseline {bman.get('seeds')}")
    if man.get("items") != bman.get("items"):
        problems.append(f"items {man.get('items')} differ from baseline {bman.get('items')}")

    # 4. a crashed grader must not become "missing" and silently drop out of the mean
    graded = _graded(spec)
    for m in graded:
        if not any(m in r for r in rows) and not any(m in r for r in brows):
            continue                      # metric not produced by either run (e.g. a synthetic report)
        holes = [f"{r.get('item_id')}@{r.get('seed')}" for r in rows if r.get(m) is None]
        if holes:
            problems.append(f"metric {m} is None/missing on {len(holes)} row(s), e.g. {holes[0]}")

    # 5. headline metrics must follow from the rows (hand-edited reports)
    reported = pr.get("metrics") or {}
    derived = _recompute(rows, [m for m in graded if any(m in r for r in rows)], spec.get("pass_k"))
    for k, v in derived.items():
        got = reported.get(k)
        if k in reported and v is not None and not _num_bad(got):
            if got is None or abs(float(got) - float(v)) > 1e-3:
                problems.append(f"metric {k} reported {got} but the rows give {v}")

    # 6. an item's slice tags may not change (relabelling hides a slice regression)
    btags = {r.get("item_id"): sorted(r.get("slices") or []) for r in brows}
    moved = sorted({r.get("item_id") for r in rows
                    if r.get("item_id") in btags and sorted(r.get("slices") or []) != btags[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags differ from baseline on {moved[:3]}")

    # 7. ratchet: on the same eval-set version thresholds only get stricter
    if base_spec is not None:
        problems += ratchet_check(spec, base_spec)
    return problems


SAFETY_COUNTS = {"secret_leak", "approval_bypass"}   # aggregated as a count, not a mean


def _num_bad(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _graded(spec: dict) -> list[str]:
    from lab9.graders import GRADERS
    return [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]


def _recompute(rows: list[dict], metric_ids: list[str], k_values) -> dict:
    """What the headline metrics MUST be given the rows (same rules as lab9.eval.aggregate)."""
    out: dict = {}
    for m in metric_ids:
        vals = [r[m] for r in rows if r.get(m) is not None]
        if m in SAFETY_COUNTS:
            out[m] = sum(bool(v) for v in vals)
        else:
            out[m] = round(sum(bool(v) for v in vals) / len(vals), 4) if vals else None
    by_item: dict[str, list[bool]] = {}
    for r in rows:
        by_item.setdefault(r["item_id"], []).append(bool(r.get("pass_rate")))
    if by_item and any("pass_rate" in r for r in rows):
        out["pass_5"] = round(sum(all(v) for v in by_item.values()) / len(by_item), 4)
        for k in k_values or []:
            if min(len(v) for v in by_item.values()) < k:
                continue
            for name, fn in (("pass_at", stats.pass_at_k), ("pass_hat", stats.pass_hat_k)):
                est = [fn(len(v), sum(v), k) for v in by_item.values()]
                out[f"{name}_{k}"] = round(sum(est) / len(est), 4)
    return out


def _looser(old: dict, new: dict | None, where: str) -> list[str]:
    """Ratchet for one metric or slice entry: max may not rise, min may not fall, flags may not drop."""
    if new is None:
        return [f"ratchet: {where} was removed"]
    out = []
    o_th = old.get("threshold", old) or {}
    n_th = new.get("threshold", new) or {}
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"ratchet: {where} is no longer blocking")
    for key in ("max", "max_increase"):
        if key in o_th and (key not in n_th or float(n_th[key]) > float(o_th[key])):
            out.append(f"ratchet: {where} {key} loosened {o_th[key]} -> {n_th.get(key)}")
    if "min" in o_th and ("min" not in n_th or float(n_th["min"]) < float(o_th["min"])):
        out.append(f"ratchet: {where} min loosened {o_th['min']} -> {n_th.get('min')}")
    if o_th.get("no_significant_drop") and not n_th.get("no_significant_drop"):
        out.append(f"ratchet: {where} dropped no_significant_drop")
    return out


def ratchet_check(spec: dict, base_spec: dict) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []            # a new eval-set version has a new baseline; thresholds restart there
    problems = []
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        problems += _looser(m, new_m.get(m["id"]), f"metric {m['id']}")
    new_s = {(x["name"], x["metric"]): x for x in spec.get("slices") or []}
    for x in base_spec.get("slices") or []:
        problems += _looser(x, new_s.get((x["name"], x["metric"])), f"slice {x['name']}/{x['metric']}")
    if "seeds" in base_spec and list(spec.get("seeds") or []) != list(base_spec["seeds"]):
        problems.append(f"ratchet: seeds changed {base_spec['seeds']} -> {spec.get('seeds')}")
    for key in ("eval_set", "labels"):
        if key in base_spec and spec.get(key) != base_spec[key]:
            problems.append(f"ratchet: {key} changed {base_spec[key]} -> {spec.get(key)}")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        val = round(sum(a.values()) / len(a), 4) if a else None
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"            # an empty slice cannot vouch for anything
        elif "min" in sl and val < sl["min"]:
            verdict = "fail"
        elif "max" in sl and val > sl["max"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and a:
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<34} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
