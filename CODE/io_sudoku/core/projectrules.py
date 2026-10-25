"""Project rules on CHARM signals: extra project columns and constraints, added through the governed rule path.

Three kinds (proposed on the Rules page, verified in the Review Queue, activated as a new pack version):
  project_column   'Add the project column Loop Check = Pending to every signal whose IO Type contains AIR.'
                   A label the project wants on some signals.  It is shown in the app (Rule Check, the
                   'where it applies' table, its own CSV); the 76-column allocation is LOCKED, so it is never
                   written into the allocation itself.
  expect_hardware  'Every signal whose Instrument type contains solenoid must use CHARM SE4302T02.'
  require_filled   'Every signal whose IO Type contains DOR must have Loop Name filled in.'
                   Constraints are CHECKS: after the solve, every signal they cover is checked, and a broken
                   constraint becomes ONE warning TQ (PROJECT-RULE-BROKEN) that must be signed off.

None of them moves a signal or changes a CHARM: placement, hardware choice and every locked rule stay
exactly as they are, and the solver stays deterministic.  This module only READS the finished rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from io_sudoku.core.constants import STATUS_ALARM, STATUS_FIELD

# Columns of the finished allocation a rule may look at (all exist in the 76-column template).
MATCH_COLUMNS: tuple[str, ...] = (
    "Tag Name", "IO Type", "Instrument type", "Service Description", "Segregation", "Technical Room", "Signal Type",
    "Signal Level", "Field Cable No", "Electronic/ Marshalling Cabinet", "Controller", "CHARM Type", "Tag Status",
    "Unit", "Loop Name", "Equipment Name", "HW Loop Typical")
CHECK_COLUMNS: tuple[str, ...] = (
    "Instrument type", "Service Description", "Signal Type", "Signal Level", "Loop Name", "Equipment Name",
    "HW Loop Typical", "Location", "Operating Area", "Risk Area", "DSTName", "Section / Sub Unit", "Remarks")
KINDS = ("project_column", "expect_hardware", "require_filled")
EVERYTHING = "*"                     # match text that means 'every signal'
_SIGNAL_STATUSES = (STATUS_FIELD, STATUS_ALARM)   # real signals; wired spares and empty slots carry no field data


def charm_types() -> tuple[str, ...]:
    """Every functional CHARM type of the hardware table (read-only: the table itself is locked)."""
    from io_sudoku.core.catalog import hardware
    from io_sudoku.core.constants import PROFILES
    return tuple(sorted({hardware(p).charm_type for p in PROFILES}))


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() in ("", "-")


def matches(rule: dict[str, Any], row: dict[str, Any]) -> bool:
    """True if the rule covers this row: a Field signal or cabinet alarm (not a wired spare or an empty slot)
    whose match column contains the match text (not case-sensitive; '*' = every signal)."""
    if row.get("Tag Status") not in _SIGNAL_STATUSES:
        return False
    args = rule.get("args") or {}
    text = str(args.get("match_text") or "").strip()
    if text == EVERYTHING:
        return True
    value = row.get(args.get("match_column"))
    return bool(text) and not _blank(value) and text.casefold() in str(value).casefold()


@dataclass(frozen=True)
class Outcome:
    """One rule on one row.  ok None = a project column (nothing to pass or fail)."""
    rule: dict[str, Any]
    row: dict[str, Any]
    ok: bool | None
    detail: str


def judge(rule: dict[str, Any], row: dict[str, Any]) -> Outcome:
    args = rule.get("args") or {}
    kind = rule.get("kind")
    if kind == "expect_hardware":
        have, want = str(row.get("CHARM Type") or "-"), str(args.get("charm_type"))
        return Outcome(rule, row, have == want, f"uses CHARM {have}" + ("" if have == want else f", the rule expects {want}"))
    if kind == "require_filled":
        column = str(args.get("check_column"))
        value = row.get(column)
        return Outcome(rule, row, not _blank(value), f"{column} is " + ("empty" if _blank(value) else f"'{value}'"))
    return Outcome(rule, row, None, f"{args.get('column')} = {args.get('value')}")


def outcomes(rule: dict[str, Any], rows: list[dict[str, Any]]) -> list[Outcome]:
    """The rule on every row it covers, in allocation order."""
    return [judge(rule, r) for r in rows if matches(rule, r)]


def project_columns(rules: tuple[dict[str, Any], ...] | list[dict[str, Any]], row: dict[str, Any]) -> dict[str, str]:
    """{column: value} of every project column that applies to this row (later rules win)."""
    out: dict[str, str] = {}
    for rule in rules:
        if rule.get("kind") == "project_column" and matches(rule, row):
            out[str(rule["args"]["column"])] = str(rule["args"]["value"])
    return out


def check_project_rules(rows: list[dict[str, Any]], rules: tuple[dict[str, Any], ...], log: Any) -> None:
    """After the solve: one PROJECT-RULE-BROKEN warning per constraint that some signal breaks."""
    from io_sudoku.core.tq import project_rule_message
    for rule in rules:
        if rule.get("kind") not in ("expect_hardware", "require_filled"):
            continue
        broken = [o for o in outcomes(rule, rows) if o.ok is False]
        if broken:
            tags = [str(o.row.get("Tag Name")) for o in broken]
            log.add("PROJECT-RULE-BROKEN", str(rule.get("id") or rule.get("statement") or "project rule"),
                    project_rule_message(str(rule.get("statement") or ""), len(broken), tags))


def validate_rule(rule: Any) -> list[str]:
    """Problems with one stored project rule (a rule pack must never carry a malformed one)."""
    if not isinstance(rule, dict) or rule.get("kind") not in KINDS or not isinstance(rule.get("args"), dict):
        return ["A project rule is malformed."]
    args, out = rule["args"], []
    if args.get("match_column") not in MATCH_COLUMNS:
        out.append("A project rule looks at a column that is not allowed.")
    text = str(args.get("match_text") or "").strip()
    if not text or len(text) > 40:
        out.append("A project rule needs a match text of 1 to 40 characters.")
    if rule["kind"] == "project_column":
        for name, limit in (("column", 30), ("value", 40)):
            value = str(args.get(name) or "").strip()
            if not value or len(value) > limit:
                out.append(f"A project column needs a {name} of 1 to {limit} characters.")
    elif rule["kind"] == "expect_hardware" and args.get("charm_type") not in charm_types():
        out.append("A hardware constraint names an unknown CHARM type.")
    elif rule["kind"] == "require_filled" and args.get("check_column") not in CHECK_COLUMNS:
        out.append("A required-value constraint checks a column that is not allowed.")
    return out
