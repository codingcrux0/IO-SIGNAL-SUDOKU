"""The revision impact report in detail: what changed in each CHARM signal, and why.

Pure logic (no widgets), so it is testable without a browser.
  change_detail(change, rows_a, rows_b)   the two rows of one change and every column that differs
  impact_html(report, rows_a, rows_b)     the whole impact report as one page you can open in a browser
Read-only: it compares rows that the solver and the revision engine already produced.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

from io_sudoku.core.revision import location

# Columns shown first for an Added or Deleted signal (it has nothing to compare with).
KEY_COLUMNS = ("Tag Name", "Tag Status", "IO Type", "Electronic/ Marshalling Cabinet", "CIOC/CSLS Name", "Baseplate",
               "Channel_No", "CHARM_No", "CHARM Type", "CHARM TB Part No", "Field Cable No", "Field Cable Pair",
               "Segregation", "Controller")


@dataclass(frozen=True)
class Detail:
    row_a: dict[str, Any] | None
    row_b: dict[str, Any] | None
    diffs: list[tuple[str, str, str]]          # (column, Rev A value, Rev B value)


def _text(value: Any) -> str:
    return "-" if value is None or str(value).strip() == "" else str(value).strip()


def by_location(rows: list[dict[str, Any]] | None) -> dict[tuple, dict[str, Any]]:
    return {location(r): r for r in rows or []}


def change_detail(change: Any, rows_a: list[dict[str, Any]] | None, rows_b: list[dict[str, Any]] | None,
                  a_index: dict | None = None, b_index: dict | None = None) -> Detail:
    """The Rev A and Rev B rows of a change and the columns whose values differ.  For an Added (Deleted)
    signal there is no other side, so its key columns are listed against '-'."""
    a_index = a_index if a_index is not None else by_location(rows_a)
    b_index = b_index if b_index is not None else by_location(rows_b)
    row_a = a_index.get(tuple(change.a_loc)) if change.a_loc else None
    row_b = b_index.get(tuple(change.b_loc)) if change.b_loc else None
    if row_a is not None and row_b is not None:
        columns = list(dict.fromkeys(list(row_a) + list(row_b)))
        diffs = [(c, _text(row_a.get(c)), _text(row_b.get(c))) for c in columns
                 if _text(row_a.get(c)) != _text(row_b.get(c)) and c not in ("Sr. No.", "Revision No")]
    else:
        only = row_a if row_a is not None else (row_b or {})
        diffs = [(c, _text(only.get(c)) if row_a is not None else "-", _text(only.get(c)) if row_b is not None else "-")
                 for c in KEY_COLUMNS if c in only]
    return Detail(row_a, row_b, diffs)


def loc_text(loc: Any) -> str:
    return "-" if not loc else f"{loc[0]} / {loc[1]} / {loc[2]} / ch {loc[3]}"


_CSS = ("body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;margin:24px;color:#1f2328;background:#fff}"
        "h1{margin:0 0 4px}h2{margin:28px 0 8px;border-bottom:2px solid #d0d7de;padding-bottom:4px}"
        ".muted{color:#57606a}.cards{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}"
        ".card{border:1px solid #d0d7de;border-radius:10px;padding:10px 16px;min-width:110px}"
        ".card b{display:block;font-size:26px}.Added b{color:#1a7f37}.Deleted b{color:#cf222e}.Moved b{color:#9a6700}"
        ".Renamed b{color:#0969da}table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0 14px}"
        "th,td{border:1px solid #d0d7de;padding:5px 8px;text-align:left;vertical-align:top}th{background:#f6f8fa}"
        "td.diff{font-size:12px}td.diff span{display:block}.old{color:#cf222e;text-decoration:line-through}"
        ".new{color:#1a7f37}.warn{background:#fff8c5;border:1px solid #d4a72c;border-radius:8px;padding:8px 12px}"
        "@media print{h2{break-after:avoid}tr{break-inside:avoid}}")


def impact_html(report: Any, rows_a: list[dict[str, Any]] | None, rows_b: list[dict[str, Any]] | None,
                title: str = "Revision Impact Report") -> str:
    """The impact report as a self-contained page (every value escaped, no scripts): the summary, then each
    category with the columns that changed for every signal."""
    a_index, b_index = by_location(rows_a), by_location(rows_b)
    counts = report.counts
    out = [f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>'
           f"<style>{_CSS}</style></head><body><h1>{escape(title)}</h1>",
           f'<p class="muted">Mode: {escape("positions pinned to Rev A" if report.mode == "pinned" else "compare only")} '
           f'· unchanged tags: {report.unchanged:,}</p><div class="cards">']
    for name in ("Added", "Deleted", "Moved", "Renamed"):
        out.append(f'<div class="card {name}"><span>{name}</span><b>{counts.get(name, 0):,}</b></div>')
    out.append(f'<div class="card"><span>CHARM changes</span><b>{len(report.hardware_changes):,}</b></div></div>')
    for warning in getattr(report, "warnings", []) or []:
        out.append(f'<p class="warn">{escape(str(warning))}</p>')
    for name in ("Added", "Deleted", "Moved", "Renamed"):
        items = [c for c in report.changes if c.category == name]
        out.append(f'<h2 id="{name.lower()}">{name} ({len(items):,})</h2>')
        if not items:
            out.append(f'<p class="muted">No tags were {name.lower()}.</p>')
            continue
        out.append("<table><tr><th>Tag</th><th>Old Tag</th><th>From</th><th>To</th><th>What changed</th><th>Note</th></tr>")
        for c in items:
            detail = change_detail(c, rows_a, rows_b, a_index, b_index)
            changed = "".join(f'<span><b>{escape(col)}</b>: <span class="old">{escape(a)}</span> → '
                              f'<span class="new">{escape(b)}</span></span>' for col, a, b in detail.diffs[:12])
            more = f"<span>+{len(detail.diffs) - 12} more columns</span>" if len(detail.diffs) > 12 else ""
            out.append(f"<tr><td>{escape(c.tag)}</td><td>{escape(c.old_tag or '-')}</td><td>{escape(loc_text(c.a_loc))}</td>"
                       f"<td>{escape(loc_text(c.b_loc))}</td><td class=\"diff\">{changed}{more}</td>"
                       f"<td>{escape(c.note or '-')}</td></tr>")
        out.append("</table>")
    out.append(f"<h2>CHARM / Hardware Changes ({len(report.hardware_changes):,})</h2>")
    out.append("<table><tr><th>Tag</th><th>Note</th></tr>" + "".join(
        f"<tr><td>{escape(c.tag)}</td><td>{escape(c.note or '-')}</td></tr>" for c in report.hardware_changes) + "</table>")
    out.append(f"<h2>Spare Conversions ({len(report.conversions):,})</h2>")
    out.append("<table><tr><th>Deleted Tag</th><th>Slot</th><th>Note</th></tr>" + "".join(
        f"<tr><td>{escape(c.tag)}</td><td>{escape(loc_text(c.a_loc))}</td><td>{escape(c.note or '-')}</td></tr>"
        for c in report.conversions) + "</table></body></html>")
    return "".join(out)
