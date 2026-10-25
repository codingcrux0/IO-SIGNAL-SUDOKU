"""Revision Library: every revision you saved from the Revision page, kept whole so it can be opened again.

Pure logic (no widgets), like history.py.  An Entry is made from a checked revision (Check Allocation First, or
Compare Revisions): the Rev B allocation and the Rev A it was compared with (rows COMPRESSED, as in history.py),
its questions and how they changed, the Added / Deleted / Moved / Renamed list, the better/worse check, the rework
estimate, the items reviewed before that have a problem in it, and what it was made from.  The Library lasts for
this browser session; it never changes the allocation on screen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core import reviewlog, revpreview
from io_sudoku.core.revision import ImpactReport
from io_sudoku.core.tqlife import diff_tqs
from io_sudoku.ui.history import pack_rows

MAX_ENTRIES = 20


def _loc(loc: Any) -> str:
    return "-" if not loc else f"{loc[0]} / {loc[1]} / {loc[2]} / ch {loc[3]}"


def _rows(z: bytes) -> list[dict[str, Any]]:
    import json
    import zlib
    try:
        return json.loads(zlib.decompress(z).decode("utf-8"))
    except Exception:  # noqa: BLE001 - a damaged entry shows as empty, it never crashes
        return []


@dataclass
class Entry:
    id: int
    name: str
    created: str
    file_name: str                  # the Rev B MDB
    label: str                      # Rev B label
    source: str                     # where Rev A came from
    mode: str                       # 'pinned' | 'compare-only'
    check: revpreview.Check
    report: ImpactReport
    tqs: list[dict[str, str]] = field(default_factory=list)          # every Rev B question, with New / Still open
    resolved: list[dict[str, str]] = field(default_factory=list)     # questions of Rev A that Rev B no longer has
    reviewed_again: list[dict[str, str]] = field(default_factory=list)
    inputs: dict[str, str] = field(default_factory=dict)
    rows_z: bytes = field(repr=False, default=b"")
    rows_a_z: bytes = field(repr=False, default=b"")

    def rows(self) -> list[dict[str, Any]]:
        return _rows(self.rows_z)

    def rows_a(self) -> list[dict[str, Any]]:
        return _rows(self.rows_a_z)

    def changes(self) -> list[dict[str, str]]:
        return [{"Change": c.category, "Tag": c.tag, "Old Tag": c.old_tag or "-", "From": _loc(c.a_loc),
                 "To": _loc(c.b_loc), "Note": c.note or "-"} for c in self.report.changes]


def make_entry(name: str, *, created: str, file_name: str, label: str, source: str, rows_a: list[dict[str, Any]],
               a_tqs: list[Any] | None, a_status: str | None, a_quarantined: int | None, result_b: Any,
               report: ImpactReport, fresh_report: ImpactReport | None, minutes: Any, review_log: list | None = None,
               inputs: dict[str, str] | None = None, b_status: str | None = None) -> Entry:
    """A revision with everything about it (not yet in the library: add() puts it there).  `b_status` is Rev B's
    readiness judged the same way as `a_status` (with the same warning sign-offs), so the two compare fairly."""
    tqs_b = list(getattr(result_b, "tqs", []) or [])
    a = revpreview.measures(rows_a, a_tqs, a_quarantined, a_status)
    readiness = getattr(result_b, "readiness", None)
    b = revpreview.measures(getattr(result_b, "rows", []), tqs_b, len(getattr(result_b, "quarantined", []) or []),
                            b_status or getattr(readiness, "status", None))
    check = revpreview.check(a, b, report, fresh_report, minutes, rows_a, list(getattr(result_b, "rows", []) or []))
    if a_tqs is not None:
        diff = diff_tqs(list(a_tqs), tqs_b)
        new = {(t.tq_id, t.ref) for t in diff.new}
        resolved = [{"ID": t.tq_id, "Severity": t.severity, "Reference": t.ref, "Question": t.message} for t in diff.resolved]
    else:
        new, resolved = set(), []
    tqs = [{"Status": ("New" if (t.tq_id, t.ref) in new else "Still open") if a_tqs is not None else "-",
            "ID": t.tq_id, "Severity": t.severity, "Reference": t.ref, "Question": t.message,
            "Suggested Fix": getattr(t, "resolution", "") or ""} for t in tqs_b]
    again = [{"Item": r.ref, "Open In Rev B": "; ".join(f"{q[0]} ({q[3].lower()})" for q in r.open_now),
              "Reviewed Before": reviewlog.count_line(r.events)} for r in reviewlog.returning(review_log or [], result_b, {})]
    return Entry(id=0, name=name, created=created, file_name=file_name or "-", label=label, source=source,
                 mode=getattr(report, "mode", "pinned"), check=check, report=report, tqs=tqs, resolved=resolved,
                 reviewed_again=again, inputs=dict(inputs or {}),
                 rows_z=pack_rows(list(getattr(result_b, "rows", []) or [])), rows_a_z=pack_rows(list(rows_a or [])))


def default_name(library: list[Entry], label: str, file_name: str) -> str:
    base = f"Rev {label or 'B'} · {file_name or 'MDB'}"
    used = {e.name for e in library}
    if base not in used:
        return base
    n = 2
    while f"{base} ({n})" in used:
        n += 1
    return f"{base} ({n})"


def add(library: list[Entry], entry: Entry) -> list[Entry]:
    """The library with the entry added (it gets the next id); the oldest go first beyond MAX_ENTRIES."""
    entry.id = max((e.id for e in library), default=0) + 1
    return (list(library) + [entry])[-MAX_ENTRIES:]


def name_problem(library: list[Entry], name: str, own_id: int | None = None) -> str:
    """'' when the name can be used, else why not."""
    name = (name or "").strip()
    if not name:
        return "A revision needs a name."
    if len(name) > 60:
        return "Keep the name under 60 characters."
    if any(e.name == name and e.id != own_id for e in library):
        return f"Another saved revision is already called “{name}”."
    return ""
