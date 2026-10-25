"""Engineer answers ("overrides"): fix a TQ without editing the Excel file.

When a signal is quarantined (say it has no IO type), an engineer can ANSWER the TQ:
"tag X is AIR".  The answer is stored as an Override and applied right after reading
the MDB and BEFORE validation, so the corrected signal still goes through every check.

Rules that keep this safe:
  * only whitelisted fields can be overridden (OVERRIDABLE_FIELDS);
  * every value is validated (IO type must be AIR/AOR/DIR/DOR, pair must be >= 1 ...);
  * locked rules (capacity, CHARM formula, A/B separation ...) and the project's settings (the alarm baseplate ...) are not
    fields of a signal at all, so they cannot be overridden;
  * overrides are plain data, saved as JSON, and hashed into the run manifest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from io_sudoku.core.config import Config
from io_sudoku.core.constants import IO_TYPES
from io_sudoku.core.models import Signal
from io_sudoku.core.textnorm import clean, match_key, normalise_io_type, text_key, to_int
from io_sudoku.core.tq import TQ, TQLog
from io_sudoku.core.validate import parse_cable_size

OVERRIDABLE_FIELDS = ("io_type", "cable_no", "pair_no", "segregation", "instrument_type",
                      "signal_type", "signal_level", "tech_room", "logic_no", "cable_size")
MAX_TEXT = 60


@dataclass(frozen=True)
class Override:
    tag_key: str            # tag (compared with match_key)
    field: str              # one of OVERRIDABLE_FIELDS
    value: str | int
    by: str                 # who answered
    note: str = ""


def validate_override(o: Override, cfg: Config) -> list[str]:
    """Problems with an override (empty list = fine)."""
    problems: list[str] = []
    if not match_key(o.tag_key):
        problems.append("The tag is empty.")
    if not clean(o.by):
        problems.append("Say who gave this answer.")
    if o.field not in OVERRIDABLE_FIELDS:
        problems.append(f"'{o.field}' cannot be changed by an answer.")
        return problems
    text = clean(o.value)
    if o.field == "io_type":
        if normalise_io_type(o.value) not in IO_TYPES:
            problems.append("IO type must be AIR, AOR, DIR or DOR.")
    elif o.field == "pair_no":
        number = to_int(o.value)
        if number is None or number < 1:
            problems.append("The pair number must be 1 or higher.")
    elif o.field == "segregation":
        allowed = {c.upper() for c in cfg.rules.a_codes + cfg.rules.b_codes + cfg.rules.neutral_codes}
        if text is not None and text.upper() not in allowed:
            problems.append("Unknown segregation code.")
    elif text is None:
        problems.append("The value is empty.")
    if text is not None and len(text) > MAX_TEXT:
        problems.append(f"The value is longer than {MAX_TEXT} characters.")
    return problems


def _apply_one(sig: Signal, field: str, value: Any) -> Signal:
    if field == "io_type":
        return replace(sig, io_type=normalise_io_type(value))
    if field == "pair_no":
        number = to_int(value)
        return replace(sig, pair_no=number, pair_text=f"Pair {number}")
    if field == "segregation":
        text = clean(value)
        return replace(sig, segregation=None if text is None else text)
    return replace(sig, **{field: clean(value)})


def apply_overrides(signals: list[Signal], overrides: list[Override], cfg: Config, log: TQLog) -> list[Signal]:
    """Return NEW signals with the answers applied (the input list is not changed)."""
    if not overrides:
        return list(signals)
    index: dict[tuple[str, str], Override] = {}
    for o in overrides:                                   # file order; the last answer wins
        problems = validate_override(o, cfg)
        if problems:
            log.add("OVERRIDE-INVALID", o.tag_key, f"The answer for {o.tag_key} ({o.field}) is not allowed: "
                    + " ".join(problems))
            continue
        index[(match_key(o.tag_key) or "", o.field)] = o
    wanted: dict[str, list[Override]] = {}
    for (tag_key, _field), o in sorted(index.items()):
        wanted.setdefault(tag_key, []).append(o)

    seen: set[str] = set()
    result: list[Signal] = []
    for sig in signals:
        mine = wanted.get(sig.key)
        if not mine:
            result.append(sig)
            continue
        seen.add(sig.key)
        for o in mine:
            sig = _apply_one(sig, o.field, o.value)
        log.add("OVERRIDE-APPLIED", sig.tag, f"The answer for {sig.tag} was applied ({', '.join(o.field for o in mine)}).")
        result.append(sig)
    for tag_key in sorted(set(wanted) - seen):
        log.add("OVERRIDE-NO-MATCH", tag_key)
    return result


ANSWERS_PREFIX = "Answers "          # Override.note of an answer given for one TQ: 'Answers MISSING-IO-TYPE'


def answered_tq(o: Override) -> str | None:
    """The TQ id an answer was given for (None for an answer typed without a question)."""
    note = str(o.note or "")
    return note[len(ANSWERS_PREFIX):].strip() or None if note.startswith(ANSWERS_PREFIX) else None


def check_answers(overrides: list[Override], log: TQLog) -> None:
    """After a solve: an answer whose question is STILL raised for its tag gets an ANSWER-UNRESOLVED warning,
    so a wrong answer is never silently accepted.  Reads the log only; it changes no signal."""
    raised = {(t.tq_id, match_key(t.ref) or "") for t in log}
    for o in overrides:
        tq_id = answered_tq(o)
        if tq_id and (tq_id, match_key(o.tag_key) or "") in raised and not log.has_once("ANSWER-UNRESOLVED", o.tag_key):
            log.add("ANSWER-UNRESOLVED", o.tag_key)


def overrides_to_json(items: list[Override]) -> str:
    return json.dumps([{"tag_key": o.tag_key, "field": o.field, "value": o.value, "by": o.by, "note": o.note}
                       for o in items], sort_keys=True)


def overrides_from_json(text: str | bytes | None) -> list[Override]:
    """Tolerant reader: bad JSON or bad rows are skipped, never raised."""
    try:
        data = json.loads(text or "[]")
        if not isinstance(data, list):
            return []
    except Exception:
        return []
    items: list[Override] = []
    for row in data:
        try:
            items.append(Override(str(row["tag_key"]), str(row["field"]), row["value"], str(row.get("by", "")),
                                  str(row.get("note", ""))))
        except Exception:
            continue
    return items


def _free_pairs(signal: Signal | None, accepted: list[Signal], limit: int = 10) -> list[int]:
    if signal is None or not signal.cable_no:
        return []
    cable = match_key(signal.cable_no)
    members = [s for s in accepted if match_key(s.cable_no) == cable and s.key != signal.key]
    size = parse_cable_size(signal.cable_size) or next(
        (parse_cable_size(m.cable_size) for m in members if parse_cable_size(m.cable_size)), None)
    used = {m.pair_no for m in members if m.pair_no is not None}
    if size is None:
        size = max(used | {0}) + limit
    return [p for p in range(1, size + 1) if p not in used][:limit]


def suggest_resolution(tq: TQ, signal: Signal | None, accepted: list[Signal], cfg: Config) -> list[dict[str, Any]]:
    """Deterministic suggestions an engineer can pick from a dropdown: [{field, value, why}]."""
    if tq.tq_id in ("MISSING-IO-TYPE", "UNKNOWN-IO-TYPE"):
        kind = text_key(signal.signal_type) if signal else ""
        level = text_key(signal.signal_level) if signal else ""
        if "4-20" in kind:
            choices, why = ["AIR", "AOR"], "the signal type is 4-20 mA"
        elif level.startswith("voltfree"):
            choices, why = ["DIR"], "the signal level is a voltage-free contact"
        elif level.startswith("volt-contact"):
            choices, why = ["DOR"], "the signal level is a voltage contact"
        else:
            choices, why = list(IO_TYPES), "no signal type or level to narrow it down"
        return [{"field": "io_type", "value": c, "why": why} for c in choices]
    if tq.tq_id in ("MISSING-PAIR", "DUPLICATE-PAIR"):
        return [{"field": "pair_no", "value": p, "why": "free pair in this cable"} for p in _free_pairs(signal, accepted)]
    if tq.tq_id == "MISSING-CABLE":
        room = match_key(signal.tech_room) if signal else None
        cables = {}
        for s in accepted:
            if s.cable_no and match_key(s.tech_room) == room:
                cables.setdefault(match_key(s.cable_no), s.cable_no)
        return [{"field": "cable_no", "value": cables[k], "why": "cable already used in this room"}
                for k in sorted(cables)[:10]]
    if tq.tq_id == "UNSUPPORTED-SEGREGATION":
        return [{"field": "segregation", "value": v, "why": "supported code"} for v in ("A", "B", "-")]
    return []
