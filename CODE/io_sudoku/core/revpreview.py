"""Check a revision BEFORE it is saved: is Rev B better than the allocation you have now, and how much rework?

Used by "Check Allocation First" on the Revision page.  It only reads finished results:
  * measures()  - the same numbers for both sides (errors, warnings, set aside, field signals, spares, cabinets);
  * verdict()   - better / worse / mixed / about the same, with the reasons in plain words.  Fixed order of
                  importance: errors, then signals set aside, then warnings, then cabinets used;
  * hours       - the rework ESTIMATE to adopt Rev B two ways, with the minutes per change of the Revision
                  Simulator (core.simulate.rework_hours): keeping positions (IO Sudoku's pinned re-solve, the
                  revision itself) versus allocating Rev B again from scratch.  Added and deleted signals cost the
                  same both ways ('same'), so only moved and renamed tags make the difference.  When Rev B shares
                  fewer than half of Rev A's signals it is a different file, not a revision of it: no saving is
                  claimed then (Hours.related is False).

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


RELATED_SHARE = 0.5          # Rev B is a revision of Rev A when it still has at least half of Rev A's signals


@dataclass
class Hours:
    keep: float = 0.0           # adopting Rev B with IO Sudoku's pinned re-solve (positions kept)
    fresh: float = 0.0          # allocating Rev B again from scratch
    keep_moved: int = 0
    fresh_moved: int = 0
    same: float = 0.0           # the added and deleted signals: in both numbers, the same either way
    added: int = 0
    deleted: int = 0
    shared: int | None = None   # Rev A signals (by tag) still in Rev B; None = not known
    a_tags: int | None = None
    mode: str = "pinned"        # 'compare-only' = Rev A's layout could not be read, so nothing was kept
    rates: dict[str, float] = field(default_factory=dict)       # minutes per moved / renamed / added / deleted tag

    @property
    def saved(self) -> float:
        return round(self.fresh - self.keep, 2) if self.related else 0.0

    @property
    def share(self) -> float | None:
        """How much of Rev A is still in Rev B (0-1), or None when not known."""
        if self.shared is None or not self.a_tags:
            return None
        return self.shared / self.a_tags

    @property
    def related(self) -> bool:
        """Is Rev B a revision of Rev A (enough signals in common for kept positions to mean anything)?"""
        share = self.share
        return (share is None or share >= RELATED_SHARE) and self.mode != "compare-only"

    @property
    def saved_pct(self) -> int:
        return round(100 * self.saved / self.fresh) if self.fresh > 0 and self.saved > 0 else 0


def hours_text(h: float) -> str:
    """'0 h', '1.2 h' under 10 hours, '17 h', '1,167 h'."""
    if not h:
        return "0 h"
    return f"{h:.1f} h" if h < 10 else f"{round(h):,} h"


def days_text(h: float) -> str:
    """' (about 146 working days)' for big numbers (8-hour days), else ''."""
    return f" (about {round(h / 8):,} working days)" if h >= 16 else ""


def shared_tags(rows_a: list[dict[str, Any]] | None, rows_b: list[dict[str, Any]] | None) -> tuple[int, int]:
    """(Rev A signals still in Rev B, Rev A signals), by tag name.  Not by 'Old Tag': the revision fills that in
    itself for any new tag that took an old tag's slot, which would make two unrelated files look related."""
    from io_sudoku.core.textnorm import match_key
    tags = (STATUS_FIELD, STATUS_ALARM)
    a = {match_key(r.get("Tag Name")) for r in rows_a or [] if r.get("Tag Status") in tags} - {None, ""}
    b = {match_key(r.get("Tag Name")) for r in rows_b or [] if r.get("Tag Status") in tags}
    return len(a & b), len(a)


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
        out.append("Rework estimate: " + self.rework_line())
        return out

    def rework_line(self) -> str:
        """The rework estimate in one plain sentence (markdown bold), honest about what it can and cannot say."""
        h = self.hours
        same = (f"{h.added:,} added and {h.deleted:,} deleted signal{'s' * (h.deleted != 1)}, about "
                f"**{hours_text(h.same)}**{days_text(h.same)}")
        if h.mode == "compare-only":
            return ("Rev A's layout could not be read, so no positions could be kept and no saving can be estimated. "
                    f"New work for the {same}.")
        if not h.related:
            pct = round(100 * (h.share or 0))
            return (f"Rev B has only {h.shared:,} of Rev A's {h.a_tags:,} signals ({pct}%), so it is a different file, "
                    f"not a revision of this allocation: there are no positions worth keeping and no saving to "
                    f"estimate. Wiring it is new work: the {same}.")
        if not h.keep and not h.fresh:
            return "no signal was added, deleted, moved or renamed, so there is no rework."
        if h.saved <= 0:
            return (f"about **{hours_text(h.keep)}**{days_text(h.keep)} either way: allocating again from scratch would "
                    f"not move any more signals here ({h.fresh_moved:,} moved against {h.keep_moved:,}), so keeping "
                    f"positions saves no time on this revision. {'Most of it' if h.same * 2 >= h.keep else 'It includes'} "
                    f"the {same}.")
        return (f"about **{hours_text(h.keep)}** keeping positions ({h.keep_moved:,} tag{'s' * (h.keep_moved != 1)} "
                f"moved) against **{hours_text(h.fresh)}** allocating again from scratch ({h.fresh_moved:,} moved): "
                f"**{hours_text(h.saved)} saved**{days_text(h.saved)}. Both include the {same}, which is the same "
                f"either way.")


def check(a: dict[str, Any], b: dict[str, Any], report: Any, fresh_report: Any, minutes: Any,
          rows_a: list[dict[str, Any]] | None = None, rows_b: list[dict[str, Any]] | None = None) -> Check:
    """Compare the two sides and estimate the rework both ways (reports from core.revision.compare).  With the
    rows of both sides it also knows how much of Rev A is still in Rev B."""
    from io_sudoku.core.simulate import rework_hours
    out = Check(a=a, b=b)
    try:
        out.word, out.reasons = verdict(a, b)
        out.counts = dict(getattr(report, "counts", {}) or {})
        out.unchanged = int(getattr(report, "unchanged", 0) or 0)
        added, deleted = out.counts.get("Added", 0), out.counts.get("Deleted", 0)
        shared, a_tags = shared_tags(rows_a, rows_b) if rows_a is not None and rows_b is not None else (None, None)
        out.hours = Hours(keep=rework_hours(report, minutes), fresh=rework_hours(fresh_report, minutes) if fresh_report else 0.0,
                          keep_moved=out.counts.get("Moved", 0),
                          fresh_moved=(getattr(fresh_report, "counts", {}) or {}).get("Moved", 0) if fresh_report else 0,
                          same=round((added * minutes.per_added_tag + deleted * minutes.per_deleted_tag) / 60.0, 2),
                          added=added, deleted=deleted, shared=shared, a_tags=a_tags,
                          mode=getattr(report, "mode", "pinned") or "pinned",
                          rates={"moved": minutes.per_moved_tag, "renamed": minutes.per_renamed_tag,
                                 "added": minutes.per_added_tag, "deleted": minutes.per_deleted_tag})
        if not fresh_report:
            out.hours.fresh = out.hours.keep          # no from-scratch run: claim no saving
    except Exception:  # noqa: BLE001
        pass
    return out
