"""Shape C — orchestrator plus read-only investigators. Student work.

1. Build a handoff with `lab8.handoff.make_handoff`. Allowed tools are read-only.
   Never put parent_secret, raw headers, or the full claim row into facts.
2. `lab8.runtime.run_readonly_investigators` runs those tools.
3. The orchestrator quotes from the investigator's order view and calls
   `durability.issue_refund`. Investigators have no write registry.
   Pass the full quote; the host subtracts earlier refunds on the same order.
   `lookup_refund_history` is a read-only tool you may hand to an investigator.
4. Trace the sanitized handoff, not the parent context.

An LLM summary of the parent context is not a sanitizer. Use the allowlist.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.

Boundary in this implementation
-------------------------------
- Code decides: claim lookup, ownership, quote (`compute_compensation` on the
  order row), the call to `durability.issue_refund`, and the final status.
- MockLLM only "plans" and drafts reply text. Its output never feeds a decision.
- Ticket text is user data: it is never parsed for numbers, never copied into
  handoff facts, and never written to the trace.
- Handoff facts are empty on purpose: the orchestrator holds no verified order
  facts before the investigator reads the order row, and ticket claims are not facts.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.handoff import make_handoff
from lab8.mock_llm import complete
from lab8.runtime import run_readonly_investigators
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish, safe_dump
from lab8.tools import ORDER_FIELDS, get_claim_view, tool_cost
from lab8.trace import Trace

SHAPE = "orchestrator"
INVESTIGATOR_TOOLS = ["lookup_order", "lookup_refund_history", "compute_compensation"]
INVESTIGATOR_TASK = "verify_order_and_quote"


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
    run_id = make_run_id(SHAPE, claim_id, seed)
    trace = Trace(run_id)
    # Last known good answer, so an unexpected error after the host committed
    # still reports the committed refund instead of "failed / 0".
    state: dict[str, Any] = {"status": "failed", "proposal": 0}

    def done(status: str, proposal: int, reason: str | None) -> RunResult:
        trace.add("decision", {"status": status, "proposal_amount": int(proposal), "reason": reason})
        return finish(
            conn,
            shape=SHAPE,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )

    try:
        # 1. Orchestrator reads the claim through the allowlisted view (no parent_secret).
        budget.add_tool(tool_cost())
        claim = get_claim_view(conn, claim_id)
        if not claim.get("found"):
            return done("failed", 0, "unknown_claim")
        trace.add("claim", {"claim_id": claim_id, "has_order_id": bool(claim.get("order_id"))})

        # Model plans only, from a fixed prompt (no ticket text). Output is discarded.
        complete(budget, seed=seed, purpose="plan", prompt=f"plan:{INVESTIGATOR_TASK}")

        # 2. Missing order_id -> ask the customer. Never mine an order id from ticket text.
        if not claim.get("order_id"):
            complete(budget, seed=seed, purpose="draft", prompt="needs_info")
            return done("needs_info", 0, "missing_order_id")

        # 3. Sanitized handoff: allowlisted fields, read-only tools, no ticket-derived facts.
        handoff = make_handoff(
            request_id=f"REQ-{claim_id}",
            claim_id=claim_id,
            task=INVESTIGATOR_TASK,
            facts={},
            allowed_tools=list(INVESTIGATOR_TOOLS),
        )
        trace.add("handoff", safe_dump(handoff))

        investigated = run_readonly_investigators(conn, budget, handoff, principal_id=claim["principal_id"])
        tools = investigated["tools"]
        order_view = tools.get("lookup_order") or {}
        trace.add("investigator", _investigator_summary(tools))

        # 4. Order not visible (missing, not found, other principal) -> escalate.
        if not order_view.get("visible"):
            complete(budget, seed=seed, purpose="draft", prompt="escalated")
            return done("escalated", 0, order_view.get("reason") or "order_not_visible")

        # 5. Quote from the order row only (investigator ran compute_compensation on it).
        quote_payload = tools.get("compute_compensation")
        if not quote_payload:
            return done("failed", 0, "missing_quote")
        proposal = int(quote_payload["amount_vnd"])
        trace.add(
            "quote",
            {
                "amount_vnd": proposal,
                "reason": quote_payload.get("reason"),
                "clause_ids": list(quote_payload.get("clause_ids") or []),
            },
        )
        complete(budget, seed=seed, purpose="draft", prompt=f"proposal={proposal}")

        if proposal <= 0:
            return done("denied", 0, quote_payload.get("reason") or "zero_quote")

        # 6. Host is the only writer. Full quote in; host applies approval, cap, idempotency.
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
        if outcome["ok"]:
            state.update(status="resolved", proposal=proposal)
        trace.add("host", {"ok": bool(outcome["ok"]), "reason": outcome["reason"], "conflict": bool(outcome["conflict"])})

        if not outcome["ok"]:
            return done("failed" if outcome["conflict"] else "denied", proposal, outcome["reason"])
        return done("resolved", proposal, None)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise
    except Exception as exc:  # run_claim must not raise; keep the message out of the trace.
        reason = f"exception:{type(exc).__name__}"
        try:
            return done(state["status"], state["proposal"], reason)
        except Exception:
            # done()/finish() itself failed (disk, locked DB): return without touching it again.
            return _bare_result(run_id, claim_id, seed, budget, trace, state, reason)


def _bare_result(
    run_id: str,
    claim_id: str,
    seed: int,
    budget: Budget,
    trace: Trace,
    state: dict[str, Any],
    reason: str,
) -> RunResult:
    try:
        path = trace.write()
    except Exception:
        path = str(trace.path)
    return RunResult(
        run_id=run_id,
        claim_id=claim_id,
        shape=SHAPE,
        seed=seed,
        status=state["status"],
        proposal_amount=int(state["proposal"]),
        refund_effects=[],
        committed_audit_count=0,
        model_calls=budget.model_calls,
        tool_calls=budget.tool_calls,
        input_tokens=budget.input_tokens,
        output_tokens=budget.output_tokens,
        cost_estimate=round(budget.cost_estimate, 6),
        trace_path=path,
        error_reason=reason,
    )


def _investigator_summary(tools: dict[str, Any]) -> dict[str, Any]:
    """Only allowlisted order fields and refund totals. Never the raw row or the ticket."""
    order_view = tools.get("lookup_order") or {}
    history = tools.get("lookup_refund_history") or {}
    order = order_view.get("order") or {}
    return {
        "order_visible": bool(order_view.get("visible")),
        "order_reason": order_view.get("reason"),
        "order": {key: order[key] for key in ORDER_FIELDS if key in order},
        "refund_history": {
            "visible": bool(history.get("visible")),
            "refund_count": int(history.get("refund_count") or 0),
            "refunded_vnd": int(history.get("refunded_vnd") or 0),
        },
    }
