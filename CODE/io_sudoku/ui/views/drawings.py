"""Drawings: front and rear elevation of a cabinet, plus the printable pack."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.elevation import cabinet_svg
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.views._common import cabinet_picker, download_button, main_ctx, result_or_empty


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
    front, rear = st.columns(2)
    with front:
        st.subheader("Front (CIOC 1–2)")
        st.html(cabinet_svg(result.rows, cabinet, "F"))
    with rear:
        st.subheader("Rear (CIOC 3–4)")
        st.html(cabinet_svg(result.rows, cabinet, "R"))
    download_button(next(d for d in ui_logic.DOWNLOADS if d.key == "drawings"), main_ctx(), st.session_state["result_key"] or "", "draw")
