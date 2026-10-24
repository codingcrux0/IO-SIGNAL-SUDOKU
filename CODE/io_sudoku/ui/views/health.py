"""Health: audit ANY allocation workbook, and compare a human allocation with IO Sudoku's."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.healthcheck import audit_allocation, health_report_bytes, scorecard
from io_sudoku.ui import ui_logic


def _run_audit() -> None:
    s = st.session_state
    uploaded = s.get("audit_uploader")
    if uploaded is None:
        s["health"] = None
        return
    report = audit_allocation(uploaded.getvalue(), s["result"].cfg_used if s["result"] is not None else None)
    seconds = ((s["result"].stages_ms.get("total", 0.0) if s["result"] is not None else 0.0)) / 1000.0
    card = scorecard(report, s["result"], seconds) if (s["result"] is not None and report.rows) else None
    s["health"] = {"report": report, "card": card, "name": uploaded.name}


def render() -> None:
    s = st.session_state
    st.header("Allocation Health Check")
    st.caption("Upload any IO allocation workbook, including one made by hand, and see which rules it breaks.")
    st.file_uploader("Allocation Workbook (.xlsx)", type=["xlsx"], key="audit_uploader")
    st.button("Run Health Check", key="audit_run", on_click=_run_audit, type="primary")
    health = s["health"]
    if not health:
        st.info("No audit yet. Choose a workbook and press Run Health Check.")
        return
    report, card = health["report"], health["card"]
    for note in report.notes:
        st.warning(note)
    if not report.rows:
        return
    a, b, c = st.columns(3)
    a.metric("Health Score", f"{report.score}/100")
    b.metric("Rows", f"{report.rows:,}")
    c.metric("Rule Violations", f"{len(report.violations):,}")
    st.progress(report.score / 100, text="Health")
    if report.by_rule:
        st.subheader("Rules Broken")
        st.dataframe([{"Rule": k, "Count": v} for k, v in report.by_rule.items()], hide_index=True, width="stretch")
    else:
        st.success("No rule is broken in this allocation.")
    st.subheader("Wired Spares")
    st.dataframe(report.spare_table, hide_index=True, width="stretch")
    st.subheader("Future Space")
    st.dataframe(report.future_space, hide_index=True, width="stretch")
    if report.violations:
        with st.expander("Every Violation"):
            st.dataframe([{"Rule": v.rule, "Severity": v.severity, "Where": ui_logic.clip(v.ref), "Message": v.message}
                          for v in report.violations], hide_index=True, width="stretch")
    if card:
        st.subheader("Human Allocation vs IO Sudoku")
        st.dataframe(card, hide_index=True, width="stretch")
    elif s["result"] is None:
        st.caption("Run an allocation too, and a side-by-side scorecard appears here.")
    st.download_button("Download Health Report (.xlsx)", data=health_report_bytes(report, card), key="dl_health",
                       file_name="Allocation_Health_Report.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
