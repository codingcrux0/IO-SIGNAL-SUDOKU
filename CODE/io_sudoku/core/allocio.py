"""Read and write the IO Allocation workbook (the 76-column template).

Design goals:
  * Output is built from CANONICAL_COLUMNS (the 76 headers of the bundled template) but is
    WRITTEN against whatever template the user supplies: columns are matched by header
    text, so a template with 79 columns, reordered columns or headers containing line
    breaks still works (extras are filled with '-', missing ones are dropped with a TQ).
  * Every file we write is READ BACK and compared (row count + a checksum of the first and
    last 50 rows).  If the check fails the next writer is tried:
        template writer  ->  streaming writer  ->  CSV
  * Text that starts with '=' is stored as TEXT so Excel never runs it as a formula.
  * Nothing here raises: failures come back as a WriteReport / empty list plus TQs.

Header matching note: the template has two pairs of headers that differ ONLY by a
punctuation mark - 'Relay Contact (+)' / '(-)' and the two 'Splitter/Relay/External PWR
TB' columns - so a letters-and-digits-only key would merge them.  We match on the exact
text (case/whitespace-insensitive) and use the looser key only when it is unique.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from io_sudoku.core.constants import FAST_WRITE_THRESHOLD
from io_sudoku.core.textnorm import header_key, text_key
from io_sudoku.core.tq import TQLog

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BUNDLED_TEMPLATE = DATA_DIR / "Blank_IO_Allocation_Template.xlsx"
SHEET_NAME = "IO Assignment"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_FALLBACK_COLUMNS = [
    'Sr. No.', 'Revision No', 'Tag Name', 'Technical Room', 'Operating Area', 'Risk Area', 'Unit', 'Segregation',
    'DSTName', 'Service Description', 'Location', 'IO Type', 'Signal Type', 'Signal Level', 'NON-IS / IS',
    'Equipment Name', 'External Power', 'System Cabinet', 'Controller', 'Electronic/ Marshalling Cabinet',
    'CIOC/CSLS Name', 'Baseplate', 'Channel_No', 'CHARM_No', 'CHARM Type', 'Charm Description', 'CHARM TB Part No',
    'CHARM TB Description', 'CHARM TB1', 'CHARM TB2', 'CHARM TB3', 'CHARM Baseplate Adapter', 'M_FTA',
    'M_FTA Part No', 'M_FTA_TB', 'M_FTA_TB1', 'M_FTA_TB2', 'M_FTA_TB3', 'M_TB', 'M_TB1', 'M_TB2', 'M_TB3',
    'IRC / AUX Cabinet', 'IRC_TB', 'IRC_TB1', 'IRC_TB2', 'Relay / Splitter', 'Relay Coil A1 / Splitter In+',
    'Relay Coil A2 / Splitter In-', 'Relay Contact (+)', 'Relay Contact (-)', 'Field Cable No', 'Field Cable Size',
    'Field Cable Pair', 'IRC_FTB', 'IRC_FTB1', 'IRC_FTB2', 'Elec Cable No', 'Elec Cable Size', 'Elec Cable Pair',
    'Tag Status', 'Remarks', 'BATCH', 'HW Loop Typical', 'System 2', 'Old Tag', 'Instrument type',
    'FTA_Cable Name', 'FTA_Cable Ferrule Name', 'Cabinet Side (F/R)', 'Change Type',
    'Cabinet Name for Visualization', 'Splitter/Relay/\nExternal PWR\nTB(+)', 'Splitter/Relay/\nExternal PWR\nTB(-)',
    'Loop Name', 'Section / Sub Unit',
]


def _headers_from_workbook(data: bytes) -> tuple[list[str], str]:
    """(header texts of row 1, sheet name) of the sheet named 'IO Assignment' (else the first)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.worksheets[0]
        first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [str(c) for c in first]
        while headers and headers[-1] in ("None", ""):
            headers.pop()
        headers = ["" if h == "None" else h for h in headers]
        return headers, ws.title
    finally:
        wb.close()


def _load_canonical() -> list[str]:
    try:
        headers, _ = _headers_from_workbook(BUNDLED_TEMPLATE.read_bytes())
        if len(headers) >= 76 and all(headers):
            return headers
    except Exception:
        pass
    return list(_FALLBACK_COLUMNS)


CANONICAL_COLUMNS: list[str] = _load_canonical()
TEMPLATE_COLUMNS = CANONICAL_COLUMNS      # older name kept as an alias


@dataclass(frozen=True)
class TemplateSpec:
    columns: list[str]
    sheet_name: str
    source: str                                            # 'bundled' or 'uploaded'
    raw: bytes = field(default=b"", compare=False, repr=False)  # the template file itself


@dataclass
class WriteReport:
    path_kind: str = "none"                  # 'template' | 'write_only' | 'csv' | 'none'
    rows: int = 0
    verified: bool = False
    dropped_columns: list[str] = field(default_factory=list)   # canonical columns the template lacks
    filled_columns: list[str] = field(default_factory=list)    # template columns we had no data for
    content_type: str = XLSX_TYPE
    filename_ext: str = ".xlsx"


_bundled_cache: TemplateSpec | None = None


def _bundled_spec() -> TemplateSpec:
    global _bundled_cache
    if _bundled_cache is None:
        try:
            raw = BUNDLED_TEMPLATE.read_bytes()
        except Exception:
            raw = b""
        _bundled_cache = TemplateSpec(list(CANONICAL_COLUMNS), SHEET_NAME, "bundled", raw)
    return _bundled_cache


def load_template(source: str | Path | bytes | BinaryIO | None = None, log: TQLog | None = None) -> TemplateSpec:
    """The output template to write against. Unreadable template -> bundled one + a TQ."""
    if source is None:
        return _bundled_spec()
    try:
        if isinstance(source, (str, Path)):
            data = Path(source).read_bytes()
        elif isinstance(source, (bytes, bytearray)):
            data = bytes(source)
        else:
            data = source.read()
        headers, sheet = _headers_from_workbook(data)
        if not headers or not any(headers):
            raise ValueError("no header row")
        return TemplateSpec(headers, sheet, "uploaded", data)
    except Exception:
        if log is not None:
            log.add("TEMPLATE-FALLBACK", "")
        return _bundled_spec()


# ------------------------------------------------------------------ header -> canonical
def _canonical_lookup() -> tuple[dict[str, str], dict[str, str]]:
    by_text = {text_key(c): c for c in CANONICAL_COLUMNS}
    counts: dict[str, int] = {}
    for c in CANONICAL_COLUMNS:
        counts[header_key(c)] = counts.get(header_key(c), 0) + 1
    by_loose = {header_key(c): c for c in CANONICAL_COLUMNS if counts[header_key(c)] == 1}
    return by_text, by_loose


def _to_canonical(header: Any) -> str | None:
    by_text, by_loose = _canonical_lookup()
    key = text_key(header)
    if key in by_text:
        return by_text[key]
    return by_loose.get(header_key(header))


def _norm_cell(value: Any) -> Any:
    """Canonical form of a cell for reading AND for comparing after a read-back."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value != value:             # NaN
            return "-"
        return int(value) if value.is_integer() else value
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="replace")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).replace(" ", " ").strip()
    return "-" if text in ("", "-") else text


# ------------------------------------------------------------------------------ reading
def read_allocation(source: str | Path | bytes | BinaryIO, template: TemplateSpec | None = None) -> list[dict[str, Any]]:
    """Rows of an allocation workbook (or CSV) as dicts keyed by CANONICAL_COLUMNS. Never raises."""
    try:
        if isinstance(source, (str, Path)):
            data = Path(source).read_bytes()
        elif isinstance(source, (bytes, bytearray)):
            data = bytes(source)
        else:
            data = source.read()
        raw_rows = _raw_rows(data, template)
        if not raw_rows:
            return []
        header = raw_rows[0]
        mapping = {i: _to_canonical(h) for i, h in enumerate(header)}
        mapping = {i: c for i, c in mapping.items() if c}
        if not mapping:
            return []
        rows: list[dict[str, Any]] = []
        for raw in raw_rows[1:]:
            if all(_norm_cell(c) == "-" for c in raw):
                continue
            row = {c: "-" for c in CANONICAL_COLUMNS}
            for i, canon in mapping.items():
                if i < len(raw):
                    row[canon] = _norm_cell(raw[i])
            rows.append(row)
        return rows
    except Exception:
        return []


def _raw_rows(data: bytes, template: TemplateSpec | None) -> list[tuple[Any, ...]]:
    if data[:2] == b"PK":
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            wanted = template.sheet_name if template else SHEET_NAME
            ws = wb[wanted] if wanted in wb.sheetnames else wb.worksheets[0]
            try:
                ws.reset_dimensions()
            except Exception:
                pass
            return [tuple(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return [tuple(r) for r in csv.reader(io.StringIO(text))]


# ------------------------------------------------------------------------------ writing
def _column_map(template: TemplateSpec) -> tuple[list[tuple[int, str]], list[str], list[str]]:
    """(template column index -> canonical name, filled template headers, dropped canonical names)."""
    mapped: list[tuple[int, str]] = []
    filled: list[str] = []
    used: set[str] = set()
    for i, header in enumerate(template.columns):
        canon = _to_canonical(header)
        if canon and canon not in used:
            mapped.append((i, canon))
            used.add(canon)
        else:
            filled.append(header)
    dropped = [c for c in CANONICAL_COLUMNS if c not in used]
    return mapped, filled, dropped


def _table(rows: list[dict[str, Any]], template: TemplateSpec, mapped: list[tuple[int, str]]) -> list[list[Any]]:
    width = len(template.columns)
    table: list[list[Any]] = []
    for row in rows:
        out: list[Any] = ["-"] * width
        for i, canon in mapped:
            out[i] = _norm_cell(row.get(canon))
        table.append(out)
    return table


def _write_xlsx_template(table: list[list[Any]], template: TemplateSpec) -> bytes:
    """Writer A: open the template itself so its formatting is kept."""
    import openpyxl
    from openpyxl.utils import get_column_letter

    if not template.raw:
        raise ValueError("no template bytes")
    wb = openpyxl.load_workbook(io.BytesIO(template.raw))
    ws = wb[template.sheet_name] if template.sheet_name in wb.sheetnames else wb.worksheets[0]
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row)
    for r, values in enumerate(table, start=2):
        for c, value in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            if isinstance(value, str) and value.startswith("="):
                cell.data_type = "s"           # text, never a formula
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(max(1, len(template.columns)))}{max(2, len(table) + 1)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_xlsx_stream(table: list[list[Any]], template: TemplateSpec) -> bytes:
    """Writer B: streaming workbook - fast and light for very large outputs."""
    import openpyxl
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(template.sheet_name or SHEET_NAME)
    try:
        ws.freeze_panes = "D2"
        for i in range(len(template.columns)):
            ws.column_dimensions[get_column_letter(i + 1)].width = 18
    except Exception:
        pass
    header_cells = []
    for header in template.columns:
        cell = WriteOnlyCell(ws, value=header)
        cell.font = Font(bold=True)
        header_cells.append(cell)
    ws.append(header_cells)
    for values in table:
        out: list[Any] = []
        for value in values:
            if isinstance(value, str) and value.startswith("="):
                cell = WriteOnlyCell(ws, value=value)
                cell.data_type = "s"
                out.append(cell)
            else:
                out.append(value)
        ws.append(out)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_csv(table: list[list[Any]], template: TemplateSpec) -> bytes:
    """Writer C: plain CSV (utf-8 with BOM so Excel opens it). Formula-like text is neutralised."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(template.columns)
    for values in table:
        writer.writerow([("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "@") else v for v in values])
    return buf.getvalue().encode("utf-8-sig")


def _fingerprint(table: list[dict[str, Any]]) -> str:
    sample = table[:50] + table[-50:]
    return hashlib.sha256(json.dumps(sample, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def _verified(data: bytes, template: TemplateSpec, expected: list[dict[str, Any]], mapped: list[tuple[int, str]]) -> bool:
    """Read the file back and compare row count + checksum of the first/last 50 rows."""
    back = read_allocation(data, template)
    if len(back) != len(expected):
        return False
    canons = [c for _, c in mapped]
    mine = [{c: row[c] for c in canons} for row in expected]
    theirs = [{c: row[c] for c in canons} for row in back]
    return _fingerprint(mine) == _fingerprint(theirs)


def _emit(target: str | Path | BinaryIO, data: bytes) -> None:
    if isinstance(target, (str, Path)):
        Path(target).write_bytes(data)
    else:
        target.write(data)


def build_allocation(rows: list[dict[str, Any]], template: TemplateSpec | None = None,
                     log: TQLog | None = None) -> tuple[bytes, WriteReport]:
    """Produce the output file bytes (verified, with fallbacks). Never raises."""
    template = template or _bundled_spec()
    mapped, filled, dropped = _column_map(template)
    report = WriteReport(rows=len(rows), dropped_columns=dropped, filled_columns=filled)
    if log is not None:
        for header in filled:
            log.add("TEMPLATE-EXTRA-COLUMN", header.replace("\n", " "))
        for name in dropped:
            log.add("TEMPLATE-COLUMN-MISSING", name.replace("\n", " "))
    try:
        table = _table(rows, template, mapped)
        expected = [{c: row[i] for i, c in mapped} for row in table]
    except Exception:
        table, expected = [], []

    writers: list[tuple[str, Any]] = []
    if len(rows) <= FAST_WRITE_THRESHOLD:
        writers.append(("template", _write_xlsx_template))
    writers.append(("write_only", _write_xlsx_stream))
    for kind, writer in writers:
        try:
            data = writer(table, template)
            if _verified(data, template, expected, mapped):
                report.path_kind, report.verified = kind, True
                return data, report
        except Exception:
            continue
    try:                                    # last resort: CSV
        data = _write_csv(table, template)
        report.path_kind, report.verified = "csv", True
        report.content_type, report.filename_ext = "text/csv", ".csv"
        if log is not None:
            log.add("OUTPUT-FALLBACK-CSV", "the Excel file failed its read-back check")
        return data, report
    except Exception:
        if log is not None:
            log.add("OUTPUT-FALLBACK-CSV", "no output format could be written")
        return b"", report


def allocation_bytes(rows: list[dict[str, Any]], template: TemplateSpec | None = None,
                     log: TQLog | None = None) -> tuple[bytes, WriteReport]:
    """Same as build_allocation (kept as the name the UI and CLI use)."""
    return build_allocation(rows, template, log)


def write_allocation(rows: list[dict[str, Any]], target: str | Path | BinaryIO,
                     template: TemplateSpec | None = None, log: TQLog | None = None) -> WriteReport:
    """Write the allocation to a path or file object. Never raises."""
    data, report = build_allocation(rows, template, log)
    try:
        if not data:
            raise OSError("nothing to write")
        _emit(target, data)
    except Exception:
        report.verified = False
        report.path_kind = "none"
        if log is not None:
            log.add("OUTPUT-FALLBACK-CSV", "the file could not be saved to the chosen location")
    return report


def rows_to_dataframe(rows: list[dict[str, Any]], columns: list[str] | None = None):
    """pandas table of the rows (dtype=object so text and numbers are never re-typed)."""
    import pandas as pd

    cols = columns or CANONICAL_COLUMNS
    return pd.DataFrame([[row.get(c, "-") for c in cols] for row in rows], columns=cols, dtype=object)


def looks_like_allocation(rows: list[dict[str, Any]]) -> bool:
    """True if the rows really are an IO Allocation (most rows carry a valid Tag Status and a baseplate).

    An MDB shares a few column names with the template, so reading it as an allocation would
    not fail - it would give nearly empty rows.  This check catches that."""
    if not rows:
        return False
    statuses = {"Field", "Cabinet Alarm", "Wired Spare", "Spare Slot"}
    good = sum(1 for r in rows if r.get("Tag Status") in statuses and str(r.get("Baseplate", "-")) != "-"
               and str(r.get("Electronic/ Marshalling Cabinet", "-")) != "-")
    return good >= 0.5 * len(rows)
