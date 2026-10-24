"""Cabinet Layout: one marshalling cabinet, shown two ways from ONE cabinet picker and ONE legend.

  Slot Map               the 384-slot grid (4 CIOCs x 8 baseplates x 12 channels) with hover cards,
                         plus the 'Why Is It Here?' decision trace for a tag or cable
  Front & Rear Drawings  the front (CIOC 1-2) and rear (CIOC 3-4) elevations with hover cards,
                         plus the printable drawings pack of every cabinet

(This view replaces the separate Grid and Drawings views; old links to either still open it.)
"""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.elevation import cabinet_svg
from io_sudoku.core.trace import explain
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.views._common import cabinet_picker, file_card, main_ctx, result_or_empty

SLOT_MAP, DRAWINGS = "Slot Map", "Front & Rear Drawings"


def render() -> None:
    s = st.session_state
    st.header("Cabinet Layout")
    result = result_or_empty("the cabinet layout", "cab")
    if result is None:
        return
    cabinet = cabinet_picker(result.rows, "cab")
    if cabinet is None:
        return
    state.sync_url()
    st.markdown(theme.LEGEND_HTML, unsafe_allow_html=True)
    st.caption("Point at any slot to see its tag, IO type, CHARM and cable.")
    slot_map, drawings = st.tabs([SLOT_MAP, DRAWINGS], key=state.CAB_TAB_KEY, on_change="rerun")   # tracked, so a link can open a tab
    with slot_map:
        st.html(ui_logic.grid_html(s["result_key"] or "", cabinet, result.rows))
        _why_here(cabinet)
    with drawings:
        for side, title in (("F", "Front (CIOC 1–2)"), ("R", "Rear (CIOC 3–4)")):
            st.subheader(title)
            page, height = ui_logic.drawing_page(cabinet_svg(result.rows, cabinet, side))
            st.iframe(page, height=height)
        file_card(next(d for d in ui_logic.DOWNLOADS if d.key == "drawings"), main_ctx(), s["result_key"] or "", "draw",
                  view_label="Show All Cabinet Drawings")


@st.fragment
def _why_here(cabinet: str) -> None:
    """The decision trace.  Runs alone when you pick a tag, so the map and drawings never flicker."""
    s = st.session_state
    result = s["result"]
    if result is None:
        return
    st.subheader("Why Is It Here?")
    tags = sorted({str(r.get("Tag Name")) for r in result.rows
                   if str(r.get("Electronic/ Marshalling Cabinet")) == cabinet and r.get("Tag Status") in ("Field", "Wired Spare", "Cabinet Alarm")})
    pick = st.selectbox("Tag", ["(Pick a tag)"] + tags, key="why_tag")
    typed = st.text_input("Or Type A Cable Number", key="why_cable", autocomplete="off",
                          placeholder="For example 320-CE-0001…")
    query = typed.strip() or (pick if pick != "(Pick a tag)" else "")
    if not query:
        st.caption("Pick a tag or type a cable number to see the decisions behind its position.")
        return
    lines = explain(result, query)
    if lines:
        with st.container(height=360) if len(lines) > 8 else st.container():      # a scroll box for long traces
            st.markdown("\n".join(f"{n}. {line}" for n, line in enumerate(lines, start=1)))
    else:
        st.info(f"No decisions were recorded for “{query}”. Check the spelling, or try the cable number.")
