"""Drawings: front and rear elevation of a cabinet, plus the printable pack."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.elevation import cabinet_svg
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.views._common import cabinet_picker, file_card, main_ctx, result_or_empty


def render() -> None:
    st.header("Cabinet Drawings")
    result = result_or_empty("the cabinet drawings", "draw")
    if result is None:
        return
    cabinet = cabinet_picker(result.rows, "draw")
    if cabinet is None:
        return
    state.sync_url()
    st.markdown(theme.LEGEND_HTML, unsafe_allow_html=True)
    st.caption("Point at any slot to see its tag, IO type, CHARM and cable.")
    for side, title in (("F", "Front (CIOC 1–2)"), ("R", "Rear (CIOC 3–4)")):
        st.subheader(title)
        page, height = ui_logic.drawing_page(cabinet_svg(result.rows, cabinet, side))
        st.iframe(page, height=height)
    file_card(next(d for d in ui_logic.DOWNLOADS if d.key == "drawings"), main_ctx(), st.session_state["result_key"] or "", "draw")
