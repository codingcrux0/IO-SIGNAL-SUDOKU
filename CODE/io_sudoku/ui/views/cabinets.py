"""Cabinet Layout: one marshalling cabinet, shown two ways from ONE cabinet picker and ONE legend.

  Slot Map               the 384-slot grid (4 CIOCs x 8 baseplates x 12 channels) with hover cards,
                         plus the 'Why Is It Here?' decision trace for a tag or cable
  Front & Rear Drawings  the front (CIOC 1-2) and rear (CIOC 3-4) elevations with hover cards
The picker's first option, All Cabinet Drawings, replaces both with the drawings of every cabinet in one
scroll box (plus the printable pack), with 'Why Is It Here?' for any tag of any cabinet below it.
Clicking any slot or drawing cell opens it on Rule Check.

(This view replaces the separate Grid and Drawings views; old links to either still open it.)
"""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.elevation import cabinet_svg
from io_sudoku.core.trace import explain
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.views._common import ALL_DRAWINGS, cabinet_picker, download_button, main_ctx, result_or_empty

SLOT_MAP, DRAWINGS = "Slot Map", "Front & Rear Drawings"


def render() -> None:
    s = st.session_state
    st.header("Cabinet Layout")
    state.show_flash("Cabinet Layout")
    result = result_or_empty("the cabinet layout", "cab")
    if result is None:
        return
    cabinet = cabinet_picker(result.rows, "cab")
    if cabinet is None:
        return
    state.sync_url()
    st.markdown(theme.LEGEND_HTML, unsafe_allow_html=True)
    if cabinet == ALL_DRAWINGS:
        _all_drawings(result)
        return
    st.caption("Point at any slot to see its tag, IO type, CHARM and cable. Click it to see every rule that applies to it.")
    slot_map, drawings = st.tabs([SLOT_MAP, DRAWINGS], key=state.CAB_TAB_KEY, on_change="rerun")   # tracked, so a link can open a tab
    with slot_map:
        st.html(ui_logic.grid_html(s["result_key"] or "", cabinet, result.rows))
        _why_here(cabinet)
    with drawings:
        for side, title in (("F", "Front (CIOC 1–2)"), ("R", "Rear (CIOC 3–4)")):
            st.subheader(title)
            page, height = ui_logic.drawing_page(cabinet_svg(result.rows, cabinet, side))
            st.iframe(page, height=height)


def _all_drawings(result) -> None:
    """Every cabinet's front and rear drawing, in one box that scrolls on its own."""
    s = st.session_state
    names = ui_logic.cabinet_names(result.rows)
    st.caption(f"{len(names):,} cabinets, front (CIOC 1–2) and rear (CIOC 3–4). Scroll inside the box; each cabinet's "
               "name stays on top while you scroll it. Click any cell to see its rules.")
    st.iframe(_all_page(s["result_key"] or "", result.rows), height=ui_logic.ALL_DRAWINGS_HEIGHT)
    download_button(next(d for d in ui_logic.DOWNLOADS if d.key == "drawings"), main_ctx(), s["result_key"] or "", "draw")
    _why_here(ALL_DRAWINGS)


@st.cache_data(max_entries=8, show_spinner=False)
def _all_page(result_key: str, _rows: list) -> str:
    return ui_logic.all_drawings_page(_rows, ui_logic.cabinet_names(_rows))


@st.fragment
def _why_here(cabinet: str) -> None:
    """The decision trace.  Runs alone when you pick a tag, so the map and drawings never flicker.
    `cabinet` = one cabinet's tags, or ALL_DRAWINGS = the tags of every cabinet."""
    s = st.session_state
    result = s["result"]
    if result is None:
        return
    st.subheader("Why Is It Here?", help="The decisions the solver wrote down for a tag or cable. Typed cable "
                                         "numbers are case-sensitive, so you get exactly the cable you typed.")
    every = cabinet == ALL_DRAWINGS
    rows = result.rows if every else [r for r in result.rows if str(r.get("Electronic/ Marshalling Cabinet")) == cabinet]
    tags = sorted({str(r.get("Tag Name")) for r in rows if r.get("Tag Status") in ("Field", "Wired Spare", "Cabinet Alarm")})
    options = ["(Pick a tag)"] + tags
    if s.get("why_tag") not in options:              # a tag of another cabinet was picked before
        s["why_tag"] = options[0]
    pick = st.selectbox("Tag (any cabinet)" if every else "Tag", options, key="why_tag")
    typed = st.text_input("Or Type A Cable Number (case-sensitive)", key="why_cable", autocomplete="off",
                          placeholder="For example 320-CE-0001…").strip()
    if typed:
        cables = {str(r.get("Field Cable No")) for r in result.rows}
        if typed not in cables:
            st.info(f"No cable is called exactly “{typed}”. Check the spelling and the capital letters.")
            return
    query = typed or (pick if pick != "(Pick a tag)" else "")
    if not query:
        st.caption("Pick a tag or type a cable number to see the decisions behind its position.")
        return
    lines = explain(result, query)
    if lines:
        with st.container(height=360) if len(lines) > 8 else st.container():      # a scroll box for long traces
            st.markdown("\n".join(f"{n}. {line}" for n, line in enumerate(lines, start=1)))
    else:
        st.info(f"No decisions were recorded for “{query}”.")
