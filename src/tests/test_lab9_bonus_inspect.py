"""Bonus: the Inspect AI port of 3 graders must agree with pydantic-evals on every sample.

Skipped when inspect-ai is not installed (it is optional: requirements-bonus.txt).
Run: python -m pytest -q -o addopts= tests/test_lab9_bonus_inspect.py
"""
import pytest

pytest.importorskip("inspect_ai")


@pytest.fixture(autouse=True)
def _restore_shapes():
    """Variants are registered into lab8.shapes.SHAPES; undo it so Lab 8 contract tests still see 4 shapes."""
    from lab8.shapes import SHAPES
    saved = dict(SHAPES)
    yield
    SHAPES.clear()
    SHAPES.update(saved)


@pytest.mark.parametrize("shape,bugs", [
    ("seeded_regression", None),
    ("bonus_bypass", "no_override,sibling_refund,misreport,ignore_denied"),
])
def test_lab9_inspect_port_agrees_with_pydantic_evals(shape, bugs):
    from lab9 import variants
    from lab9.eval import SPEC, load_spec, run_eval
    from lab9.inspect_port import PORTED, compare, run_inspect

    variants.register()
    if bugs:
        from lab8.shapes import SHAPES
        from lab9.variant_agent import make_shape
        SHAPES[shape] = make_shape(shape, frozenset(bugs.split(",")))
    spec = load_spec(SPEC)
    report = run_eval(shape, spec, seeds=[11, 22])
    summary, mismatches = compare(run_inspect(shape, spec, seeds=[11, 22]), report)
    assert mismatches == []
    assert set(summary) == set(PORTED)
    # the comparison is not vacuous: each shape fails at least one ported grader
    assert summary["reply_matches_ledger"]["inspect"] < 1.0
    if bugs:
        assert summary["approval_bypass"]["inspect"] > 0
