from __future__ import annotations

import pytest

from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.pipeline import solve
from io_sudoku.core.simulate import ReworkMinutes, make_revision, make_revision_with_edits, simulate_churn, _quotas
from io_sudoku.core.tq import TQLog


@pytest.fixture(scope="module")
def churn(mdb_path):
    return simulate_churn(mdb_path, pct=5.0, seed=1)


def test_quotas_split_by_largest_remainder():
    assert _quotas(9) == {"deleted": 3, "renamed": 2, "added": 2, "pair_change": 2}
    for n in range(0, 60):
        q = _quotas(n)
        assert sum(q.values()) == n and all(v >= 0 for v in q.values())
    assert _quotas(10) == {"deleted": 3, "renamed": 2, "added": 3, "pair_change": 2}


def test_same_seed_same_revision_different_seed_different(mdb_path):
    a, ea = make_revision_with_edits(mdb_path, 5.0, 1)
    b, eb = make_revision_with_edits(mdb_path, 5.0, 1)
    c, ec = make_revision_with_edits(mdb_path, 5.0, 2)
    assert ea == eb and solve(a).rows == solve(b).rows
    assert ea == ec or solve(c).rows != solve(a).rows
    sigs = lambda data: sorted(s.tag for s in read_mdb(data, TQLog()).signals)
    assert sigs(a) == sigs(b) and sigs(a) != sigs(c)


def test_edit_counts_match_five_percent(churn):
    total = sum(churn.edits.values())
    assert 7 <= total <= round(0.05 * 177) + 1
    assert churn.edits["deleted"] == 3 and churn.edits["renamed"] == 2


def test_zero_percent_changes_nothing(mdb_path):
    r = simulate_churn(mdb_path, pct=0.0, seed=1)
    assert sum(r.edits.values()) == 0
    assert r.naive.changes == [] and r.incremental.changes == []
    assert r.naive_moved_pct == r.incremental_moved_pct == 0.0 and r.hours_saved == 0.0


def test_pinned_resolve_moves_only_the_pair_changes(churn):
    assert churn.incremental.counts["Moved"] <= churn.edits["pair_change"]
    assert churn.incremental.counts["Deleted"] == churn.edits["deleted"]
    assert churn.incremental.counts["Renamed"] == churn.edits["renamed"]
    assert churn.incremental.counts["Added"] == churn.edits["added"]


def test_naive_reallocation_moves_far_more(churn):
    print(f"\n5% revision: naive moved {churn.naive_moved_pct}% vs pinned {churn.incremental_moved_pct}%, "
          f"hours {churn.hours_naive} vs {churn.hours_incremental} (saved {churn.hours_saved})")
    assert churn.naive_moved_pct >= churn.incremental_moved_pct
    assert churn.naive_moved_pct > 10 and churn.incremental_moved_pct < 5


def test_hours_are_arithmetic_on_the_editable_minutes(mdb_path, churn):
    assert churn.hours_saved == round(churn.hours_naive - churn.hours_incremental, 2) and churn.hours_saved > 0
    c = churn.naive.counts
    expected = round((c["Moved"] * 15 + c["Renamed"] * 3 + c["Added"] * 10 + c["Deleted"] * 5) / 60, 2)
    assert churn.hours_naive == expected
    zero_moves = simulate_churn(mdb_path, 5.0, 1, ReworkMinutes(per_moved_tag=0.0))
    assert zero_moves.hours_naive < churn.hours_naive


def test_garbage_and_empty_inputs_give_zeros():
    for junk in (b"garbage", b"", b"\xd0\xcf\x11\xe0xx"):
        r = simulate_churn(junk, 5.0, 1)
        assert sum(r.edits.values()) == 0 and r.naive_moved_pct == 0.0 and r.hours_saved == 0.0
        assert make_revision(junk) == b""


def test_revision_is_still_a_valid_mdb(mdb_path):
    data = make_revision(mdb_path, 10.0, 3)
    r = solve(data)
    assert r.readiness.status in ("ISSUE-READY", "DRAFT") and len(r.rows) >= 1152
    assert not any(t.tq_id == "INTERNAL" for t in r.tqs)
