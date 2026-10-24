"""Which CHARM signals a rule applies to, and what a new rule pack would change in each signal.

Pure logic (no widgets).  Read-only: it looks at finished allocation rows; it never changes them.
  applies_to(template, args, rows, raw_io)   the rows a rule (proposed, approved or active) covers
  signal_changes(before, after)              every cell that changes, signal by signal (for Preview)
"""
from __future__ import annotations

from typing import Any

from io_sudoku.core import cellcheck
from io_sudoku.core.constants import BPS_PER_CIOC, CIOCS_PER_CAB, STATUS_ALARM, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED
from io_sudoku.core.projectrules import judge, matches
from io_sudoku.core.revision import location
from io_sudoku.core.textnorm import match_key

MAX_ROWS = 500
SIGNALS = (STATUS_FIELD, STATUS_WIRED, STATUS_ALARM)


def _s(row: dict[str, Any], column: str) -> str:
    value = row.get(column)
    return "" if value is None else str(value).strip()


def scope_text(template: str, args: dict[str, Any]) -> str:
    """In words: which signals the rule is about."""
    a = args or {}
    return {
        "io_alias": f"signals whose IO type is written '{a.get('alias')}' in the file",
        "high_current_keyword": f"Field signals whose instrument type or service mentions '{a.get('keyword')}'",
        "instrument_profile": f"Field signals with instrument type '{a.get('instrument')}'",
        "segregation_family": f"Field signals with segregation code '{a.get('code')}'",
        "spare_pct": "every wired spare (the quota per IO type and controller)",
        "future_pct": "every Spare Slot kept free for the future",
        "end_reserve_bps": f"the last {a.get('value')} baseplates of CIOC 4",
        "add_cabinet": f"the signals of technical room {a.get('room')}",
    }.get(template, f"signals whose {a.get('match_column')} contains '{a.get('match_text')}'")


def applies_to(template: str, args: dict[str, Any], rows: list[dict[str, Any]],
               raw_io: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """The allocation rows a rule covers (at most MAX_ROWS).  `raw_io` = {tag key: IO type text as written in
    the file}, needed only for an IO-type alias (the allocation itself holds the cleaned type)."""
    a = args or {}
    out: list[dict[str, Any]] = []
    for r in rows:
        status = r.get("Tag Status")
        if template == "io_alias":
            hit = status in SIGNALS and (raw_io or {}).get(match_key(_s(r, "Tag Name")) or "", "").casefold() == str(a.get("alias", "")).casefold()
        elif template == "high_current_keyword":
            hit = status == STATUS_FIELD and str(a.get("keyword", "")).casefold() in f"{_s(r, 'Instrument type')} {_s(r, 'Service Description')}".casefold()
        elif template == "instrument_profile":
            hit = status == STATUS_FIELD and _s(r, "Instrument type").casefold() == str(a.get("instrument", "")).casefold()
        elif template == "segregation_family":
            hit = status == STATUS_FIELD and _s(r, "Segregation").upper() == str(a.get("code", "")).upper()
        elif template == "spare_pct":
            hit = status == STATUS_WIRED
        elif template == "future_pct":
            hit = status == STATUS_SLOT
        elif template == "end_reserve_bps":
            pos = cellcheck.position(r)
            hit = bool(pos) and pos[1] == CIOCS_PER_CAB and pos[2] > BPS_PER_CIOC - int(a.get("value") or 0)
        elif template == "add_cabinet":
            hit = status in SIGNALS and _s(r, "Technical Room").casefold() == str(a.get("room", "")).casefold()
        else:
            hit = matches({"kind": template, "args": a}, r)
        if hit:
            out.append(r)
            if len(out) >= MAX_ROWS:
                break
    return out


def table(template: str, args: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per covered signal: where it is, its CHARM, and (for a project rule) its result."""
    out = []
    for r in rows:
        pos = cellcheck.position(r)
        line = {"Tag": _s(r, "Tag Name") or "-", "Status": _s(r, "Tag Status"), "Cabinet": pos[0] if pos else "-",
                "CIOC": pos[1] if pos else None, "BP": pos[2] if pos else None, "CH": pos[3] if pos else None,
                "CHARM Type": _s(r, "CHARM Type"), "IO": _s(r, "IO Type")}
        if template in ("project_column", "expect_hardware", "require_filled"):
            o = judge({"kind": template, "args": args}, r)
            line["Result"] = o.detail if o.ok is None else (("✓ " if o.ok else "✗ ") + o.detail)
        out.append(line)
    return out


def signal_changes(before: list[dict[str, Any]], after: list[dict[str, Any]], limit: int = 2000) -> list[dict[str, Any]]:
    """Every cell that differs between two allocations, listed per signal (matched by tag; spares and empty
    slots by position): Tag, Where (after), Column, Before, After."""
    def key(r: dict[str, Any]) -> tuple:
        tag = match_key(_s(r, "Tag Name"))
        return ("tag", tag) if r.get("Tag Status") in (STATUS_FIELD, STATUS_ALARM) and tag else ("slot", location(r))
    a, b = {key(r): r for r in before}, {key(r): r for r in after}
    out: list[dict[str, Any]] = []
    for k in list(dict.fromkeys(list(a) + list(b))):
        ra, rb = a.get(k), b.get(k)
        tag = _s(rb or ra or {}, "Tag Name") or "-"
        where = cellcheck.slot_label(rb or ra).split(" · ", 1)[-1]
        if ra is None or rb is None:
            out.append({"Tag": tag, "Where": where, "Column": "(whole signal)", "Before": "-" if ra is None else "present",
                        "After": "-" if rb is None else "present"})
            continue
        for column in rb:
            if column in ("Sr. No.",):
                continue
            if _s(ra, column) != _s(rb, column):
                out.append({"Tag": tag, "Where": where, "Column": column, "Before": _s(ra, column) or "-",
                            "After": _s(rb, column) or "-"})
        if len(out) >= limit:
            break
    return out[:limit]
