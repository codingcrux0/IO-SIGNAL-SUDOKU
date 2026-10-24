"""IO Signal Sudoku - Streamlit entry point.   Run:  streamlit run app.py"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="IO Signal Sudoku", page_icon="\U0001F9E9", layout="wide", initial_sidebar_state="expanded")

from io_sudoku.ui import state, theme                                    # noqa: E402  (after set_page_config)
from io_sudoku.ui.errors import error_boundary                           # noqa: E402
from io_sudoku.ui.views import (downloads, drawings, grid, health, parts, preflight, revision, rules, simulator,  # noqa: E402
                                solve, tq, upload)

VIEW_MODULES = {"Upload": upload, "Preflight": preflight, "Solve": solve, "Grid": grid, "TQ Board": tq, "Health": health,
                "Drawings": drawings, "Parts": parts, "Revision": revision, "Simulator": simulator, "Rules": rules,
                "Files": downloads}


def main() -> None:
    state.init_state()
    theme.inject(st.session_state["lite"])
    with st.sidebar:
        st.markdown("### IO Signal Sudoku")
        st.radio("View", state.VIEWS, key="view", label_visibility="collapsed")
        st.toggle("Lite Mode", key="lite", help="Turns off animation and the gradient for slower computers.")
        if st.session_state["result"] is not None:
            from io_sudoku.ui import ui_logic
            status, _ = ui_logic.readiness_text(st.session_state["result"])
            st.markdown(theme.badge(status), unsafe_allow_html=True)
        st.divider()
        st.checkbox("I understand this clears everything", key="confirm_reset")
        st.button("Reset Session", on_click=state.reset_session, disabled=not st.session_state["confirm_reset"])
    view = st.session_state["view"]
    st.markdown('<a class="iosg-skip" href="#iosg-main">Skip to main content</a><span id="iosg-main"></span>'
                + ('' if view == "Upload" else '<h1 class="iosg-sr">IO Signal Sudoku</h1>'), unsafe_allow_html=True)
    state.show_flash()
    with error_boundary(view):
        VIEW_MODULES[view].render()
    state.sync_url()


main()
