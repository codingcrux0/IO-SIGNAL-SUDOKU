"""Check a revision BEFORE it is saved: is Rev B better than the allocation you have now, and how much rework?

Used by "Check Allocation First" on the Revision page.  It only reads finished results:
  * measures()  - the same numbers for both sides (errors, warnings, set aside, field signals, spares, cabinets);
  * verdict()   - better / worse / mixed / about the same, with the reasons in plain words.  Fixed order of
                  importance: errors, then signals set aside, then warnings, then cabinets used;
  * hours       - the rework ESTIMATE to adopt Rev B two ways, with the minutes per change of the Revision
                  Simulator (core.simulate.rework_hours): keeping positions (IO Sudoku's pinned re-solve, the
                  revision itself) versus allocating Rev B again from scratch.

Deterministic and read-only: no allocation is changed and nothing is saved here.  Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.constants import STATUS_ALARM, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED

MEASURES = (("status", "Readiness"), ("error", "Errors"), ("warning", "Warnings"), ("info", "Info Notes"),
            ("quarantined", "Signals Set Aside"), ("field", "Field Signals"), ("cabinet_alarm", "Cabinet Alarms"),
            ("wired_spare", "Wired Spares"), ("spare_slot", "Spare Slots"), ("cabinets_used", "Cabinets Used"))
LOWER_IS_BETTER = ("error", "quarantined", "warning", "cabinets_used")      # in this order of importance
STATUS_RANK = {"ISSUE-READY": 0, "DRAFT": 1, "BLOCKED": 2}


def measures(rows: list[dict[str, Any]] | None, tqs: list[Any] | None = None, quarantined: int | None = None,
             status: str | None = None) -> dict[str, Any]:
    """The numbers of one side.  Questions, set-aside and readiness are None when they are not known (a Rev A
    read from a workbook has only its rows)."""
    rows = list(rows or [])
    out: dict[str, Any] = {k: None for k, _ in MEASURES}
    try:
        status_of = [str(r.get("Tag Status") or "") for r in rows]
        out.update(field=status_of.count(STATUS_FIELD), cabinet_alarm=status_of.count(STATUS_ALARM),
                   wired_spare=status_of.count(STATUS_WIRED), spare_slot=status_of.count(STATUS_SLOT),
                   cabinets_used=len({str(r.get("Electronic/ Marshalling Cabinet")).strip() for r in rows
                                      if str(r.get("Electronic/ Marshalling Cabinet") or "").strip() not in ("", "-")}))
        if tqs is not None:
            for sev in ("error", "warning", "info"):
                out[sev] = sum(1 for t in tqs if getattr(t, "severity", "") == sev)
        out["quarantined"] = quarantined
        out["status"] = status
    except Exception:  # noqa: BLE001
        pass
    return out


def verdict(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, list[str]]:
    """('better' | 'worse' | 'mixed' | 'same', reasons).  Only numbers known on both sides are compared."""
    better, worse = [], []
    for key in LOWER_IS_BETTER:
        x, y = a.get(key), b.get(key)
        if x is None or y is None or x == y:
            continue
        name = dict(MEASURES)[key].lower()
        line = f"{name}: {x:,} → {y:,} ({abs(y - x):,} {'fewer' if y < x else 'more'})"
        (better if y < x else worse).append(line)
    ra, rb = STATUS_RANK.get(a.get("status") or ""), STATUS_RANK.get(b.get("status") or "")
    if ra is not None and rb is not None and ra != rb:
        (better if rb < ra else worse).append(f"readiness: {a['status']} → {b['status']}")
    if better and not worse:
        word = "better"
    elif worse and not better:
        word = "worse"
    elif better and worse:
        word = "mixed"
    else:
        word = "same"
    return word, [f"Better - {x}" for x in better] + [f"Worse - {x}" for x in worse]


VERDICT_TEXT = {"better": "Rev B looks BETTER than the current allocation.",
                "worse": "Rev B looks WORSE than the current allocation.",
                "mixed": "Rev B is better in some ways and worse in others.",
                "same": "Rev B is about the same as the current allocation (no error, set-aside, warning or cabinet "
                        "count changes)."}


@dataclass
class Hours:
    keep: float = 0.0           # adopting Rev B with IO Sudoku's pinned re-solve (positions kept)
    fresh: float = 0.0          # allocating Rev B again from scratch
    keep_moved: int = 0
    fresh_moved: int = 0

    @property
    def saved(self) -> float:
        return round(self.fresh - self.keep, 2)


@dataclass
class Check:
    a: dict[str, Any] = field(default_factory=dict)
    b: dict[str, Any] = field(default_factory=dict)
    word: str = "same"
    reasons: list[str] = field(default_factory=list)
    hours: Hours = field(default_factory=Hours)
    counts: dict[str, int] = field(default_factory=dict)
    unchanged: int = 0

    @property
    def headline(self) -> str:
        return VERDICT_TEXT.get(self.word, "")

    def table(self) -> list[dict[str, str]]:
        """Measure / Now / Rev B / Change rows for a table (a '-' when one side does not know it)."""
        out = []
        for key, name in MEASURES:
            x, y = self.a.get(key), self.b.get(key)
            if key == "status":
                change = "" if x is None or y is None or x == y else ("✓ better" if STATUS_RANK.get(y, 9) < STATUS_RANK.get(x, 9)
                                                                      else "✗ worse")
            elif x is None or y is None or x == y:
                change = ""
            else:
                diff = f"{y - x:+,}"
                change = diff + ((" ✓ better" if y < x else " ✗ worse") if key in LOWER_IS_BETTER else "")
            out.append({"Measure": name, "Now (Rev A)": "-" if x is None else (f"{x:,}" if isinstance(x, int) else str(x)),
                        "Rev B": "-" if y is None else (f"{y:,}" if isinstance(y, int) else str(y)), "Change": change})
        return out

    def lines(self) -> list[str]:
        """The whole check in plain lines (for the Helpdesk and the saved revision)."""
        out = [self.headline] + self.reasons
        out += [f"{r['Measure']}: now {r['Now (Rev A)']}, Rev B {r['Rev B']} {r['Change']}".strip() for r in self.table()]
        out.append("Changes: " + ", ".join(f"{k} {v:,}" for k, v in self.counts.items()) + f", unchanged {self.unchanged:,}")
        out.append(f"Rework estimate: {self.hours.keep:g} h keeping positions ({self.hours.keep_moved:,} moved) versus "
                   f"{self.hours.fresh:g} h allocating again from scratch ({self.hours.fresh_moved:,} moved): "
                   f"{self.hours.saved:g} h saved")
        return out


def check(a: dict[str, Any], b: dict[str, Any], report: Any, fresh_report: Any, minutes: Any) -> Check:
    """Compare the two sides and estimate the rework both ways (reports from core.revision.compare)."""
    from io_sudoku.core.simulate import rework_hours
    out = Check(a=a, b=b)
    try:
        out.word, out.reasons = verdict(a, b)
        out.counts = dict(getattr(report, "counts", {}) or {})
        out.unchanged = int(getattr(report, "unchanged", 0) or 0)
        out.hours = Hours(keep=rework_hours(report, minutes), fresh=rework_hours(fresh_report, minutes) if fresh_report else 0.0,
                          keep_moved=out.counts.get("Moved", 0),
                          fresh_moved=(getattr(fresh_report, "counts", {}) or {}).get("Moved", 0) if fresh_report else 0)
    except Exception:  # noqa: BLE001
        pass
    return out
