"""Shape B — one ReAct agent. Student work.

Use `lab8.runtime.run_react` with max_steps=8. `decide` may pick a read tool.
It must not call `issue_refund`. After the loop, the host validates the quote
and is the only writer.

A decide() that trusts ticket text over the order row will fail hidden claims
where the customer overstates the delay or cites a superseded clause.

Per-order cap: an order may already have been refunded by an earlier claim.
The read tool `lookup_refund_history` shows how much. The host still enforces
the cap, so pass the full quote to `durability.issue_refund`, not a net amount.

Caps: stop at 8 steps. Count model calls in the Budget so cost stays comparable.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.mock_llm import complete
from lab8.runtime import run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

SHAPE = "single"
MAX_STEPS = 8


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(SHAPE, claim_id, seed))

    def done(status: str, amount: int, reason: str | None = None) -> RunResult:
        trace.add("decision", {"status": status, "proposal_amount": amount, "reason": reason})
        return finish(
            conn,
            shape=SHAPE,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=amount,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )

    # 1. Read the claim through the filtered view. Never log the ticket.
    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim["found"]:
        return done("failed", 0, "unknown_claim")
    trace.add("claim", {"claim_id": claim_id, "has_order_id": bool(claim["order_id"])})

    # 2. Missing order id -> ask for info, no ledger write.
    if not claim["order_id"]:
        return done("needs_info", 0, "missing_order_id")

    scope = {"order_id": claim["order_id"], "principal_id": claim["principal_id"]}
    # run_react only passes the last tool result back, so decide keeps its own memory.
    state: dict[str, Any] = {}

    # 3. ReAct loop: decide only picks READ tools. It never returns issue_refund.
    def decide(obs: dict[str, Any]) -> dict[str, Any]:
        last = obs.get("last_tool")
        complete(budget, seed=seed, purpose="react", prompt=f"last_tool={last}")
        if last == "lookup_order":
            state["order_view"] = obs["last_result"]
            if not obs["last_result"].get("visible"):
                return {"final": {"status": "escalated"}}
            return {"tool": "lookup_refund_history", "args": dict(scope)}
        if last == "lookup_refund_history":
            state["history"] = obs["last_result"]  # traced as counts only; never subtracted from the quote
            return {"tool": "compute_compensation", "args": {"order": state["order_view"]["order"]}}
        if last == "compute_compensation":
            state["quote"] = obs["last_result"]
            return {"final": {"status": "quoted"}}
        return {"tool": "lookup_order", "args": dict(scope)}

    loop = run_react(
        conn,
        budget,
        observation={"claim": {"claim_id": claim_id}},
        decide=decide,
        max_steps=MAX_STEPS,
    )
    trace.add("react", {"stopped": loop["stopped"], "final": loop["final"]})

    # 4. After the loop, CODE decides. The model never picks the amount.
    if loop["stopped"] != "final":
        return done("failed", 0, "step_cap")
    if loop["final"].get("status") == "escalated":
        return done("escalated", 0, state["order_view"].get("reason"))
    if "quote" not in state:
        return done("failed", 0, "no_quote")

    trace.add("order", state["order_view"]["order"])  # already allowlisted by lookup_order
    history = state.get("history") or {}
    # Counts only, for the audit trail. The host enforces the per-order cap, so it is not subtracted here.
    trace.add(
        "refund_history",
        {"refund_count": history.get("refund_count", 0), "refunded_vnd": history.get("refunded_vnd", 0)},
    )
    quote = state["quote"]
    trace.add("quote", quote)
    proposal = int(quote["amount_vnd"])

    # 5. Zero quote -> denied, host is not called.
    if proposal <= 0:
        return done("denied", 0, quote.get("reason"))

    # 6. Full quote to the host. Never swallow InjectedCrash.
    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise
    trace.add("host", {"ok": outcome["ok"], "reason": outcome["reason"]})

    # 7. Model only drafts reply text.
    complete(budget, seed=seed, purpose="draft", prompt=f"outcome={outcome['reason']}")

    if not outcome["ok"]:
        return done("failed" if outcome["conflict"] else "denied", proposal, outcome["reason"])
    return done("resolved", proposal)
