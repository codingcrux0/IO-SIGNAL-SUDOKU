"""A finished IO Allocation as the input file: Field rows read, spares rebuilt, shifted rows repaired with TQs."""
from __future__ import annotations

import io
from collections import Counter
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from io_sudoku.core import allocinput
from io_sudoku.core.allocio import CANONICAL_COLUMNS, allocation_bytes
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui import ui_logic

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_ALLOCATION = ROOT / "Files" / "Sample_IO_Allocation_VIT_v2 1.xlsx"


def solve(data: bytes):
    return ui_logic.solve_inputs(data, "", "[]", "{}", "{}", "00")


@pytest.fixture(scope="module")
def mdb_result():
    return solve(sample_mdb_bytes())


@pytest.fixture(scope="module")
def allocation(mdb_result) -> bytes:
    return allocation_bytes(mdb_result.rows)[0]


def _sheet(data: bytes) -> list[list]:
    ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _shift_tail(row: list, start: int, k: int) -> list:
    """Push the values from `start` on k columns right (k > 0, inserting '-') or left (k < 0, dropping cells)."""
    return row[:start] + ["-"] * k + row[start:] if k > 0 else row[:start] + row[start - k:]


def test_detect_only_matches_the_allocation_template(allocation):
    assert allocinput.detect(_sheet(allocation)[0]) is not None
    assert allocinput.detect(_sheet(sample_mdb_bytes())[0]) is None
    assert allocinput.detect([]) is None and allocinput.detect(["Tag", "IO Type"]) is None


def test_allocation_input_reads_field_and_alarm_rows_and_rebuilds_spares(mdb_result, allocation):
    result = solve(allocation)
    k, m = result.kpis, mdb_result.kpis
    assert k["field"] == m["field"] and k["cabinet_alarm"] == m["cabinet_alarm"]
    assert not any(t.tq_id in ("BLANK-TAG", "MISSING-CABLE") for t in result.tqs)
    assert [t.tq_id for t in result.tqs].count("ALLOCATION-AS-INPUT") == 1
    assert result.readiness.status == "ISSUE-READY"            # a clean allocation is not downgraded


def test_mdb_input_is_untouched(mdb_result):
    assert not any(t.tq_id.startswith(("ALLOCATION-AS-INPUT", "ROW-")) for t in mdb_result.tqs)


def test_shifted_rows_are_repaired_and_reported(mdb_result, allocation):
    rows = _sheet(allocation)
    header = rows[0]
    cable_i, status_i = header.index("Field Cable No"), header.index("Tag Status")
    field_rows = [i for i, r in enumerate(rows) if i and r[status_i] == "Field"][:5]
    alarm_rows = [i for i, r in enumerate(rows) if i and r[status_i] == "Cabinet Alarm"][:2]
    for i in field_rows:
        rows[i] = _shift_tail(rows[i], cable_i, 1)
    for i in alarm_rows:
        rows[i] = _shift_tail(rows[i], status_i - 1, -1)
    result = solve(_xlsx(rows))
    ids = Counter(t.tq_id for t in result.tqs)
    assert ids["ROW-REALIGNED"] == 2 and "ROW-MISALIGNED" not in ids and "MISSING-CABLE" not in ids
    assert result.kpis["field"] == mdb_result.kpis["field"]
    assert result.kpis["cabinet_alarm"] == mdb_result.kpis["cabinet_alarm"]
    assert result.readiness.status == "DRAFT"                   # a repaired file needs a human to confirm
    assert any(str(field_rows[0] + 1) in t.ref for t in result.tqs if t.tq_id == "ROW-REALIGNED")


def test_unrepairable_row_is_set_aside_with_an_error(allocation):
    rows = _sheet(allocation)
    header = rows[0]
    status_i = header.index("Tag Status")
    i = next(i for i, r in enumerate(rows) if i and r[status_i] == "Field")
    rows[i][status_i] = "nonsense"                               # no valid status anywhere near
    result = solve(_xlsx(rows))
    misaligned = [t for t in result.tqs if t.tq_id == "ROW-MISALIGNED"]
    assert len(misaligned) == 1 and misaligned[0].severity == "error"
    assert str(i + 1) in misaligned[0].ref
    assert not any(r.get("Tag Name") == rows[i][header.index("Tag Name")] for r in result.rows)
    assert result.readiness.status == "BLOCKED" and result.rows        # an error blocks, the rest is still allocated


def test_realign_never_drops_a_value():
    header = list(CANONICAL_COLUMNS)
    layout = allocinput.detect(header)
    row = ["v"] * len(header)
    row[header.index("Tag Status")] = "Field"
    row.insert(10, "v")                                          # everything slipped right, but no cell is blank
    fixed, _shift, _ = layout.realign(row)
    assert fixed is None


def test_ambiguous_shift_is_not_guessed():
    header = list(CANONICAL_COLUMNS)
    layout = allocinput.detect(header)
    status_i = header.index("Tag Status")
    row = ["-"] * len(header)
    row[status_i] = "?"
    row[status_i - 1], row[status_i + 1] = "Field", "Field"
    assert layout.realign(row)[0] is None


@pytest.mark.skipif(not OFFICIAL_ALLOCATION.exists(), reason="official sample not in this checkout")
def test_official_sample_allocation_as_input():
    result = solve(OFFICIAL_ALLOCATION.read_bytes())
    assert result.kpis["field"] == 177 and result.kpis["cabinet_alarm"] == 12
    assert not any(t.tq_id == "BLANK-TAG" for t in result.tqs)
