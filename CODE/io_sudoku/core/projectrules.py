"""Project rules on CHARM signals: extra project columns and constraints, added through the governed rule path.

The main kind (proposed on the Rules page, verified in the Review Queue, activated as a new pack version):
  column_rule      ONE column with everything about it:
                   * a NEW project column ('Voltage', a number in V) with a value for each signal: values typed
                     per signal first, then fill rules ('signals whose IO Type contains AI get 24'), then one
                     value for every other signal (or blank);
                   * or an EXISTING allocation column (checks only: the allocation itself is locked);
                   * its checks: at most / at least / between / not blank / equal / one of / no duplicates ...,
                     each on every signal or only some, each an ERROR (blocks the result) or a WARNING (sign off).
                   A column has one rule: a new version of it replaces the old one, and it can be removed.
The first three kinds are kept so older rule packs keep working:
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
from io_sudoku.core.textnorm import match_key

# Columns of the finished allocation a rule may look at (all exist in the 76-column template).
MATCH_COLUMNS: tuple[str, ...] = (
    "Tag Name", "IO Type", "Instrument type", "Service Description", "Segregation", "Technical Room", "Signal Type",
    "Signal Level", "Field Cable No", "Electronic/ Marshalling Cabinet", "Controller", "CHARM Type", "Tag Status",
    "Unit", "Loop Name", "Equipment Name", "HW Loop Typical")
CHECK_COLUMNS: tuple[str, ...] = (
    "Instrument type", "Service Description", "Signal Type", "Signal Level", "Loop Name", "Equipment Name",
    "HW Loop Typical", "Location", "Operating Area", "Risk Area", "DSTName", "Section / Sub Unit", "Remarks")
ALLOCATION_COLUMNS: tuple[str, ...] = tuple(sorted(set(MATCH_COLUMNS) | set(CHECK_COLUMNS), key=str.casefold))
KINDS = ("project_column", "expect_hardware", "require_filled", "column_rule")
COLUMN_TYPES = ("text", "number")
HOWS = {"contains": "contains", "is": "is exactly", "starts": "starts with", "all": "(every signal)"}
TAGS = "tags"                        # a scope that names its signals one by one: {"how": "tags", "tags": [...]}
# check key: (label in the form, how many values it needs, the column types it suits)
CHECKS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "max": ("At most (maximum)", "one", ("number",)),
    "min": ("At least (minimum)", "one", ("number",)),
    "between": ("Between two values", "two", ("number",)),
    "required": ("Must not be blank", "none", COLUMN_TYPES),
    "equals": ("Must equal", "one", COLUMN_TYPES),
    "not_equals": ("Must not equal", "one", COLUMN_TYPES),
    "one_of": ("Must be one of", "list", COLUMN_TYPES),
    "contains": ("Must contain", "one", ("text",)),
    "max_length": ("At most N characters", "one", ("text",)),
    "unique": ("No two signals the same", "none", COLUMN_TYPES),
}
SEVERITIES = ("error", "warning")
LIMITS = {"column": 30, "unit": 12, "value": 60, "values": 20000, "fills": 30, "checks": 20, "list": 50, "note": 300,
          "tag": 80, "scope_tags": 2000}
EVERYTHING = "*"                     # match text that means 'every signal'
_SIGNAL_STATUSES = (STATUS_FIELD, STATUS_ALARM)   # real signals; wired spares and empty slots carry no field data


def charm_types() -> tuple[str, ...]:
    """Every functional CHARM type of the hardware table (read-only: the table itself is locked)."""
    from io_sudoku.core.catalog import hardware
    from io_sudoku.core.constants import PROFILES
    return tuple(sorted({hardware(p).charm_type for p in PROFILES}))


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() in ("", "-")


def is_signal(row: dict[str, Any]) -> bool:
    return row.get("Tag Status") in _SIGNAL_STATUSES


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
    """{column: value} of every project column that applies to this row (later rules win).  A column with a unit
    is named 'Voltage (V)'; blank values are left out."""
    out: dict[str, str] = {}
    for rule in rules:
        if rule.get("kind") == "project_column" and matches(rule, row):
            out[str(rule["args"]["column"])] = str(rule["args"]["value"])
        elif rule.get("kind") == "column_rule" and (rule.get("args") or {}).get("new") and is_signal(row):
            value, _ = column_value(rule, row)
            if not _blank(value):
                a = rule["args"]
                out[str(a["column"]) + (f" ({a['unit']})" if a.get("unit") else "")] = value
    return out


def check_project_rules(rows: list[dict[str, Any]], rules: tuple[dict[str, Any], ...], log: Any) -> None:
    """After the solve: one TQ per constraint or check that some signal breaks - PROJECT-RULE-BROKEN (a warning)
    or PROJECT-CHECK-ERROR (an error, for a check the engineer marked as an error)."""
    from io_sudoku.core.tq import project_rule_message
    for rule in rules:
        if rule.get("kind") == "column_rule":
            a = rule.get("args") or {}
            for i, chk in enumerate(a.get("checks") or []):
                dupes = duplicates(rule, chk, rows) if chk.get("check") == "unique" else None
                broken = [r for r in rows if is_signal(r) and in_scope(chk.get("scope"), r)
                          and judge_check(rule, chk, r, dupes).ok is False]
                if broken:
                    tags = [str(r.get("Tag Name")) for r in broken]
                    log.add("PROJECT-CHECK-ERROR" if chk.get("severity") == "error" else "PROJECT-RULE-BROKEN",
                            f"{rule.get('id') or a.get('column')} check {i + 1}",
                            project_rule_message(check_text(a, chk), len(broken), tags))
            continue
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
    if rule["kind"] == "column_rule":
        return normalize_column_rule(rule["args"])[1]
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


# ------------------------------------------------------------------------------------------- column rules
def tag_key(tag: Any) -> str:
    """How a signal is found in a column's typed values: its tag, cleaned and not case-sensitive."""
    return match_key(tag) or ""


def to_number(value: Any) -> float | None:
    """'24', '24.5', ' 1,000 ' -> a number; anything else -> None."""
    try:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        number = float(text)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def show_number(number: float) -> str:
    return f"{number:g}"


def in_scope(scope: Any, row: dict[str, Any]) -> bool:
    """True if the row is one of the signals a fill rule or a check is about (no scope = every signal)."""
    if not isinstance(scope, dict) or scope.get("how", "all") == "all":
        return True
    if scope.get("how") == TAGS:
        return tag_key(row.get("Tag Name")) in {tag_key(t) for t in scope.get("tags") or []}
    text = str(scope.get("text") or "").strip().casefold()
    value = row.get(scope.get("column"))
    if not text or _blank(value):
        return False
    have = str(value).strip().casefold()
    how = scope.get("how")
    if how == "is":
        return " ".join(have.split()) == " ".join(text.split())
    if how == "starts":
        return have.startswith(text)
    return text in have


def scope_words(scope: Any) -> str:
    if not isinstance(scope, dict) or scope.get("how", "all") == "all":
        return "every signal"
    if scope.get("how") == TAGS:
        tags = [str(t) for t in scope.get("tags") or []]
        return f"the signal {tags[0]}" if len(tags) == 1 else \
            f"these {len(tags)} signals: " + ", ".join(tags[:5]) + (" …" if len(tags) > 5 else "")
    return f"signals whose {scope.get('column')} {HOWS.get(scope.get('how'), 'contains')} '{scope.get('text')}'"


def _with_unit(a: dict[str, Any], value: Any) -> str:
    return f"{value} {a['unit']}" if a.get("unit") and str(value).strip() else str(value)


def column_value(rule: dict[str, Any], row: dict[str, Any]) -> tuple[str, str]:
    """(value, where it came from) of a column rule's column on one signal.  A new column: the value typed for
    the signal, else the LAST fill rule that covers it, else the value for every other signal.  An existing
    allocation column: the value in the allocation."""
    a = rule.get("args") or {}
    if not a.get("new"):
        value = row.get(a.get("column"))
        return ("" if value is None else str(value).strip()), "the allocation"
    typed = a.get("values") or {}
    key = tag_key(row.get("Tag Name"))
    if key and key in typed:
        return str(typed[key]), "typed for this signal"
    fills = a.get("fills") or []
    for i in range(len(fills) - 1, -1, -1):
        if in_scope(fills[i], row):
            return str(fills[i].get("value") or ""), f"fill rule {i + 1}: {scope_words(fills[i])}"
    return str(a.get("default") or ""), "the value for every other signal"


def check_text(a: dict[str, Any], chk: dict[str, Any], severity: bool = True) -> str:
    """One check in words: 'Voltage must be at most 24 V on every signal (error)'."""
    col, kind = a.get("column"), chk.get("check")
    v, v2 = chk.get("value", ""), chk.get("value2", "")
    quote = (lambda x: _with_unit(a, x)) if a.get("type") == "number" else (lambda x: f"'{x}'")
    body = {
        "max": f"must be at most {_with_unit(a, v)}",
        "min": f"must be at least {_with_unit(a, v)}",
        "between": f"must be between {v} and {_with_unit(a, v2)}",
        "required": "must not be blank",
        "equals": f"must be {quote(v)}",
        "not_equals": f"must not be {quote(v)}",
        "one_of": "must be one of " + ", ".join(quote(x) for x in chk.get("values") or []),
        "contains": f"must contain '{v}'",
        "max_length": f"must be at most {v} characters long",
        "unique": "must be different on every signal (no duplicates)",
    }.get(kind, "must pass a check")
    out = f"{col} {body} on {scope_words(chk.get('scope'))}"
    return out + (f" ({chk.get('severity', 'warning')})" if severity else "")


def duplicates(rule: dict[str, Any], chk: dict[str, Any], rows: list[dict[str, Any]]) -> set[str]:
    """The values that more than one covered signal has (for a 'no two signals the same' check)."""
    seen: dict[str, int] = {}
    for r in rows:
        if is_signal(r) and in_scope(chk.get("scope"), r):
            value, _ = column_value(rule, r)
            if not _blank(value):
                key = _same(rule, value)
                seen[key] = seen.get(key, 0) + 1
    return {k for k, n in seen.items() if n > 1}


def _same(rule: dict[str, Any], value: Any) -> str:
    """A comparison key: numbers by value (24 = 24.0), text not case-sensitive."""
    if (rule.get("args") or {}).get("type") == "number":
        number = to_number(value)
        if number is not None:
            return show_number(number)
    return " ".join(str(value).casefold().split())


def judge_check(rule: dict[str, Any], chk: dict[str, Any], row: dict[str, Any], dupes: set[str] | None = None) -> Outcome:
    """One check on one signal.  ok None = not checked (a blank value: only 'must not be blank' checks blanks)."""
    a = rule.get("args") or {}
    value, _ = column_value(rule, row)
    col, kind = a.get("column"), chk.get("check")
    shown = _with_unit(a, value)
    if kind == "required":
        return Outcome(rule, row, not _blank(value), f"{col} is " + ("blank" if _blank(value) else f"'{shown}'"))
    if _blank(value):
        return Outcome(rule, row, None, f"{col} is blank, so this check is skipped")
    number = a.get("type") == "number"
    x = to_number(value) if number else None
    if number and x is None:
        return Outcome(rule, row, False, f"{col} is '{value}', which is not a number")
    v, v2 = chk.get("value", ""), chk.get("value2", "")
    if kind == "max":
        ok = x <= to_number(v)
        return Outcome(rule, row, ok, f"{col} is {shown}" + ("" if ok else f", above the maximum {_with_unit(a, v)}"))
    if kind == "min":
        ok = x >= to_number(v)
        return Outcome(rule, row, ok, f"{col} is {shown}" + ("" if ok else f", below the minimum {_with_unit(a, v)}"))
    if kind == "between":
        ok = to_number(v) <= x <= to_number(v2)
        return Outcome(rule, row, ok, f"{col} is {shown}" + ("" if ok else f", outside {v} to {_with_unit(a, v2)}"))
    if kind in ("equals", "not_equals"):
        same = _same(rule, value) == _same(rule, v)
        ok = same if kind == "equals" else not same
        return Outcome(rule, row, ok, f"{col} is '{shown}'" + ("" if ok else (f", not '{_with_unit(a, v)}'" if kind == "equals"
                                                                         else ", which is not allowed")))
    if kind == "one_of":
        allowed = {_same(rule, w) for w in chk.get("values") or []}
        ok = _same(rule, value) in allowed
        return Outcome(rule, row, ok, f"{col} is '{shown}'" + ("" if ok else ", which is not in the allowed list"))
    if kind == "contains":
        ok = str(v).casefold() in value.casefold()
        return Outcome(rule, row, ok, f"{col} is '{value}'" + ("" if ok else f", without '{v}'"))
    if kind == "max_length":
        ok = len(value) <= int(to_number(v) or 0)
        return Outcome(rule, row, ok, f"{col} has {len(value)} characters" + ("" if ok else f", more than {v}"))
    if kind == "unique":
        ok = _same(rule, value) not in (dupes or set())
        return Outcome(rule, row, ok, f"{col} is '{shown}'" + ("" if ok else ", which another signal also has"))
    return Outcome(rule, row, None, "unknown check")


def rule_outcomes(rule: dict[str, Any], row: dict[str, Any], dupes: dict[int, set[str]] | None = None
                  ) -> list[tuple[str, Outcome, str]]:
    """Every result of one project rule on one row: (title, outcome, severity).  Empty when it does not apply.
    `dupes` = {check index: duplicated values} for the 'no two signals the same' checks."""
    if rule.get("kind") != "column_rule":
        return [(str(rule.get("statement") or rule.get("kind")), judge(rule, row), "warning")] if matches(rule, row) else []
    if not is_signal(row):
        return []
    a = rule.get("args") or {}
    out = []
    if a.get("new"):
        value, source = column_value(rule, row)
        if not _blank(value):
            out.append((f"Project column '{a.get('column')}'", Outcome(rule, row, None, f"{a.get('column')} = "
                                                                       f"{_with_unit(a, value)} ({source})"), "info"))
    for i, chk in enumerate(a.get("checks") or []):
        if in_scope(chk.get("scope"), row):
            out.append((check_text(a, chk, severity=False), judge_check(rule, chk, row, (dupes or {}).get(i)),
                        chk.get("severity", "warning")))
    return out


def all_dupes(rule: dict[str, Any], rows: list[dict[str, Any]]) -> dict[int, set[str]]:
    """{check index: duplicated values} of every 'no two signals the same' check of a column rule."""
    if rule.get("kind") != "column_rule":
        return {}
    return {i: duplicates(rule, chk, rows) for i, chk in enumerate((rule.get("args") or {}).get("checks") or [])
            if chk.get("check") == "unique"}


def titles(rule: dict[str, Any]) -> list[str]:
    """The titles rule_outcomes() gives this rule (so a rule that covers no cell yet can still be listed)."""
    if rule.get("kind") != "column_rule":
        return [str(rule.get("statement") or rule.get("kind"))]
    a = rule.get("args") or {}
    return ([f"Project column '{a.get('column')}'"] if a.get("new") else []) + \
        [check_text(a, chk, severity=False) for chk in a.get("checks") or []]


def covers(rule: dict[str, Any], row: dict[str, Any]) -> bool:
    """True if the rule says anything about this row (a value, or a check that covers it)."""
    if rule.get("kind") != "column_rule":
        return matches(rule, row)
    return bool(rule_outcomes(rule, row))


def column_statement(a: dict[str, Any]) -> str:
    """The rule in words, written by code from the form (never typed free-hand)."""
    col = a.get("column")
    if a.get("remove"):
        return (f"Remove the project column '{col}' and its checks." if a.get("new")
                else f"Remove the checks on the column '{col}'.")
    checks = "; ".join(check_text(a, c) for c in a.get("checks") or [])
    if not a.get("new"):
        return f"Checks on the allocation column '{col}': {checks or 'none'}."
    kind = a.get("type", "text") + (f", {a['unit']}" if a.get("unit") else "")
    parts = []
    n = len(a.get("values") or {})
    if n:
        parts.append(f"{n:,} signal{'s have their' if n != 1 else ' has its'} own value")
    for f in a.get("fills") or []:
        parts.append(f"{scope_words(f)} get {_with_unit(a, f.get('value')) if str(f.get('value') or '').strip() else 'blank'}")
    default = str(a.get("default") or "").strip()
    parts.append(f"every other signal gets {_with_unit(a, default)}" if default else "every other signal is blank")
    text = f"Project column '{col}' ({kind}): " + "; ".join(parts) + "."
    return text + (f" Checks: {checks}." if checks else " No checks.")


def _clean_text(value: Any, limit: int, name: str, errors: list[str], blank_ok: bool = True) -> str:
    text = "" if value is None else str(value).strip()
    if any(ord(ch) < 32 for ch in text):
        errors.append(f"{name} must be plain text (no line breaks).")
        return ""
    if len(text) > limit:
        errors.append(f"{name} must be at most {limit} characters.")
        return text[:limit]
    if not text and not blank_ok:
        errors.append(f"Please fill in {name}.")
    return text


def _clean_scope(scope: Any, name: str, errors: list[str]) -> dict[str, str]:
    if not isinstance(scope, dict) or scope.get("how", "all") in ("all", None, ""):
        return {"how": "all"}
    if scope.get("how") == TAGS:
        raw = scope.get("tags") if isinstance(scope.get("tags"), (list, tuple)) else []
        tags = list(dict.fromkeys(" ".join(str(t).split())[:LIMITS["tag"]] for t in raw if str(t or "").strip()))
        if not tags:
            errors.append(f"{name}: pick at least one signal.")
        if len(tags) > LIMITS["scope_tags"]:
            errors.append(f"{name}: at most {LIMITS['scope_tags']:,} signals can be picked one by one.")
        return {"how": TAGS, "tags": tags[:LIMITS["scope_tags"]]}
    how = scope.get("how") if scope.get("how") in HOWS else "contains"
    column = next((c for c in MATCH_COLUMNS if c.casefold() == str(scope.get("column") or "").strip().casefold()), None)
    if column is None:
        errors.append(f"{name}: '{scope.get('column')}' is not a column a rule can look at.")
        column = MATCH_COLUMNS[0]
    text = _clean_text(scope.get("text"), 40, f"{name}: the text to look for", errors, blank_ok=False)
    if text == EVERYTHING:
        return {"how": "all"}
    return {"column": column, "how": how, "text": text}


def _clean_value(value: Any, number: bool, name: str, errors: list[str]) -> str:
    text = _clean_text(value, LIMITS["value"], name, errors)
    if number and text:
        x = to_number(text)
        if x is None:
            errors.append(f"{name} must be a number ('{text}' is not).")
            return text
        return show_number(x)
    return text


def normalize_column_rule(args: Any) -> tuple[dict[str, Any], list[str]]:
    """A column rule cleaned and checked: (clean args, problems).  Used for the form, the AI's draft and a loaded
    rule pack alike, so a column rule is always one of the known shapes with valid values."""
    errors: list[str] = []
    if not isinstance(args, dict):
        return {}, ["A column rule is malformed."]
    new = bool(args.get("new", True))
    out: dict[str, Any] = {"new": new}
    if new:
        column = _clean_text(args.get("column"), LIMITS["column"], "the column name", errors, blank_ok=False)
        if column and any(column.casefold() == c.casefold() for c in ALLOCATION_COLUMNS):
            errors.append(f"'{column}' is already a column of the allocation: pick it from the list to add checks to it.")
    else:
        column = next((c for c in ALLOCATION_COLUMNS if c.casefold() == str(args.get("column") or "").strip().casefold()), "")
        if not column:
            errors.append(f"'{args.get('column')}' is not an allocation column that can be checked.")
    out["column"] = column
    if args.get("remove"):
        out["remove"] = True
        return out, errors
    kind = str(args.get("type") or "text").strip().lower()
    if kind not in COLUMN_TYPES:
        errors.append(f"The column type must be text or number, not '{kind}'.")
        kind = "text"
    number = kind == "number"
    out["type"] = kind
    out["unit"] = _clean_text(args.get("unit"), LIMITS["unit"], "the unit", errors) if number else ""
    out["note"] = _clean_text(args.get("note"), LIMITS["note"], "the purpose", errors)
    if new:
        values = args.get("values") or {}
        if not isinstance(values, dict):
            errors.append("The typed values are malformed.")
            values = {}
        if len(values) > LIMITS["values"]:
            errors.append(f"At most {LIMITS['values']:,} signals can have their own value.")
        clean_values: dict[str, str] = {}
        bad: list[str] = []
        for tag, value in list(values.items())[:LIMITS["values"]]:
            key = tag_key(tag)
            if not key or len(key) > LIMITS["tag"]:
                continue
            problems: list[str] = []
            clean_values[key] = _clean_value(value, number, f"the value of {tag}", problems)
            if problems:
                bad.append(str(tag))
        if bad:
            errors.append(f"{len(bad):,} typed value{'s are' if len(bad) != 1 else ' is'} not "
                          f"{'a number' if number else 'plain text of at most 60 characters'}: " + ", ".join(bad[:5])
                          + (" ..." if len(bad) > 5 else ""))
        out["values"] = dict(sorted(clean_values.items()))
        fills = args.get("fills") or []
        if not isinstance(fills, list) or len(fills) > LIMITS["fills"]:
            errors.append(f"A column can have at most {LIMITS['fills']} fill rules.")
            fills = list(fills)[:LIMITS["fills"]] if isinstance(fills, list) else []
        out["fills"] = []
        for i, f in enumerate(fills, 1):
            if not isinstance(f, dict):
                errors.append(f"Fill rule {i} is malformed.")
                continue
            scope = _clean_scope(f, f"Fill rule {i}", errors)
            out["fills"].append({**scope, "value": _clean_value(f.get("value"), number, f"the value of fill rule {i}", errors)})
        out["default"] = _clean_value(args.get("default"), number, "the value for every other signal", errors)
    checks = args.get("checks") or []
    if not isinstance(checks, list) or len(checks) > LIMITS["checks"]:
        errors.append(f"A column can have at most {LIMITS['checks']} checks.")
        checks = list(checks)[:LIMITS["checks"]] if isinstance(checks, list) else []
    out["checks"] = []
    for i, c in enumerate(checks, 1):
        name = f"Check {i}"
        if not isinstance(c, dict) or c.get("check") not in CHECKS:
            errors.append(f"{name} is not one of the known checks.")
            continue
        label, needs, suits = CHECKS[c["check"]]
        if kind not in suits:
            errors.append(f"{name} ('{label}') does not suit a {kind} column.")
            continue
        chk: dict[str, Any] = {"check": c["check"]}
        if needs in ("one", "two"):
            limit_name = f"{name}: the value"
            if c["check"] == "max_length":
                n = to_number(c.get("value"))
                if n is None or n != int(n) or not 1 <= n <= 500:
                    errors.append(f"{name}: the number of characters must be a whole number from 1 to 500.")
                chk["value"] = str(int(n)) if n is not None and n == int(n) else str(c.get("value") or "")
            else:
                chk["value"] = _clean_value(c.get("value"), number, limit_name, errors)
                if not chk["value"]:
                    errors.append(f"{name}: please give the value to compare with.")
            if needs == "two":
                chk["value2"] = _clean_value(c.get("value2"), number, f"{name}: the second value", errors)
                lo, hi = to_number(chk["value"]), to_number(chk["value2"])
                if lo is None or hi is None:
                    errors.append(f"{name}: please give both ends of the range.")
                elif lo > hi:
                    errors.append(f"{name}: the first value must not be bigger than the second.")
        elif needs == "list":
            items = c.get("values")
            if isinstance(items, str):
                items = [x for x in items.split(",")]
            items = [x for x in (items or []) if str(x).strip()]
            if not items:
                errors.append(f"{name}: please give at least one allowed value.")
            if len(items) > LIMITS["list"]:
                errors.append(f"{name}: at most {LIMITS['list']} allowed values.")
            chk["values"] = list(dict.fromkeys(_clean_value(x, number, f"{name}: an allowed value", errors)
                                               for x in items[:LIMITS["list"]]))
        severity = str(c.get("severity") or "warning").lower()
        chk["severity"] = severity if severity in SEVERITIES else "warning"
        chk["scope"] = _clean_scope(c.get("scope"), name, errors)
        out["checks"].append(chk)
    if not new and not out["checks"]:
        errors.append("Add at least one check to the column.")
    return out, list(dict.fromkeys(errors))
