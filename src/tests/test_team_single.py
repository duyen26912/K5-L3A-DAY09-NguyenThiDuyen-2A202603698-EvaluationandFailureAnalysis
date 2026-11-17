from __future__ import annotations

import json
from pathlib import Path

import pytest

import lab8.shapes.single as single_mod
from lab8.db import connect, init_store
from lab8.durability import InjectedCrash
from lab8.handoff import WRITE_TOOLS
from lab8.runtime import ToolRejected
from lab8.runtime import run_react as real_run_react
from lab8.shapes import SHAPES
from tests.conftest import BY_ID, CLAIMS, WORLD

# Claims that have an order id, so the ReAct loop actually runs.
LOOP_CASES = [c["claim_id"] for c in CLAIMS if c.get("order_id")]


def _store(tmp_path, name: str) -> str:
    store = tmp_path / f"{name}.sqlite"
    init_store(store, WORLD, CLAIMS).close()
    return str(store)


def _spy(monkeypatch):
    """Wrap run_react: record the kwargs single.py passes and every action decide() returns."""
    log = {"calls": [], "actions": []}

    def spy_run_react(*args, **kwargs):
        log["calls"].append(dict(kwargs))
        decide = kwargs["decide"]

        def recording_decide(obs):
            action = decide(obs)
            log["actions"].append(action)
            return action

        kwargs["decide"] = recording_decide
        return real_run_react(*args, **kwargs)

    monkeypatch.setattr(single_mod, "run_react", spy_run_react)
    return log


@pytest.mark.parametrize("claim_id", [c["claim_id"] for c in CLAIMS])
def test_single_matches_expected_labels(tmp_path, claim_id):
    expected = BY_ID[claim_id]["expected"]
    result = SHAPES["single"](claim_id, seed=11, store_path=_store(tmp_path, claim_id))
    assert result.status == expected["status"]
    assert result.proposal_amount == expected["proposal_amount"]
    assert len(result.refund_effects) == expected["refund_count"]
    assert sum(e["amount_vnd"] for e in result.refund_effects) == expected["refund_vnd"]
    assert result.committed_audit_count == expected["audit_refund_committed"]
    text = Path(result.trace_path).read_text(encoding="utf-8")
    for secret in expected["forbid_substrings"]:
        assert secret not in text


@pytest.mark.parametrize("claim_id", LOOP_CASES)
def test_single_decide_never_returns_write_tool(tmp_path, monkeypatch, claim_id):
    log = _spy(monkeypatch)
    try:
        SHAPES["single"](claim_id, seed=11, store_path=_store(tmp_path, claim_id))
    except ToolRejected:
        pass  # the assertion below reports which write tool decide() tried to call
    tools = [a["tool"] for a in log["actions"] if "tool" in a]
    assert tools, "decide should call at least one read tool"
    assert not set(tools) & set(WRITE_TOOLS), f"decide returned a write tool: {tools}"


@pytest.mark.parametrize("claim_id", LOOP_CASES)
def test_single_stops_within_8_steps(tmp_path, monkeypatch, claim_id):
    log = _spy(monkeypatch)
    result = SHAPES["single"](claim_id, seed=11, store_path=_store(tmp_path, claim_id))
    assert len(log["calls"]) == 1
    assert log["calls"][0].get("max_steps") == 8, "single.py must pass max_steps=8 explicitly"
    assert 1 <= len(log["actions"]) <= 8
    assert "final" in log["actions"][-1]
    assert result.error_reason != "step_cap"


@pytest.mark.parametrize(
    ("claim_id", "status", "reason"),
    [("C-004", "needs_info", "missing_order_id"), ("C-NOT-EXIST", "failed", "unknown_claim")],
)
def test_single_early_returns_skip_loop_and_write_trace(tmp_path, monkeypatch, claim_id, status, reason):
    log = _spy(monkeypatch)
    result = SHAPES["single"](claim_id, seed=11, store_path=_store(tmp_path, "early"))
    assert result.status == status
    assert result.error_reason == reason
    assert log["calls"] == [], "the ReAct loop must not run without an order id"
    body = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
    assert body["run_id"] == result.run_id


def test_single_crash_reraises_then_resume_pays_once(tmp_path):
    store = _store(tmp_path, "crash")
    with pytest.raises(InjectedCrash):
        SHAPES["single"]("C-012", seed=11, store_path=store, crash_at="after_effect_before_checkpoint")
    resumed = SHAPES["single"]("C-012", seed=11, store_path=store)
    assert resumed.status == "resolved"
    assert resumed.committed_audit_count == 1
    conn = connect(store)
    try:
        n = conn.execute("SELECT COUNT(*) FROM refund_ledger WHERE claim_id = 'C-012'").fetchone()[0]
    finally:
        conn.close()
    assert n == 1
