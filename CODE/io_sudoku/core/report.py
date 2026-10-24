"""Excel reports: the TQ register, the verification list and the revision impact report.

Every function returns BYTES (so Streamlit can offer them as downloads with nothing written
to disk) and has a write_* twin that saves to a path or file object.  Reports never raise: if
building one fails, a workbook with a single explanatory sheet is returned instead.
Text that begins with '=' is stored as text so Excel never runs it as a formula.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, BinaryIO, Sequence

from io_sudoku.core.models import Quarantined, Violation
from io_sudoku.core.tq import TQ
from io_sudoku.core.tqlife import TQDiff, tq_key

_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _workbook_bytes(sheets: list[tuple[str, Sequence[str], Sequence[Sequence[Any]]]]) -> bytes:
    """A workbook with the given (name, headers, rows) sheets; bold header, frozen, filtered."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    for name, headers, rows in sheets:
        ws = wb.create_sheet(name[:31])
        ws.append(list(headers))
        for cell in ws[1]:
            cell.font = Font(bold=True)
        widths = [len(str(h)) + 2 for h in headers]
        for row in rows:
            ws.append([("" if v is None else v) for v in row])
            for i, v in enumerate(row[: len(widths)]):
                widths[i] = min(60, max(widths[i], len(str(v)) + 2))
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cell.data_type = "s"                      # text, never a formula
                if isinstance(cell.value, str) and len(cell.value) > 60:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        for i, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = width
        ws.freeze_panes = "A2"
        if headers:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(2, len(rows) + 1)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _safe(build) -> bytes:
    try:
        return build()
    except Exception as exc:  # noqa: BLE001 - reports must never take the app down
        return _workbook_bytes([("Report", ["Message"], [[f"This report could not be built ({type(exc).__name__}). "
                                                           "Please download the support bundle and report it."]])])


def _emit(target: str | Path | BinaryIO, data: bytes) -> None:
    if isinstance(target, (str, Path)):
        Path(target).write_bytes(data)
    else:
        target.write(data)


# ----------------------------------------------------------------------------- TQ register
def tq_register_bytes(tqs: list[TQ], quarantined: list[Quarantined] | None = None, diff: TQDiff | None = None,
                      assumptions: list[Any] | None = None) -> bytes:
    def build() -> bytes:
        ordered = sorted(enumerate(tqs), key=lambda item: (_SEVERITY_RANK.get(item[1].severity, 3), item[0]))
        status: dict[tuple[str, str], str] = {}
        if diff is not None:
            for t in diff.still_open:
                status[tq_key(t)] = "Open"
            for t in diff.new:
                status[tq_key(t)] = "New"
        headers = ["TQ No", "ID", "Severity", "Category", "Owner", "Reference", "Question", "Suggested Resolution"]
        rows: list[list[Any]] = []
        for number, (_, t) in enumerate(ordered, start=1):
            row = [f"TQ-{number:04d}", t.tq_id, t.severity, t.category, t.owner, t.ref, t.message, t.resolution]
            if diff is not None:
                row.append(status.get(tq_key(t), "Open"))
            rows.append(row)
        if diff is not None:
            headers.append("Status")
            for t in diff.resolved:
                rows.append([f"TQ-{len(rows) + 1:04d}", t.tq_id, t.severity, t.category, t.owner, t.ref, t.message,
                             t.resolution, "Resolved"])
        quarantine_rows = [[q.signal.tag, q.signal.sheet, q.signal.row_ref, q.tq_id, q.signal.cable_no or "-",
                            q.signal.pair_text or "-", q.signal.io_type or "-"] for q in (quarantined or [])]
        sheets = [("TQ Register", headers, rows),
                  ("Quarantined Signals", ["Tag", "Sheet", "MDB Row", "TQ ID", "Cable", "Pair", "IO Type"], quarantine_rows)]
        if assumptions is not None:
            sheets.append(("Assumptions", ["ID", "Assumption", "Source", "Confirm By"],
                           [[a.id, a.text, a.source, a.confirm_by] for a in assumptions]))
        return _workbook_bytes(sheets)
    return _safe(build)


def write_tq_register(tqs: list[TQ], quarantined: list[Quarantined] | None, target: str | Path | BinaryIO,
                      diff: TQDiff | None = None, assumptions: list[Any] | None = None) -> None:
    _emit(target, tq_register_bytes(tqs, quarantined, diff, assumptions))


# ------------------------------------------------------------------------------ violations
def violations_bytes(violations: list[Violation]) -> bytes:
    return _safe(lambda: _workbook_bytes([("Verification", ["Rule", "Severity", "Reference", "Message"],
                                           [[v.rule, v.severity, v.ref, v.message] for v in violations])]))


def write_violations(violations: list[Violation], target: str | Path | BinaryIO) -> None:
    _emit(target, violations_bytes(violations))


# ------------------------------------------------------------------------------ impact report
def _loc_text(loc: tuple | None) -> str:
    if not loc:
        return "-"
    cab, cioc, bp, ch = loc
    return f"{cab} / {cioc} / {bp} / channel {ch}"


def impact_report_bytes(report: Any, rows_a: list[dict[str, Any]] | None = None, rows_b: list[dict[str, Any]] | None = None) -> bytes:
    def build() -> bytes:
        counts = report.counts
        touched = sum(counts.get(k, 0) for k in ("Added", "Deleted", "Moved", "Renamed"))
        total = touched + report.unchanged
        wired = lambda rows: sum(1 for r in (rows or []) if r.get("Tag Status") == "Wired Spare")   # noqa: E731
        summary = [["Added", counts.get("Added", 0)], ["Deleted", counts.get("Deleted", 0)],
                   ["Moved", counts.get("Moved", 0)], ["Renamed", counts.get("Renamed", 0)],
                   ["Unchanged", report.unchanged],
                   ["Tags touched (%)", round(100.0 * touched / total, 1) if total else 0.0],
                   ["Comparison mode", getattr(report, "mode", "pinned")],
                   ["Affected cabinets", ", ".join(report.affected_cabinets) or "-"],
                   ["Affected cables", ", ".join(report.affected_cables) or "-"],
                   ["CHARM / hardware changes", len(report.hardware_changes)],
                   ["Wired spares (Rev A -> Rev B)", f"{wired(rows_a)} -> {wired(rows_b)}"]]
        for warning in getattr(report, "warnings", []):
            summary.append(["Warning", warning])
        headers = ["Tag", "Old Tag", "From Location", "To Location", "Note"]
        sheets: list[tuple[str, Sequence[str], Sequence[Sequence[Any]]]] = [("Summary", ["Item", "Value"], summary)]
        for category in ("Added", "Deleted", "Moved", "Renamed"):
            sheets.append((category, headers, [[c.tag, c.old_tag or "-", _loc_text(c.a_loc), _loc_text(c.b_loc), c.note or "-"]
                                               for c in report.changes if c.category == category]))
        sheets.append(("Conversions", headers, [[c.tag, c.old_tag or "-", _loc_text(c.a_loc), _loc_text(c.b_loc), c.note or "-"]
                                                for c in report.conversions]))
        return _workbook_bytes(sheets)
    return _safe(build)


def write_impact_report(report: Any, rows_a: list[dict[str, Any]] | None, rows_b: list[dict[str, Any]] | None,
                        target: str | Path | BinaryIO) -> None:
    _emit(target, impact_report_bytes(report, rows_a, rows_b))
