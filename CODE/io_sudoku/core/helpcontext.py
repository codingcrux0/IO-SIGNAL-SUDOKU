"""What the Helpdesk is told about the ONE thing it was opened from: a question, an answer, a cell, a rule.

When the Helpdesk is opened from a button next to something (a TQ, the answer box, a cell on Rule Check, a rule
on Rule Impact), it gets a short FOCUS: everything the app knows about that one thing, so the user does not have
to explain it.  Each builder returns (title, text):
  * title - one line shown at the top of the chat, so the user sees what the conversation is about;
  * text  - plain facts copied from the finished result (the question, its fix, the signal's row, where it sits,
            the rules on it, the other questions about it).

Read-only, like trace and cellcheck: the text is built from data the page already shows; nothing is changed, and
the Helpdesk still has no tools (it can only read this text and reply in words).  Never raises; capped in size.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from io_sudoku.core.textnorm import match_key

MAX_CHARS = 3500
ROW_FIELDS = ("Tag Name", "Tag Status", "IO Type", "Signal Type", "Instrument type", "Service Description",
              "Segregation", "Controller", "Electronic/ Marshalling Cabinet", "Cabinet Side (F/R)", "CIOC/CSLS Name",
              "Baseplate", "Channel_No", "CHARM_No", "CHARM Type", "CHARM TB Part No", "Field Cable No",
              "Field Cable Size", "Field Cable Pair", "Technical Room", "Unit")
SIGNAL_FIELDS = ("tag", "row_ref", "sheet", "io_type", "signal_type", "signal_level", "segregation", "tech_room",
                 "unit", "cable_no", "cable_size", "pair_no", "instrument_type", "service")


def _cap(lines: list[str]) -> str:
    text = "\n".join(x for x in lines if x)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS].rsplit("\n", 1)[0] + "\n(more left out)"


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() in ("", "-")


def row_line(row: dict[str, Any]) -> str:
    """One allocated row as 'Column: value; ...' (only the columns that matter for a question)."""
    return "; ".join(f"{c}: {row[c]}" for c in ROW_FIELDS if c in row and not _blank(row[c]))


def _rows_about(result: Any, ref: str) -> list[dict[str, Any]]:
    """The allocated rows a reference is about: a tag, or every pair of a cable."""
    key = match_key(ref) or ""
    if not key:
        return []
    rows = getattr(result, "rows", []) or []
    mine = [r for r in rows if match_key(r.get("Tag Name")) == key]
    return mine or [r for r in rows if match_key(r.get("Field Cable No")) == key]


def _set_aside(result: Any, ref: str) -> list[str]:
    """A signal that was not allocated: its cleaned MDB values and why it was set aside."""
    key = match_key(ref) or ""
    out = []
    for q in getattr(result, "quarantined", []) or []:
        sig = getattr(q, "signal", None)
        if sig is not None and match_key(sig.tag) == key:
            values = {k: v for k, v in asdict(sig).items() if k in SIGNAL_FIELDS and not _blank(v)}
            out.append(f"Not allocated (set aside by {q.tq_id}). Its values in the file: "
                       + "; ".join(f"{k}: {v}" for k, v in values.items()))
    return out


def _where(result: Any, ref: str) -> list[str]:
    rows = _rows_about(result, ref)
    lines = [f"- {row_line(r)}" for r in rows[:8]]
    if len(rows) > 8:
        lines.append(f"- and {len(rows) - 8} more rows")
    lines = (["Where it is in the allocation:"] + lines) if lines else []
    return lines + _set_aside(result, ref)


def _why(result: Any, tag: str) -> list[str]:
    try:
        from io_sudoku.core import trace
        steps = trace.explain(result, tag)[:6]
    except Exception:  # noqa: BLE001 - the focus works without the solver's reasons
        steps = []
    return (["Why the solver put it there:"] + [f"- {x}" for x in steps]) if steps else []


def _others(result: Any, ref: str, skip: str = "") -> list[str]:
    key = match_key(ref) or ""
    same = [t for t in getattr(result, "tqs", []) or [] if key and match_key(t.ref) == key and t.tq_id != skip]
    return (["Other questions about the same reference:"] +
            [f"- {t.severity} {t.tq_id}: {t.message}" for t in same[:8]]) if same else []


def tq_focus(result: Any, tq_id: str, ref: str, text: str = "", note: dict | None = None,
             suggestions: list[Any] | None = None) -> tuple[str, str]:
    """One question (TQ, or a checker finding) on the TQ Board."""
    try:
        tq = next((t for t in getattr(result, "tqs", []) or [] if t.tq_id == tq_id and str(t.ref) == str(ref)), None)
        lines = [f"The user opened the Helpdesk from the question {tq_id} on {ref or '(no reference)'}."]
        if tq is not None:
            lines += [f"Severity: {tq.severity}. Owner: {tq.owner}. Category: {tq.category}.",
                      f"Full question: {tq.message}", f"The tool's suggested fix: {tq.resolution}"]
        elif text:
            lines.append(f"Full text: {text}")
        lines += _where(result, ref) + _why(result, ref) + _others(result, ref, tq_id)
        if note and note.get("text"):
            lines.append(f"The engineer's saved note: {note['text']} ({note.get('by') or 'unnamed'})")
        for sg in suggestions or []:
            lines.append(f"A suggestion ({sg.status}) by {sg.author}: {sg.text}")
        return f"Question {tq_id} · {ref or '-'}", _cap(lines)
    except Exception:  # noqa: BLE001
        return f"Question {tq_id} · {ref or '-'}", f"The question {tq_id} on {ref}."


def answer_focus(result: Any, picked: str = "", tag: str = "", field: str = "", value: str = "",
                 check: dict | None = None, fields: tuple[str, ...] = ()) -> tuple[str, str]:
    """The Answer A Question box: what is picked or typed, and everything about that tag."""
    try:
        lines = ["The user opened the Helpdesk from the Answer A Question box of the TQ Board. An answer gives a "
                 "missing or wrong value for one field of one tag without editing the file; it is checked, every rule "
                 "still runs on it, and Verify re-allocates to see whether the question is cleared."]
        if fields:
            lines.append("Fields that can be answered: " + ", ".join(f.replace("_", " ") for f in fields) + ".")
        if picked:
            lines.append(f"Suggested answer currently picked: {picked}")
        if tag or value:
            lines.append(f"Own answer being typed: tag {tag or '(none)'}, field {(field or '').replace('_', ' ')}, "
                         f"value {value or '(empty)'}.")
        if check:
            state = {"waiting": "saved, not verified yet", "ok": "verified: it cleared the question",
                     "failed": "verified: it did NOT clear everything"}.get(check.get("state"), check.get("state"))
            lines.append(f"Last answer: {check.get('tag')} {str(check.get('field', '')).replace('_', ' ')} = "
                         f"{check.get('value')} ({state}).")
            lines += [f"- still open: {i} ({sev}): {msg}" for i, sev, msg in check.get("open") or []]
        about = tag or (picked.split(" · ", 1)[1].split(" → ", 1)[0] if " · " in picked else "")
        if about:
            lines += [f"Everything about the tag {about}:"] + _where(result, about) + _others(result, about)
        open_qs = [t for t in getattr(result, "tqs", []) or [] if t.severity in ("error", "warning")]
        if open_qs and not about:
            lines += ["Open errors and warnings (first 15):"] + [f"- {t.severity} {t.tq_id} on {t.ref}: {t.message}"
                                                                 for t in open_qs[:15]]
        title = f"Answer A Question · {about}" if about else "Answer A Question"
        return title, _cap(lines)
    except Exception:  # noqa: BLE001
        return "Answer A Question", "The user is answering a question on the TQ Board."


def cell_focus(result: Any, row: dict[str, Any], checks: list[Any], path: list[tuple[str, str]],
               label: str) -> tuple[str, str]:
    """One cell (slot) on Rule Check: its row, every rule that applies to it and its signal path."""
    try:
        lines = [f"The user opened the Helpdesk from Rule Check, about the cell {label}.",
                 f"The cell's row: {row_line(row)}",
                 "Every rule that applies to it (✓ met, ✗ broken, ▲ needs a look, • note):"]
        icons = {"pass": "✓", "fail": "✗", "warn": "▲", "info": "•"}
        lines += [f"- {icons.get(c.status, '•')} {c.rule} {c.title}: {c.detail}" for c in checks[:40]]
        lines += ["Signal path:"] + [f"- {step}: {text}" for step, text in path]
        tag = str(row.get("Tag Name") or "")
        if not _blank(tag):
            lines += _why(result, tag) + _others(result, tag)
        return f"Cell {label}", _cap(lines)
    except Exception:  # noqa: BLE001
        return f"Cell {label}", f"The cell {label}."


def rule_focus(impact: Any, source: str = "") -> tuple[str, str]:
    """One rule or constraint on Rule Impact: where it is met, broken or needs a look."""
    try:
        hits = list(impact.hits)
        counts = {s: sum(1 for h in hits if h.status == s) for s in ("pass", "fail", "warn", "info")}
        lines = [f"The user opened the Helpdesk from Rule Impact, about the rule {impact.rule} \"{impact.title}\" "
                 f"({impact.group})" + (f", looking at the {source}." if source else "."),
                 f"It applies to {len(hits)} cells, {len(impact.signals)} signals, {len(impact.cabinets)} cabinets: "
                 f"{counts['pass']} met, {counts['fail']} broken, {counts['warn']} need a look, {counts['info']} notes.",
                 "Cabinets: " + ", ".join(impact.cabinets[:12]),
                 "CHARM types: " + ", ".join(f"{k} ({v})" for k, v in list(impact.charms.items())[:10])]
        bad = [h for h in hits if h.status in ("fail", "warn")]
        if bad:
            lines.append("Cells where it is broken or needs a look (first 20):")
            lines += [f"- {h.status} {h.tag} at {h.cabinet} CIOC {h.cioc} BP {h.bp} CH {h.ch} ({h.charm}): {h.detail}"
                      for h in bad[:20]]
        else:
            lines.append("Examples of how it is met:")
            lines += [f"- {h.tag} at {h.cabinet} CIOC {h.cioc} BP {h.bp} CH {h.ch}: {h.detail}" for h in hits[:5]]
        return f"Rule {impact.rule} · {impact.title}", _cap(lines)
    except Exception:  # noqa: BLE001
        return "A rule on Rule Impact", "The user is looking at one rule on Rule Impact."


def tag_focus(result: Any, query: str, steps: list[str] | None = None) -> tuple[str, str]:
    """A tag or cable on Why Is It Here?: where it sits, the solver's reasons and its questions."""
    try:
        lines = [f"The user opened the Helpdesk from Why Is It Here? (Cabinet Layout), about {query}."]
        lines += _where(result, query)
        reasons = steps if steps is not None else None
        if reasons:
            lines += ["Why the solver put it there:"] + [f"- {x}" for x in reasons[:12]]
        else:
            lines += _why(result, query)
        lines += _others(result, query)
        return f"Why Is It Here? · {query}", _cap(lines)
    except Exception:  # noqa: BLE001
        return f"Why Is It Here? · {query}", f"The tag or cable {query}."


def change_focus(change: Any, diffs: list[tuple[str, Any, Any]], checks: list[Any], a_loc: str, b_loc: str) -> tuple[str, str]:
    """One signal that changed between Rev A and Rev B on the Revision page."""
    try:
        lines = [f"The user opened the Helpdesk from the Revision page, about a {change.category.lower()} signal: "
                 f"{change.tag}" + (f" (was {change.old_tag})" if getattr(change, "old_tag", None) else "") + ".",
                 f"Rev A position: {a_loc}. Rev B position: {b_loc}."]
        if getattr(change, "note", None):
            lines.append(f"Note: {change.note}")
        if diffs:
            lines += ["Columns that changed (Rev A -> Rev B):"] + [f"- {c}: {a} -> {b}" for c, a, b in diffs[:25]]
        icons = {"pass": "✓", "fail": "✗", "warn": "▲", "info": "•"}
        shown = [c for c in checks if c.status in ("fail", "warn") or c.rule in ("Decision", "Project rule", "Answer", "Pin")]
        if shown:
            lines += ["Rules and decisions behind its Rev B place:"] + [f"- {icons.get(c.status, '•')} {c.rule} "
                                                                        f"{c.title}: {c.detail}" for c in shown[:15]]
        return f"Revision · {change.category}: {change.tag}", _cap(lines)
    except Exception:  # noqa: BLE001
        return "A revision change", "A signal that changed between Rev A and Rev B."


def history_focus(result: Any, ref: str, events: list[Any], open_now: list[tuple]) -> tuple[str, str]:
    """An item from "Reviewed Before" on the TQ Board: its open questions now and everything decided about it."""
    try:
        lines = [f"The user opened the Helpdesk from Reviewed Before (TQ Board), about {ref}: it was reviewed before "
                 "and has an open problem again."]
        if open_now:
            lines += ["Open now:"] + [f"- {tq_id} ({sev}, {kind}): {msg}" for tq_id, sev, msg, kind in open_now[:10]]
        lines += _where(result, ref)
        if events:
            lines.append("What was decided before (oldest first):")
            for e in events[-25:]:
                lines.append(f"- {e.time} · {e.revision} · {e.tq_id}: {e.label}" + (f" by {e.by}" if e.by else "")
                             + (f" - {e.detail}" if e.detail else "") + (f" [was at {e.where}]" if e.where else ""))
        return f"Reviewed Before · {ref}", _cap(lines)
    except Exception:  # noqa: BLE001
        return f"Reviewed Before · {ref}", f"An item that was reviewed before: {ref}."


def preview_focus(name: str, lines_in: list[str]) -> tuple[str, str]:
    """A revision preview (Check Allocation First on the Revision page): the comparison with the current one."""
    try:
        lines = [f"The user opened the Helpdesk from the preview of a revision ({name}), before deciding whether to "
                 "save it. Nothing is saved yet. The comparison with the current allocation:"]
        lines += [f"- {x}" for x in lines_in[:60]]
        return f"Revision Preview · {name}", _cap(lines)
    except Exception:  # noqa: BLE001
        return f"Revision Preview · {name}", "A preview of a revision."


__all__ = ["MAX_CHARS", "answer_focus", "cell_focus", "change_focus", "history_focus", "preview_focus", "row_line",
           "rule_focus", "tag_focus", "tq_focus"]
