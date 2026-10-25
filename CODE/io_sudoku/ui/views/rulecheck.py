"""Rule Check (the first tab of Audit): pick one or more cells (slots) and see, live, every rule and constraint
that applies to each.

Cells are picked here (case-sensitive search) or by clicking a slot on Cabinet Layout.  The log is worked
out again from the current allocation on every run (core.cellcheck), so it is always up to date.
"""
from __future__ import annotations

import time
from functools import partial
from html import escape

import streamlit as st

from io_sudoku.core import cellcheck as cc, helpcontext
from io_sudoku.ui import state, ui_logic
from io_sudoku.ui.nav import link_to
from io_sudoku.ui.views import assistant
from io_sudoku.ui.views._common import heading, md_escape, result_or_empty

CURRENT, REV_B = "Current Allocation", "Rev B Comparison"
ALL_CABINETS = "All Cabinets"
MAX_CARDS = 12
MAX_TABLE = 400


@st.cache_data(max_entries=8, show_spinner=False)
def _index(result_key: str, _rows: list) -> dict:
    return cc.index_rows(_rows)


@st.cache_data(max_entries=8, show_spinner=False)
def _table(result_key: str, _rows: list) -> list[dict]:
    """One line per slot for the picker (with the text the search looks in)."""
    out = []
    for r in _rows:
        sid = cc.slot_id(r)
        if not sid:
            continue
        cab, cioc, bp, ch = sid.split(cc.SEP)
        out.append({"id": sid, "Tag": str(r.get("Tag Name") or "-"), "Status": str(r.get("Tag Status") or "-"),
                    "Cabinet": cab, "CIOC": int(cioc), "BP": int(bp), "CH": int(ch), "CHARM_No": r.get("CHARM_No"),
                    "CHARM Type": str(r.get("CHARM Type") or "-"), "IO": str(r.get("IO Type") or "-"),
                    "Cable": str(r.get("Field Cable No") or "-"), "Pair": str(r.get("Field Cable Pair") or "-"),
                    "_find": " ".join(str(r.get(c) or "") for c in ("Tag Name", "Field Cable No", "CHARM Type", "IO Type",
                                                                     "Tag Status", "CIOC/CSLS Name", "Baseplate"))
                             + f" CIOC {cioc} BP {bp} CH {ch}"})
    return out


def _source():
    """(result, its key) of the allocation being checked."""
    s = st.session_state
    if s.get("rev_b_result") is not None and s.get("rc_source") == REV_B:
        return s["rev_b_result"], "revb_" + (s.get("rev_key") or "")
    return s["result"], s["result_key"] or ""


def render() -> None:
    s = st.session_state
    if result_or_empty("the rule check", "rc") is None:
        return
    if s.get("rev_b_result") is not None:
        st.selectbox("Which Revision To Check", (CURRENT, REV_B), key="rc_source",
                     help="Rev B Comparison = the new revision worked out on the Revision page.")
    result, key = _source()
    st.caption("Pick any cell of the allocation and see every rule and constraint that applies to it: the locked rules, "
               "the project rules of the active pack, answers, pins, open questions and the solver's own decisions. The "
               f"other way round (one rule, every cell it affects) is the "
               f"{link_to('Rule Impact', 'Audit › Rule Impact')} tab.")
    _picker(result, key)
    _log(result, key)


# ------------------------------------------------------------------ picking cells
def _picked(widget: str, ids: list[str]) -> None:
    s = st.session_state
    rows = ((s.get(widget) or {}).get("selection") or {}).get("rows") or []
    chosen = [ids[i] for i in rows if i < len(ids)]
    shown = set(ids)
    s["rc_cells"] = [x for x in s["rc_cells"] if x not in shown or x in chosen] + [x for x in chosen if x not in s["rc_cells"]]


def _clear() -> None:
    st.session_state["rc_cells"] = []


def _picker(result, key: str) -> None:
    s = st.session_state
    heading("Pick The Cells To Check", "Tick one or more rows. The search is case-sensitive, so you get exactly the "
                                       "cell you typed. You can also click any slot on Cabinet Layout to open it here.")
    names = ui_logic.cabinet_names(result.rows)
    options = [ALL_CABINETS] + names
    if s.get("rc_cab") not in options:
        s["rc_cab"] = s.get("selected_cabinet") if s.get("selected_cabinet") in names else ALL_CABINETS
    c1, c2 = st.columns([2, 3])
    cab = c1.selectbox("Cabinet", options, key="rc_cab")
    needle = c2.text_input("Find (case-sensitive)", key="rc_find", autocomplete="off",
                           placeholder="A tag, cable, CHARM type, or CIOC 1 BP 2 CH 3…").strip()
    lines = [x for x in _table(key, result.rows) if (cab == ALL_CABINETS or x["Cabinet"] == cab)
             and (not needle or needle in x["_find"])]
    shown = lines[:MAX_TABLE]
    st.caption(f"{len(lines):,} cells" + (f" · showing the first {len(shown):,}; search to narrow it down" if len(lines) > len(shown) else "")
               + f" · {len(s['rc_cells']):,} picked")
    if not shown:
        st.info("No cell matches. Check the spelling and the capital letters, or pick All Cabinets.")
        return
    ids = [x["id"] for x in shown]
    widget = "rc_table_" + ui_logic.sha256_hex("|".join([key[:12], cab, needle] + s["rc_cells"]))[:12]
    import pandas as pd
    frame = pd.DataFrame([{k: v for k, v in x.items() if k not in ("id", "_find")} for x in shown])
    st.dataframe(frame, key=widget, on_select=partial(_picked, widget, ids), selection_mode="multi-row", hide_index=True,
                 width="stretch", height=min(360, 38 + 35 * len(shown)),
                 selection_default={"selection": {"rows": [i for i, x in enumerate(ids) if x in s["rc_cells"]]}})


# ------------------------------------------------------------------ the live log
def _remove(sid: str) -> None:
    st.session_state["rc_cells"] = [x for x in st.session_state["rc_cells"] if x != sid]


COLOURS = {cc.PASS: "#3fb950", cc.FAIL: "#ff7b72", cc.WARN: "#e3b341", cc.INFO: "#8b949e"}


def _log(result, key: str) -> None:
    s = st.session_state
    heading("Live Rule Log", "For each picked cell: ✓ the rule is met, ✗ it is broken, ▲ it needs a look, "
                             "• information (answers, project columns, the solver's decisions). It is worked out "
                             "again from the allocation every time, so it always matches what you see. Point at "
                             "Signal Path to see the way from the field device to the controller.")
    cells = s["rc_cells"]
    if not cells:
        st.info("Pick cells above, or click a slot on Cabinet Layout, to see the rules that apply to them.")
        return
    if s.get("stale") and key == (s["result_key"] or ""):
        st.warning("Your inputs changed after this allocation: this log is for the last allocation. Re-allocate to refresh it.")
    left, right = st.columns([3, 2], vertical_alignment="center")
    left.caption(f"Checked at {time.strftime('%H:%M:%S')} against the {ui_logic.readiness_text(result)[0]} allocation.")
    with right, st.container(horizontal=True, horizontal_alignment="right", gap="small"):
        st.segmented_control("Show", ("Everything", "Problems Only"), key="rc_show", label_visibility="collapsed")
        st.button("Clear All", key="rc_clear", on_click=_clear)
    index = _index(key, result.rows)
    problems_only = s.get("rc_show") == "Problems Only"
    missing = [sid for sid in cells if sid not in index]
    if missing:
        _missing(missing, s.get("rev_b_result") is not None and s.get("rc_source") != REV_B)
    for sid in [x for x in cells if x in index][:MAX_CARDS]:
        _card(result, index, sid, problems_only)
    if len(cells) > MAX_CARDS:
        st.caption(f"The first {MAX_CARDS} of {len(cells):,} picked cells are shown. Remove some to see the others.")


def _drop(sids: list[str]) -> None:
    gone = set(sids)
    st.session_state["rc_cells"] = [x for x in st.session_state["rc_cells"] if x not in gone]


def _missing(sids: list[str], rev_b_exists: bool) -> None:
    """Cells picked earlier that this allocation does not have (an earlier file, or Rev B): said once, plainly."""
    names = ", ".join(x.replace(cc.SEP, " / ") for x in sids[:4]) + (" …" if len(sids) > 4 else "")
    where = (" They may be from Rev B: switch Check to Rev B Comparison above to see them." if rev_b_exists else
             " They were picked in an earlier file or allocation whose cabinets are different (for example the sample "
             "data before you uploaded your own file).")
    with st.container(border=True, key="rc_missing"):
        left, right = st.columns([5, 1.4], vertical_alignment="center")
        left.markdown(f"ℹ️ **{len(sids):,} picked cell(s) are not in this allocation:** {md_escape(names)}.{where}")
        right.button("Remove Them", key="rc_drop_missing", on_click=_drop, args=(list(sids),), width="stretch")


def _cell_topic(sid: str) -> dict | None:
    """The Helpdesk topic of one cell: its row, every rule on it and its signal path (worked out again on click)."""
    s = st.session_state
    result, key = _source()
    row = _index(key, result.rows).get(sid)
    if row is None:
        return None
    checks = cc.check_cell(result, row, overrides=s["overrides"], pins=s["pins"])
    title, context = helpcontext.cell_focus(result, row, checks, cc.signal_path(row), cc.slot_label(row))
    return assistant.topic(f"cell|{key[:12]}|{sid}", "cell", title, context)


def _card(result, index: dict, sid: str, problems_only: bool) -> None:
    s = st.session_state
    h = ui_logic.sha256_hex(sid)[:10]
    row = index.get(sid)
    with st.container(border=True, key=f"rc_card_{h}"):
        top, path, ask, rm = st.columns([5.2, 1.7, 1.2, .5], vertical_alignment="center")
        if row is None:
            top.markdown(f"**{md_escape(sid.replace(cc.SEP, ' / '))}**: this cell is not in this allocation.")
            rm.button("✕", key=f"rc_rm_{h}", on_click=_remove, args=(sid,), help="Remove from the log")
            return
        with ask:
            assistant.ask_button(f"rc_ask_{h}", _cell_topic, (sid,), label="Ask AI", width="stretch",
                                 help="Opens the Helpdesk on the right, already told about this cell: its signal, every "
                                      "rule on it and its signal path. Advice only: it cannot change anything.")
        checks = cc.check_cell(result, row, overrides=s["overrides"], pins=s["pins"])
        n = cc.summary(checks)
        top.markdown(f"**{md_escape(cc.slot_label(row))}**  \n<small>"
                     f"<span style='color:{COLOURS[cc.PASS]}'>✓ {n[cc.PASS]} met</span> · "
                     f"<span style='color:{COLOURS[cc.FAIL]}'>✗ {n[cc.FAIL]} broken</span> · "
                     f"<span style='color:{COLOURS[cc.WARN]}'>▲ {n[cc.WARN]} to check</span> · "
                     f"<span style='color:{COLOURS[cc.INFO]}'>• {n[cc.INFO]} notes</span></small>",
                     unsafe_allow_html=True)
        path.markdown("\U0001F6E4️ **Signal Path**", help="  \n".join(f"**{step}:** {md_escape(text)}"
                                                                       for step, text in cc.signal_path(row)))
        rm.button("✕", key=f"rc_rm_{h}", on_click=_remove, args=(sid,), help="Remove from the log")
        shown = [c for c in checks if not problems_only or c.status in (cc.FAIL, cc.WARN)]
        if not shown:
            st.caption("No rule is broken and nothing needs a look.")
            return
        body = "".join(f'<div><span style="color:{COLOURS[c.status]};font-weight:700">{cc.ICONS[c.status]}</span> '
                       f'<span class="iosg-rule">{escape(c.rule)}</span> <b>{escape(c.title)}</b>: {escape(c.detail)}</div>'
                       for c in shown)
        with st.container(height=300, key=f"rc_logbox_{h}") if len(shown) > 9 else st.container(key=f"rc_logbox_{h}"):
            st.markdown(f'<div class="iosg-log">{body}</div>', unsafe_allow_html=True)


def pick(sid: str) -> None:
    """Open Rule Check with this cell first in the log (used by the slots of Cabinet Layout)."""
    s = st.session_state
    s["rc_cells"] = [sid] + [x for x in s.get("rc_cells", []) if x != sid][:MAX_CARDS - 1]
    s["rc_source"] = CURRENT
    cab = sid.split(cc.SEP)[0]
    s["rc_cab"] = cab
    s["view"] = "Audit"
    s[state.RULE_TAB_KEY] = state.CHECK_TAB
    s["scroll_to"] = "Live Rule Log"
    state.flash("info", f"Showing the rules of {sid.replace(cc.SEP, ' / ')}.", "Live Rule Log")
