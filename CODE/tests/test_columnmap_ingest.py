from __future__ import annotations

import io

import pytest

from io_sudoku.core.columnmap import load_aliases, map_columns, missing_mandatory
from io_sudoku.core.constants import IO_TYPES
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.tq import TQLog
from tests.mutate import col, mutated, read_table, to_xlsx_bytes


@pytest.fixture(scope="module")
def table(mdb_path):
    return read_table(mdb_path)


# ----------------------------------------------------------------------- columnmap
def test_fixture_headers_map_exactly(table):
    headers, _ = table
    m = map_columns(headers, load_aliases())
    assert m["tag"].index == 3 and m["tag"].method == "exact"          # 'Tag Number', NOT 'TagNumber'
    assert m["tag_compact"].index == 4
    assert m["instrument_type"].index == col(headers, "Instrument Type Description")
    assert m["instrument_code"].index == col(headers, "Instrument Type")
    assert all(x.method in ("exact", "alias") for x in m.values()), {k: v.method for k, v in m.items() if v.method not in ("exact", "alias")}
    assert missing_mandatory(m) == []
    used = [x.index for x in m.values()]
    assert len(used) == len(set(used))


def test_renamed_headers_use_alias_key_and_fuzzy_tiers():
    m = map_columns(["Tag Numbr", "I/O Type", "Technical Room", "Multipair Cabel No."], load_aliases())
    assert m["tag"].method == "fuzzy" and m["tag"].score >= 0.88      # typo -> fuzzy
    assert m["io_type"].method == "alias"                            # 'I/O Type' ~ 'IO Type' by key
    assert m["tech_room"].method == "alias"
    assert m["cable_no"].method == "fuzzy" and m["cable_no"].score >= 0.88


def test_below_threshold_is_missing():
    m = map_columns(["Totally Unrelated", "Banana"], load_aliases())
    assert m["tag"].method == "missing" and m["tag"].index is None
    assert set(missing_mandatory(m)) == {"tag", "io_type", "tech_room"}


def test_override_wins_and_no_column_used_twice():
    m = map_columns(["Instrument Tag", "Tag Number", "I/O Type Name", "Technical Room"], load_aliases(), {"tag": "Instrument Tag"})
    assert m["tag"].index == 0 and m["tag"].method == "override"
    idx = [x.index for x in m.values() if x.index is not None]
    assert len(idx) == len(set(idx))


def test_header_with_line_break_matches():
    m = map_columns(["Tag\nNumber", "I/O Type\nName", "Technical Room"], load_aliases())
    assert m["tag"].index == 0 and m["io_type"].index == 1


def test_fuzzy_cannot_steal_an_exact_match():
    # 'Tag Numbr' is a near miss for 'tag'; 'TagNumber' is the exact name of 'tag_compact'.
    m = map_columns(["Tag Numbr", "TagNumber", "I/O Type Name", "Technical Room"], load_aliases())
    assert m["tag_compact"].index == 1 and m["tag_compact"].method == "exact"
    assert m["tag"].index == 0 and m["tag"].method == "fuzzy"
    # Same hazard through the loose key tier: 'Tag Number' renamed 'Tag No.' must not
    # fall onto the compact 'TagNumber' column.
    m = map_columns(["Tag No.", "TagNumber", "I/O Type Name", "Technical Room"], load_aliases())
    assert m["tag"].index == 0 and m["tag_compact"].index == 1


# -------------------------------------------------------------------------- ingest
def test_fixture_counts(mdb_path):
    log = TQLog()
    r = read_mdb(mdb_path, log)
    assert (len(r.signals), len(r.alarms), len(r.deleted)) == (177, 12, 1)
    assert r.rows_read == 190
    assert r.deleted[0].tag == "320-FT   -80002"
    assert r.sheets_used == ["MDB-1"]
    assert log.has("DELETED-IN-MDB") and not log.has("UNREADABLE-FILE")
    assert all(s.io_type in IO_TYPES for s in r.signals)
    assert all(isinstance(s.unit, int) for s in r.signals)
    assert not any(s.service and s.service.endswith(" ") for s in r.signals)
    assert r.stats["deleted_excluded"] == 1 and r.stats["io_alias_fixed"] > 0


def test_tags_keep_internal_spaces_proving_f02_fixed(mdb_path):
    r = read_mdb(mdb_path, TQLog())
    tags = {s.tag for s in r.signals}
    assert "320-FT   -20645-A" in tags          # three inner spaces survive
    assert all("  " in s.tag for s in r.signals if s.tag.startswith("320-FT"))


def test_io_type2_rows(mdb_path):
    r = read_mdb(mdb_path, TQLog())
    both = [s for s in r.signals + r.alarms if s.io_type2]
    assert len(both) == 6
    hvac = next(s for s in r.signals if s.tag == "500-EJR  -00012-D")
    assert hvac.io_type == "DIR" and hvac.io_type2 == "DOR"


def test_alarms_internal_wiring_has_no_cable(mdb_path):
    r = read_mdb(mdb_path, TQLog())
    internal = [a for a in r.alarms if a.cable_no is None]
    assert len(internal) == 9              # 9 alarms wired internally, 3 on ICE cables
    assert all(a.pair_no is None for a in internal)
    ice = [a for a in r.alarms if a.cable_no]
    assert {a.cable_no for a in ice} == {"P30-ICE-0001", "P30-ICE-0002"}


def test_row_refs_are_excel_row_numbers(mdb_path):
    r = read_mdb(mdb_path, TQLog())
    assert r.deleted[0].row_ref == 4
    assert max(s.row_ref for s in r.signals + r.alarms) == 191


def test_bytes_equal_path(mdb_path, mdb_bytes):
    a, b = read_mdb(mdb_path, TQLog()), read_mdb(mdb_bytes, TQLog())
    assert a.signals == b.signals and a.alarms == b.alarms
    c = read_mdb(io.BytesIO(mdb_bytes), TQLog())
    assert c.signals == a.signals


def test_blank_rows_in_the_middle_keep_row_numbers():
    headers = ["Tag Number", "I/O Type Name", "Technical Room (Signal Location 2)"]
    data = to_xlsx_bytes(headers, [["T-1", "AI", "PIB-30"], [None, None, None], [None, None, None], ["T-2", "DO", "PIB-30"]])
    r = read_mdb(data, TQLog())
    assert [(s.tag, s.row_ref, s.io_type) for s in r.signals] == [("T-1", 2, "AIR"), ("T-2", 5, "DOR")]
    assert r.stats["blank_rows_skipped"] == 2


def test_header_only_and_missing_column_and_garbage(mdb_path):
    headers = ["Tag Number", "I/O Type Name", "Technical Room (Signal Location 2)"]
    log = TQLog()
    r = read_mdb(to_xlsx_bytes(headers, []), log)
    assert r.signals == [] and not log.has("UNREADABLE-FILE")

    log = TQLog()
    r = read_mdb(to_xlsx_bytes(["Foo", "Bar"], [["a", "b"]]), log)
    assert r.signals == [] and log.has("MISSING-COLUMN")

    for junk, tq in ((b"garbage", "UNREADABLE-FILE"), (b"not an excel file", "UNREADABLE-FILE"), (b"", "UNREADABLE-FILE"),
                     (b"\xd0\xcf\x11\xe0" + b"x" * 50, "UNSUPPORTED-FORMAT"), (b"PK\x03\x04broken", "UNREADABLE-FILE")):
        log = TQLog()
        r = read_mdb(junk, log)
        assert r.signals == [] and log.has(tq), (junk[:8], [t.tq_id for t in log])


def test_missing_file_path_and_wrong_type_never_raise(tmp_path):
    log = TQLog()
    assert read_mdb(tmp_path / "nope.xlsx", log).signals == [] and log.has("UNREADABLE-FILE")
    log = TQLog()
    assert read_mdb(12345, log).signals == [] and log.has("UNREADABLE-FILE")   # type: ignore[arg-type]


def test_too_large(monkeypatch):
    import io_sudoku.core.ingest as ing
    monkeypatch.setattr(ing, "MAX_FILE_BYTES", 10)
    log = TQLog()
    assert ing.read_mdb(b"x" * 11, log).signals == [] and log.has("FILE-TOO-LARGE")


def test_too_many_rows(monkeypatch):
    import io_sudoku.core.ingest as ing
    monkeypatch.setattr(ing, "MAX_DATA_ROWS", 3)
    headers = ["Tag Number", "I/O Type Name", "Technical Room (Signal Location 2)"]
    data = to_xlsx_bytes(headers, [[f"T-{i}", "AI", "PIB-30"] for i in range(10)])
    log = TQLog()
    r = ing.read_mdb(data, log)
    assert r.signals == [] and log.has("TOO-MANY-ROWS")


def test_csv_export_gives_equal_signals(table, mdb_path):
    import csv
    headers, rows = table
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for row in rows:
        w.writerow(["" if v is None else v for v in row])
    from_csv = read_mdb(buf.getvalue().encode("utf-8"), TQLog())
    from_xlsx = read_mdb(mdb_path, TQLog())
    assert [s.tag for s in from_csv.signals] == [s.tag for s in from_xlsx.signals]
    assert [s.io_type for s in from_csv.signals] == [s.io_type for s in from_xlsx.signals]
    assert [s.pair_no for s in from_csv.signals] == [s.pair_no for s in from_xlsx.signals]
    assert from_csv.sheets_used == ["csv"]


def test_two_sheet_split_reads_both(table):
    headers, rows = table
    half = len(rows) // 2
    data = to_xlsx_bytes(headers, rows[:half], sheet="A", extra_sheets={"B": (headers, rows[half:])})
    log = TQLog()
    r = read_mdb(data, log)
    assert r.sheets_used == ["A", "B"] and log.has("MULTI-SHEET-USED")
    assert len(r.signals) + len(r.alarms) + len(r.deleted) == 190


def test_shuffled_and_extra_columns_give_equal_signals(table, mdb_path):
    headers, rows = table
    order = list(range(len(headers)))[::-1]                      # reverse every column
    shuffled_h = [headers[i] for i in order] + ["Junk Column"]
    shuffled_r = [[r[i] for i in order] + ["x"] for r in rows]
    a = read_mdb(to_xlsx_bytes(shuffled_h, shuffled_r), TQLog())
    b = read_mdb(mdb_path, TQLog())
    assert [(s.tag, s.io_type, s.cable_no, s.pair_no) for s in a.signals] == [(s.tag, s.io_type, s.cable_no, s.pair_no) for s in b.signals]


def test_odd_cell_types_do_not_raise(table, mdb_path):
    def change(headers, rows):
        rows[0][col(headers, "Service")] = "=1+1"
        rows[1][col(headers, "Service")] = 3.5
        import datetime
        rows[2][col(headers, "Loop Name")] = datetime.datetime(2024, 1, 1)
        rows[3][col(headers, "WBS")] = 320.0
        rows[4][col(headers, "Pair Number")] = 7
    log = TQLog()
    r = read_mdb(mutated(mdb_path, change), log)
    assert len(r.signals) + len(r.alarms) + len(r.deleted) == 190
    assert r.signals[3].unit == 320


def test_fuzzy_header_logged(table):
    headers, rows = table
    h2 = ["Tag No." if h == "Tag Number" else h for h in headers]
    log = TQLog()
    r = read_mdb(to_xlsx_bytes(h2, rows), log)
    assert r.mapping["tag"].index == 3 and r.mapping["tag"].method == "alias"
    assert r.mapping["tag_compact"].index == 4
    assert len(r.signals) == 177
    assert "320-FT   -20645-A" in {s.tag for s in r.signals}      # spaces preserved: not the compact column


def test_column_override_used(table):
    headers, rows = table
    h2 = ["Instrument Tag" if h == "Tag Number" else h for h in headers]
    log = TQLog()
    r = read_mdb(to_xlsx_bytes(h2, rows), log, column_overrides={"tag": "Instrument Tag"})
    assert len(r.signals) == 177 and r.mapping["tag"].method == "override"
