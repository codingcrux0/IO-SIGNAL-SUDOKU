"""Revision redline: Rev B's allocation with every change highlighted, as engineers review it.

A SEPARATE workbook is produced (the official allocation file is never coloured):
    green = Added   yellow = Moved   blue = Renamed   red = Deleted (the freed slot)
plus a Legend sheet and a Changes sheet listing every change with its old and new location.
If colouring fails for any reason the plain allocation is still delivered, with a note.
"""
from __future__ import annotations

import io
from typing import Any, BinaryIO

from io_sudoku.core.allocio import TemplateSpec, WriteReport, build_allocation
from io_sudoku.core.revision import ImpactReport, location
from io_sudoku.core.tq import TQLog

FILLS = {"Added": "C6EFCE", "Moved": "FFEB9C", "Renamed": "BDD7EE", "Deleted": "FFC7CE"}
MEANING = {"Added": "New tag in Rev B", "Moved": "Same tag, different location (may also be renamed)",
           "Renamed": "Different tag name, same location", "Deleted": "Tag removed; the slot is now a spare"}


def _loc_text(loc: tuple | None) -> str:
    return "-" if not loc else f"{loc[0]} / {loc[1]} / {loc[2]} / channel {loc[3]}"


def redline_bytes(rows_b: list[dict[str, Any]], report: ImpactReport, template: TemplateSpec | None = None,
                  log: TQLog | None = None) -> tuple[bytes, WriteReport]:
    """(workbook bytes, write report). Never raises."""
    data, write_report = build_allocation(rows_b, template, log)
    if not data or write_report.path_kind in ("csv", "none"):
        return data, write_report
    try:
        from openpyxl import load_workbook
        from openpyxl.styles import Font, PatternFill

        wb = load_workbook(io.BytesIO(data))
        ws = wb.worksheets[0]
        position = {location(r): i for i, r in enumerate(rows_b, start=2)}
        width = ws.max_column
        for change in report.changes:
            where = change.a_loc if change.category == "Deleted" else change.b_loc
            excel_row = position.get(where) if where else None
            if excel_row is None or change.category not in FILLS:
                continue
            fill = PatternFill(fill_type="solid", start_color=FILLS[change.category], end_color=FILLS[change.category])
            for c in range(1, width + 1):
                ws.cell(row=excel_row, column=c).fill = fill
        legend = wb.create_sheet("Legend")
        legend.append(["Colour", "Meaning", "Count"])
        for cell in legend[1]:
            cell.font = Font(bold=True)
        for category, colour in FILLS.items():
            legend.append([category, MEANING[category], report.counts.get(category, 0)])
            legend.cell(row=legend.max_row, column=1).fill = PatternFill(fill_type="solid", start_color=colour, end_color=colour)
        changes = wb.create_sheet("Changes")
        changes.append(["Category", "Tag", "Old Tag", "From", "To", "Note"])
        for cell in changes[1]:
            cell.font = Font(bold=True)
        for c in report.changes:
            changes.append([c.category, c.tag, c.old_tag or "-", _loc_text(c.a_loc), _loc_text(c.b_loc), c.note or "-"])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), write_report
    except Exception:  # noqa: BLE001 - deliver the plain allocation rather than nothing
        return data, write_report


def write_redline(rows_b: list[dict[str, Any]], report: ImpactReport, target: str | BinaryIO,
                  template: TemplateSpec | None = None, log: TQLog | None = None) -> WriteReport:
    data, write_report = redline_bytes(rows_b, report, template, log)
    try:
        if isinstance(target, str):
            with open(target, "wb") as fh:
                fh.write(data)
        else:
            target.write(data)
    except Exception:  # noqa: BLE001
        write_report.verified = False
    return write_report
