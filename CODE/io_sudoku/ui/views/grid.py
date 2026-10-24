"""Grid: the 384-slot map of one cabinet, with a 'why is it here?' panel."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.trace import explain
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.views._common import cabinet_picker, result_or_empty


def render() -> None:
    st.header("Cabinet Grid")
    result = result_or_empty("the cabinet grid", "grid")
    if result is None:
        return
    _grid_fragment()


@st.fragment
def _grid_fragment() -> None:
    """Re-runs alone when you pick a cabinet, so the rest of the page never flickers."""
    s = st.session_state
    result = s["result"]
    if result is None:
        return
    cabinet = cabinet_picker(result.rows, "grid")
    if cabinet is None:
        return
    state.sync_url()
    st.markdown(theme.LEGEND_HTML, unsafe_allow_html=True)
    st.html(ui_logic.grid_html(s["result_key"] or "", cabinet, result.rows))
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
        st.markdown("\n".join(f"{n}. {line}" for n, line in enumerate(lines, start=1)))
    else:
        st.info(f"No decisions were recorded for “{query}”. Check the spelling, or try the cable number.")
