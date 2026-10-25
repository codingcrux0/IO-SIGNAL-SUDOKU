"""The rework estimate on the Revision page: honest about what keeping positions saves.

A revision of the same project saves the moves; a different file is not a revision (no saving claimed);
added and deleted signals are the same either way; no change means no rework."""
from __future__ import annotations

from pathlib import Path

import pytest

from io_sudoku.core import revpreview
from io_sudoku.core.pipeline import solve
from io_sudoku.core.revision import compare, solve_incremental
from io_sudoku.core.simulate import ReworkMinutes, make_revision
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui.views import revision as revision_view

CASES = Path(__file__).resolve().parents[1] / "test_cases"


@pytest.fixture(scope="module")
def rev_a():
    return solve(sample_mdb_bytes())


def _check(rows_a, data_b) -> revpreview.Check:
    b, report = solve_incremental(data_b, rows_a, None, "B")
    fresh = compare(rows_a, solve(data_b, None, "B").rows)
    return revpreview.check({}, {}, report, fresh, ReworkMinutes(), rows_a, b.rows)


def test_a_real_revision_saves_the_moves_and_counts_new_work_once(rev_a):
    chk = _check(rev_a.rows, make_revision(sample_mdb_bytes(), 5, 1))
    h = chk.hours
    assert h.related and h.share > 0.9
    assert h.fresh > h.keep > 0 and h.saved == round(h.fresh - h.keep, 2) and 0 < h.saved_pct <= 100
    assert h.fresh_moved > h.keep_moved
    assert h.same == round((h.added * 10 + h.deleted * 5) / 60, 2) and h.same <= h.keep     # in both numbers
    assert "saved" in chk.rework_line() and "same either way" in chk.rework_line()
    labels = [k for k, _ in revision_view._rework_cards(h)]
    assert "Time Saved" in labels and "Same Either Way" in labels


def test_a_different_file_is_not_called_a_revision(rev_a):
    chk = _check(rev_a.rows, (CASES / "16_big_project_1600_signals.xlsx").read_bytes())
    h = chk.hours
    assert not h.related and h.share < 0.5 and h.saved == 0
    assert "different file" in chk.rework_line() and "new work" in chk.rework_line()
    cards = dict(revision_view._rework_cards(h))
    assert cards["Time Saved"] == "Not a revision" and "Rework Keeping Positions" not in cards
    assert "%" in cards["Rev A Signals Still In Rev B"]


def test_no_change_means_no_rework(rev_a):
    chk = _check(rev_a.rows, sample_mdb_bytes())
    assert chk.hours.related and chk.hours.keep == chk.hours.fresh == 0
    assert "no rework" in chk.rework_line()


def test_shared_signals_are_counted_by_tag_name_not_by_a_filled_in_old_tag():
    a = [{"Tag Name": "T1", "Tag Status": "Field"}, {"Tag Name": "T2", "Tag Status": "Field"},
         {"Tag Name": "-", "Tag Status": "Spare Slot"}]
    b = [{"Tag Name": "T1", "Tag Status": "Field"}, {"Tag Name": "X9", "Tag Status": "Field", "Old Tag": "T2"}]
    assert revpreview.shared_tags(a, b) == (1, 2)


def test_hours_read_simply():
    assert revpreview.hours_text(0) == "0 h" and revpreview.hours_text(1.234) == "1.2 h"
    assert revpreview.hours_text(1167.42) == "1,167 h" and revpreview.days_text(1167.42) == " (about 146 working days)"
    assert revpreview.days_text(3) == ""
