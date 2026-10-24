"""Read the customer IO MDB (Excel or CSV) into clean Signal objects - never crashing.

What this module guarantees:
  * ANY input (corrupt file, empty bytes, old .xls, huge file, wrong columns) produces
    an IngestResult - possibly empty - plus TQs explaining what happened.
  * Cells are read one by one; the file's declared range / autofilter is NOT trusted
    (in the sample MDB the last 12 rows lie outside the autofilter).
  * Text is cleaned with textnorm (ends stripped, inner spaces of tags kept).
  * IO types are normalised (AI/DI/DO/AO -> AIR/DIR/DOR/AOR).
  * Rows marked DELETED are set aside; Cabinet Diagnostic Alarm rows go to `alarms`.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from io_sudoku.core.columnmap import ColumnMatch, load_aliases, map_columns, missing_mandatory
from io_sudoku.core.constants import IO_TYPES, MAX_DATA_ROWS, MAX_FILE_BYTES
from io_sudoku.core.models import Signal
from io_sudoku.core.textnorm import clean, is_blank, match_key, normalise_io_type, to_int
from io_sudoku.core.tq import TQLog

_OLE_MAGIC = b"\xd0\xcf\x11\xe0"
_CSV_DELIMITERS = ",;\t|"
_HEADER_SEARCH_ROWS = 10      # the header row is one of the first non-empty rows


@dataclass
class IngestResult:
    signals: list[Signal] = field(default_factory=list)   # normal field signals
    alarms: list[Signal] = field(default_factory=list)    # Cabinet Diagnostic Alarm rows
    deleted: list[Signal] = field(default_factory=list)   # rows marked DELETED (excluded)
    rows_read: int = 0                                    # non-blank data rows seen
    mapping: dict[str, ColumnMatch] = field(default_factory=dict)
    sheets_used: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def _new_stats() -> dict[str, int]:
    return {"whitespace_fixed": 0, "io_alias_fixed": 0, "deleted_excluded": 0,
            "io_type2_rows": 0, "blank_rows_skipped": 0}


def empty_result() -> IngestResult:
    return IngestResult(stats=_new_stats())


# ------------------------------------------------------------------ getting the bytes
def _get_bytes(source: str | Path | bytes | BinaryIO) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    if hasattr(source, "read"):
        data = source.read()
        if hasattr(source, "seek"):
            try:
                source.seek(0)
            except Exception:
                pass
        return data if isinstance(data, bytes) else bytes(data)
    raise ValueError("unsupported source type")


# --------------------------------------------------------------- reading raw tables
def _xlsx_tables(data: bytes) -> list[tuple[str, list[tuple[Any, ...]]]]:
    """Return [(sheet name, rows)] for every worksheet. Rows keep Excel row numbering."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    tables: list[tuple[str, list[tuple[Any, ...]]]] = []
    try:
        for ws in wb.worksheets:
            try:
                ws.reset_dimensions()          # the declared range may be wrong
            except Exception:
                pass
            rows: list[tuple[Any, ...]] = []
            for row in ws.iter_rows(values_only=True):
                rows.append(tuple(row))
                if len(rows) > MAX_DATA_ROWS + 50:
                    break
            tables.append((ws.title, rows))
    finally:
        wb.close()
    return tables


def _csv_tables(data: bytes) -> list[tuple[str, list[tuple[Any, ...]]]]:
    """Parse a CSV file; raises ValueError if it does not look like a table."""
    if b"\x00" in data[:2048]:
        raise ValueError("binary data")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    first_line = text.splitlines()[0] if text.strip() else ""
    counts = {d: first_line.count(d) for d in _CSV_DELIMITERS}
    delimiter = max(counts, key=lambda d: counts[d])
    if counts[delimiter] == 0:
        raise ValueError("no delimiter")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [("csv", [tuple(row) for row in reader])]


# ------------------------------------------------------------------ one sheet -> signals
def _pick_header(rows: list[tuple[Any, ...]], aliases: dict[str, list[str]],
                 overrides: dict[str, str] | None) -> tuple[int, dict[str, ColumnMatch]]:
    """Index of the header row and its column mapping.

    Normally row 0. If a sheet starts with title rows, one of the first few non-empty
    rows that satisfies all mandatory fields wins; otherwise the first non-empty row.
    """
    first_nonblank = None
    seen = 0
    for i, row in enumerate(rows):
        if all(is_blank(c) for c in row):
            continue
        mapping = map_columns(list(row), aliases, overrides)
        if first_nonblank is None:
            first_nonblank = (i, mapping)
        if not missing_mandatory(mapping):
            return i, mapping
        seen += 1
        if seen >= _HEADER_SEARCH_ROWS:
            break
    if first_nonblank is not None:
        return first_nonblank
    return 0, map_columns([], aliases, overrides)


def _build_signal(row: tuple[Any, ...], excel_row: int, sheet: str, mapping: dict[str, ColumnMatch],
                  extra_io_aliases: dict[str, str] | None, stats: dict[str, int]) -> Signal:
    def raw(name: str) -> Any:
        match = mapping.get(name)
        if match is None or match.index is None or match.index >= len(row):
            return None
        return row[match.index]

    def text(name: str) -> str | None:
        value = raw(name)
        cleaned = clean(value)
        if cleaned is not None and isinstance(value, str) and value != value.strip():
            stats["whitespace_fixed"] += 1
        return cleaned

    tag = text("tag") or ""
    io_raw = clean(raw("io_type"))
    io_type = normalise_io_type(raw("io_type"), extra_io_aliases)
    if io_raw is not None and io_type in IO_TYPES and io_raw.upper() != io_type:
        stats["io_alias_fixed"] += 1
    io_type2 = normalise_io_type(raw("io_type2"), extra_io_aliases)
    if io_type2 is not None:
        stats["io_type2_rows"] += 1

    cable_no = text("cable_no")
    cable_size = text("cable_size")
    pair_text = text("pair_no")
    pair_no = to_int(raw("pair_no"))
    instrument_type = text("instrument_type")
    is_alarm = bool(instrument_type and "cabinet diagnostic alarm" in instrument_type.casefold())
    if is_alarm and cable_no and cable_no.casefold() == "internal wiring":
        # internal cabinet wiring has no field cable and no pair
        cable_no, cable_size, pair_text, pair_no = None, None, None, None

    return Signal(
        row_ref=excel_row, sheet=sheet, tag=tag, key=match_key(tag) or "",
        io_type=io_type, io_type2=io_type2,
        signal_type=text("signal_type"), signal_level=text("signal_level"),
        execution=text("execution"), ext_power=text("ext_power"),
        segregation=text("segregation"), logic_no=text("logic_no"),
        tech_room=text("tech_room"), operating_area=text("operating_area"),
        risk_area=text("risk_area"), unit=to_int(raw("unit")),
        location=text("location"), equipment=text("equipment"),
        cable_no=cable_no, cable_size=cable_size, pair_no=pair_no, pair_text=pair_text,
        service=text("service"), instrument_type=instrument_type,
        instrument_code=text("instrument_code"), loop_name=text("loop_name"),
        old_tag=text("old_tag"), system2=text("system2"), status=text("status"),
        is_alarm=is_alarm,
    )


def _read_table(sheet: str, rows: list[tuple[Any, ...]], mapping: dict[str, ColumnMatch], header_index: int,
                extra_io_aliases: dict[str, str] | None, result: IngestResult, log: TQLog) -> None:
    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if all(is_blank(c) for c in row):
            result.stats["blank_rows_skipped"] += 1
            continue
        result.rows_read += 1
        if result.rows_read > MAX_DATA_ROWS:
            return
        signal = _build_signal(row, offset, sheet, mapping, extra_io_aliases, result.stats)
        status = (signal.status or "").casefold()
        if status == "deleted":
            result.deleted.append(signal)
            result.stats["deleted_excluded"] += 1
            log.add("DELETED-IN-MDB", signal.tag)
        elif signal.is_alarm:
            result.alarms.append(signal)
        else:
            result.signals.append(signal)


# ------------------------------------------------------------------------ public API
def read_mdb(source: str | Path | bytes | BinaryIO, log: TQLog,
             column_overrides: dict[str, str] | None = None,
             extra_io_aliases: dict[str, str] | None = None) -> IngestResult:
    """Read an MDB. Never raises: problems become TQs and an (empty) result."""
    result = empty_result()
    try:
        data = _get_bytes(source)
        if len(data) > MAX_FILE_BYTES:
            log.add("FILE-TOO-LARGE", "")
            return result
        if not data:
            log.add("UNREADABLE-FILE", "", "The file is empty. Can you upload it again?")
            return result
        if data[:4] == _OLE_MAGIC:
            log.add("UNSUPPORTED-FORMAT", "")
            return result
        tables = _xlsx_tables(data) if data[:2] == b"PK" else _csv_tables(data)
    except Exception:
        log.add("UNREADABLE-FILE", "")
        return empty_result()

    try:
        aliases = load_aliases()
        usable: list[tuple[str, list[tuple[Any, ...]], int, dict[str, ColumnMatch]]] = []
        first_mapping: dict[str, ColumnMatch] = {}
        for name, rows in tables:
            header_index, mapping = _pick_header(rows, aliases, column_overrides)
            if not first_mapping:
                first_mapping = mapping
            if not missing_mandatory(mapping) and len(rows) > header_index:
                usable.append((name, rows, header_index, mapping))
        if not usable:
            result.mapping = first_mapping
            for fld in missing_mandatory(first_mapping) or ["tag"]:
                log.add("MISSING-COLUMN", fld)
            return result

        result.mapping = usable[0][3]
        for name, rows, header_index, mapping in usable:
            result.sheets_used.append(name)
            _read_table(name, rows, mapping, header_index, extra_io_aliases, result, log)
            if result.rows_read > MAX_DATA_ROWS:
                log.add("TOO-MANY-ROWS", "")
                return empty_result()
        if len(usable) > 1:
            log.add("MULTI-SHEET-USED", ", ".join(result.sheets_used))
        for fld, match in result.mapping.items():
            if match.method == "fuzzy":
                log.add("COLUMN-FUZZY-MATCHED", fld,
                        f"The column for {fld} was guessed as '{match.header}' (score {match.score}). Is that right?")
        return result
    except Exception:
        log.add("UNREADABLE-FILE", "")
        return empty_result()
