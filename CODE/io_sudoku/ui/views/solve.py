"""Solve: the Run Allocation button, readiness, KPIs, self-test badge, stage timings."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.selftest import SelfTestReport, run_selftest
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui import nav
from io_sudoku.ui.nav import link
from io_sudoku.ui.views._common import allocate_button, heading, md_escape, readiness_block, stale_banner


@st.cache_resource(show_spinner=False)
def _selftest() -> SelfTestReport:
    return run_selftest()


def _kpi_boxes(result) -> None:
    """The summary boxes.  Each one is clickable and leads to the part of the tool it counts."""
    cards = ui_logic.kpi_cards(result)
    for column, (label, value) in zip(st.columns(len(cards)), cards):
        kind, target = ui_logic.KPI_LINKS.get(label, ("", ""))
        slug = "".join(ch for ch in label.lower() if ch.isalnum())
        with column:
            if kind == "anchor":
                st.markdown(theme.kpi_card_html(label, value, "Show the table", f"#{target}"), unsafe_allow_html=True)
            elif kind == "view":
                with st.container(key=f"kpicard_{slug}"):
                    st.markdown(theme.kpi_card_html(label, value, f"Open {target}"), unsafe_allow_html=True)
                    st.button(f"{label}: {value}. Open {target}", key=f"kpigo_{slug}", on_click=state.go_to,
                              args=(target, ui_logic.KPI_TABS.get(label)))
            else:
                st.markdown(theme.kpi_html([(label, value)]), unsafe_allow_html=True)


def render() -> None:
    s = st.session_state
    st.header("Run Allocation")
    if not s["mdb_bytes"]:
        st.info(f"Upload an MDB on the {link('Upload', 'Upload')} view, or load the sample data, first.")
        st.button("Try With Sample Data", key="sample_solve", on_click=state.on_sample)
    else:
        allocate_button("solve_main")
    if s["ui_error"]:
        state.alert("error", s["ui_error"], once=True)
    state.show_flash("Run Allocation")
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
    _kpi_boxes(result)
    if result.quarantined:
        st.warning(f"{len(result.quarantined):,} signals were set aside because they could not be placed safely. "
                   f"Open the {nav.link_to('TQ Board', 'TQ Board › Errors To Fix')} to fix them.")
    heading("Wired Spares Per Controller", "Every controller keeps the project's percentage of wired spares for each "
                                            "IO type (10% by default, rounded up). Short = how many are missing.",
            anchor=ui_logic.SPARES_ANCHOR)
    lines = [{"Controller": l.controller, "IO Type": l.io_type, "Field": l.field, "Required": l.quota, "Wired": l.wired,
              "Short": l.shortfall, "Status": "\u2713 Met" if l.shortfall <= 0 else f"\u2717 {l.shortfall} short"}
             for l in result.spare_lines]
    # tall enough for every row (up to 30), so no scroll bar sits on top of the numbers
    st.dataframe(lines, hide_index=True, width="stretch", height=min(38 + 35 * len(lines) + 3, 38 + 35 * 30),
                 column_config={"Status": st.column_config.TextColumn(width="small")})
    with st.expander("Assumptions Used In This Run"), st.container(height=320):
        st.caption("Every default the tool applied that a senior engineer should confirm. The same list is in the TQ "
                   "register and the summary report.")
        for a in result.assumptions:
            st.markdown(f"**{a.id}** — {md_escape(a.text)}  \n*Source: {md_escape(a.source)} Confirm with: {a.confirm_by}.*")
    with st.expander("Stage Timings"):
        st.dataframe([{"Stage": k, "Milliseconds": v} for k, v in result.stages_ms.items()], hide_index=True, width="stretch")
