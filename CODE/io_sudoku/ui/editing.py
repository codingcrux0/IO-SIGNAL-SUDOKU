"""Edit the uploaded MDB in the browser: find a cell, change it, write it back into the SAME file.

Pure logic (no widgets), so it is testable without a browser.

  read_editable(data)          every sheet as (header row, data rows with their real Excel row numbers)
  apply_edits(data, name, ...) the same workbook / CSV with the changed cells - formatting, other sheets
                               and untouched cells are kept exactly as they were
  build_index(...)             tag / cable / room -> the row it is on (from the same reader the solver uses)
  cell_for_tq(...)             the exact cell a TQ is about (for example MISSING-PAIR -> the Pair Number cell)

Editing changes the INPUT only.  The solver, the rules and the checks are untouched: after an edit the
result is out of date (DRAFT) until the engineer re-allocates, and the new input gets a new fingerprint.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Any

from io_sudoku.core.columnmap import ColumnMatch, load_aliases
from io_sudoku.core.ingest import _csv_tables, _pick_header, _xlsx_tables, read_mdb
from io_sudoku.core.textnorm import is_blank, match_key
from io_sudoku.core.tq import TQLog

MAX_SHOWN_ROWS = 300          # rows shown at once in the table editor (search narrows it down)

# Which MDB field (see columnmap) each TQ is about, so an Edit button can open the exact cell.
FIELD_FOR_TQ: dict[str, str] = {
    "BLANK-TAG": "tag", "DUPLICATE-TAG": "tag", "ALARM-UNKNOWN-KIND": "tag",
    "MISSING-IO-TYPE": "io_type", "UNKNOWN-IO-TYPE": "io_type", "IO-TYPE-CONFLICT": "io_type2",
    "MISSING-CABLE": "cable_no", "CAPACITY-OVERFLOW": "cable_no", "PIN-UNSATISFIABLE": "cable_no",
    "SPARE-SHORTFALL": "cable_no", "HIGH-CURRENT-VERIFY": "cable_no",
    "MISSING-PAIR": "pair_no", "DUPLICATE-PAIR": "pair_no", "PAIR-BEYOND-CABLE": "pair_no",
    "BAD-CABLE-SIZE": "cable_size", "CABLE-SIZE-INFERRED": "cable_size", "CABLE-SIZE-CONFLICT": "cable_size",
    "CABLE-SIZE-ROUNDED": "cable_size", "CABLE-TOO-LARGE": "cable_size",
    "UNSUPPORTED-SEGREGATION": "segregation", "MIXED-SEGREGATION": "segregation",
    "IS-SIGNAL-UNSUPPORTED": "execution", "OUT-OF-SCOPE-SIGNAL": "service",
    "MISSING-SIGNAL-LEVEL": "signal_level", "RTD-FIELD-SIGNAL": "signal_type", "UNKNOWN-DOR-DUTY": "instrument_type",
    "NO-CABINET-FOR-ROOM": "tech_room", "TOPOLOGY-INFERRED": "tech_room", "GROUP-SPANS-ROOMS": "tech_room",
    "NO-CABINET-FOR-ALARM": "equipment", "DELETED-IN-MDB": "status",
}
_ROWS_IN_REF = re.compile(r"rows?\s+(\d+)")


@dataclass(frozen=True)
class EditSheet:
    name: str
    header_row: int                          # Excel row number of the header (1-based)
    headers: tuple[str, ...]
    rows: tuple[tuple[int, tuple[Any, ...]], ...]   # (Excel row number, cell values)

    def row(self, number: int) -> tuple[Any, ...] | None:
        for excel_row, values in self.rows:
            if excel_row == number:
                return values
        return None


@dataclass(frozen=True)
class CellEdit:
    sheet: str
    row: int            # Excel row number (1-based)
    col: int            # column position (0-based)
    header: str
    old: Any
    new: Any


@dataclass(frozen=True)
class Target:
    """Where an Edit button should open the editor.  col None = the whole row; row None = search only."""
    sheet: str | None
    row: int | None
    col: int | None
    search: str
    why: str


def _header_text(value: Any, index: int) -> str:
    text = "" if value is None else str(value).strip()
    return text or f"Column {index + 1}"


def read_editable(data: bytes) -> list[EditSheet]:
    """Every non-empty sheet with its header row and data rows.  Never raises (unreadable -> [])."""
    try:
        tables = _xlsx_tables(data) if data[:2] == b"PK" else _csv_tables(data)
        aliases = load_aliases()
    except Exception:  # noqa: BLE001
        return []
    sheets: list[EditSheet] = []
    for name, rows in tables:
        if not any(any(not is_blank(c) for c in r) for r in rows):
            continue
        header_index, _ = _pick_header(rows, aliases, None)
        width = max((len(r) for r in rows), default=0)
        header = list(rows[header_index]) + [None] * (width - len(rows[header_index]))
        headers, seen = [], set()
        for i, cell in enumerate(header):
            text = _header_text(cell, i)
            while text in seen:                          # duplicate headers would break the table editor
                text += " "
            seen.add(text)
            headers.append(text)
        body = tuple((i + 1, tuple(r) + (None,) * (width - len(r))) for i, r in enumerate(rows)
                     if i > header_index and any(not is_blank(c) for c in r))
        sheets.append(EditSheet(name, header_index + 1, tuple(headers), body))
    return sheets


def find_rows(sheet: EditSheet, needle: str = "", row_number: int | None = None) -> list[tuple[int, tuple[Any, ...]]]:
    """Rows containing `needle` (any cell, case-insensitive), or the one row asked for."""
    if row_number:
        return [r for r in sheet.rows if r[0] == row_number]
    text = (needle or "").strip().casefold()
    if not text:
        return list(sheet.rows)
    return [r for r in sheet.rows if any(text in str(v).casefold() for v in r[1] if v is not None)]


def typed_value(text: Any, old: Any) -> Any:
    """What to store: '' -> empty; a number stays a number if the old cell was one; otherwise text."""
    if text is None:
        return None
    raw = str(text)
    if raw.strip() == "":
        return None
    if isinstance(old, (int, float)) and not isinstance(old, bool):
        try:
            number = float(raw.strip())
            return int(number) if number.is_integer() and isinstance(old, int) else number
        except ValueError:
            pass
    return raw


def same(a: Any, b: Any) -> bool:
    """True if two cell values show the same thing (None, '' and NaN all mean empty)."""
    def norm(v: Any) -> str:
        if v is None or (isinstance(v, float) and v != v):
            return ""
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    return norm(a) == norm(b)


def apply_edits(data: bytes, name: str, edits: list[CellEdit]) -> bytes:
    """The file with these cells changed.  Raises ValueError if the file cannot be written back."""
    if not edits:
        return data
    if data[:2] == b"PK":
        import openpyxl
        keep_vba = str(name).lower().endswith(".xlsm")
        wb = openpyxl.load_workbook(io.BytesIO(data), keep_vba=keep_vba)
        for e in edits:
            if e.sheet not in wb.sheetnames:
                raise ValueError(f"sheet {e.sheet!r} not found")
            wb[e.sheet].cell(row=e.row, column=e.col + 1).value = e.new
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text, encoding = data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = data.decode("latin-1"), "latin-1"
    first = text.splitlines()[0] if text.strip() else ""
    delimiter = max(",;\t|", key=first.count)
    grid = [list(r) for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    for e in edits:
        while len(grid) < e.row:
            grid.append([])
        line = grid[e.row - 1]
        line.extend([""] * (e.col + 1 - len(line)))
        line[e.col] = "" if e.new is None else str(e.new)
    out = io.StringIO()
    csv.writer(out, delimiter=delimiter, lineterminator="\r\n").writerows(grid)
    body = out.getvalue().encode(encoding)
    return (b"\xef\xbb\xbf" + body) if bom and encoding == "utf-8" else body


# ------------------------------------------------------------------ TQ -> cell
@dataclass(frozen=True)
class RowIndex:
    tags: dict[str, tuple[str, int]]        # tag match key -> (sheet, row)
    cables: dict[str, tuple[str, int]]      # first row of each cable
    rooms: dict[str, tuple[str, int]]       # first row of each technical room
    mapping: dict[str, ColumnMatch]


def build_index(data: bytes, column_overrides: dict[str, str] | None = None,
                io_aliases: dict[str, str] | None = None) -> RowIndex:
    """Where every tag, cable and room is in the file (read with the solver's own reader)."""
    ing = read_mdb(data, TQLog(), column_overrides, io_aliases)
    tags: dict[str, tuple[str, int]] = {}
    cables: dict[str, tuple[str, int]] = {}
    rooms: dict[str, tuple[str, int]] = {}
    for sig in sorted(ing.signals + ing.alarms + ing.deleted, key=lambda s: (s.sheet, s.row_ref)):
        where = (sig.sheet, sig.row_ref)
        if sig.key:
            tags.setdefault(sig.key, where)
        if sig.cable_no:
            cables.setdefault(match_key(sig.cable_no) or "", where)
        if sig.tech_room:
            rooms.setdefault(match_key(sig.tech_room) or "", where)
    return RowIndex(tags, cables, rooms, ing.mapping)


def cell_for_tq(tq_id: str, ref: str, index: RowIndex, quarantined: list[Any] | None = None, nth: int = 0) -> Target:
    """The cell a TQ is about.  Falls back to the whole row, then to a search for the reference."""
    why = f"{tq_id} · {ref or '(no tag)'}"
    field = FIELD_FOR_TQ.get(tq_id)
    match = index.mapping.get(field) if field else None
    col = match.index if match is not None else None
    key = match_key(ref) or ""
    where: tuple[str, int] | None = None
    # a quarantined signal knows its own row; the nth TQ with the same id and tag is the nth such row
    # (this tells apart two rows with the same tag, or several rows with no tag)
    same_kind = [q.signal for q in (quarantined or []) if q.tq_id == tq_id and (match_key(q.signal.tag) or "") == key]
    if same_kind:
        sig = same_kind[min(nth, len(same_kind) - 1)]
        where = (sig.sheet, sig.row_ref)
    if where is None:
        where = index.tags.get(key) or index.cables.get(key) or index.rooms.get(key)
    if where is None and tq_id in ("ROW-REALIGNED", "ROW-MISALIGNED"):
        found = _ROWS_IN_REF.search(ref or "")
        sheet = re.search(r"sheet '([^']*)'", ref or "")
        if found and sheet:
            return Target(sheet.group(1), int(found.group(1)), None, "", why)
    if where is None:
        return Target(None, None, None, ref or "", why)
    return Target(where[0], where[1], col, "", why)
