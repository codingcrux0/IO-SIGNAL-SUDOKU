"""Downloads: every file the tool can produce, named with the readiness suffix."""
from __future__ import annotations

import streamlit as st

from io_sudoku.ui import ui_logic
from io_sudoku.ui.views._common import download_button, main_ctx, readiness_block, result_or_empty


def render() -> None:
    st.header("Downloads")
    result = result_or_empty("the downloads", "dl")
    if result is None:
        return
    readiness_block(result)
    st.caption("Files from a draft result carry _DRAFT in the name, so nobody issues them by mistake. "
               "Revision reports are on the Revision view.")
    ctx = main_ctx()
    key = st.session_state["result_key"] or ""
    specs = ui_logic.available_downloads(False)
    for left, right in zip(specs[0::2], list(specs[1::2]) + [None]):
        c1, c2 = st.columns(2)
        with c1:
            download_button(left, ctx, key)
        with c2:
            if right is not None:
                download_button(right, ctx, key)
