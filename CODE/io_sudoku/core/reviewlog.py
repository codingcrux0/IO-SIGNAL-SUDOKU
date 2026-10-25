"""Review memory: everything that was ever decided about a signal (or cable, cabinet ...) on the TQ Board.

Every time an engineer reviews a question - Approve, Problem, an Edit of the file, an answer, a note, a suggested
fix that was verified or rejected - one ReviewEvent is written down with the question, the decision, who, when,
in which revision, and where the signal sat at that moment.  Two events are added by the app itself after a
re-allocation, only for items that were reviewed before: 'resolved' (a reviewed question is gone) and 'raised'
(a question appeared on an item that was reviewed before).

returning() then lists every item that was reviewed before and has an open problem again (a new question
because of another signal or a changed rule, or the same question coming back), so the TQ Board can show it
under "Reviewed Before" with its whole past.

Pure and read-only: it only records what happened and reads the finished result.  It never changes the
allocation, a sign-off or a rule, and it never raises (bad data is skipped).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from io_sudoku.core.textnorm import match_key

MAX_EVENTS = 3000
MAX_CHANGES = 40                 # cell changes kept with one decision
CHANGE_FIELDS = ("Sheet", "Row", "Column", "Before", "After", "When")
FACT_COLUMNS = ("Tag Name", "Tag Status", "IO Type", "Segregation", "Electronic/ Marshalling Cabinet", "CIOC/CSLS Name",
                "Baseplate", "Channel_No", "CHARM_No", "CHARM Type", "Field Cable No", "Field Cable Pair")

# action -> (what it is called, which count it adds to)
ACTIONS = {
    "approved": ("Approved", "approved"),
    "problem": ("Marked as a problem", "rejected"),
    "cleared": ("Sign-off taken back", "reviewed"),
    "edited": ("Fixed with Edit (file changed)", "fixed"),
    "answered": ("Answered (value given)", "fixed"),
    "answer-ok": ("Answer verified: question cleared", "fixed"),
    "answer-failed": ("Answer checked: question still open", "rejected"),
    "note": ("Note written", "reviewed"),
    "suggested": ("Fix sent for verification", "reviewed"),
    "suggestion-verified": ("Suggested fix verified", "approved"),
    "suggestion-rejected": ("Suggested fix rejected", "rejected"),
    "resolved": ("Gone after a re-allocation", "resolved"),
    "raised": ("Raised again after a re-allocation", "raised"),
}
AUTOMATIC = ("resolved", "raised")
COUNT_NAMES = (("reviewed", "Reviewed"), ("approved", "Approved"), ("rejected", "Rejected / problem"),
               ("fixed", "Fixed or answered"), ("resolved", "Cleared later"), ("raised", "Came back"))


@dataclass(frozen=True)
class ReviewEvent:
    item: str                     # match key of the ref (tag, cable, cabinet ...): the item is remembered by this
    ref: str                      # the ref as it was shown
    tq_id: str
    severity: str
    action: str                   # a key of ACTIONS
    question: str = ""            # the question's text at that time
    detail: str = ""              # what was done: 'IO Type AI -> AIR', the note, the reason ...
    by: str = ""
    time: str = ""
    revision: str = ""            # which saved revision / file it happened in
    where: str = ""               # where the signal sat at that moment (one line)
    facts: dict[str, str] = field(default_factory=dict)
    changes: tuple[dict[str, str], ...] = ()   # the exact cells changed before this decision (Column, Before, After ...)

    @property
    def label(self) -> str:
        return ACTIONS.get(self.action, (self.action, ""))[0]


def item_key(ref: Any) -> str:
    text = "" if ref is None else str(ref).strip()
    return match_key(text) or text.upper()


def to_dict(event: ReviewEvent) -> dict[str, Any]:
    out = asdict(event)
    out["changes"] = [dict(c) for c in event.changes]
    return out


def clean_changes(changes: Any) -> tuple[dict[str, str], ...]:
    """Cell changes as plain text ({'Sheet', 'Row', 'Column', 'Before', 'After', 'When'}); bad entries are skipped."""
    out = []
    for c in changes if isinstance(changes, (list, tuple)) else []:
        if isinstance(c, dict) and str(c.get("Column") or "").strip():
            out.append({k: str(c.get(k) if c.get(k) is not None else "") for k in CHANGE_FIELDS})
    return tuple(out[:MAX_CHANGES])


def change_key(c: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(c.get(k) if c.get(k) is not None else "") for k in CHANGE_FIELDS)


def change_line(c: dict[str, Any]) -> str:
    """'row 12 Signal Level: '24 VDC' → 'Voltfree'' (empty values shown as (empty))."""
    return (f"row {c.get('Row')} {c.get('Column')}: '{c.get('Before') or '(empty)'}' → '{c.get('After') or '(empty)'}'")


def changes_in(events: list[ReviewEvent]) -> list[tuple[ReviewEvent, dict[str, str]]]:
    """Every cell change written down with the decisions of one item, oldest first."""
    return [(e, c) for e in events for c in e.changes]


def from_dict(data: Any) -> ReviewEvent | None:
    """An event from saved JSON (None when it is not one)."""
    try:
        if not isinstance(data, dict) or data.get("action") not in ACTIONS:
            return None
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        text = {k: str(data.get(k) or "") for k in ("ref", "tq_id", "severity", "question", "detail", "by", "time",
                                                     "revision", "where")}
        return ReviewEvent(item=item_key(data.get("item") or text["ref"]), action=str(data["action"]),
                           facts={str(k): str(v) for k, v in facts.items()}, changes=clean_changes(data.get("changes")),
                           **text)
    except Exception:  # noqa: BLE001 - a damaged entry is skipped
        return None


# ------------------------------------------------------------------ what the item looked like at that moment
def facts_of(result: Any, ref: Any) -> tuple[str, dict[str, str]]:
    """(one line, a few columns) of where the ref sits in the result: its tag row, else its cable's first row."""
    try:
        key = item_key(ref)
        rows = list(getattr(result, "rows", []) or [])
        row = next((r for r in rows if item_key(r.get("Tag Name")) == key), None) \
            or next((r for r in rows if item_key(r.get("Field Cable No")) == key), None)
        if row is None:
            for q in getattr(result, "quarantined", []) or []:
                sig = getattr(q, "signal", None)
                if sig is not None and item_key(getattr(sig, "tag", "")) == key:
                    return f"Not allocated (set aside by {getattr(q, 'tq_id', '?')})", {"Set aside by": str(getattr(q, "tq_id", ""))}
            return "", {}
        facts = {c: str(row[c]) for c in FACT_COLUMNS if c in row and str(row[c]).strip() not in ("", "-", "None")}
        where = " / ".join(facts.get(c, "-") for c in ("Electronic/ Marshalling Cabinet", "CIOC/CSLS Name", "Baseplate")) \
            + f" / ch {facts.get('Channel_No', '-')}"
        return where, facts
    except Exception:  # noqa: BLE001
        return "", {}


def question_of(result: Any, tq_id: str, ref: Any) -> tuple[str, str]:
    """(severity, text) of a question in the result ('', '' when it is not there any more)."""
    key = item_key(ref)
    for t in list(getattr(result, "tqs", []) or []) + list(getattr(result, "violations", []) or []):
        kind = getattr(t, "tq_id", None) or getattr(t, "rule", "")
        if kind == tq_id and item_key(getattr(t, "ref", "")) == key:
            return str(getattr(t, "severity", "")), str(getattr(t, "message", ""))
    return "", ""


def make_event(result: Any, tq_id: str, ref: Any, action: str, *, detail: str = "", by: str = "", time: str = "",
               revision: str = "", severity: str = "", question: str = "",
               changes: Any = ()) -> ReviewEvent | None:
    """One event, filled in from the result (the question's text and where the signal sits).  None if unknown."""
    if action not in ACTIONS or not str(tq_id or "").strip():
        return None
    try:
        sev, text = question_of(result, tq_id, ref)
        where, facts = facts_of(result, ref)
        return ReviewEvent(item=item_key(ref), ref=str(ref or ""), tq_id=str(tq_id), severity=severity or sev,
                           action=action, question=question or text, detail=str(detail or "")[:600], by=str(by or ""),
                           time=str(time or ""), revision=str(revision or ""), where=where, facts=facts,
                           changes=clean_changes(changes))
    except Exception:  # noqa: BLE001
        return None


def record(log: list[ReviewEvent], *events: ReviewEvent | None) -> list[ReviewEvent]:
    """The log with the events added (None is skipped; the oldest go first beyond MAX_EVENTS)."""
    out = list(log or []) + [e for e in events if isinstance(e, ReviewEvent)]
    return out[-MAX_EVENTS:]


# ------------------------------------------------------------------ reading the log
def by_item(log: list[ReviewEvent]) -> dict[str, list[ReviewEvent]]:
    out: dict[str, list[ReviewEvent]] = {}
    for e in log or []:
        out.setdefault(e.item, []).append(e)
    return out


def reviewed_items(log: list[ReviewEvent]) -> set[str]:
    """Items an engineer really reviewed (the automatic events alone do not count)."""
    return {e.item for e in log or [] if e.action not in AUTOMATIC}


def counts(events: list[ReviewEvent]) -> dict[str, int]:
    """How often: reviewed (every human decision), approved, rejected, fixed, resolved later, came back."""
    out = {k: 0 for k, _ in COUNT_NAMES}
    for e in events:
        group = ACTIONS.get(e.action, ("", ""))[1]
        if e.action not in AUTOMATIC:
            out["reviewed"] += 1
        if group in out and group != "reviewed":
            out[group] += 1
    return out


def count_line(events: list[ReviewEvent]) -> str:
    n = counts(events)
    return " · ".join(f"{name} {n[k]}" for k, name in COUNT_NAMES if n[k] or k == "reviewed")


def revisions_seen(events: list[ReviewEvent]) -> list[str]:
    return list(dict.fromkeys(e.revision for e in events if e.revision))


@dataclass
class Returning:
    item: str
    ref: str
    open_now: list[tuple[str, str, str, str]]   # (tq_id, severity, message, 'New problem' | 'Came back')
    events: list[ReviewEvent]

    @property
    def is_new(self) -> bool:
        return any(kind == "New problem" for *_, kind in self.open_now)


def _open_questions(result: Any) -> list[tuple[str, str, str, str]]:
    """(tq_id, ref, severity, message) of every error and warning of a result (TQs and verifier findings)."""
    out = []
    for t in list(getattr(result, "tqs", []) or []) + list(getattr(result, "violations", []) or []):
        severity = str(getattr(t, "severity", ""))
        if severity in ("error", "warning"):
            out.append((str(getattr(t, "tq_id", None) or getattr(t, "rule", "")), str(getattr(t, "ref", "") or ""),
                        severity, str(getattr(t, "message", ""))))
    return out


def returning(log: list[ReviewEvent], result: Any, signoffs: dict[str, str] | None = None) -> list[Returning]:
    """Items reviewed before that have an open error or warning again.  A warning that is already signed off
    in this session is settled and not listed.  'New problem' = a question this item never had before (for
    example caused by another signal or a changed rule); 'Came back' = the same question again."""
    try:
        past = by_item([e for e in log or []])
        mine = reviewed_items(log)
        signoffs = signoffs or {}
        out: dict[str, Returning] = {}
        for tq_id, ref, severity, message in _open_questions(result):
            key = item_key(ref)
            if key not in mine or (severity == "warning" and signoffs.get(f"{tq_id}|{ref}")):
                continue
            events = past.get(key, [])
            seen = {e.tq_id for e in events if e.action not in AUTOMATIC}
            entry = out.setdefault(key, Returning(key, ref, [], events))
            row = (tq_id, severity, message, "Came back" if tq_id in seen else "New problem")
            if row not in entry.open_now:
                entry.open_now.append(row)
        return sorted(out.values(), key=lambda r: (not r.is_new, not any(x[1] == "error" for x in r.open_now), r.ref))
    except Exception:  # noqa: BLE001
        return []


def after_solve(log: list[ReviewEvent], before: Any, after: Any, revision: str, time: str) -> list[ReviewEvent]:
    """After a re-allocation, for items reviewed before only: a reviewed question that is gone -> 'resolved';
    a question that was not there before -> 'raised'.  The log is returned unchanged when nothing applies."""
    try:
        mine = reviewed_items(log)
        if not mine or after is None:
            return list(log or [])
        old = {(q[0], item_key(q[1])): q for q in _open_questions(before)} if before is not None else {}
        new = {(q[0], item_key(q[1])): q for q in _open_questions(after)}
        asked = {(e.tq_id, e.item) for e in log if e.action not in AUTOMATIC}
        added: list[ReviewEvent | None] = []
        for (tq_id, key), q in sorted(old.items()):
            if key in mine and (tq_id, key) in asked and (tq_id, key) not in new:
                added.append(make_event(after, tq_id, q[1], "resolved", time=time, revision=revision, severity=q[2],
                                        question=q[3]))
        for (tq_id, key), q in sorted(new.items()):
            if key in mine and (tq_id, key) not in old:
                added.append(make_event(after, tq_id, q[1], "raised", time=time, revision=revision, severity=q[2],
                                        question=q[3]))
        return record(log, *added)
    except Exception:  # noqa: BLE001
        return list(log or [])


def summary_text(events: list[ReviewEvent], limit: int = 6) -> str:
    """The small hover box: the counts, the revisions, and the last few things that happened (markdown)."""
    if not events:
        return "Never reviewed."
    lines = [f"**Reviewed before:** {count_line(events)}"]
    revs = revisions_seen(events)
    if revs:
        lines.append(f"**In revisions:** {', '.join(revs)}")
    lines.append("**Latest:**")
    for e in events[-limit:][::-1]:
        who = f" by {e.by}" if e.by else ""
        lines.append(f"- {e.time} · {e.tq_id}: {e.label}{who}" + (f" ({e.detail[:80]})" if e.detail and not e.changes else ""))
    if len(events) > limit:
        lines.append(f"- and {len(events) - limit} earlier")
    changed = changes_in(events)
    if changed:
        lines.append("**Cells changed before these decisions:**")
        for e, c in changed[-limit:][::-1]:
            lines.append(f"- {e.time} · before “{e.label}”: {change_line(c)}")
        if len(changed) > limit:
            lines.append(f"- and {len(changed) - limit} earlier changes (press ▸ to see them all)")
    return "\n".join(lines)
