"""Notes (Rules › Propose Rules › Columns And Checks): columns of your file that could be compared with a limit.

When the uploaded file has columns with measurements or limits in them (a temperature, a voltage, a current, a
range, an alarm limit ...), a note asks for the value to compare them against (a "par value").  For each note you
can give the limit, say which signals it is for (every signal with a value, only some, or signals you pick one by
one), say whether a blank value is a problem, or leave the column without a limit.

The tool reads the columns itself (core.columnnotes); when an AI key is set, the AI also reads them in the
background - it is shown only the column names and a few example values - and its notes are added when it is
done.  A note is NEVER an error or a warning: nothing is checked until you propose a limit and it is verified in
the Review Queue like every other rule.
"""
from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import streamlit as st

from io_sudoku.core import autofix, columnnotes as cn, projectrules as pr, rulechange as rc
from io_sudoku.ui import autofill, state
from io_sudoku.ui.views._common import md_escape

QUEUE = "Review Queue"
BOX_WHERE = "colnotes"                           # messages about a note are shown inside the notes box
CHECKS = {"max": "At most", "min": "At least", "between": "Between", "equals": "Must equal"}
WHO = {"all": "Every signal with a value", "some": "Only some signals", "tags": "Signals I pick"}
BLANK = {"skip": "Skip signals with no value", "problem": "No value is a problem too"}
SEV = {"warning": "Warning · sign off", "error": "Error · blocks the result"}
STATUS = {"open": "○ Open", "proposed": "✓ Limit proposed", "blank": "– Left blank"}

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="iosg-colnotes")
_JOBS: dict[str, Future] = {}                    # the AI readings, shared by every session (same columns = same answer)
_LOCK = threading.Lock()


# ------------------------------------------------------------------------------------------- reading
@st.cache_data(max_entries=6, show_spinner=False)
def _unused(mdb_bytes: bytes, overrides_text: str) -> list[tuple[str, int, dict[str, str]]]:
    return autofix.unused_columns(mdb_bytes, json.loads(overrides_text or "{}"))


def _client():
    from io_sudoku.ui.views import rules
    return rules._client()


def _job_key(columns: list[tuple[str, list[str]]]) -> str:
    return hashlib.sha256(json.dumps(columns, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _ai_job(columns: list[tuple[str, list[str]]], client) -> tuple[str, Future]:
    """Start the AI reading in the background (once per set of columns); the page never waits for it."""
    from io_sudoku.core import advisor
    key = _job_key(columns)
    with _LOCK:
        job = _JOBS.get(key)
        if job is None:
            if len(_JOBS) > 32:
                for k in [k for k, j in _JOBS.items() if j.done()][:16]:
                    _JOBS.pop(k, None)
            job = _POOL.submit(advisor.read_columns, columns, client)
            _JOBS[key] = job
    return key, job


def _ai_result(job: Future | None) -> tuple[list[dict[str, str]], str]:
    if job is None or not job.done():
        return [], ""
    try:
        return job.result()
    except Exception:  # noqa: BLE001
        return [], "The AI is unavailable right now, so only the tool's own reading is shown."


def _retry(key: str) -> None:
    with _LOCK:
        _JOBS.pop(key, None)


def _wait(key: str) -> None:
    """Shown while the AI reads (a fragment that looks again every 1.5 s, then redraws the page once)."""
    job = _JOBS.get(key)
    if job is None or job.done():
        st.rerun()
    st.caption("✨ The AI is reading your file's columns in the background. Its notes are added here when it is done; "
               "you can keep working.")


# ------------------------------------------------------------------------------------------- state
def _status_key(note: cn.Note) -> str:
    return f"{state.upload_sha()[:12]}:{note.key}"


def _status(note: cn.Note) -> str:
    return (st.session_state.get("col_notes") or {}).get(_status_key(note), "open")


def _set_status(note: cn.Note, status: str) -> None:
    s = st.session_state
    s["col_notes"] = {**(s.get("col_notes") or {}), _status_key(note): status}


def _prefix(note: cn.Note) -> str:
    return "cn_" + hashlib.sha256(note.key.encode("utf-8")).hexdigest()[:8]


def _signals() -> list[dict[str, Any]]:
    result = st.session_state.get("result")
    return [r for r in (getattr(result, "rows", None) or []) if pr.is_signal(r)]


def _tag_names(note: cn.Note) -> dict[str, str]:
    """{tag key: the tag as written} of the signals with a number in this column (the allocation's own spelling)."""
    names = {pr.tag_key(r.get("Tag Name")): str(r.get("Tag Name")) for r in _signals()}
    return {k: names.get(k, k) for k in note.numbers}


def _scope(note: cn.Note) -> dict[str, Any]:
    s = st.session_state
    p = _prefix(note)
    who = s.get(f"{p}_who") or "all"
    if who == "tags":
        return {"how": pr.TAGS, "tags": list(s.get(f"{p}_tags") or [])}
    if who == "some":
        return {"column": s.get(f"{p}_col") or "IO Type", "how": s.get(f"{p}_how") or "contains",
                "text": str(s.get(f"{p}_text") or "").strip()}
    return {"how": "all"}


def _taken() -> list[str]:
    s = st.session_state
    names = [str((r.get("args") or {}).get("column")) for r in (s["pack"].overrides or {}).get("project_rules", [])]
    names += [str((p.args or {}).get("column")) for p in s["proposals"] if p.template == "column_rule" and p.status == "pending"]
    return names


def _args(note: cn.Note) -> dict[str, Any]:
    s = st.session_state
    p = _prefix(note)
    return cn.rule_args(note, cn.column_name(note, _taken()), s.get(f"{p}_check") or "max", str(s.get(f"{p}_v") or "").strip(),
                        str(s.get(f"{p}_v2") or "").strip(), _scope(note), s.get(f"{p}_sev") or "warning",
                        s.get(f"{p}_blank") == "problem", str(s.get(f"{p}_unit") or "").strip())


# ------------------------------------------------------------------------------------------- callbacks
def _propose(note: cn.Note) -> None:
    s = st.session_state
    proposal, errors = rc.build_proposal("column_rule", _args(note), s.get("rule_author") or "", now=columns_now())
    if proposal is None:
        hint = "" if str(s.get("rule_author") or "").strip() else " (Your Name is at the top of Propose Rules.)"
        state.flash("error", " ".join(errors) + hint, BOX_WHERE)
        return
    s["proposals"] = s["proposals"] + [proposal]
    _set_status(note, "proposed")
    s["scroll_to"] = QUEUE
    state.flash("success", f"Proposed: {proposal.statement} It waits in the Review Queue: press Verify there, then "
                           "Preview And Activate.", QUEUE)


def _to_form(note: cn.Note) -> None:
    from io_sudoku.ui.views import columns
    columns._load(_args(note), columns.NEW)
    state.flash("info", f"“{note.column}” is open in the Columns And Checks form below with its {len(note.numbers):,} "
                        "numbers and your limit. Change anything, then press Propose This Column.", BOX_WHERE)


def _leave_blank(note: cn.Note, blank: bool) -> None:
    _set_status(note, "blank" if blank else "open")
    state.flash("info", f"“{note.column}” is left without a limit. Nothing is checked for it." if blank else
                f"“{note.column}” is open again.", BOX_WHERE)


def columns_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------- view
def notes() -> tuple[list[cn.Note], str, str | None, bool]:
    """(notes, what read them, the AI job key, the AI is still reading)."""
    s = st.session_state
    if not s.get("mdb_bytes"):
        return [], "", None, False
    unused = _unused(s["mdb_bytes"], json.dumps(s["column_overrides"], sort_keys=True))
    found = cn.find(unused)
    client = _client()
    columns = cn.ai_columns(unused)
    if client is None or not columns:
        return found, "Read by the tool (the AI is switched off: no API key is set)." if client is None else \
            "Read by the tool.", None, False
    key, job = _ai_job(columns, client)
    if not job.done():
        return found, "Read by the tool; the AI is still reading.", key, True
    ai, why = _ai_result(job)
    merged = cn.merge(found, ai, unused)
    return merged, why or "Read by the tool and the AI (the AI saw only the column names and a few example values).", key, False


def render() -> None:
    s = st.session_state
    if not s.get("mdb_bytes"):
        return
    found, reader, key, pending = notes()
    if not found and not pending:
        return
    open_n = sum(1 for n in found if _status(n) == "open")
    with st.container(border=True, key="colnotes_box"):
        st.markdown(f"📝 **Notes · columns that could be compared with a limit** ({open_n:,} open of {len(found):,})",
                    help="Columns of your file that hold a measurement or a limit (a temperature, a voltage, a "
                         "current, a range ...). For each one you can give a value to compare against, choose the "
                         "signals it is for, or leave it blank. These are notes, never errors or warnings: nothing "
                         "is checked until you propose a limit and it is verified in the Review Queue.")
        state.show_flash(BOX_WHERE)
        caption = reader
        if pending and key:
            st.fragment(run_every=1.5)(_wait)(key)
        elif key and ("unavailable" in reader or "could not be read" in reader):
            a, b = st.columns([4, 1.2], vertical_alignment="center")
            a.caption(reader)
            b.button("Ask The AI Again", key="cn_retry", on_click=_retry, args=(key,))
            caption = ""
        if caption:
            st.caption(caption)
        if not found:
            return
        st.dataframe([{"Column In Your File": n.column, "Holds": n.quantity, "In Your File": n.span() or "-",
                       "Signals With A Number": len(n.numbers), "Read By": n.source.replace("ai", "AI"),
                       "Status": STATUS[_status(n)]} for n in found],
                     hide_index=True, width="stretch", height=min(250, 38 + 35 * len(found)))
        order = sorted(found, key=lambda n: (_status(n) != "open", n.column.casefold()))
        by_key = {n.key: n for n in order}
        if s.get("cn_pick") not in by_key:
            s["cn_pick"] = order[0].key
        st.selectbox("Give A Limit For", list(by_key), key="cn_pick",
                     format_func=lambda k: f"{STATUS[_status(by_key[k])].split()[0]}  {by_key[k].column} · {by_key[k].quantity}")
        _note_form(by_key[s["cn_pick"]])


def _note_form(note: cn.Note) -> None:
    s = st.session_state
    p = _prefix(note)
    status = _status(note)
    st.markdown(f"**{md_escape(note.question)}**")
    if note.examples:
        st.caption("For example: " + ", ".join(md_escape(e) for e in note.examples)
                   + f" · {note.filled:,} signals have something written in this column, {len(note.numbers):,} of them a number.")
    if status == "blank":
        st.caption("You left this column without a limit. Nothing is checked for it.")
        st.button("Give It A Limit After All", key=f"{p}_back", on_click=_leave_blank, args=(note, False))
        return
    if status == "proposed":
        st.caption("✓ A limit for this column is waiting in the Review Queue. You can propose another one below.")
    defaults = {f"{p}_check": "max", f"{p}_v": "", f"{p}_v2": "", f"{p}_unit": note.unit, f"{p}_who": "all",
                f"{p}_tags": [], f"{p}_blank": "skip", f"{p}_sev": "warning", f"{p}_how": "contains", f"{p}_col": "IO Type"}
    for k, v in defaults.items():
        if k not in s:
            s[k] = list(v) if isinstance(v, list) else v
    a, b, c, d = st.columns([1.2, 1.1, 1.1, .8])
    a.selectbox("Compare", list(CHECKS), key=f"{p}_check", format_func=CHECKS.get)
    between = s.get(f"{p}_check") == "between"
    b.text_input("From" if between else "Value", key=f"{p}_v", autocomplete="off", max_chars=pr.LIMITS["value"],
                 placeholder="A number")
    if between:
        c.text_input("To", key=f"{p}_v2", autocomplete="off", max_chars=pr.LIMITS["value"], placeholder="A number")
    else:
        c.selectbox("If Broken", list(SEV), key=f"{p}_sev", format_func=SEV.get)
    autofill.offer(f"{p}_unit", autofill.UNITS)
    d.text_input("Unit", key=f"{p}_unit", autocomplete="off", max_chars=pr.LIMITS["unit"], placeholder="V, °C …")
    if between:
        st.selectbox("If Broken", list(SEV), key=f"{p}_sev", format_func=SEV.get)
    st.segmented_control("For Which Signals", list(WHO), key=f"{p}_who", format_func=WHO.get)
    if s.get(f"{p}_who") not in WHO:
        s[f"{p}_who"] = "all"
    if s[f"{p}_who"] == "some":
        from io_sudoku.ui.views import columns
        columns._scope_widgets(p, _signals(), with_all=False)
    elif s[f"{p}_who"] == "tags":
        names = _tag_names(note)
        st.multiselect("Pick The Signals", list(names), key=f"{p}_tags", format_func=lambda k: names.get(k, k),
                       placeholder="Type a few letters of a tag…",
                       help="Only these signals are compared with the limit. Every signal with a number in this "
                            "column is listed.")
    st.segmented_control("Signals With No Value", list(BLANK), key=f"{p}_blank", format_func=BLANK.get)
    if s.get(f"{p}_blank") not in BLANK:
        s[f"{p}_blank"] = "skip"
    args, errors = pr.normalize_column_rule(_args(note))
    if errors:
        st.caption("Not ready yet: " + " ".join(md_escape(e) for e in errors))
    else:
        st.caption("📝 " + md_escape(pr.column_statement(args)))
        _preview(args)
    if not str(s.get("rule_author") or "").strip():
        st.caption("⚠ Write your name in Your Name at the top of Propose Rules first: every proposal needs an author.")
    with st.container(horizontal=True, gap="small"):
        st.button("Propose This Limit", key=f"{p}_propose", type="primary", on_click=_propose, args=(note,),
                  disabled=bool(errors), help="Sends it to the Review Queue. Nothing is checked before it is verified "
                                              "and activated.")
        st.button("Open In The Columns Form", key=f"{p}_form", on_click=_to_form, args=(note,),
                  help="Fills the Columns And Checks form below with this column, its numbers and your limit, to "
                       "change anything before proposing.")
        st.button("Leave It Blank (No Limit)", key=f"{p}_blank_btn", on_click=_leave_blank, args=(note, True),
                  help="This column needs no limit: the note is closed and nothing is checked.")


def _preview(args: dict[str, Any]) -> None:
    """How many signals of the current allocation the limit covers and breaks, as you type."""
    signals = _signals()
    if not signals or not args.get("checks"):
        return
    rule = {"kind": "column_rule", "args": args}
    chk = args["checks"][0]
    covered = [r for r in signals if pr.in_scope(chk.get("scope"), r)]
    results = [pr.judge_check(rule, chk, r, None) for r in covered]
    broken = [r for r, o in zip(covered, results) if o.ok is False]
    if broken:
        tags = ", ".join(str(r.get("Tag Name")) for r in broken[:4]) + (" …" if len(broken) > 4 else "")
        st.markdown(f"<small style='color:#e3b341'>Right now {len(broken):,} of the {len(covered):,} signals it covers "
                    f"would break it: {md_escape(tags)}</small>", unsafe_allow_html=True)
    else:
        st.markdown(f"<small style='color:#3fb950'>Right now none of the {len(covered):,} signals it covers would break "
                    "it.</small>", unsafe_allow_html=True)
