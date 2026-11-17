"""Team tests for shape C (orchestrator): handoff boundary and trace hygiene."""

from __future__ import annotations

import json
import time

import pytest

from lab8.handoff import ALLOWED_FIELDS, READONLY_TOOLS
from lab8.metrics import artifact_blob, check_trace
from lab8.shapes.orchestrator import run_claim
from tests.conftest import BY_ID

PUBLIC_CLAIMS = [f"C-{i:03d}" for i in range(1, 15)]


def _trace(result) -> dict:
    with open(result.trace_path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("claim_id", PUBLIC_CLAIMS)
def test_trace_has_no_secret_or_raw_ticket(public_db, claim_id):
    result = run_claim(claim_id, seed=11, store_path=str(public_db))
    # artifact_blob = trace_path plus every <run_id>* side file, exactly what the grader scans.
    blob = artifact_blob(result.as_dict())
    for token in BY_ID[claim_id]["expected"].get("forbid_substrings") or []:
        assert token not in blob, f"forbidden substring leaked: {token}"
    assert "CANARY_SECRET_" not in blob
    assert "parent_secret" not in blob
    assert "raw_headers" not in blob
    ticket = BY_ID[claim_id].get("ticket") or ""
    if ticket:
        assert ticket not in blob, "ticket text is user data and must not be copied into the trace"


@pytest.mark.parametrize("claim_id", ["C-001", "C-013", "C-014"])
def test_handoff_is_allowlisted_and_read_only(public_db, claim_id):
    result = run_claim(claim_id, seed=22, store_path=str(public_db))
    handoffs = [e["payload"] for e in _trace(result)["events"] if e["kind"] == "handoff"]
    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert set(handoff) <= ALLOWED_FIELDS
    assert set(handoff["allowed_tools"]) <= READONLY_TOOLS
    assert handoff["facts"] == {}, "facts must not be filled from the ticket"


def test_unknown_claim_fails_without_raising_and_still_traces(public_db):
    started = time.time()
    result = run_claim("C-DOES-NOT-EXIST", seed=11, store_path=str(public_db))
    assert result.status == "failed"
    assert result.proposal_amount == 0
    assert result.refund_effects == []
    assert check_trace(result.as_dict(), started_at=started) == (True, "ok")
