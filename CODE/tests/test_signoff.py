"""Warning sign-off: with sign-offs given, every warning must be approved before ISSUE-READY."""
from __future__ import annotations

from io_sudoku.core.readiness import APPROVED, PROBLEM, assess, signoff_counts, warning_key, warnings_of
from io_sudoku.samples import load_sample_result


def _all(result, decision):
    return {warning_key(w): decision for w in warnings_of(result)}


def test_without_signoffs_the_command_line_verdict_is_unchanged():
    assert assess(load_sample_result()).status == "ISSUE-READY"


def test_unreviewed_warnings_keep_the_result_in_draft():
    result = load_sample_result()
    assert warnings_of(result)
    r = assess(result, {})
    assert r.status == "DRAFT" and any("waiting for sign-off" in x for x in r.reasons)


def test_all_approved_is_issue_ready():
    result = load_sample_result()
    r = assess(result, _all(result, APPROVED))
    assert r.status == "ISSUE-READY" and any("signed off" in x for x in r.reasons)


def test_one_problem_keeps_draft_even_when_the_rest_are_approved():
    result = load_sample_result()
    signoffs = _all(result, APPROVED)
    signoffs[next(iter(signoffs))] = PROBLEM
    r = assess(result, signoffs)
    assert r.status == "DRAFT" and any("marked as a problem" in x for x in r.reasons)
    counts = signoff_counts(result, signoffs)
    assert counts[PROBLEM] == 1 and counts["waiting"] == 0 and counts["total"] == len(signoffs)


def test_signoffs_for_warnings_that_are_gone_are_ignored():
    result = load_sample_result()
    signoffs = {**_all(result, APPROVED), "OLD-WARNING|nothing": PROBLEM}
    assert assess(result, signoffs).status == "ISSUE-READY"


def test_errors_still_win_over_signoffs():
    from io_sudoku.core.pipeline import solve
    from io_sudoku.samples import case_bytes
    bad = solve(case_bytes("07_tag_errors.xlsx"))
    assert assess(bad, _all(bad, APPROVED)).status == "DRAFT"
