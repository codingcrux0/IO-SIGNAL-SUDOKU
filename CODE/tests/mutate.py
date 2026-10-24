"""Helpers that read the sample MDB and rebuild altered copies of it (for tests)."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable, Sequence

import openpyxl


def read_table(path: str | Path) -> tuple[list[Any], list[list[Any]]]:
    """(headers, data rows) of the first sheet, exactly as stored (no cleaning)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = [[ws.cell(r, c).value for c in range(1, ws.max_column + 1)] for r in range(1, ws.max_row + 1)]
    wb.close()
    return rows[0], rows[1:]


def to_xlsx_bytes(headers: Sequence[Any], rows: Sequence[Sequence[Any]], sheet: str = "MDB-1",
                  extra_sheets: dict[str, tuple[Sequence[Any], Sequence[Sequence[Any]]]] | None = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    for name, (h, r) in (extra_sheets or {}).items():
        other = wb.create_sheet(name)
        other.append(list(h))
        for row in r:
            other.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def col(headers: Sequence[Any], name: str) -> int:
    """0-based index of the header called `name`."""
    return list(headers).index(name)


def mutated(path: str | Path, change: Callable[[list[Any], list[list[Any]]], None]) -> bytes:
    """Load the MDB, let `change(headers, rows)` edit it in place, return new xlsx bytes."""
    headers, rows = read_table(path)
    headers = list(headers)
    rows = [list(r) for r in rows]
    change(headers, rows)
    return to_xlsx_bytes(headers, rows)


def row_of(headers: Sequence[Any], rows: Sequence[Sequence[Any]], tag: str) -> int:
    """Index in `rows` of the signal with this exact Tag Number."""
    t = col(headers, "Tag Number")
    for i, r in enumerate(rows):
        if r[t] == tag:
            return i
    raise KeyError(tag)
