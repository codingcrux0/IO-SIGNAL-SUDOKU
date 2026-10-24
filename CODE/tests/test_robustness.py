"""Try to break the tool: every mutation must give a normal result, never an exception."""
from __future__ import annotations

import random
from collections import Counter

import pytest

from io_sudoku.core.allocio import CANONICAL_COLUMNS
from io_sudoku.core.pipeline import solve
from tests.mutate import col, mutated, read_table, row_of, to_xlsx_bytes

TAG = "320-FT   -20645-A"          # a normal field signal (cable 320-CE-0001, pair 1)


@pytest.fixture(scope="module")
def baseline(mdb_path):
    return solve(mdb_path)


def check_sane(r):
    assert all(list(row) == CANONICAL_COLUMNS for row in r.rows)
    assert [v for v in r.violations if v.severity == "error"] == [], [v for v in r.violations][:5]
    assert r.readiness is not None and isinstance(r.kpis["rows"], int)
    assert not any(t.tq_id == "INTERNAL" for t in r.tqs), [t.message for t in r.tqs if t.tq_id == "INTERNAL"]


def first_other(headers, rows, cable_col="Multipair Cable No."):
    """Index of a normal signal row that has a cable and a pair."""
    c = col(headers, cable_col)
    for i, r in enumerate(rows):
        if r[c] not in (None, "-", "Internal Wiring") and r[col(headers, "Status")] != "DELETED":
            return i
    raise AssertionError


def m_blank_io(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "I/O Type Name")] = None

def m_unknown_io(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "I/O Type Name")] = "XYZ"

def m_blank_pair(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "Pair Number")] = None

def m_dash_pair(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "Pair Number")] = "-"

def m_blank_cable(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "Multipair Cable No.")] = "-"

def m_same_pair(h, rows):
    i = row_of(h, rows, TAG)
    j = next(k for k, r in enumerate(rows) if r[col(h, "Multipair Cable No.")] == "320-CE-0001" and k != i and r[col(h, "Pair Number")] == "Pair 2")
    rows[j][col(h, "Pair Number")] = rows[i][col(h, "Pair Number")]

def m_pair_beyond(h, rows):
    i = next(k for k, r in enumerate(rows) if str(r[col(h, "Multi-cable / Cable")]).startswith("12P"))
    rows[i][col(h, "Pair Number")] = "Pair 99"

def m_duplicate_tag(h, rows):
    rows.append(list(rows[row_of(h, rows, TAG)]))

def m_unsupported_segregation(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "IO Grouping")] = "A-B"

def m_blank_tag(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "Tag Number")] = None

def m_mixed_ab(h, rows):
    c = col(h, "Multipair Cable No.")
    j = next(k for k, r in enumerate(rows) if r[c] == "320-CE-0040" and r[col(h, "IO Grouping")] in (None, "-"))
    rows[j][col(h, "IO Grouping")] = "B"

def m_formulas(h, rows):
    for r in rows:
        r[col(h, "Service")] = "=1+1"
        r[col(h, "Loop Name")] = 3.14

def m_floats_everywhere(h, rows):
    for r in rows:
        for name in ("WBS", "Pair Number", "Logic Number", "Equipment Name"):
            if isinstance(r[col(h, name)], int):
                r[col(h, name)] = float(r[col(h, name)])

def m_giant_text(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "Service")] = "x" * 50_000

def m_unicode(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "Service")] = "Ünïcödé ‮ 日本語 \U0001F600"

def m_is_signal(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "Execution")] = "IS"

def m_irc(h, rows):
    rows[row_of(h, rows, TAG)][col(h, "Instrument Type Description")] = "IRC interface"

def m_cable_size_conflict(h, rows):
    c = col(h, "Multipair Cable No.")
    j = next(k for k, r in enumerate(rows) if r[c] == "320-CE-0040")
    rows[j][col(h, "Multi-cable / Cable")] = "12PX1MM2/FR/IND&OS/ARM/NIS"

def m_missing_cable_size(h, rows):
    c = col(h, "Multipair Cable No.")
    for r in rows:
        if r[c] == "320-CE-0040":
            r[col(h, "Multi-cable / Cable")] = None


CASES = [
    (m_blank_io, "MISSING-IO-TYPE"), (m_unknown_io, "UNKNOWN-IO-TYPE"), (m_blank_pair, "MISSING-PAIR"),
    (m_dash_pair, "MISSING-PAIR"), (m_blank_cable, "MISSING-CABLE"), (m_same_pair, "DUPLICATE-PAIR"),
    (m_pair_beyond, "PAIR-BEYOND-CABLE"), (m_duplicate_tag, "DUPLICATE-TAG"),
    (m_unsupported_segregation, "UNSUPPORTED-SEGREGATION"), (m_blank_tag, "BLANK-TAG"), (m_mixed_ab, "MIXED-SEGREGATION"),
    (m_is_signal, "IS-SIGNAL-UNSUPPORTED"), (m_irc, "OUT-OF-SCOPE-SIGNAL"), (m_cable_size_conflict, "CABLE-SIZE-CONFLICT"),
    (m_missing_cable_size, "CABLE-SIZE-INFERRED"),
]


@pytest.mark.parametrize("change,tq", CASES, ids=[c[0].__name__ for c in CASES])
def test_bad_data_becomes_a_tq_and_a_valid_result(mdb_path, change, tq):
    r = solve(mutated(mdb_path, change))
    assert any(t.tq_id == tq for t in r.tqs), (tq, sorted({t.tq_id for t in r.tqs}))
    check_sane(r)
    if tq != "CABLE-SIZE-INFERRED":
        assert r.readiness.status == "DRAFT" and r.quarantined
    else:
        assert r.readiness.status == "ISSUE-READY" and r.quarantined == []    # inferred 24 from highest pair


@pytest.mark.parametrize("change", [m_formulas, m_floats_everywhere, m_giant_text, m_unicode],
                         ids=lambda f: f.__name__)
def test_odd_cell_contents_do_not_change_the_allocation(mdb_path, baseline, change):
    r = solve(mutated(mdb_path, change))
    check_sane(r)
    assert r.readiness.status == "ISSUE-READY"
    assert [x["Tag Status"] for x in r.rows] == [x["Tag Status"] for x in baseline.rows]
    assert [x["Channel_No"] for x in r.rows] == [x["Channel_No"] for x in baseline.rows]


def test_unseen_technical_room_is_inferred(mdb_path):
    def change(h, rows):                                   # every signal of one self-contained cable moves to a new room
        for r in rows:
            if r[col(h, "Multipair Cable No.")] == "320-CE-0040":
                r[col(h, "Technical Room (Signal Location 2)")] = "PIB-99"
    r = solve(mutated(mdb_path, change))
    check_sane(r)
    assert any(t.tq_id == "TOPOLOGY-INFERRED" for t in r.tqs)
    assert Counter(x["Tag Status"] for x in r.rows)["Field"] == 177
    assert any(x["Electronic/ Marshalling Cabinet"].startswith("P99-DCM") for x in r.rows)


def test_one_signal_in_another_room_makes_its_cable_span_rooms(mdb_path):
    def change(h, rows):
        rows[row_of(h, rows, TAG)][col(h, "Technical Room (Signal Location 2)")] = "PIB-24"
    r = solve(mutated(mdb_path, change))
    check_sane(r)
    assert any(t.tq_id == "GROUP-SPANS-ROOMS" for t in r.tqs) and len(r.quarantined) >= 18


def test_room_that_cannot_be_inferred_is_quarantined(mdb_path):
    def change(h, rows):
        rows[row_of(h, rows, TAG)][col(h, "Technical Room (Signal Location 2)")] = "LAB"
    r = solve(mutated(mdb_path, change))
    check_sane(r)
    assert any(t.tq_id == "NO-CABINET-FOR-ROOM" for t in r.tqs) and len(r.quarantined) >= 1


def test_renamed_mandatory_header_gives_missing_column(mdb_path):
    headers, rows = read_table(mdb_path)
    h2 = ["Zzz Qqq" if h == "Tag Number" else ("Zzz Www" if h == "TagNumber" else h) for h in headers]
    r = solve(to_xlsx_bytes(h2, rows))
    assert any(t.tq_id == "MISSING-COLUMN" for t in r.tqs) and r.readiness.status == "BLOCKED"


def test_header_only_zero_byte_and_random_bytes():
    for data in (to_xlsx_bytes(["Tag Number", "I/O Type Name", "Technical Room"], []), b"", bytes(range(256)) * 40):
        r = solve(data)
        assert r.rows == [] and r.readiness.status == "BLOCKED"
        assert all(isinstance(v, (int, float, dict)) for v in r.kpis.values() if not isinstance(v, str))


def test_padded_cells_nbsp_and_trailing_spaces_change_nothing(mdb_path, baseline):
    def pad(h, rows):
        for r in rows:
            for i, v in enumerate(r):
                if isinstance(v, str) and v not in ("",):
                    r[i] = ("  " if i % 2 else "  ") + v + ("  " if i % 3 else "   ")
        for i, v in enumerate(h):
            h[i] = "  " + v + " "
    r = solve(mutated(mdb_path, pad))
    assert r.rows == baseline.rows


def test_shuffled_columns_change_nothing(mdb_path, baseline):
    headers, rows = read_table(mdb_path)
    order = list(range(len(headers)))
    random.Random(3).shuffle(order)
    data = to_xlsx_bytes([headers[i] for i in order], [[r[i] for i in order] for r in rows])
    assert solve(data).rows == baseline.rows


def test_blank_cells_sprinkled_at_random_never_crash(mdb_path):
    headers, rows = read_table(mdb_path)
    rng = random.Random(7)
    columns = rng.sample(range(len(headers)), 20)
    rows = [list(r) for r in rows]
    for c in columns:
        for r in rows:
            if rng.random() < 0.05:
                r[c] = None
    r = solve(to_xlsx_bytes(headers, rows))
    check_sane(r)


@pytest.mark.parametrize("seed", range(5))
def test_random_garbage_in_random_cells_never_crashes(mdb_path, seed):
    headers, rows = read_table(mdb_path)
    rng = random.Random(100 + seed)
    junk = ["", " ", "-", "None", "nan", 0, -5, 3.7, "Pair x", " ", "=SUM(A1)", "PIB-30", "A", "B", "AIR", "12PX1MM2", 99999, "☃"]
    rows = [list(r) for r in rows]
    for _ in range(400):
        rows[rng.randrange(len(rows))][rng.randrange(len(headers))] = rng.choice(junk)
    r = solve(to_xlsx_bytes(headers, rows))
    assert all(list(row) == CANONICAL_COLUMNS for row in r.rows)
    assert not any(t.tq_id == "INTERNAL" for t in r.tqs), [t.message for t in r.tqs if t.tq_id == "INTERNAL"]
    assert [v for v in r.violations if v.severity == "error"] == [], r.violations[:5]


def test_duplicate_everything_and_empty_rows(mdb_path):
    headers, rows = read_table(mdb_path)
    data = to_xlsx_bytes(headers, [list(r) for r in rows] + [[None] * len(headers)] * 5 + [list(r) for r in rows[:20]])
    r = solve(data)
    check_sane(r)
    assert any(t.tq_id == "DUPLICATE-TAG" for t in r.tqs)
