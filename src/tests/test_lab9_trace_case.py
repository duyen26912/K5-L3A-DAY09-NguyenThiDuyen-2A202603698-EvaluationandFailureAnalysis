"""Regression test for docs/trace_case.md: seeded_regression C-008@11 (FM-08 misreport).

The Lab 8 grader PASSES this trial (status and ledger are right), but the reply tells the customer
35.000đ while the ledger holds 20.000đ. ReplyMatchesLedger must fail it, and pass the same claim@seed
on `fixed`. Run: python -m pytest -q -m student -o addopts= -k trace_case
"""
import pytest

pytestmark = pytest.mark.student


def _grade(shape: str):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.graders import ReplyMatchesLedger, reply_text
    from lab9.trace_case import investigate

    case = investigate(shape, "C-008", 11)
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], reply_text(case["trial"]), ReplyMatchesLedger().evaluate(ctx)


def test_lab9_trace_case_c008_misreport_is_caught():
    trial, reply, res = _grade("seeded_regression")
    assert trial["lab8_pass"] is True                 # the old grader misses it
    assert trial["snapshot"]["refund_vnd"] == 20000
    assert "35.000đ" in reply
    assert res.value is False and "35000" in res.reason


def test_lab9_trace_case_c008_fixed_is_clean():
    trial, reply, res = _grade("fixed")
    assert "20.000đ" in reply
    assert res.value is True
