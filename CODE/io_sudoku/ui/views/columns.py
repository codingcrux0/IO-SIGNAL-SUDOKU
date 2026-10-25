"""Columns And Checks: the Rules page form for ONE column with its values and its checks.

  1 · Column   a new project column (name, text or number, unit), a project column that is already active (to
               change it), or an existing allocation column (checks only: the 76-column allocation is locked).
  2 · Values   first: type a value per signal in the table (find signals, then give all the shown ones one value
               at once), or paste / upload a list of tags and values.  Second: fill rules ('signals whose IO Type
               contains AI get 24') and one value for every other signal (or blank).
  3 · Checks   at most / at least / between / not blank / equal / one of / no duplicates ..., each on every
               signal or only some, each an error (blocks the result) or a warning (sign off).  Every check shows
               live how many signals of the current allocation break it.
The wording is written by code (projectrules.column_statement).  Proposing sends the column to the Review Queue
like every other rule; nothing changes before it is verified and activated.  The optional AI only fills in this
form or makes the purpose note clearer; it never sees the MDB data and never proposes or changes anything.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

import streamlit as st

from io_sudoku.core import projectrules as pr
from io_sudoku.core import rulechange as rc
from io_sudoku.ui import state
from io_sudoku.ui.views._common import md_escape

GROUP = "Columns And Checks"
WHERE = "Propose A Rule"
NEW = "__new__"
TYPE_LABELS = {"text": "Text", "number": "Number"}
SEV_LABELS = {"error": "Error · blocks the result", "warning": "Warning · sign off"}
SCOPE_LABELS = {"all": "Every signal", "some": "Only some signals"}
SHOW = ("All", "Filled", "Blank", "Typed")
EMPTY_VIEW = {"Filled": "No signal has a value yet, so Filled shows none (that is correct). Pick Show: All and type "
                        "values in the table, paste them, or use Fill Many At Once; they then show up here.",
              "Typed": "No value has been typed by hand yet, so Typed shows none (that is correct). Values from fill "
                       "rules or “every other signal” count as Filled, not Typed.",
              "Blank": "Every signal has a value, so Blank shows none.",
              "All": "No signal to show. Run an allocation first."}
SHOWN_COLUMNS = (("Tag", "Tag Name"), ("IO Type", "IO Type"), ("Instrument", "Instrument type"),
                 ("Service", "Service Description"), ("Cabinet", "Electronic/ Marshalling Cabinet"))
MAX_PICKS = 400
DEFAULTS: dict[str, Any] = {"cb_target": NEW, "cb_name": "", "cb_type": "text", "cb_unit": "", "cb_note": "",
                            "cb_values": {}, "cb_ver": 0, "cb_view": None, "cb_find": "", "cb_show": "All",
                            "cb_fills": [], "cb_default": "", "cb_checks": [], "cb_uid": 0, "cb_set_value": "",
                            "cb_paste": "", "cb_ai_request": "", "cb_result": None}


# ----------------------------------------------------------------------------------------------- state
def _init() -> None:
    s = st.session_state
    for key, value in DEFAULTS.items():
        if key not in s:
            s[key] = value.copy() if isinstance(value, (dict, list)) else value
    if s.get("cb_type") not in TYPE_LABELS:              # pressing the chosen button again clears it: keep the last
        s["cb_type"] = s.get("cb_type_last") or "text"
    s["cb_type_last"] = s["cb_type"]
    if s.get("cb_show") not in SHOW:
        s["cb_show"] = "All"
    if s["cb_target"] not in _targets():
        s["cb_target"] = NEW
    result = s.get("result")
    if s.get("cb_result") != id(result):              # a new allocation: keep what was typed, rebuild the table
        if s.get("cb_result") is not None:
            _fold()
        s["cb_result"] = id(result)


def _uid() -> int:
    s = st.session_state
    s["cb_uid"] = int(s.get("cb_uid") or 0) + 1
    return s["cb_uid"]


def _signals() -> list[dict[str, Any]]:
    result = st.session_state.get("result")
    return [r for r in (getattr(result, "rows", None) or []) if pr.is_signal(r)]


def _active() -> list[dict[str, Any]]:
    return list((st.session_state["pack"].overrides or {}).get("project_rules", []))


def _project_names() -> list[str]:
    names = []
    for r in _active():
        a = r.get("args") or {}
        if (r.get("kind") == "column_rule" and a.get("new")) or r.get("kind") == "project_column":
            names.append(str(a.get("column")))
    return list(dict.fromkeys(names))


def _targets() -> list[str]:
    return [NEW] + [f"project:{n}" for n in _project_names()] + [f"alloc:{c}" for c in pr.ALLOCATION_COLUMNS]


def _target_label(t: str) -> str:
    if t == NEW:
        return "➕ A new column"
    kind, name = t.split(":", 1)
    return f"✏️ {name} · project column (change it)" if kind == "project" else f"🔒 {name} · allocation column (checks only)"


def _is_new() -> bool:
    return not str(st.session_state.get("cb_target") or NEW).startswith("alloc:")


def _column_name() -> str:
    t = str(st.session_state.get("cb_target") or NEW)
    return str(st.session_state.get("cb_name") or "").strip() if t == NEW else t.split(":", 1)[1]


def _number() -> bool:
    return st.session_state.get("cb_type") == "number"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return "" if value != value else pr.show_number(value)
    return str(value).strip()


def _editor_key() -> str:
    return f"cb_editor_{st.session_state.get('cb_ver', 0)}"


def _typed() -> dict[str, str]:
    """The values typed by hand: those saved so far plus the edits waiting in the table."""
    s = st.session_state
    typed = dict(s.get("cb_values") or {})
    view = s.get("cb_view")
    edits = (s.get(_editor_key()) or {}).get("edited_rows") or {}
    if not view or view[0] != s.get("cb_ver"):
        return typed
    keys = view[1]
    for index, change in edits.items():
        try:
            key = keys[int(index)]
        except (ValueError, IndexError):
            continue
        if "Value" in change:
            typed[key] = _text(change["Value"])
    return typed


def _fold() -> None:
    """Save the table's edits as typed values and start a fresh table (after a filter or a bulk change)."""
    s = st.session_state
    s["cb_values"] = _typed()
    s["cb_ver"] = int(s.get("cb_ver") or 0) + 1
    s["cb_view"] = None


def _scope_of(prefix: str) -> dict[str, str]:
    s = st.session_state
    if s.get(f"{prefix}_how") in (None, "all"):
        return {"how": "all"}
    return {"column": s.get(f"{prefix}_col") or pr.MATCH_COLUMNS[0], "how": s.get(f"{prefix}_how") or "contains",
            "text": _text(s.get(f"{prefix}_text"))}


def _draft(values: dict[str, str] | None = None) -> dict[str, Any]:
    """The form as rule arguments (not yet cleaned: projectrules.normalize_column_rule does that)."""
    s = st.session_state
    new = _is_new()
    args: dict[str, Any] = {"new": new, "column": _column_name(), "type": s.get("cb_type") or "text",
                            "unit": s.get("cb_unit") or "", "note": s.get("cb_note") or ""}
    if new:
        args["values"] = _typed() if values is None else values
        args["fills"] = [{**_scope_of(f"cb_f{u}"), "value": _text(s.get(f"cb_f{u}_val"))} for u in s["cb_fills"]]
        args["default"] = s.get("cb_default") or ""
    checks = []
    for u in s["cb_checks"]:
        p = f"cb_c{u}"
        scope = _scope_of(p) if s.get(f"{p}_scope") == "some" else {"how": "all"}
        checks.append({"check": s.get(f"{p}_kind"), "value": _text(s.get(f"{p}_v")), "value2": _text(s.get(f"{p}_v2")),
                       "values": [_text(x) for x in s.get(f"{p}_list") or []], "severity": s.get(f"{p}_sev") or "warning",
                       "scope": scope})
    args["checks"] = checks
    return args


def _set_scope(prefix: str, scope: dict[str, Any] | None) -> None:
    s = st.session_state
    scope = scope or {"how": "all"}
    s[f"{prefix}_col"] = scope.get("column") if scope.get("column") in pr.MATCH_COLUMNS else pr.MATCH_COLUMNS[1]
    s[f"{prefix}_how"] = scope.get("how") if scope.get("how") in pr.HOWS else "all"
    s[f"{prefix}_text"] = scope.get("text") or None


def _load(args: dict[str, Any], target: str, keep_values: bool = False) -> None:
    """Fill the form from rule arguments (an active rule, the AI's draft, or nothing to start again)."""
    s = st.session_state
    values = _typed() if keep_values else dict(args.get("values") or {})
    s["cb_target"] = target if target in _targets() else NEW
    s["cb_name"] = str(args.get("column") or "") if s["cb_target"] == NEW else ""
    s["cb_type"] = args.get("type") if args.get("type") in TYPE_LABELS else "text"
    s["cb_unit"] = str(args.get("unit") or "")
    s["cb_note"] = str(args.get("note") or "")
    s["cb_default"] = str(args.get("default") or "")
    s["cb_values"] = values
    s["cb_ver"] = int(s.get("cb_ver") or 0) + 1
    s["cb_view"] = None
    s["cb_find"], s["cb_show"], s["cb_set_value"] = "", "All", ""
    s["cb_fills"] = []
    for f in args.get("fills") or []:
        u = _uid()
        _set_scope(f"cb_f{u}", f if f.get("how", "all") != "all" else {"how": "all"})
        s[f"cb_f{u}_val"] = str(f.get("value") or "")
        s["cb_fills"].append(u)
    s["cb_checks"] = []
    for c in args.get("checks") or []:
        u = _uid()
        p = f"cb_c{u}"
        s[f"{p}_kind"] = c.get("check")
        s[f"{p}_v"], s[f"{p}_v2"] = str(c.get("value") or ""), str(c.get("value2") or "")
        s[f"{p}_list"] = [str(x) for x in c.get("values") or []]
        s[f"{p}_sev"] = c.get("severity") if c.get("severity") in SEV_LABELS else "warning"
        scope = c.get("scope") or {"how": "all"}
        s[f"{p}_scope"] = "all" if scope.get("how", "all") == "all" else "some"
        _set_scope(p, scope if s[f"{p}_scope"] == "some" else {"how": "contains"})
        s["cb_checks"].append(u)


def _rule_args_for(target: str) -> dict[str, Any]:
    """What the form starts with when this column is picked: its active rule, if it has one."""
    if target == NEW:
        return {}
    kind, name = target.split(":", 1)
    for r in reversed(_active()):
        a = r.get("args") or {}
        if r.get("kind") == "column_rule" and str(a.get("column")) == name and bool(a.get("new")) == (kind == "project"):
            return dict(a)
        if kind == "project" and r.get("kind") == "project_column" and str(a.get("column")) == name:
            fill = {"column": a.get("match_column"), "how": "contains", "text": a.get("match_text"), "value": a.get("value")}
            if str(a.get("match_text") or "").strip() == pr.EVERYTHING:
                fill = {"how": "all", "value": a.get("value")}
            return {"new": True, "column": name, "type": "text", "fills": [fill]}
    return {"new": kind != "alloc", "column": name}


# ------------------------------------------------------------------------------------------- callbacks
def _on_target() -> None:
    target = st.session_state.get("cb_target") or NEW
    _load(_rule_args_for(target), target)


def edit_rule(rule: dict[str, Any]) -> None:
    """The Edit button of an active project column: open it in this form."""
    s = st.session_state
    a = rule.get("args") or {}
    target = f"{'project' if (rule.get('kind') == 'project_column' or a.get('new')) else 'alloc'}:{a.get('column')}"
    _load(_rule_args_for(target), target)
    s["rule_group"] = GROUP
    s["scroll_to"] = WHERE
    state.flash("info", f"“{a.get('column')}” is open in the form below. Change it, then press Propose This Change.", WHERE)


def start_from_values(name: str, values: dict[str, str]) -> None:
    """Open the form as a NEW column with a value for each tag already typed in (a column of the uploaded file that
    the allocation does not read, from Preflight › Suggested Fixed File).  Nothing is proposed until you press
    Propose This Column."""
    s = st.session_state
    clean_name = " ".join(str(name or "").split())[:pr.LIMITS["column"]]
    filled = {str(k): str(v).strip()[:pr.LIMITS["value"]] for k, v in (values or {}).items() if str(v).strip()}
    number = bool(filled) and all(pr.to_number(v) is not None for v in filled.values())
    if number:
        filled = {k: pr.show_number(pr.to_number(v)) for k, v in filled.items()}
    _load({"column": clean_name, "type": "number" if number else "text", "values": dict(list(filled.items())[:pr.LIMITS["values"]]),
           "note": f"Copied from the column “{clean_name}” of the uploaded file."}, NEW)
    s["rule_group"] = GROUP
    s["view"] = "Rules"
    s["scroll_to"] = WHERE
    state.flash("info", f"“{clean_name}” is open in the form below with {len(filled):,} values from your file. Check the "
                        "name, add checks if you want, then press Propose This Column.", WHERE)


def remove_rule(rule: dict[str, Any], where: str) -> None:
    """Propose removing an active project column (or the checks on an allocation column)."""
    s = st.session_state
    a = rule.get("args") or {}
    new = rule.get("kind") == "project_column" or bool(a.get("new"))
    proposal, errors = rc.build_proposal("column_rule", {"new": new, "column": a.get("column"), "remove": True},
                                         s.get("rule_author") or "", now=_now())
    if proposal is None:
        state.flash("error", " ".join(errors) + " (Your Name is at the top of Propose A Rule.)", where)
        return
    s["proposals"] = s["proposals"] + [proposal]
    state.flash("success", f"Proposed: {proposal.statement} It waits in the Review Queue.", where)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add_fill() -> None:
    u = _uid()
    _set_scope(f"cb_f{u}", {"column": "IO Type", "how": "contains"})
    st.session_state[f"cb_f{u}_val"] = ""
    st.session_state["cb_fills"] = st.session_state["cb_fills"] + [u]


def _drop(list_key: str, u: int) -> None:
    st.session_state[list_key] = [x for x in st.session_state[list_key] if x != u]


def _add_check() -> None:
    s = st.session_state
    u = _uid()
    p = f"cb_c{u}"
    s[f"{p}_kind"] = "max" if _number() else "required"
    s[f"{p}_v"], s[f"{p}_v2"], s[f"{p}_list"] = "", "", []
    s[f"{p}_sev"], s[f"{p}_scope"] = "error" if _number() else "warning", "all"
    _set_scope(p, {"column": "IO Type", "how": "contains"})
    s["cb_checks"] = s["cb_checks"] + [u]


def _clear() -> None:
    _load({}, NEW)


def _set_shown(clear: bool) -> None:
    """Give every signal shown in the table one value (or take away their typed values)."""
    s = st.session_state
    keys = (s.get("cb_view") or (None, []))[1]
    _fold()
    value = _text(s.get("cb_set_value"))
    if not clear and _number() and value and pr.to_number(value) is None:
        state.flash("error", f"'{value}' is not a number, and this is a number column.", WHERE)
        return
    typed = dict(s["cb_values"])
    for key in keys:
        if clear:
            typed.pop(key, None)
        else:
            typed[key] = pr.show_number(pr.to_number(value)) if _number() and value else value
    s["cb_values"] = typed
    state.flash("success", (f"Took away the typed values of {len(keys):,} signals." if clear else
                            f"Gave {len(keys):,} signals the value “{value or 'blank'}”."), WHERE)


def _read_pairs(text: str, upload: Any) -> list[tuple[str, str]]:
    """(tag, value) pairs from pasted lines ('TAG<tab>value', 'TAG, value' or 'TAG; value') or a CSV / Excel file
    whose first two columns (or the columns named Tag and Value / the column's name) hold them."""
    rows: list[list[Any]] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        if "\t" in line:
            rows.append(line.split("\t"))
        elif ";" in line:
            rows.append(line.split(";"))
        else:
            rows.append(line.rsplit(",", 1))
    if upload is not None:
        data = upload.getvalue()
        if str(upload.name).lower().endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            rows += [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
        else:
            rows += list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        return []
    tag_at, value_at = 0, 1
    header = [_text(x).casefold() for x in rows[0]]
    names = {"tag", "tag name", "tag no", "tag number"}
    if any(h in names for h in header):
        tag_at = next(i for i, h in enumerate(header) if h in names)
        wanted = {_column_name().casefold(), "value"}
        value_at = next((i for i, h in enumerate(header) if h in wanted), tag_at + 1)
        rows = rows[1:]
    return [(_text(r[tag_at]), _text(r[value_at]) if value_at < len(r) else "") for r in rows if len(r) > tag_at and _text(r[tag_at])]


def _use_pasted() -> None:
    s = st.session_state
    try:
        pairs = _read_pairs(s.get("cb_paste") or "", s.get("cb_upload"))
    except Exception:  # noqa: BLE001 - a bad file is a message, never a crash
        state.flash("error", "That file could not be read. Save it as .xlsx or .csv with the tags in the first column "
                             "and the values in the second, then try again.", WHERE)
        return
    if not pairs:
        state.flash("warning", "Nothing to use yet: paste lines like “320-FT-1001, 24” or upload a file.", WHERE)
        return
    known = {pr.tag_key(r.get("Tag Name")) for r in _signals()}
    _fold()
    typed, used, unknown, bad = dict(s["cb_values"]), 0, [], []
    for tag, value in pairs:
        key = pr.tag_key(tag)
        if known and key not in known:
            unknown.append(tag)
            continue
        if _number() and value and pr.to_number(value) is None:
            bad.append(tag)
            continue
        typed[key] = pr.show_number(pr.to_number(value)) if _number() and value else value
        used += 1
    s["cb_values"] = typed
    s["cb_paste"] = ""
    parts = [f"Gave values to {used:,} signals."]
    if unknown:
        parts.append(f"{len(unknown):,} tags are not signals of this allocation and were left out: "
                     + ", ".join(unknown[:5]) + (" ..." if len(unknown) > 5 else ""))
    if bad:
        parts.append(f"{len(bad):,} values are not numbers and were left out: " + ", ".join(bad[:5]) + (" ..." if len(bad) > 5 else ""))
    state.flash("warning" if unknown or bad else "success", " ".join(parts), WHERE)


def _propose() -> None:
    s = st.session_state
    proposal, errors = rc.build_proposal("column_rule", _draft(), s.get("rule_author") or "", now=_now())
    if proposal is None:
        state.flash("error", " ".join(errors), WHERE)
        return
    s["proposals"] = s["proposals"] + [proposal]
    _clear()
    state.flash("success", f"Proposed: {proposal.statement} It waits in the Review Queue: press Verify there, then "
                           "Preview And Activate.", WHERE)


def _client():
    from io_sudoku.ui.views import rules
    return rules._client()


def _ai_fill() -> None:
    from io_sudoku.core import advisor
    s = st.session_state
    draft = advisor.draft_column(s.get("cb_ai_request") or "", _client())
    if not draft.ok:
        state.flash("warning", draft.message + (" " + " ".join(draft.errors) if draft.errors else ""), WHERE)
        return
    a = draft.args
    name = str(a.get("column"))
    target = f"alloc:{name}" if not a.get("new") else (f"project:{name}" if name in _project_names() else NEW)
    _load(a, target, keep_values=True)
    note = "The assistant filled in the form below. Check every part, then press Propose."
    if draft.rationale:
        note += f" How it read your words: {draft.rationale}"
    if draft.errors:
        note += " Left out (they did not pass the checks): " + " ".join(draft.errors)
    state.flash("info", note, WHERE)


def _polish() -> None:
    from io_sudoku.core import advisor
    s = st.session_state
    text, why = advisor.polish_text(s.get("cb_note") or "", _client())
    if text is None:
        state.flash("warning", why, WHERE)
        return
    s["cb_note"] = text
    state.flash("success", "The assistant made the purpose clearer. Change it back if it is not what you meant.", WHERE)


# ------------------------------------------------------------------------------------------------ widgets
def _counts(column: str, signals: list[dict[str, Any]]) -> Counter:
    return Counter(_text(r.get(column)) for r in signals if _text(r.get(column)) not in ("", "-"))


def _picker(label: str, key: str, options: Counter, placeholder: str = "Pick or type…", help: str | None = None) -> None:
    """A dropdown of the values that are really in the allocation (most common first, with how many signals
    have each) that also takes a value you type."""
    s = st.session_state
    choices = [v for v, _ in options.most_common(MAX_PICKS)]
    current = s.get(key)
    if current not in (None, "") and current not in choices:
        choices = [current] + choices
    if key not in s:
        s[key] = None
    st.selectbox(label, choices, key=key, accept_new_options=True, placeholder=placeholder, help=help,
                 format_func=lambda v: f"{v}  ·  {options[v]:,}" if options.get(v) else str(v))


def _scope_widgets(prefix: str, signals: list[dict[str, Any]], with_all: bool) -> None:
    s = st.session_state
    hows = list(pr.HOWS) if with_all else [h for h in pr.HOWS if h != "all"]
    if s.get(f"{prefix}_how") not in hows:
        s[f"{prefix}_how"] = hows[0]
    if s.get(f"{prefix}_col") not in pr.MATCH_COLUMNS:
        s[f"{prefix}_col"] = "IO Type"
    a, b, c = st.columns([1.3, 1, 1.5])
    a.selectbox("Look At Column", pr.MATCH_COLUMNS, key=f"{prefix}_col")
    b.selectbox("How", hows, key=f"{prefix}_how", format_func=lambda h: pr.HOWS[h])
    if s.get(f"{prefix}_how") != "all":
        with c:
            _picker("Text", f"{prefix}_text", _counts(s.get(f"{prefix}_col") or "IO Type", signals),
                    help="The values really in this column of the allocation are listed, with how many signals have "
                         "each. You can also type part of a value.")


def _scope_count(scope: dict[str, Any], signals: list[dict[str, Any]]) -> int:
    return sum(1 for r in signals if pr.in_scope(scope, r))


def render() -> None:
    _init()
    s = st.session_state
    signals = _signals()
    st.caption("One column with everything about it: its values for each signal and the checks they must pass. "
               "Nothing changes until the column is verified in the Review Queue and activated.")
    st.markdown("**1 · Which column?**")
    a, b, c = st.columns([2.2, 1, 1])
    a.selectbox("Column", _targets(), key="cb_target", format_func=_target_label, on_change=_on_target,
                help="A new project column, a project column that is already active (to change it), or a column of "
                     "the allocation itself (only checks: the allocation cannot be changed here).")
    with b:
        st.segmented_control("Values Are", list(TYPE_LABELS), key="cb_type", format_func=TYPE_LABELS.get,
                             help="Number columns can have at most / at least / between checks; their values must be numbers.")
    c.text_input("Unit", key="cb_unit", max_chars=pr.LIMITS["unit"], placeholder="V, mA, °C …", disabled=not _number(),
                 autocomplete="off")
    if s["cb_target"] == NEW:
        st.text_input("New Column Name", key="cb_name", max_chars=pr.LIMITS["column"], placeholder="For example: Voltage",
                      autocomplete="off")
    n, p = st.columns([5, 1.3], vertical_alignment="bottom")
    n.text_input("Purpose (optional)", key="cb_note", max_chars=pr.LIMITS["note"], autocomplete="off",
                 placeholder="Why this column and its checks exist, in your own words…")
    p.button("✨ Make It Clearer", key="cb_polish", on_click=_polish, disabled=_client() is None,
             help="The AI rewrites your purpose in clear words. It never sees your data and changes nothing else."
                  if _client() is not None else "The AI is switched off because no API key is set.")
    if _is_new():
        _values(signals)
    _checks(signals)
    _wording(signals)
    _ai(signals)


def _values(signals: list[dict[str, Any]]) -> None:
    s = st.session_state
    st.markdown("**2 · Values for each signal**", help="A typed value wins; then the LAST fill rule that covers the "
                "signal; then the value for every other signal (leave it empty for blank).")
    typed_tab, paste_tab, fill_tab = st.tabs(["✍️ Type Per Signal", "📋 Paste Or Upload", "⚡ Fill Many At Once"])
    rule_now = {"kind": "column_rule", "args": {**_draft(values=s["cb_values"]), "new": True}}
    with typed_tab:
        _table(signals, rule_now)
    with paste_tab:
        st.caption("One signal per line: the tag, then its value. Lines copied from Excel (two columns) work as they "
                   "are; “TAG, value” and “TAG; value” work too. Or upload a .xlsx / .csv with the tags in the first "
                   "column (or a column named Tag) and the values next to it.")
        st.text_area("Tags And Values", key="cb_paste", height=140, placeholder="320-FT-20645-A\t24\n320-LT-80001\t24")
        st.file_uploader("Or Upload A List", type=["xlsx", "csv"], key="cb_upload")
        st.button("Use These Values", key="cb_use_paste", on_click=_use_pasted, type="primary")
    with fill_tab:
        st.caption("For many signals at once, and for signals that arrive in a later revision. Typed values still win. "
                   "When two fill rules cover a signal, the lower one wins.")
        for i, u in enumerate(list(s["cb_fills"]), 1):
            with st.container(border=True, key=f"cb_fill_box_{u}"):
                top, bin_ = st.columns([8, 1], vertical_alignment="center")
                top.markdown(f"**Fill rule {i}**")
                bin_.button("🗑", key=f"cb_f{u}_drop", on_click=_drop, args=("cb_fills", u), help="Remove this fill rule")
                _scope_widgets(f"cb_f{u}", signals, with_all=True)
                st.text_input("These Signals Get", key=f"cb_f{u}_val", max_chars=pr.LIMITS["value"], autocomplete="off",
                              placeholder="Leave empty for blank")
                scope = _scope_of(f"cb_f{u}")
                if signals:
                    st.caption(f"Covers {_scope_count(scope, signals):,} signals right now.")
        st.button("➕ Add A Fill Rule", key="cb_add_fill", on_click=_add_fill)
        st.text_input("Every Other Signal Gets", key="cb_default", max_chars=pr.LIMITS["value"], autocomplete="off",
                      placeholder="Leave empty to keep them blank",
                      help="The value of every signal that has no typed value and no fill rule. Use it to give every "
                           "signal the same value, or leave it empty for blank.")


def _table(signals: list[dict[str, Any]], rule_now: dict[str, Any]) -> None:
    import pandas as pd
    s = st.session_state
    if not signals:
        st.info("Run an allocation first: then every signal is listed here to type its value. Fill rules and "
                "checks work without it.")
        return
    f, g = st.columns([2.6, 2.4], vertical_alignment="bottom")
    f.text_input("Find Signals", key="cb_find", on_change=_fold, autocomplete="off",
                 placeholder="Tag, IO type, instrument, service or cabinet · several with commas")
    g.segmented_control("Show", list(SHOW), key="cb_show", on_change=_fold,
                        help="Filled = has a value · Blank = no value · Typed = typed by hand")
    typed = _typed()
    by_key = {pr.tag_key(r.get("Tag Name")): r for r in signals}
    view = s.get("cb_view")
    if not view or view[0] != s["cb_ver"]:                      # which rows the table shows, fixed until the next fold
        words = [w.strip().casefold() for w in str(s.get("cb_find") or "").split(",") if w.strip()]
        show = s.get("cb_show") or "All"
        keys = []
        for key, r in by_key.items():
            if words and not any(w in " ".join(_text(r.get(c)) for _, c in SHOWN_COLUMNS).casefold() for w in words):
                continue
            value = typed[key] if key in typed else pr.column_value(rule_now, r)[0]
            if (show == "Filled" and not value) or (show == "Blank" and value) or (show == "Typed" and key not in typed):
                continue
            keys.append(key)
        s["cb_view"] = view = (s["cb_ver"], keys)
    keys = [k for k in view[1] if k in by_key]
    rule_typed = {"kind": "column_rule", "args": {**rule_now["args"], "values": typed}}
    lines, sources = [], Counter()
    for key in keys:
        r = by_key[key]
        value, source = pr.column_value(rule_typed, r)
        short = "typed" if source.startswith("typed") else (source.split(":")[0] if source.startswith("fill") else
                                                           ("every other" if value else ""))
        line = {name: _text(r.get(col)) for name, col in SHOWN_COLUMNS}
        line["Value"] = (pr.to_number(value) if value else None) if _number() else value
        line["From"] = short
        lines.append(line)
    for key, r in by_key.items():
        value, source = pr.column_value(rule_typed, r)
        sources["typed" if source.startswith("typed") else ("fill" if source.startswith("fill") else
                                                            ("default" if value else "blank"))] += 1
    st.caption(f"{len(by_key):,} signals · {sources['typed']:,} typed by hand · {sources['fill']:,} from fill rules · "
               f"{sources['default']:,} from “every other signal” · {sources['blank']:,} blank"
               + (f" · showing {len(keys):,}" if len(keys) != len(by_key) else ""))
    if not keys:
        st.info(EMPTY_VIEW.get(s.get("cb_show") or "All", EMPTY_VIEW["All"]) if not str(s.get("cb_find") or "").strip()
                else "No signal matches this search with this Show filter. Clear the search or pick Show: All.")
    frame = pd.DataFrame(lines, columns=["Tag", "Value", "From"] + [n for n, _ in SHOWN_COLUMNS[1:]])
    title = (_column_name() or "Value") + (f" ({s['cb_unit']})" if s.get("cb_unit") else "")    # the column's own name
    if _number():
        frame["Value"] = pd.to_numeric(frame["Value"], errors="coerce")
        value_col = st.column_config.NumberColumn(title, format="%g", help=f"Type each signal's {title} here.")
    else:
        value_col = st.column_config.TextColumn(title, max_chars=pr.LIMITS["value"], help=f"Type each signal's {title} here.")
    st.data_editor(frame, key=_editor_key(), hide_index=True, width="stretch", height=min(430, 38 + 35 * max(len(lines), 1)),
                   num_rows="fixed", disabled=[n for n, _ in SHOWN_COLUMNS] + ["From"],
                   column_config={"Value": value_col, "From": st.column_config.TextColumn("From", width="small",
                                                                                          help="typed = typed by hand; fill N = fill rule N; every other = the value for every other signal")})
    a, b, c = st.columns([2, 1.6, 1.6], vertical_alignment="bottom")
    a.text_input("Value For All Shown Signals", key="cb_set_value", max_chars=pr.LIMITS["value"], autocomplete="off",
                 placeholder="Find signals above, then give them one value")
    b.button(f"Give The {len(keys):,} Shown This Value", key="cb_set_shown", on_click=_set_shown, args=(False,),
             disabled=not keys)
    c.button("Take Away Their Typed Values", key="cb_clear_shown", on_click=_set_shown, args=(True,),
             disabled=not keys or not any(k in typed for k in keys))


def _check_values(p: str, kind: str, signals: list[dict[str, Any]], rule_now: dict[str, Any]) -> None:
    s = st.session_state
    needs = pr.CHECKS[kind][1]
    unit = f" ({s['cb_unit']})" if _number() and s.get("cb_unit") else ""
    if needs == "one":
        st.text_input("Number Of Characters" if kind == "max_length" else f"Value{unit}", key=f"{p}_v", autocomplete="off",
                      max_chars=pr.LIMITS["value"])
    elif needs == "two":
        x, y = st.columns(2)
        x.text_input(f"From{unit}", key=f"{p}_v", autocomplete="off", max_chars=pr.LIMITS["value"])
        y.text_input(f"To{unit}", key=f"{p}_v2", autocomplete="off", max_chars=pr.LIMITS["value"])
    elif needs == "list":
        if _is_new():
            options = Counter(v for v in (pr.column_value(rule_now, r)[0] for r in signals) if v)
        else:
            options = _counts(_column_name(), signals)
        chosen = [x for x in s.get(f"{p}_list") or []]
        choices = list(dict.fromkeys(chosen + [v for v, _ in options.most_common(MAX_PICKS)]))
        st.multiselect("Allowed Values", choices, key=f"{p}_list", accept_new_options=True,
                       placeholder="Pick or type the allowed values…")
    else:
        st.caption(" ")


def _checks(signals: list[dict[str, Any]]) -> None:
    s = st.session_state
    st.markdown("**3 · Checks**", help="Each check is run on every signal it covers after each allocation. A broken "
                "check marked Error blocks the result until it is fixed; one marked Warning must be signed off on the "
                "TQ Board. Checks never move a signal.")
    kinds = [k for k, (_, _, suits) in pr.CHECKS.items() if (s.get("cb_type") or "text") in suits]
    rule_now = {"kind": "column_rule", "args": {**_draft(), "new": _is_new()}}
    if not s["cb_checks"]:
        st.caption("No checks yet. Add one, for example “At most 24 V” or “Must not be blank”.")
    for i, u in enumerate(list(s["cb_checks"]), 1):
        p = f"cb_c{u}"
        if s.get(f"{p}_kind") not in kinds:
            s[f"{p}_kind"] = kinds[0]
        if s.get(f"{p}_sev") not in SEV_LABELS:
            s[f"{p}_sev"] = "warning"
        if s.get(f"{p}_scope") not in SCOPE_LABELS:
            s[f"{p}_scope"] = "all"
        with st.container(border=True, key=f"cb_check_box_{u}"):
            head, bin_ = st.columns([8, 1], vertical_alignment="center")
            head.markdown(f"**Check {i}**")
            bin_.button("🗑", key=f"{p}_drop", on_click=_drop, args=("cb_checks", u), help="Remove this check")
            a, b, c = st.columns([1.3, 1.6, 1.3])
            a.selectbox("Rule", kinds, key=f"{p}_kind", format_func=lambda k: pr.CHECKS[k][0])
            with b:
                _check_values(p, s[f"{p}_kind"], signals, rule_now)
            c.selectbox("If Broken", list(SEV_LABELS), key=f"{p}_sev", format_func=SEV_LABELS.get)
            st.segmented_control("Applies To", list(SCOPE_LABELS), key=f"{p}_scope", format_func=SCOPE_LABELS.get)
            if s.get(f"{p}_scope") == "some":
                _scope_widgets(p, signals, with_all=False)
            _live(i, rule_now, signals)
    st.button("➕ Add A Check", key="cb_add_check", on_click=_add_check)


def _live(i: int, rule_now: dict[str, Any], signals: list[dict[str, Any]]) -> None:
    """How many signals of the current allocation this check covers and breaks, as you type."""
    one = {**rule_now["args"], "checks": [rule_now["args"]["checks"][i - 1]]}
    args, errors = pr.normalize_column_rule({**one, "values": one.get("values") or {}} if one.get("new") else one)
    own = [e for e in errors if e.startswith("Check 1")]
    if own:
        st.caption("⚠ " + " ".join(e.replace("Check 1", "This check", 1) for e in own))
        return
    if not signals or not args.get("checks"):
        return
    rule = {"kind": "column_rule", "args": args}
    chk = args["checks"][0]
    dupes = pr.duplicates(rule, chk, signals) if chk["check"] == "unique" else None
    covered = [r for r in signals if pr.in_scope(chk.get("scope"), r)]
    results = [pr.judge_check(rule, chk, r, dupes) for r in covered]
    broken = [r for r, o in zip(covered, results) if o.ok is False]
    skipped = sum(1 for o in results if o.ok is None)
    text = f"Right now: covers {len(covered):,} signals"
    if broken:
        tags = ", ".join(_text(r.get("Tag Name")) for r in broken[:4]) + (" …" if len(broken) > 4 else "")
        st.markdown(f"<small style='color:#ff7b72'>✗ {md_escape(text)} · {len(broken):,} break it: {md_escape(tags)}</small>",
                    unsafe_allow_html=True)
    else:
        st.markdown(f"<small style='color:#3fb950'>✓ {md_escape(text)} · none break it</small>", unsafe_allow_html=True)
    if skipped:
        st.caption(f"{skipped:,} of them are blank, so this check skips them (add “Must not be blank” to require a value).")


def _wording(signals: list[dict[str, Any]]) -> None:
    s = st.session_state
    args, errors = pr.normalize_column_rule(_draft())
    active = _rule_args_for(s["cb_target"])
    editing = s["cb_target"] != NEW and bool(active.get("checks") or active.get("fills") or active.get("values"))
    with st.container(border=True, key="cb_wording_box"):
        if errors:
            st.markdown("📝 **Not ready yet:**  \n" + "  \n".join(f"• {md_escape(e)}" for e in errors))
        else:
            st.markdown(f"📝 **Wording:** {md_escape(pr.column_statement(args))}",
                        help="Written by the tool from the form, never typed free-hand. This is what reviewers verify.")
            if args.get("note"):
                st.caption(f"Purpose: {args['note']}")
        if editing:
            st.caption("Once verified and activated, this replaces the active version of the column.")
        with st.container(horizontal=True, gap="small"):
            st.button("Propose This Change" if editing else "Propose This Column", key="cb_propose", type="primary",
                      on_click=_propose, disabled=bool(errors))
            st.button("Start Again", key="cb_clear", on_click=_clear, help="Empty the form.")


def _ai(signals: list[dict[str, Any]]) -> None:
    configured = _client() is not None
    with st.expander("✨ Describe It In Words And Let The AI Fill The Form", expanded=False):
        st.caption("For example: “Add a Voltage column in V. AI signals are 24 V, DO signals 230 V. No signal may be "
                   "above 250 V, and AI signals must have a value.” The AI only fills in the form above for you to "
                   "check: it never sees your data, never proposes anything and cannot change the allocation.")
        if not configured:
            st.caption("The AI is switched off because no API key is set. The form works without it.")
        st.text_area("Describe The Column And Its Checks", key="cb_ai_request", max_chars=500, disabled=not configured,
                     height=100)
        st.button("Fill The Form With AI", key="cb_ai_fill", on_click=_ai_fill, disabled=not configured)
