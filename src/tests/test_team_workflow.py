from __future__ import annotations

from lab8.db import connect, init_store
from lab8.shapes import SHAPES
from tests.conftest import CLAIMS, WORLD


def test_workflow_ignores_ticket_delay_on_t02(tmp_path):
    for seed in (11, 22, 33, 44, 55):
        store = tmp_path / f"w-{seed}.sqlite"
        init_store(store, WORLD, CLAIMS).close()
        result = SHAPES["workflow"]("C-002", seed=seed, store_path=str(store))
        assert result.status == "denied"
        assert result.refund_effects == []


def test_workflow_replay_keeps_one_ledger_row(tmp_path):
    store = tmp_path / "replay.sqlite"
    init_store(store, WORLD, CLAIMS).close()
    first = SHAPES["workflow"]("C-001", seed=11, store_path=str(store))
    second = SHAPES["workflow"]("C-001", seed=11, store_path=str(store))
    assert first.status == second.status == "resolved"
    conn = connect(store)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM refund_ledger WHERE claim_id = 'C-001'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1
