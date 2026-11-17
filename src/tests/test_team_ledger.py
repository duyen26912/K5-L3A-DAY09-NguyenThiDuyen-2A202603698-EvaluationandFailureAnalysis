from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab8.db import connect, init_store
from lab8.durability import InjectedCrash, committed_audit_count, get_refund
from lab8.shapes import SHAPES
from tests.conftest import CLAIMS, WORLD

TEAM_SHAPES = ["workflow", "single", "orchestrator"]
CRASH_POINTS = ["before_effect", "after_effect_before_checkpoint", "after_checkpoint"]


def _store(tmp_path: Path, name: str) -> str:
    store = tmp_path / name
    init_store(store, WORLD, CLAIMS).close()
    return str(store)


def _ledger_rows(store: str, claim_id: str) -> int:
    conn = connect(store)
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM refund_ledger WHERE claim_id = ?", (claim_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


@pytest.mark.parametrize("point", CRASH_POINTS)
@pytest.mark.parametrize("shape", TEAM_SHAPES)
def test_crash_then_resume_leaves_one_refund(tmp_path, shape, point):
    store = _store(tmp_path, f"{shape}-{point}.sqlite")
    with pytest.raises(InjectedCrash):
        SHAPES[shape]("C-001", seed=11, store_path=store, crash_at=point)
    if point == "before_effect":
        assert _ledger_rows(store, "C-001") == 0

    result = SHAPES[shape]("C-001", seed=11, store_path=store)

    assert result.status == "resolved"
    assert result.proposal_amount == 35000
    conn = connect(store)
    try:
        effect = get_refund(conn, "C-001")
        assert effect is not None and int(effect["amount_vnd"]) == 35000
        assert committed_audit_count(conn, "C-001") == 1
    finally:
        conn.close()
    assert _ledger_rows(store, "C-001") == 1


@pytest.mark.parametrize("shape", TEAM_SHAPES)
def test_retry_without_approval_never_refunds(tmp_path, shape):
    store = _store(tmp_path, f"{shape}-noapproval.sqlite")
    conn = connect(store)
    conn.execute("UPDATE claims SET approval_id = NULL WHERE claim_id = 'C-001'")
    conn.commit()
    conn.close()

    for _ in range(2):
        result = SHAPES[shape]("C-001", seed=11, store_path=store)
        assert result.status == "denied"
        assert result.refund_effects == []
        payload = json.dumps(result.as_dict(), ensure_ascii=False)
        payload += Path(result.trace_path).read_text(encoding="utf-8")
        assert "CANARY_SECRET_PARENT_C-001" not in payload

    conn = connect(store)
    try:
        assert get_refund(conn, "C-001") is None
        assert committed_audit_count(conn, "C-001") == 0
        denied = conn.execute(
            "SELECT COUNT(*) AS n FROM audit_events WHERE claim_id = 'C-001' AND event_type = 'policy_denied'"
        ).fetchone()["n"]
        assert denied >= 1
    finally:
        conn.close()
