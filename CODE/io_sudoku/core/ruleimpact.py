"""Rule Impact: Rule Check the other way round - for each rule or constraint, every cell (slot) it applies to.

Rule Check answers "which rules apply to this cell?"; Rule Impact answers "which cells, CHARMs and signals does
this rule touch, and where is it met or broken?".  It is built from cellcheck.check_cell over every slot of the
allocation, so the two pages always agree to the letter.  The solver's own per-tag decisions ("why it is here")
are left out: they are notes about one signal, not rules.

Read-only, like cellcheck and trace: it looks at the finished rows and never influences placement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.cellcheck import FAIL, INFO, PASS, WARN, check_cell, context, position, slot_id
from io_sudoku.core.projectrules import titles

LOCKED, SETTINGS, PROJECT, PEOPLE, QUESTIONS = ("Locked Rules", "Pack Settings", "Project Rules", "Answers And Pins",
                                                "Questions And Findings")
GROUPS = (LOCKED, SETTINGS, PROJECT, PEOPLE, QUESTIONS)
GROUP_HELP = {
    LOCKED: "Hardware and template rules every allocation must keep. They can never be changed.",
    SETTINGS: "Project choices the rule pack tunes: the cabinet-alarm baseplate, wired spares, future space, empty "
              "baseplates, high-current outputs, instrument hardware and segregation codes.",
    PROJECT: "The project columns and constraints added on the Rules page. They check, they never move a signal.",
    PEOPLE: "Answers given on the TQ Board and cables pinned by an engineer.",
    QUESTIONS: "Open errors and warnings, findings of the independent checker, and inferred cabinet names.",
}
_SETTING_RULES = {"V07", "V10", "V14", "V16"}             # project choices (the VIT guide), not DeltaV rules
_SETTING_TITLES = {"High-current output", "Instrument hardware", "Segregation code"}   # set by the pack, not added rules
_V_CODE = re.compile(r"^V\d\d$")


def group_of(rule: str, title: str) -> str:
    if title in ("Open question", "Checker finding") or rule == "Topology":
        return QUESTIONS
    if rule in _SETTING_RULES or (rule == "Project rule" and title in _SETTING_TITLES):
        return SETTINGS
    if rule == "Project rule":
        return PROJECT
    if rule in ("Answer", "Pin"):
        return PEOPLE
    if rule == "Locked" or _V_CODE.match(rule):
        return LOCKED
    return QUESTIONS


@dataclass(frozen=True)
class Hit:
    """One cell a rule applies to, and how it came out there."""
    sid: str
    status: str            # pass | fail | warn | info
    detail: str
    tag: str
    kind: str              # Tag Status: Field, Wired Spare, Spare Slot, Cabinet Alarm
    io: str
    charm: str
    cable: str
    cabinet: str
    cioc: int
    bp: int
    ch: int


@dataclass
class Impact:
    """One rule (or constraint) and every cell it applies to."""
    key: str
    group: str
    rule: str
    title: str
    hits: list[Hit] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for h in self.hits if h.status == status)

    @property
    def problems(self) -> int:
        return self.count(FAIL) + self.count(WARN)

    @property
    def signals(self) -> list[str]:
        """The distinct tags (signals) it touches."""
        return sorted({h.tag for h in self.hits if h.tag != "-"})

    @property
    def charms(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for h in self.hits:
            out[h.charm] = out.get(h.charm, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    @property
    def cabinets(self) -> list[str]:
        return sorted({h.cabinet for h in self.hits})


def _text(row: dict[str, Any], column: str) -> str:
    value = row.get(column)
    return "-" if value is None or str(value).strip() == "" else str(value).strip()


def rule_impact(result: Any, overrides: list[Any] | None = None,
                pins: dict[str, tuple[str, int]] | None = None) -> list[Impact]:
    """Every rule that applies anywhere in `result`, each with the cells it applies to (never raises)."""
    found: dict[str, Impact] = {}
    try:
        ctx = context(result)
        seen: set[str] = set()
        for row in getattr(result, "rows", []) or []:
            sid = slot_id(row)
            if not sid or sid in seen:
                continue
            seen.add(sid)
            cab, cioc, bp, ch = position(row)
            for c in check_cell(result, row, overrides=overrides, pins=pins, ctx=ctx):
                if c.rule == "Decision":
                    continue
                key = f"{c.rule}|{c.title}"
                impact = found.get(key)
                if impact is None:
                    impact = found[key] = Impact(key, group_of(c.rule, c.title), c.rule, c.title)
                impact.hits.append(Hit(sid, c.status, c.detail, _text(row, "Tag Name"), _text(row, "Tag Status"),
                                       _text(row, "IO Type"), _text(row, "CHARM Type"), _text(row, "Field Cable No"),
                                       cab, cioc, bp, ch))
        cfg = getattr(result, "cfg_used", None)
        for rule in (cfg.rules.project_rules if cfg is not None else []):     # a constraint that covers no cell yet
            for title in titles(rule):
                found.setdefault(f"Project rule|{title}", Impact(f"Project rule|{title}", PROJECT, "Project rule", title))
    except Exception:  # noqa: BLE001 - a broken row must never break the page; what was found so far is shown
        pass
    order = {g: i for i, g in enumerate(GROUPS)}
    return sorted(found.values(), key=lambda x: (order.get(x.group, len(GROUPS)), x.rule, x.title))


def summary(impacts: list[Impact]) -> dict[str, int]:
    """How many rules are met everywhere, broken somewhere, or need a look somewhere."""
    return {"rules": len(impacts), "broken": sum(1 for x in impacts if x.count(FAIL)),
            "to_check": sum(1 for x in impacts if x.count(WARN) and not x.count(FAIL)),
            "met": sum(1 for x in impacts if x.hits and not x.problems)}


__all__ = ["FAIL", "GROUPS", "GROUP_HELP", "Hit", "INFO", "Impact", "PASS", "WARN", "group_of", "rule_impact", "summary"]
