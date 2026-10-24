"""Smoke test: the sample files are in place and look the way the audit found."""
from __future__ import annotations

from pathlib import Path

import openpyxl

DATA = Path(__file__).resolve().parents[1] / "io_sudoku" / "data"


def test_fixtures_exist(mdb_path, alloc_path):
    assert mdb_path.exists()
    assert alloc_path.exists()


def test_template_has_76_header_cells():
    wb = openpyxl.load_workbook(DATA / "Blank_IO_Allocation_Template.xlsx")
    ws = wb["IO Assignment"]
    headers = [ws.cell(1, c).value for c in range(1, 200) if ws.cell(1, c).value is not None]
    assert len(headers) == 76
    assert headers[0] == "Sr. No."
    assert headers[-1] == "Section / Sub Unit"
