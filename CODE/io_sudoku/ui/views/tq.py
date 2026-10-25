"""TQ board: sign off warnings, filter and page the questions, answer them, pin cables, copy e-mail text."""
from __future__ import annotations

import json
import time

import streamlit as st

from io_sudoku.core import helpcontext, readiness as readiness_mod, reviewlog
from io_sudoku.core.config import Config
from io_sudoku.core.constants import IO_TYPES
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.models import Signal
from io_sudoku.core.overrides import ANSWERS_PREFIX, OVERRIDABLE_FIELDS, Override, suggest_resolution, validate_override
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.topology_infer import infer_cabinets
from io_sudoku.core.tq import TQLog
from io_sudoku.core.tqlife import group_by_owner, tqs_as_email_text
from io_sudoku.core.validate import validate
from io_sudoku.ui import autofill, editing, state, theme, ui_logic
from io_sudoku.ui.views import assistant, reviewed
from io_sudoku.ui.nav import link
from io_sudoku.ui.views._common import (allocate_button, ask_first, heading, md_escape, pager, result_or_empty,
                                        tq_table)


@st.cache_data(max_entries=4, show_spinner=False)
def _signals(mdb_bytes: bytes, pack_text: str, column_text: str) -> tuple[dict[str, Signal], list[Signal]]:
    """(every signal by tag key, accepted signals) - the context the suggestions need."""
    from io_sudoku.core.config import copy_config
    from io_sudoku.core.rulepack import pack_from_dict
    cfg = copy_config(ui_logic.config_for_pack(pack_from_dict(json.loads(pack_text))))
    log = TQLog()
    ing = read_mdb(mdb_bytes, log, json.loads(column_text), cfg.rules.io_aliases)
    infer_cabinets(ing, cfg, log)
    val = validate(ing, cfg, log)
    everyone = list(val.accepted) + [q.signal for q in val.quarantined] + list(ing.alarms)
    return {match_key(sg.tag) or sg.tag: sg for sg in everyone}, list(val.accepted)


def render() -> None:
    s = st.session_state
    st.header("TQ Board")
    result = result_or_empty("the open questions", "tq")
    if result is None:
        return
    tqs = result.tqs
    counts = {sev: sum(1 for t in tqs if t.severity == sev) for sev in ("error", "warning", "info")}
    st.markdown(theme.severity_cards_html(counts), unsafe_allow_html=True)
    if not s.get("stale"):                       # when out of date, the banner above already has the button
        allocate_button("reallocate_tq")
    back = reviewlog.returning(s["review_log"], result, s["signoffs"])
    if back and s.get(state.TQ_TAB_KEY) != state.REVIEWED_TAB:
        st.warning(f"↺ {len(back):,} item(s) you reviewed before have a problem again. Open the "
                   f"{link('Reviewed Before', 'TQ Board', 'Problems Again On Items You Reviewed Before')} tab to see "
                   "what was decided about them last time.")
    if s.get(state.TQ_TAB_KEY) not in state.TQ_TABS:
        s[state.TQ_TAB_KEY] = state.TQ_TABS[0]
    questions_tab, reviewed_tab = st.tabs(list(state.TQ_TABS), key=state.TQ_TAB_KEY, on_change="rerun")
    with questions_tab:
        _signoff(result)
        if not tqs:
            st.success("No questions were raised. Nothing needs an answer.")
        else:
            _all_questions(tqs, counts)
            _email_text(tqs)
            _answers(result)
        _pins(result)
    with reviewed_tab:
        reviewed.render(result, back)


# ------------------------------------------------------------------ sign-off box
ROWS_PER_PAGE = 25
SHOW = ("All", "Errors", "Waiting", "Signed Off", "Problem")
SHOW_KEY = "signoff_show"


def _box(count: int):
    """A scroll box for long lists, so the page itself does not have to be scrolled."""
    return st.container(height=460, key="signoff_box") if count > 5 else st.container(key="signoff_box")


def _items(result) -> list[tuple]:
    """(severity, id, ref, text, extra) for every error (extra = which of several equal ones) and every
    distinct warning (extra = its sign-off key).  Errors first."""
    seen: dict[tuple[str, str], int] = {}
    items: list[tuple] = []
    for t in result.tqs:
        if t.severity == "error":
            n = seen.get((t.tq_id, t.ref), 0)
            seen[(t.tq_id, t.ref)] = n + 1
            items.append(("error", t.tq_id, t.ref, t.message, n))
    return items + [("warning", kind, ref, text, key) for key, kind, ref, text in ui_logic.warning_rows(result)]


def _shown(item: tuple, show: str, signoffs: dict[str, str]) -> bool:
    severity, *_, extra = item
    decision = signoffs.get(extra) if severity == "warning" else None
    return {"All": True, "Errors": severity == "error",
            "Waiting": severity == "warning" and decision not in (readiness_mod.APPROVED, readiness_mod.PROBLEM),
            "Signed Off": decision == readiness_mod.APPROVED, "Problem": decision == readiness_mod.PROBLEM}.get(show, True)


def _signoff(result) -> None:
    """ONE scroll box with every error and warning.  Errors (listed first) must be fixed: Edit opens the exact
    cell.  Warnings need Approve (or Problem) before the allocation can be ISSUE-READY, and can be edited too."""
    s = st.session_state
    heading("Sign Off The Warnings",
            "Errors are listed first and must be fixed: press Edit to open the exact cell (or the cable, cabinet or "
            "page the question is about), then re-allocate. Every warning needs Approve before the allocation can "
            "be ISSUE-READY; Problem keeps it in DRAFT. The ▸ arrow next to a row shows the suggested fix, "
            "where you can write your own suggestion for the next person.")
    items = _items(result)
    if not items:
        st.caption("There are no errors or warnings.")
        return
    errors = sum(1 for i in items if i[0] == "error")
    signed = readiness_mod.signoff_counts(result, s["signoffs"])
    st.caption(f"{errors:,} errors to fix · {signed[readiness_mod.APPROVED]:,} of {signed['total']:,} warnings approved "
               f"· {signed[readiness_mod.PROBLEM]:,} marked as a problem · {signed['waiting']:,} waiting")
    if s.get(SHOW_KEY) not in SHOW:
        s[SHOW_KEY] = "All"
    numbers = {o: sum(1 for i in items if _shown(i, o, s["signoffs"])) for o in SHOW}
    left, right = st.columns([3, 2], vertical_alignment="center")
    with left:
        st.segmented_control("Show", SHOW, key=SHOW_KEY, format_func=lambda o: f"{o} · {numbers[o]:,}",
                             label_visibility="collapsed", on_change=state.reset_page, args=("err_page",))
    show = s.get(SHOW_KEY) or "All"
    picked = [i for i in items if _shown(i, show, s["signoffs"])]
    page_items, page, pages = ui_logic.page_slice(picked, s.get("err_page", 0), ROWS_PER_PAGE)
    s["err_page"] = page
    with right:
        pager("err_page", pages)
    if not picked:
        st.info(f"Nothing is {show.lower()} right now.")
    with _box(len(page_items)):
        for i, (severity, kind, ref, text, extra) in enumerate(page_items):
            _row(result, page, i, severity, kind, ref, text, extra)
    if signed["waiting"]:
        c1, c2 = st.columns([3, 2], vertical_alignment="center")
        sure = c1.checkbox("I have checked every warning above", key="approve_all_ok")
        c2.button("Approve All Warnings", key="approve_all", disabled=not sure, on_click=state.approve_all_warnings)


FIX_LABELS = {"edit": "✎ Edit", "cabinet": "↗ Cabinet", "place": "↗ Open"}


def _row(result, page: int, i: int, severity: str, kind: str, ref: str, text: str, extra) -> None:
    s = st.session_state
    tq_key = f"{kind}|{ref}"
    left, mid, right, more = st.columns([5, 2.2, 1.1, .45], vertical_alignment="center")
    mark = "●" if severity == "error" else "▲"
    past = [e for e in s["review_log"] if e.item == reviewlog.item_key(ref)]
    seen = f" · <span style=\"color:#58a6ff\">↺ reviewed {reviewlog.counts(past)['reviewed']}× before</span>" \
        if reviewlog.counts(past)["reviewed"] else ""
    left.markdown(f"{mark} **{md_escape(kind)}** · {md_escape(ref) or '-'}{seen}  \n"
                  f"<small>{md_escape(ui_logic.short_text(text))}</small>", unsafe_allow_html=True,
                  help=_details(result, kind, ref, text) + ("\n\n" + reviewlog.summary_text(past) if past else ""))
    nth = extra if severity == "error" else 0
    plan = state.fix_plan(kind, ref, nth)
    tip = plan.why or ("Open the cell this question is about on the Edit File page." if plan.target is None or
                       plan.target.row is not None else "Open every row of this cable on the Edit File page.")
    if severity == "error":
        mid.markdown('<span style="color:#ff7b72;font-weight:700">Error: fix it</span>', unsafe_allow_html=True)
        key = f"edit_err_{page}_{i}"
    else:
        widget = state.signoff_widget_key(extra)
        s[widget] = state.SIGNOFF_LABELS.get(s["signoffs"].get(extra))     # the sign-offs are the one source of truth
        mid.segmented_control(f"Sign-off for {kind} {ref}", list(state.SIGNOFF_LABELS.values()), key=widget,
                              on_change=state.on_signoff, args=(extra,), label_visibility="collapsed")
        key = f"edit_warn_{widget}"
    right.button(FIX_LABELS.get(plan.kind, "✎ Edit"), key=key, on_click=state.edit_for_tq, args=(kind, ref, nth),
                 disabled=plan.kind == "none", help=tip)
    is_open = s.get("fix_open") == tq_key
    more.button("▾" if is_open else "▸", key=f"fixmore_{page}_{i}", on_click=_toggle_fix, args=(tq_key,),
                help="Suggested fix: add your own suggestion, or talk it through with the assistant.")
    if is_open:
        _fix_panel(result, kind, ref, tq_key, text)


def _toggle_fix(tq_key: str) -> None:
    s = st.session_state
    s["fix_open"] = None if s.get("fix_open") == tq_key else tq_key


def _details(result, kind: str, ref: str, text: str) -> str:
    """What the (i) next to a question shows on hover: the whole text, the suggested fix and the owner."""
    note = st.session_state["tq_notes"].get(f"{kind}|{ref}")
    return "\n\n".join(f"**{label}:** {md_escape(value)}"
                       for label, value in ui_logic.question_details(result, kind, ref, text, note))


# ------------------------------------------------------------------ the suggested fix and your own suggestion
def _fix_panel(result, kind: str, ref: str, tq_key: str, text: str = "") -> None:
    """Under a row: the tool's suggested fix, then two options - write your own suggestion (kept with the
    project for the next person), or talk it through with the Helpdesk in the panel on the right."""
    s = st.session_state
    h = ui_logic.sha256_hex(tq_key)[:10]
    with st.container(border=True, key=f"fixpanel_{h}"):
        state.show_flash(f"fix_{h}")
        fix = ui_logic.suggested_fix(result, kind, ref)
        st.markdown(f"**Suggested fix:** {md_escape(fix) if fix else 'none was given for this check.'}")
        for sg in [x for x in s["suggestions"] if x.tq_key == tq_key]:
            if sg.status == "approved":
                st.success(f"Verified suggestion by {md_escape(sg.author)}: {md_escape(sg.text)}")
            elif sg.status == "pending":
                st.caption(f"Waiting for verification on the {link('Rules', 'Rules', 'Review Queue')} page: "
                           f"“{md_escape(sg.text)}” by {md_escape(sg.author)}.")
        own, chat = st.tabs(["\U0001F4DD Write Your Own Suggestion", "\U0001F4AC Talk It Through With The Helpdesk"])
        note = s["tq_notes"].get(tq_key) or {}
        with own:
            st.text_area("Your Suggestion", value=note.get("text", ""), key=f"note_text_{h}", max_chars=1000,
                         placeholder="What should be done? The next person who opens this question will see it.",
                         help="Saved with the project (it is in the workspace download), so whoever opens this "
                              "question next sees it. A note changes nothing in the allocation.")
            autofill.offer("note_by", autofill.names())
            st.text_input("Your Name", key="note_by", autocomplete="off", placeholder="Who wrote this?…")
            with st.container(horizontal=True, gap="small"):
                st.button("Save Note", key=f"note_save_{h}", on_click=_save_note, args=(tq_key, h))
                st.button("Send For Verification", key=f"note_send_{h}", on_click=_send_note, args=(kind, ref, h),
                          help="Turns this note into a suggestion that is verified with one button on the Rules page. "
                               "A verified suggestion is guidance: the fix is still made with Edit or an answer.")
            if note.get("text"):
                st.caption(f"Saved note by {md_escape(note.get('by') or 'unnamed')} at {note.get('time', '')}.")
        with chat:
            st.caption("Opens the Helpdesk on the right, already told everything about this question: its full text, "
                       "the suggested fix, where the signal is, why it is there and the other questions about it. "
                       "Ask why it was raised, how to fix it, or get your suggestion worded better. Advice only: it "
                       "cannot change any file, rule or code.")
            assistant.ask_button(f"chat_open_{h}", _tq_topic, (kind, ref, fix, h, text))


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _save_note(tq_key: str, h: str) -> None:
    s = st.session_state
    text = (s.get(f"note_text_{h}") or "").strip()
    notes = dict(s["tq_notes"])
    if text:
        notes[tq_key] = {"text": text, "by": (s.get("note_by") or "").strip(), "time": _now()}
        if (s["tq_notes"].get(tq_key) or {}).get("text") != text:
            tq_id, _, ref = tq_key.partition("|")
            state.note_review(tq_id, ref, "note", text)
        state.flash("success", "Note saved. It is kept with the project for the next person.", f"fix_{h}")
    else:
        notes.pop(tq_key, None)
        state.flash("info", "The note was removed.", f"fix_{h}")
    s["tq_notes"] = notes


def _send_note(kind: str, ref: str, h: str) -> None:
    from io_sudoku.core.suggestion import make_suggestion
    s = st.session_state
    _save_note(f"{kind}|{ref}", h)
    sg, errors = make_suggestion(kind, ref, s.get(f"note_text_{h}") or "", s.get("note_by") or "", _now())
    if sg is None:
        state.flash("error", " ".join(errors), f"fix_{h}")
        return
    s["suggestions"] = s["suggestions"] + [sg]
    state.note_review(kind, ref, "suggested", sg.text, by=sg.author)
    state.flash("success", "Sent for verification. Press Verify on the Rules page (Suggested Fixes) to accept it.", f"fix_{h}")


def _tq_topic(kind: str, ref: str, fix: str, h: str, text: str = "") -> dict:
    """The Helpdesk topic of one question: everything about it (core.helpcontext), in its own conversation."""
    s = st.session_state
    note = (s.get(f"note_text_{h}") or "").strip()
    result = s["result"]
    question = next((t.message for t in (result.tqs if result is not None else []) if t.tq_id == kind and str(t.ref) == str(ref)), text)
    tq_key = f"{kind}|{ref}"
    title, context = helpcontext.tq_focus(result, kind, ref, text, s["tq_notes"].get(tq_key),
                                          [x for x in s["suggestions"] if x.tq_key == tq_key])
    s["assistant_final"] = note or fix
    return assistant.topic(f"tq|{tq_key}", "tq", title, context, tq_key=tq_key, tq_id=kind, ref=ref, fix=fix,
                           question=question, note=note)


# ------------------------------------------------------------------ all questions
SEVERITIES = (("error", "● Errors"), ("warning", "▲ Warnings"), ("info", "ℹ Info"))


def _toggle_sev(severity: str) -> None:
    s = st.session_state
    chosen = list(s.get("tq_sev") or [])
    s["tq_sev"] = [x for x in chosen if x != severity] if severity in chosen else chosen + [severity]
    s["tq_page"] = 0


def _all_questions(tqs, counts: dict[str, int]) -> None:
    s = st.session_state
    heading("All Questions", "Every question the tool raised, errors first. Red = error (must be answered), amber = "
                             "warning (please confirm), blue = info (no action). The search is not case-sensitive. "
                             "Press a colour to show only that kind; press it again to show everything.")
    autofill.offer("tq_search", autofill.tags() + autofill.column("Field Cable No") + sorted({t.tq_id for t in tqs}))
    text = st.text_input("Search The Questions", key="tq_search", autocomplete="off", label_visibility="collapsed",
                         placeholder="\U0001F50E Search the questions: a tag, a cable or any word…")
    chosen = [x for x in (s.get("tq_sev") or []) if x in counts]
    shown = ui_logic.by_severity(ui_logic.filter_tqs(tqs, chosen, text))
    page_items, page, pages = ui_logic.page_slice(shown, s["tq_page"])
    s["tq_page"] = page
    left, right = st.columns([3, 2], vertical_alignment="center")
    with left, st.container(horizontal=True, gap="small", key="sev_buttons"):
        for severity, label in SEVERITIES:
            st.button(f"{label} · {counts.get(severity, 0):,}", key=f"sevbtn_{severity}",
                      type="primary" if severity in chosen else "secondary", on_click=_toggle_sev, args=(severity,),
                      help=f"Show only the {label.split()[-1].lower()} (press again to show everything).")
    with right:
        pager("tq_page", pages)
    st.caption(f"Showing {len(page_items):,} of {len(shown):,} questions" + (f" · page {page + 1:,} of {pages:,}" if pages > 1 else ""))
    if page_items:
        tq_table(page_items, s["signoffs"], s["tq_notes"])
    else:
        st.info("No questions match your search.")


def _email_text(tqs) -> None:
    owners = list(group_by_owner(tqs))
    with st.expander("Copy Questions For An Owner"):
        owner = st.selectbox("Owner", owners, key="tq_owner")
        st.code(tqs_as_email_text(tqs, owner), language="text")


# ------------------------------------------------------------------ answers
ANSWER = "Answer A Question"


def _answers(result) -> None:
    s = st.session_state
    heading(ANSWER, "Give the missing value for a tag without editing the file. The answer is checked first, applied "
                    "before validation, and every rule still runs on it. After you save it, verify it: the tool "
                    "re-allocates and tells you whether the question is really cleared.")
    if not s["mdb_bytes"]:
        return
    signals, accepted = _signals(s["mdb_bytes"], ui_logic.pack_json(s["pack"]), json.dumps(s["column_overrides"], sort_keys=True))
    cfg: Config = result.cfg_used
    options: dict[str, tuple] = {}
    for t in result.tqs:
        sig = signals.get(match_key(t.ref) or "")
        if sig is None or t.severity == "info":
            continue
        for sug in suggest_resolution(t, sig, accepted, cfg):
            options[f"{t.tq_id} · {t.ref} → set {sug['field']} to {sug['value']} ({sug['why']})"] = (sig.tag, sug, t.tq_id)
    s["_answer_options"] = options
    with st.container(border=True, key="answer_box"):
        if options:
            st.selectbox("Suggested Answers", list(options), key="answer_pick")
        else:
            st.caption("No suggested answers are available for the current questions. You can still give an answer below.")
        autofill.offer("answer_by", autofill.names())
        st.text_input("Answered By", key="answer_by", autocomplete="off", placeholder="Your name…")
        st.caption("Or give your own answer:")
        tags = sorted({sg.tag for sg in signals.values() if sg.tag})
        c1, c2, c3 = st.columns(3)
        c1.selectbox("Tag", tags, index=None, key="manual_tag", placeholder="Pick a tag…",
                     help="Every tag of your file is listed: type a few letters to find one.")
        field = c2.selectbox("Field", OVERRIDABLE_FIELDS, key="manual_field", format_func=lambda f: f.replace("_", " ").title())
        with c3:
            _value_widget(field, cfg)
        with st.container(horizontal=True, gap="small", vertical_alignment="center", key="answer_buttons"):
            st.button("Apply Answer", key="answer_apply", type="primary", on_click=_apply_answer, args=(cfg,))
            assistant.ask_button("answer_ask", _answer_topic, label="Ask The Helpdesk About This Answer",
                                 help="Opens the Helpdesk on the right, already told which answer you picked or typed, "
                                      "everything about that tag and its open questions. Ask which value is right "
                                      "before you apply it. Advice only: it cannot change anything.")
    _answer_check()
    if s["overrides"]:
        st.dataframe(ui_logic.overrides_summary(s["overrides"]), hide_index=True, width="stretch")
        ask_first("clear_answers", "Clear All Answers", f"Remove all {len(s['overrides']):,} saved answers?", _clear_answers,
                  yes="Yes, remove them")


def _answer_topic() -> dict:
    """The Helpdesk topic of the answer box: what is picked or typed now, and everything about that tag."""
    s = st.session_state
    field = s.get("manual_field") or ""
    raw = s.get(f"manual_value_{field}")
    tag = (s.get("manual_tag") or "").strip()
    value = "" if raw is None else str(raw).strip()
    picked = "" if (tag or value) else str(s.get("answer_pick") or "")
    title, context = helpcontext.answer_focus(s["result"], picked, tag, field, value, s.get("answer_check"),
                                              tuple(OVERRIDABLE_FIELDS))
    about = title.split(" · ", 1)[1] if " · " in title else ""
    return assistant.topic(f"answer|{about}", "answer", title, context)


def _value_widget(field: str, cfg: Config) -> None:
    """The value box fits the field: a dropdown when only some values are allowed."""
    key = f"manual_value_{field}"
    if field == "io_type":
        st.selectbox("Value", IO_TYPES, index=None, key=key, placeholder="Pick an IO type…")
    elif field == "segregation":
        codes = sorted({c.upper() for c in cfg.rules.a_codes + cfg.rules.b_codes + cfg.rules.neutral_codes})
        st.selectbox("Value", codes, index=None, key=key, placeholder="Pick a code…")
    elif field == "pair_no":
        st.number_input("Value", min_value=1, step=1, value=None, key=key, placeholder="Pair number…")
    else:
        st.text_input("Value", key=key, autocomplete="off", max_chars=60)


def _question_for(result, tag: str, field: str) -> str:
    """The open question an answer for this tag and field is most likely meant for ('' if none)."""
    key = match_key(tag) or ""
    mine = [t for t in result.tqs if match_key(t.ref) == key and t.severity in ("error", "warning")]
    pick = [t for t in mine if editing.FIELD_FOR_TQ.get(t.tq_id) == field] or mine
    return pick[0].tq_id if pick else ""


def _apply_answer(cfg: Config) -> None:
    s = st.session_state
    who = (s.get("answer_by") or "").strip()
    field = s.get("manual_field")
    tag = (s.get("manual_tag") or "").strip()
    raw = s.get(f"manual_value_{field}")
    value = "" if raw is None else (str(int(raw)) if isinstance(raw, float) and raw.is_integer() else str(raw).strip())
    override, tq_id = None, ""
    if tag or value:
        if not tag or not value:
            state.flash("error", "Pick a tag and give a value, or use a suggested answer.", ANSWER)
            return
        tq_id = _question_for(s["result"], tag, field) if s["result"] is not None else ""
        override = Override(tag, field, value, who, f"{ANSWERS_PREFIX}{tq_id}" if tq_id else "")
    else:
        picked = s.get("_answer_options", {}).get(s.get("answer_pick"))
        if picked:
            tag, tq_id = picked[0], picked[2]
            field, value = picked[1]["field"], str(picked[1]["value"])
            override = Override(tag, field, value, who, f"{ANSWERS_PREFIX}{tq_id}")
    problems = validate_override(override, cfg) if override else ["Pick a suggested answer, or give your own answer."]
    if problems:
        state.flash("error", "This answer cannot be used: " + " ".join(problems), ANSWER)
        return
    s["overrides"] = [o for o in s["overrides"] if (match_key(o.tag_key), o.field) != (match_key(override.tag_key), override.field)] + [override]
    if tq_id:
        state.note_review(tq_id, tag, "answered", f"{field.replace('_', ' ')} = {value}", by=who)
    s["answer_check"] = {"tag": tag, "field": field, "value": value, "tq_id": tq_id, "state": "waiting", "open": []}
    state.mark_stale()
    state.flash("success", f"Answer saved for {tag}: {field.replace('_', ' ')} = {value}.", ANSWER)


def _answer_check() -> None:
    """Under the answer box: ask to verify the answer, then say whether it cleared the question."""
    s = st.session_state
    check = s.get("answer_check")
    if not check:
        return
    what = f"**{md_escape(check['tag'])}** ({md_escape(check['field'].replace('_', ' '))} = {md_escape(check['value'])})"
    if check["state"] == "waiting":
        with st.container(border=True, key="answer_verify"):
            st.markdown(f"\U0001F50D **Verify the answer.** The answer for {what} is saved but not checked yet. "
                        "Verify re-allocates with it and checks that the question is really cleared.")
            with st.container(horizontal=True, gap="small"):
                st.button("✓ Verify And Re-allocate", key="answer_verify_go", type="primary", on_click=_verify_answer)
                st.button("Later", key="answer_verify_later", on_click=_dismiss_check)
    elif check["state"] == "ok":
        st.success(f"Verified: the answer for {check['tag']} works. Its question is cleared and nothing new was "
                   "raised for this tag. You can continue.")
        st.button("OK", key="answer_verify_ok", on_click=_dismiss_check)
    else:
        lines = "\n".join(f"- **{md_escape(i)}** ({sev}): {md_escape(msg)}" for i, sev, msg in check["open"])
        state.alert("error", f"Not resolved: the answer for {check['tag']} did not clear everything. These questions "
                    f"are now on the board for this tag:\n\n{lines}\n\nChange the answer above, or fix it with Edit "
                    f"under {link('Sign Off The Warnings', 'TQ Board', 'Sign Off The Warnings')}.", once=True)
        st.button("OK", key="answer_verify_ok", on_click=_dismiss_check)


def _verify_answer() -> None:
    s = st.session_state
    check = s.get("answer_check")
    state.on_solve()
    if not check or s["result"] is None:
        return
    key = match_key(check["tag"]) or ""
    still = [t for t in s["result"].tqs if match_key(t.ref) == key and t.severity in ("error", "warning")]
    check["open"] = [(t.tq_id, t.severity, ui_logic.short_text(t.message)) for t in still]
    check["state"] = "failed" if still else "ok"
    if check.get("tq_id"):
        state.note_review(check["tq_id"], check["tag"], "answer-failed" if still else "answer-ok",
                          f"{check['field'].replace('_', ' ')} = {check['value']}"
                          + (f"; still open: {', '.join(i for i, *_ in check['open'])}" if still else ""))
    s["answer_check"] = dict(check)


def _dismiss_check() -> None:
    st.session_state["answer_check"] = None


def _clear_answers() -> None:
    st.session_state["overrides"] = []
    st.session_state["answer_check"] = None
    state.mark_stale()
    state.flash("success", "All saved answers were removed.", ANSWER)


# ------------------------------------------------------------------ pins
def _clear_pins() -> None:
    st.session_state["pins"] = {}
    state.mark_stale()
    state.flash("success", "All pins were removed.", "Pin A Cable")


def _add_pin() -> None:
    s = st.session_state
    cable, cab, cioc = s.get("pin_cable"), s.get("pin_cab"), s.get("pin_cioc")
    if cable and cab and cioc:
        s["pins"] = {**s["pins"], cable: (cab, int(cioc))}
        state.mark_stale()
        state.flash("success", f"{cable} will be placed in {cab}, CIOC {cioc} when you re-allocate.", "Pin A Cable")


def _pins(result) -> None:
    s = st.session_state
    heading("Pin A Cable", "Fix a cable to a cabinet and CIOC. The solver still checks every rule; if the pin would "
                           "break one, a PIN-UNSATISFIABLE question is raised instead.")
    cables = sorted({str(r.get("Field Cable No")) for r in result.rows if r.get("Field Cable No") not in (None, "-")})
    cabinets = ui_logic.cabinet_names(result.rows)
    if not cables:
        st.caption("There are no cables to pin yet.")
        return
    with st.form("pin_form"):
        c1, c2, c3 = st.columns(3)
        c1.selectbox("Cable", cables, key="pin_cable")
        c2.selectbox("Cabinet", cabinets, key="pin_cab")
        c3.selectbox("CIOC", [1, 2, 3, 4], key="pin_cioc")
        st.form_submit_button("Add Pin", on_click=_add_pin)
    if s["pins"]:
        st.dataframe([{"Cable": k, "Cabinet": v[0], "CIOC": v[1]} for k, v in sorted(s["pins"].items())],
                     hide_index=True, width="stretch")
        ask_first("clear_pins", "Clear All Pins", f"Remove all {len(s['pins']):,} pins?", _clear_pins, yes="Yes, remove them")
