"""Parts: bill of materials, cable utilisation and headroom per cabinet."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.bom import bom, cable_utilisation, headroom
from io_sudoku.ui import ui_logic
from io_sudoku.ui.views._common import file_card, main_ctx, result_or_empty


def render() -> None:
    st.header("Parts And Cable Use")
    result = result_or_empty("the parts list", "parts")
    if result is None:
        return
    st.subheader("Bill Of Materials")
    st.dataframe(bom(result.rows), hide_index=True, width="stretch")
    st.subheader("Cable Utilisation")
    st.caption("Advisory only: a smaller cable might do, but pair numbers are positional, so engineering must review any change.")
    st.dataframe(cable_utilisation(result.rows), hide_index=True, width="stretch")
    st.subheader("Room To Grow")
    lines = headroom(result.rows, result.cfg_used)
    st.dataframe(lines, hide_index=True, width="stretch")
    file_card(next(d for d in ui_logic.DOWNLOADS if d.key == "parts"), main_ctx(), st.session_state["result_key"] or "", "parts")
