"""TQ board: filter and page the questions, answer them from dropdowns, pin cables, copy e-mail text."""
from __future__ import annotations

import json

import streamlit as st

from io_sudoku.core.config import Config
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.models import Signal
from io_sudoku.core.overrides import OVERRIDABLE_FIELDS, Override, suggest_resolution, validate_override
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.topology_infer import infer_cabinets
from io_sudoku.core.tq import TQLog
from io_sudoku.core.tqlife import group_by_owner, tqs_as_email_text
from io_sudoku.core.validate import validate
from io_sudoku.ui import state, ui_logic
from io_sudoku.ui.views._common import result_or_empty


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
    a, b, c = st.columns(3)
    a.metric("Errors", f"{counts['error']:,}")
    b.metric("Warnings", f"{counts['warning']:,}")
    c.metric("Info", f"{counts['info']:,}")
    if not tqs:
        st.success("No questions were raised. Nothing needs an answer.")
    else:
        f1, f2 = st.columns([1, 2])
        f1.selectbox("Show", ui_logic.TQ_FILTERS, key="tq_filter")
        text = f2.text_input("Search", key="tq_search", autocomplete="off", placeholder="Tag, cable or words…")
        shown = ui_logic.filter_tqs(tqs, s["tq_filter"], text)
        page_items, page, pages = ui_logic.page_slice(shown, s["tq_page"])
        if pages > 1:
            s["tq_page"] = page
            st.number_input(f"Page (of {pages:,})", min_value=0, max_value=pages - 1, key="tq_page", step=1)
        st.caption(f"Showing {len(page_items):,} of {len(shown):,} questions.")
        if page_items:
            st.dataframe(ui_logic.tq_rows(page_items), hide_index=True, width="stretch")
        else:
            st.info("No questions match your filter.")
        _email_text(tqs)
        _answers(result)
    _pins(result)


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
