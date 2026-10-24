"""Read-only previews of every file the tool produces, so engineers can look before they download.

Pure helpers (no widgets): `preview_bytes` turns file bytes into a FilePreview (tables for
workbooks and CSV, the page for HTML, the tree for JSON, the contents list for ZIP), and
`filter_rows` / `rows_to_csv` / `to_frame` back the search box and the "download this view" button.
Previews never change a file and never raise: anything unreadable becomes a plain note.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.redline import FILLS

MAX_READ_ROWS = 50_000          # rows kept per sheet (search and CSV export work on all of them)
MAX_SHOW_ROWS = 5_000           # rows sent to the browser at once
MAX_TEXT_CHARS = 200_000
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MARK_COLUMN = "Change"
_MARK_BY_FILL = {colour.upper(): name for name, colour in FILLS.items()}
_CSV_RISKY = ("=", "+", "@", "\t", "\r")


@dataclass
class SheetPreview:
    name: str
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int                         # data rows in the sheet (may exceed len(rows))
    marks: list[str] = field(default_factory=list)   # redline colour label per row ('' = none)

    @property
    def truncated(self) -> bool:
        return self.total_rows > len(self.rows)


@dataclass
class FilePreview:
    name: str
    kind: str                               # table | html | json | zip | text | empty | unsupported
    size: int
    sheets: list[SheetPreview] = field(default_factory=list)
    html: str = ""
    data: Any = None
    text: str = ""
    entries: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _header(values: list[Any]) -> list[str]:
    """Header texts, blanks named 'Column N', duplicates numbered so every column is unique."""
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, value in enumerate(values, start=1):
        text = str(value).strip() if value is not None and str(value).strip() else f"Column {i}"
        seen[text] = seen.get(text, 0) + 1
        out.append(text if seen[text] == 1 else f"{text} ({seen[text]})")
    return out


def _blank(row: list[Any]) -> bool:
    return all(v is None or (isinstance(v, str) and not v.strip()) for v in row)


def _table(name: str, raw: list[list[Any]], marks: list[str] | None = None) -> SheetPreview:
    """First non-blank row is the header; trailing blank rows are dropped; rows padded to the header width."""
    start = next((i for i, r in enumerate(raw) if not _blank(r)), None)
    if start is None:
        return SheetPreview(name, [], [], 0)
    body = raw[start + 1:]
    body_marks = (marks or [])[start + 1:]
    while body and _blank(body[-1]):
        body.pop()
    width = max([len(raw[start])] + [len(r) for r in body[:MAX_READ_ROWS]])
    columns = _header(list(raw[start]) + [None] * (width - len(raw[start])))
    kept = [list(r) + [None] * (width - len(r)) for r in body[:MAX_READ_ROWS]]
    kept_marks = list(body_marks[:len(kept)])
    if any(kept_marks):
        kept_marks += [""] * (len(kept) - len(kept_marks))
    else:
        kept_marks = []
    return SheetPreview(name, columns, kept, len(body), kept_marks)


def _fill_mark(cell: Any) -> str:
    try:
        colour = str(cell.fill.start_color.rgb or "")
    except Exception:  # noqa: BLE001 - empty cells and themed colours have no plain RGB
        return ""
    return _MARK_BY_FILL.get(colour[-6:].upper(), "") if len(colour) >= 6 else ""


def _xlsx_sheets(data: bytes) -> list[SheetPreview]:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheets = []
        for ws in wb.worksheets:
            raw: list[list[Any]] = []
            marks: list[str] = []
            for row in ws.iter_rows():
                raw.append([getattr(c, "value", None) for c in row])
                marks.append(_fill_mark(row[0]) if row else "")
                if len(raw) > MAX_READ_ROWS + 50:
                    break
            sheet = _table(ws.title, raw, marks)
            if ws.max_row and ws.max_row - 1 > sheet.total_rows and len(raw) > MAX_READ_ROWS:
                sheet.total_rows = ws.max_row - 1
            sheets.append(sheet)
        return sheets
    finally:
        wb.close()


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _csv_sheet(data: bytes, name: str) -> SheetPreview:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    raw = []
    for row in csv.reader(io.StringIO(text), dialect):
        raw.append(row)
        if len(raw) > MAX_READ_ROWS + 50:
            break
    return _table(name, raw)


def preview_bytes(data: bytes | None, name: str) -> FilePreview:
    """A read-only preview of one file. Never raises."""
    data = data or b""
    size = len(data)
    if not data:
        return FilePreview(name, "empty", 0, note="This file is empty.")
    ext = _ext(name)
    try:
        if ext in ("xlsx", "xlsm"):
            sheets = _xlsx_sheets(data)
            return FilePreview(name, "table", size, sheets=sheets) if sheets else \
                FilePreview(name, "empty", size, note="This workbook has no sheets.")
        if ext == "csv":
            return FilePreview(name, "table", size, sheets=[_csv_sheet(data, name)])
        if ext in ("html", "htm"):
            return FilePreview(name, "html", size, html=_decode(data))
        if ext == "json":
            text = _decode(data)
            try:
                return FilePreview(name, "json", size, data=json.loads(text))
            except ValueError:
                return FilePreview(name, "text", size, text=text[:MAX_TEXT_CHARS], note="This JSON file could not be read, so it is shown as text.")
        if ext == "zip":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                entries = [{"File": i.filename, "Size": size_text(i.file_size)} for i in zf.infolist() if not i.is_dir()]
            return FilePreview(name, "zip", size, entries=entries)
        if ext in ("txt", "log", "md"):
            text = _decode(data)
            return FilePreview(name, "text", size, text=text[:MAX_TEXT_CHARS],
                               note="Only the start of this file is shown." if len(text) > MAX_TEXT_CHARS else "")
    except Exception:  # noqa: BLE001 - a broken file must never break the page
        return FilePreview(name, "unsupported", size, note="This file could not be opened for viewing. You can still download it.")
    return FilePreview(name, "unsupported", size, note="This kind of file cannot be shown in the browser. You can still download it.")


def preview_member(data: bytes, member: str) -> FilePreview:
    """Preview one file inside a ZIP (size-capped; nested HTML is shown as text, never rendered)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            info = zf.getinfo(member)
            if info.file_size > MAX_MEMBER_BYTES:
                return FilePreview(member, "unsupported", info.file_size, note="This file is too large to show here.")
            inner = zf.read(info)
    except Exception:  # noqa: BLE001
        return FilePreview(member, "unsupported", 0, note="This file could not be read from the bundle.")
    preview = preview_bytes(inner, member)
    if preview.kind == "html":
        return FilePreview(member, "text", preview.size, text=preview.html[:MAX_TEXT_CHARS])
    return preview


def size_text(n: int) -> str:
    if n < 1024:
        return f"{n:,} bytes"
    return f"{n / 1024:,.1f} KB" if n < 1024 * 1024 else f"{n / (1024 * 1024):,.1f} MB"


# ------------------------------------------------------------------- search, export, frames
def filter_rows(sheet: SheetPreview, needle: str | list[str] = "", columns: list[str] | None = None,
                mark: str = "") -> tuple[list[str], list[list[Any]], list[str]]:
    """(columns, rows, marks) after a CASE-SENSITIVE search (you get exactly the tag you typed), an optional
    column choice and an optional redline colour.  The search looks at every column, even hidden ones.
    `needle` may be several terms (for example several tags): a row is kept if it matches ANY of them."""
    terms = [needle] if isinstance(needle, str) else list(needle or [])
    texts = [t for t in (str(x or "").strip() for x in terms) if t]
    marks = sheet.marks or [""] * len(sheet.rows)

    def hit(row: list[Any]) -> bool:
        cells = [str(v) for v in row if v is not None]
        return any(t in c for t in texts for c in cells)

    picked = [(r, m) for r, m in zip(sheet.rows, marks) if (not texts or hit(r)) and (not mark or m == mark)]
    wanted = [c for c in (columns or []) if c in sheet.columns]
    if wanted:
        idx = [sheet.columns.index(c) for c in wanted]
        rows = [[r[i] for i in idx] for r, _ in picked]
    else:
        wanted, rows = list(sheet.columns), [r for r, _ in picked]
    return wanted, rows, ([m for _, m in picked] if sheet.marks else [])


def _safe_cell(value: Any) -> Any:
    """Stop spreadsheet programs from running a cell as a formula when the CSV is opened."""
    if isinstance(value, str) and value.startswith(_CSV_RISKY):
        return "'" + value
    if isinstance(value, str) and value.startswith("-"):
        try:
            float(value)
        except ValueError:
            return "'" + value
    return "" if value is None else value


def rows_to_csv(columns: list[str], rows: list[list[Any]], marks: list[str] | None = None) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    header = ([MARK_COLUMN] if marks else []) + list(columns)
    writer.writerow([_safe_cell(c) for c in header])
    for i, row in enumerate(rows):
        writer.writerow([_safe_cell(v) for v in (([marks[i]] if marks else []) + list(row))])
    return buf.getvalue().encode("utf-8-sig")


def to_frame(columns: list[str], rows: list[list[Any]], marks: list[str] | None = None):
    """A pandas DataFrame safe for st.dataframe: numeric columns stay numeric, anything mixed becomes text."""
    import pandas as pd

    header = ([MARK_COLUMN] if marks else []) + list(columns)
    body = [([marks[i]] if marks else []) + list(r) for i, r in enumerate(rows)]
    frame = pd.DataFrame(body, columns=header)
    for name in header:
        values = [v for v in frame[name] if v is not None and not (isinstance(v, str) and not v.strip())]
        numeric = bool(values) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
        if not numeric:
            frame[name] = ["" if v is None else str(v) for v in frame[name]]
    return frame


def mark_colour(mark: str) -> str:
    """Background hex for a redline label ('' when the row is unchanged)."""
    return f"#{FILLS[mark]}" if mark in FILLS else ""
