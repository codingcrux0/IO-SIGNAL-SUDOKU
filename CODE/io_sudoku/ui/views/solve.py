"""Solve: the Run Allocation button, readiness, KPIs, self-test badge, stage timings."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.selftest import SelfTestReport, run_selftest
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.views._common import readiness_block, stale_banner


@st.cache_resource(show_spinner=False)
def _selftest() -> SelfTestReport:
    return run_selftest()


def render() -> None:
    s = st.session_state
    st.header("Run Allocation")
    if not s["mdb_bytes"]:
        st.info("Upload an MDB on the Upload view, or load the sample data, first.")
        st.button("Try With Sample Data", key="sample_solve", on_click=state.on_sample)
    else:
        st.button("Run Allocation", key="solve_main", on_click=state.on_solve, type="primary",
                  help="Solves on demand. Nothing recomputes until you press this.")
    if s["ui_error"]:
        st.error(s["ui_error"])
    report = _selftest()
    st.markdown(f'<span class="iosg-badge {"ready" if report.ok else "blocked"}" role="status">'
                f'Self-test {"passed" if report.ok else "FAILED"} ({report.ms:,.0f} ms)</span>', unsafe_allow_html=True)
    with st.expander("Self-Test Details"):
        st.dataframe([{"Check": n, "Result": "pass" if ok else "FAIL", "Detail": d} for n, ok, d in report.checks],
                     hide_index=True, width="stretch")
    result = s["result"]
    if result is None:
        st.info("No result yet. Press Run Allocation to see the numbers.")
        return
    stale_banner("solve")
    readiness_block(result)
    st.markdown(theme.kpi_html(ui_logic.kpi_cards(result)), unsafe_allow_html=True)
    if result.quarantined:
        st.warning(f"{len(result.quarantined):,} signals were set aside because they could not be placed safely. "
                   "Open the TQ Board to answer them.")
    st.subheader("Wired Spares Per Controller")
    st.dataframe([{"Controller": l.controller, "IO Type": l.io_type, "Field": l.field, "Required": l.quota,
                   "Wired": l.wired, "Short": l.shortfall} for l in result.spare_lines], hide_index=True, width="stretch")
    with st.expander("Assumptions Used In This Run"):
        for a in result.assumptions:
            st.markdown(f"**{a.id}** — {a.text}  \n*Source: {a.source}. Confirm with: {a.confirm_by}.*")
    with st.expander("Stage Timings"):
        st.dataframe([{"Stage": k, "Milliseconds": v} for k, v in result.stages_ms.items()], hide_index=True, width="stretch")
