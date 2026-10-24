"""IO Signal Sudoku - Streamlit entry point.   Run:  streamlit run app.py"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="IO Signal Sudoku", page_icon="\U0001F9E9", layout="wide", initial_sidebar_state="expanded")

from io_sudoku.ui import nav, search, state, theme                          # noqa: E402  (after set_page_config)
from io_sudoku.ui.errors import error_boundary                           # noqa: E402
from io_sudoku.ui.views import (cabinets, downloads, edit, health, parts, preflight, revision, rules,  # noqa: E402
                                simulator, solve, tq, upload)

VIEW_MODULES = {"Upload": upload, "Edit File": edit, "Preflight": preflight, "Solve": solve, "Cabinet Layout": cabinets, "TQ Board": tq,
                "Health": health, "Parts": parts, "Revision": revision, "Simulator": simulator, "Rules": rules,
                "Files": downloads}


def main() -> None:
    state.init_state()
    theme.inject(st.session_state["lite"])
    no_file = not st.session_state["mdb_bytes"]
    if no_file and st.session_state["view"] in state.NEEDS_FILE:      # e.g. reached by keyboard or by a search
        st.session_state["view"] = "Upload"
        state.flash("info", "Upload a file (or load the sample data) first; then you can edit it on the Edit File page.")
    with st.sidebar:
        st.markdown("### IO Signal Sudoku")
        if no_file:                              # greyed out and unclickable until a file is uploaded
            st.markdown(theme.disabled_views_css([state.VIEWS.index(v) for v in state.NEEDS_FILE]), unsafe_allow_html=True)
        st.radio("View", state.VIEWS, key="view", label_visibility="collapsed")
        st.toggle("Lite Mode", key="lite", help="Turns off animation and the gradient for slower computers.")
        if st.session_state["result"] is not None:
            from io_sudoku.ui import ui_logic
            status, _ = ui_logic.readiness_text(st.session_state["result"])
            st.markdown(theme.badge(status), unsafe_allow_html=True)
        st.divider()
        st.checkbox("I understand this clears everything", key="confirm_reset")
        st.button("Reset Session", on_click=state.reset_session, disabled=not st.session_state["confirm_reset"])
        nav.render_targets()                     # hidden: what the links inside sentences press
    view = st.session_state["view"]
    st.markdown('<a class="iosg-skip" href="#iosg-main">Skip to main content</a><span id="iosg-main"></span>'
                + ('' if view == "Upload" else '<h1 class="iosg-sr">IO Signal Sudoku</h1>'), unsafe_allow_html=True)
    with error_boundary("Search"):
        search.render()
    state.show_flash()
    with error_boundary(view):
        VIEW_MODULES[view].render()
    target = st.session_state.get("scroll_to")
    if target:                                   # a search result asked to scroll to one of its headings
        st.session_state["scroll_to"] = None
        st.session_state["_scroll_n"] = st.session_state.get("_scroll_n", 0) + 1
        with st.sidebar:                         # an invisible 1-pixel frame, out of the page's way
            st.iframe(search.scroll_page(target, st.session_state["_scroll_n"]), height=1)
    state.sync_url()


main()
