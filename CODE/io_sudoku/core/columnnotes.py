"""Column notes: columns of the uploaded file that hold a measurement or a limit (a temperature, a voltage, a
current, a pressure, a range ...) and could be compared with a limit value - a "par value" - that the engineer
gives.

A note is information only.  It is never an error or a warning, it raises no question and it changes nothing.
The engineer answers it on the Rules page (give the limit, pick which signals it is for, or leave the column
without a limit), and that only fills a proposal that waits in the Review Queue like every other rule.

  find(unused)            the tool's own reading: words in the column name and units next to the numbers
  merge(found, ai, ...)   adds what the optional AI reading says (advisor.read_columns).  The AI can only describe
                          columns that really are in the file; it can never add a column, a value or a check.
  rule_args(note, ...)    the Columns And Checks arguments for the answer (a new project column holding the file's
                          numbers, with the check), cleaned later by projectrules.normalize_column_rule

Pure: no Streamlit, no AI imports, never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.projectrules import LIMITS, show_number

# (what it is, words in the column name, units seen next to the numbers)
QUANTITIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Temperature", r"\btemp(erature)?s?\b|°\s*[cf]\b|\bdeg\s*[cf]\b", ("°C", "°F", "degC", "degF")),
    ("Voltage", r"\bvolt(age)?s?\b|\bv[ad]c\b", ("V", "VDC", "VAC", "mV", "kV")),
    ("Current", r"\bcurrent\b|\bamps?\b|\bampere", ("mA", "A")),
    ("Pressure", r"\bpressure\b|\bpsi[ag]?\b|\bk?pa\b|\bbar[ag]?\b", ("barg", "bar", "psi", "kPa", "MPa", "Pa")),
    ("Power", r"\bpower\b|\bwatts?\b|\bkw\b", ("kW", "W")),
    ("Frequency", r"\bfreq(uency)?\b|\bhz\b", ("kHz", "Hz")),
    ("Flow", r"\bflow\s*rate\b", ("m3/h", "t/h", "kg/h", "l/min")),
    ("Time", r"\btime\b|\bseconds?\b|\bdelay\b", ("ms", "s", "sec", "min")),
    ("Length", r"\blength\b|\bdistance\b", ("mm", "m", "km")),
    ("Limit", r"\blimit\b|\bset\s*-?\s*point\b|\bdead\s*band\b|\bcut\s*-?\s*off\b|\bthreshold\b", ()),
    ("Range", r"\brange\b|\bscale\b|\bspan\b|\bsensitivity\b", ()),
)
# names that are labels, priorities or switches even when they contain one of the words above
NOT_A_MEASURE = re.compile(r"priority|enable|word|name|model|part number|type|units?\b|\beu\b|invert|direction|"
                           r"action|reference|description|revision|date|track|orientation", re.I)
_NUMBER = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*([^\d\s].{0,8})?\s*$")
MAX_EXAMPLES = 4
MAX_NOTES = 40


@dataclass
class Note:
    column: str                       # the header exactly as written in the file
    quantity: str                     # Temperature, Voltage ... or "Number"
    unit: str = ""                    # the unit seen next to the numbers ('' = not known)
    filled: int = 0                   # signals with any value in this column
    numbers: dict[str, str] = field(default_factory=dict)    # tag key -> the number (units taken off)
    low: float | None = None
    high: float | None = None
    examples: list[str] = field(default_factory=list)       # a few values exactly as written
    question: str = ""                # what the note asks
    source: str = "tool"              # 'tool', 'ai' or 'tool + ai'

    @property
    def key(self) -> str:
        return " ".join(self.column.casefold().split())

    def span(self) -> str:
        if self.low is None:
            return ""
        unit = f" {self.unit}" if self.unit else ""
        return f"{show_number(self.low)}{unit}" if self.low == self.high else \
            f"{show_number(self.low)} to {show_number(self.high)}{unit}"


def _unit_of(text: str) -> str:
    match = _NUMBER.match(text)
    return (match.group(2) or "").strip() if match else ""


def number_of(value: Any) -> float | None:
    """'24', '24 V', '4,5 mA', '-10°C' -> the number; anything else (text, '4-20 mA', a date) -> None."""
    match = _NUMBER.match(str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _quantity(header: str, units: list[str]) -> tuple[str, str]:
    """(what the column holds, its unit) from its name, then from the units next to its numbers."""
    unit = max(set(units), key=units.count) if units else ""
    for name, words, known in QUANTITIES:
        if re.search(words, header, re.I):
            return name, unit or next((u for u in known if re.search(rf"\b{re.escape(u)}\b", header)), "")
    for name, _, known in QUANTITIES:
        if unit and any(unit.casefold() == u.casefold() for u in known):
            return name, unit
    return "", unit


def question_for(note: Note) -> str:
    what = note.quantity.lower() if note.quantity not in ("Number", "Limit", "Range") else "values"
    span = f" (from {note.span()} in your file)" if note.span() and note.low != note.high else \
        (f" ({note.span()} in your file)" if note.span() else "")
    return (f"“{note.column}” holds {what} for {len(note.numbers):,} signals{span}. What value should they be compared "
            "against, and for which signals? Leave it blank if this column needs no limit.")


def find(unused: list[tuple[str, int, dict[str, str]]]) -> list[Note]:
    """The tool's own reading of the columns the allocation does not use: a column is noted when its name says it
    is a measurement or a limit (or its values carry a unit) AND at least one signal has a number in it."""
    out: list[Note] = []
    try:
        for header, filled, values in unused or []:
            name = " ".join(str(header or "").split())
            if not name or NOT_A_MEASURE.search(name):
                continue
            numbers, units, examples = {}, [], []
            for tag, raw in values.items():
                text = str(raw).strip()
                x = number_of(text)
                if x is None:
                    continue
                numbers[tag] = show_number(x)
                if _unit_of(text):
                    units.append(_unit_of(text))
                if len(examples) < MAX_EXAMPLES and text not in examples:
                    examples.append(text)
            if not numbers:
                continue
            quantity, unit = _quantity(name, units)
            if not quantity:
                continue
            xs = [float(v) for v in numbers.values()]
            note = Note(name, quantity, unit[:LIMITS["unit"]], int(filled), numbers, min(xs), max(xs), examples)
            note.question = question_for(note)
            out.append(note)
    except Exception:  # noqa: BLE001 - notes are optional; a strange file just gives fewer of them
        return out[:MAX_NOTES]
    return out[:MAX_NOTES]


def ai_columns(unused: list[tuple[str, int, dict[str, str]]], limit: int = 80) -> list[tuple[str, list[str]]]:
    """What the optional AI reading is shown: each column's name and a few example values - never a tag, never
    a whole column."""
    out = []
    for header, _, values in unused or []:
        examples = list(dict.fromkeys(str(v).strip() for v in values.values() if str(v).strip()))[:MAX_EXAMPLES]
        if examples:
            out.append((" ".join(str(header).split()), [e[:40] for e in examples]))
    return out[:limit]


def merge(found: list[Note], ai: list[dict[str, str]], unused: list[tuple[str, int, dict[str, str]]]) -> list[Note]:
    """The tool's notes with the AI's reading added: the AI may say what a column holds, its unit and the question
    to ask, and may point out a column the tool missed - only a column of the file with numbers in it."""
    by_key = {n.key: n for n in found}
    raw = {" ".join(str(h).split()).casefold(): (h, f, v) for h, f, v in unused or []}
    for item in ai or []:
        key = " ".join(str(item.get("column") or "").split()).casefold()
        if key in by_key:
            note = by_key[key]
            note.source = "tool + ai"
        elif key in raw:
            header, filled, values = raw[key]
            fresh = find([(header, filled, values)])
            if fresh:
                note = fresh[0]
            else:
                numbers = {t: show_number(number_of(v)) for t, v in values.items() if number_of(v) is not None}
                if not numbers:
                    continue
                xs = [float(v) for v in numbers.values()]
                note = Note(" ".join(str(header).split()), "Number", "", int(filled), numbers, min(xs), max(xs),
                            [str(v).strip() for v in list(values.values())[:MAX_EXAMPLES]])
            note.source = "ai"
            by_key[key] = note
        else:
            continue
        quantity = " ".join(str(item.get("quantity") or "").split())[:30]
        unit = " ".join(str(item.get("unit") or "").split())[:LIMITS["unit"]]
        question = " ".join(str(item.get("question") or "").split())[:240]
        if quantity:
            note.quantity = quantity
        if unit and not note.unit:
            note.unit = unit
        note.question = question or question_for(note)
    return list(by_key.values())[:MAX_NOTES]


def column_name(note: Note, taken: list[str]) -> str:
    """A project-column name for the note's column (at most 30 characters, not one that is already used)."""
    base = re.sub(r"\s*\([^)]*\)\s*", " ", note.column).strip() or note.column
    base = " ".join(base.split())[:LIMITS["column"]].strip()
    used = {t.casefold() for t in taken}
    name, n = base, 2
    while name.casefold() in used:
        tail = f" {n}"
        name, n = base[:LIMITS["column"] - len(tail)].rstrip() + tail, n + 1
    return name


def rule_args(note: Note, name: str, check: str, value: str, value2: str, scope: dict[str, Any], severity: str,
              blank_is_problem: bool, unit: str = "") -> dict[str, Any]:
    """Columns And Checks arguments for a note's answer: a new number column holding the file's numbers, with the
    limit check (and, if asked, a check that no signal it covers is blank)."""
    checks: list[dict[str, Any]] = []
    if check in ("max", "min", "between", "equals", "not_equals"):
        checks.append({"check": check, "value": value, "value2": value2 if check == "between" else "",
                       "values": [], "severity": severity, "scope": scope})
    if blank_is_problem:
        checks.append({"check": "required", "value": "", "value2": "", "values": [], "severity": severity, "scope": scope})
    return {"new": True, "column": name, "type": "number", "unit": unit or note.unit,
            "note": f"From the column “{note.column}” of the uploaded file, compared with a limit (Rules › Notes)."[:LIMITS["note"]],
            "values": dict(note.numbers), "fills": [], "default": "", "checks": checks}
