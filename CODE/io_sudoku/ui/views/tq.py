"""TQ board: sign off warnings, filter and page the questions, answer them, pin cables, copy e-mail text."""
from __future__ import annotations

import json

import streamlit as st

from io_sudoku.core import readiness as readiness_mod
from io_sudoku.core.config import Config
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.models import Signal
from io_sudoku.core.overrides import OVERRIDABLE_FIELDS, Override, suggest_resolution, validate_override
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.topology_infer import infer_cabinets
from io_sudoku.core.tq import TQLog
from io_sudoku.core.tqlife import group_by_owner, tqs_as_email_text
from io_sudoku.core.validate import validate
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.views._common import allocate_button, md_escape, result_or_empty, tq_table


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
    _signoff(result)
    if not tqs:
        st.success("No questions were raised. Nothing needs an answer.")
    else:
        st.subheader("All Questions")
        f1, f2 = st.columns([1, 2])
        f1.selectbox("Show", ui_logic.TQ_FILTERS, key="tq_filter")
        text = f2.text_input("Search", key="tq_search", autocomplete="off", placeholder="Tag, cable or words…")
        shown = ui_logic.by_severity(ui_logic.filter_tqs(tqs, s["tq_filter"], text))
        page_items, page, pages = ui_logic.page_slice(shown, s["tq_page"])
        if pages > 1:
            s["tq_page"] = page
            st.number_input(f"Page (of {pages:,})", min_value=0, max_value=pages - 1, key="tq_page", step=1)
        st.caption(f"Showing {len(page_items):,} of {len(shown):,} questions, errors first. "
                   "Red = error (must be answered), amber = warning (please confirm), blue = info (no action).")
        if page_items:
            tq_table(page_items, s["signoffs"])
        else:
            st.info("No questions match your filter.")
        _email_text(tqs)
        _answers(result)
    _pins(result)


ROWS_PER_PAGE = 60


def _box(count: int):
    """A scroll box for long lists, so the page itself does not have to be scrolled."""
    return st.container(height=420, key="signoff_box") if count > 4 else st.container(key="signoff_box")


def _signoff(result) -> None:
    """ONE scroll box with every error and warning.  Errors (listed first) must be fixed: Edit opens the exact
    cell.  Warnings need Approve (or Problem) before the allocation can be ISSUE-READY, and can be edited too."""
    s = st.session_state
    st.subheader("Sign Off The Warnings")
    seen: dict[tuple[str, str], int] = {}
    items: list[tuple] = []
    for t in result.tqs:
        if t.severity == "error":                      # nth: which of several same (id, tag) rows this one is
            n = seen.get((t.tq_id, t.ref), 0)
            seen[(t.tq_id, t.ref)] = n + 1
            items.append(("error", t.tq_id, t.ref, t.message, n))
    errors = len(items)
    items += [("warning", kind, ref, text, key) for key, kind, ref, text in ui_logic.warning_rows(result)]
    if not items:
        st.caption("There are no errors or warnings.")
        return
    signed = readiness_mod.signoff_counts(result, s["signoffs"])
    st.caption(f"{errors:,} errors to fix \u00b7 {signed[readiness_mod.APPROVED]:,} of {signed['total']:,} warnings approved "
               f"\u00b7 {signed[readiness_mod.PROBLEM]:,} marked as a problem \u00b7 {signed['waiting']:,} waiting. "
               "Errors are listed first and must be fixed: press Edit to open the exact cell, then re-allocate. "
               "Every warning needs Approve before the allocation can be ISSUE-READY; Problem keeps it in DRAFT.")
    page_items, page, pages = ui_logic.page_slice(items, s.get("err_page", 0), ROWS_PER_PAGE)
    if pages > 1:
        s["err_page"] = page
        st.number_input(f"Page (of {pages:,})", min_value=0, max_value=pages - 1, key="err_page", step=1)
    with _box(len(page_items)):
        for i, (severity, kind, ref, text, extra) in enumerate(page_items):
            left, mid, right = st.columns([4, 2, 1], vertical_alignment="center")
            mark = "\u25cf" if severity == "error" else "\u25b2"
            left.markdown(f"{mark} **{md_escape(kind)}** \u00b7 {md_escape(ref) or '-'}  \n"
                          f"<small>{md_escape(ui_logic.short_text(text))}</small>", unsafe_allow_html=True,
                          help=_details(result, kind, ref, text))
            if severity == "error":
                mid.markdown('<span style="color:#ff7b72;font-weight:700">Error: fix it</span>', unsafe_allow_html=True)
                right.button("\u270e Edit", key=f"edit_err_{page}_{i}", on_click=state.edit_for_tq,
                             args=(kind, ref, extra), help="Open the cell this error is about on the Edit File page.")
                continue
            widget = state.signoff_widget_key(extra)
            s[widget] = state.SIGNOFF_LABELS.get(s["signoffs"].get(extra))     # the sign-offs are the one source of truth
            mid.segmented_control(f"Sign-off for {kind} {ref}", list(state.SIGNOFF_LABELS.values()), key=widget,
                                  on_change=state.on_signoff, args=(extra,), label_visibility="collapsed")
            right.button("\u270e Edit", key=f"edit_warn_{widget}", on_click=state.edit_for_tq, args=(kind, ref, 0),
                         help="Open the cell this warning is about on the Edit File page.")
    if signed["waiting"]:
        c1, c2 = st.columns([3, 2], vertical_alignment="center")
        sure = c1.checkbox("I have checked every warning above", key="approve_all_ok")
        c2.button("Approve All Warnings", key="approve_all", disabled=not sure, on_click=state.approve_all_warnings)


def _details(result, kind: str, ref: str, text: str) -> str:
    """What the (i) next to a question shows on hover: the whole text, the suggested fix and the owner."""
    return "\n\n".join(f"**{label}:** {md_escape(value)}" for label, value in ui_logic.question_details(result, kind, ref, text))


def _email_text(tqs) -> None:
    owners = list(group_by_owner(tqs))
    with st.expander("Copy Questions For An Owner"):
        owner = st.selectbox("Owner", owners, key="tq_owner")
        st.code(tqs_as_email_text(tqs, owner), language="text")


def _answers(result) -> None:
    s = st.session_state
    st.subheader("Answer A Question")
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
            options[f"{t.tq_id} · {t.ref} → set {sug['field']} to {sug['value']} ({sug['why']})"] = (sig.tag, sug)
    s["_answer_options"] = {k: (tag, sug) for k, (tag, sug) in options.items()}
    with st.form("answer_form"):
        if options:
            st.selectbox("Suggested Answers", list(options), key="answer_pick")
        else:
            st.caption("No suggested answers are available for the current questions. You can still type an answer below.")
        st.text_input("Answered By", key="answer_by", autocomplete="off", placeholder="Your name\u2026")
        c1, c2, c3 = st.columns(3)
        c1.text_input("Or Tag", key="manual_tag", autocomplete="off")
        c2.selectbox("Field", OVERRIDABLE_FIELDS, key="manual_field")
        c3.text_input("Value", key="manual_value", autocomplete="off")
        st.form_submit_button("Apply Answer", on_click=_apply_answer, args=(cfg,))
    if s["overrides"]:
        st.dataframe(ui_logic.overrides_summary(s["overrides"]), hide_index=True, width="stretch")
        sure = st.checkbox("I understand this removes all saved answers", key="clear_answers_ok")
        st.button("Clear All Answers", disabled=not sure, key="clear_answers", on_click=_clear_answers)


def _apply_answer(cfg: Config) -> None:
    s = st.session_state
    who = (s.get("answer_by") or "").strip()
    tag, field, value = (s.get("manual_tag") or "").strip(), s.get("manual_field"), (s.get("manual_value") or "").strip()
    override = None
    if tag and value:
        override = Override(tag, field, value, who)
    else:
        picked = s.get("_answer_options", {}).get(s.get("answer_pick"))
        if picked:
            override = Override(picked[0], picked[1]["field"], picked[1]["value"], who)
    problems = validate_override(override, cfg) if override else ["Pick a suggested answer, or fill in both tag and value."]
    if problems:
        state.flash("error", " ".join(problems))
        return
    s["overrides"] = [o for o in s["overrides"] if (o.tag_key, o.field) != (override.tag_key, override.field)] + [override]
    state.mark_stale()
    state.flash("success", "Answer saved. Re-solve to see its effect.")


def _clear_answers() -> None:
    st.session_state["overrides"] = []
    state.mark_stale()
    state.flash("success", "All saved answers were removed.")


def _clear_pins() -> None:
    st.session_state["pins"] = {}
    state.mark_stale()
    state.flash("success", "All pins were removed.")


def _add_pin() -> None:
    s = st.session_state
    cable, cab, cioc = s.get("pin_cable"), s.get("pin_cab"), s.get("pin_cioc")
    if cable and cab and cioc:
        s["pins"] = {**s["pins"], cable: (cab, int(cioc))}
        state.mark_stale()
        state.flash("success", f"{cable} will be placed in {cab}, CIOC {cioc} when you re-solve.")


def _pins(result) -> None:
    s = st.session_state
    st.subheader("Pin A Cable")
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
        sure = st.checkbox("I understand this removes all pins", key="clear_pins_ok")
        st.button("Clear All Pins", disabled=not sure, key="clear_pins", on_click=_clear_pins)
