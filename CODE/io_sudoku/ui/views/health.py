"""Health: audit ANY allocation workbook, and compare a human allocation with IO Sudoku's."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.healthcheck import audit_allocation, health_report_bytes, scorecard
from io_sudoku.ui import state, ui_logic
from io_sudoku.ui.views._viewer import file_viewer


def _run_audit() -> None:
    s = st.session_state
    uploaded = s.get("audit_uploader")
    if uploaded is None:
        state.flash("info", "Choose an allocation workbook first.", "health")
        return
    report = audit_allocation(uploaded.getvalue(), s["result"].cfg_used if s["result"] is not None else None)
    seconds = ((s["result"].stages_ms.get("total", 0.0) if s["result"] is not None else 0.0)) / 1000.0
    card = scorecard(report, s["result"], seconds) if (s["result"] is not None and report.rows) else None
    s["health"] = {"report": report, "card": card, "name": uploaded.name, "bytes": uploaded.getvalue()}   # kept: the
    # upload box forgets its file when you visit another page, the viewer below must not


def render() -> None:
    s = st.session_state
    st.header("Allocation Health Check")
    st.caption("Upload any IO allocation workbook, including one made by hand, and see which rules it breaks.")
    st.file_uploader("Allocation Workbook (.xlsx)", type=["xlsx"], key="audit_uploader")
    st.button("Run Health Check", key="audit_run", on_click=_run_audit, type="primary")
    state.show_flash("health")
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
    data = health_report_bytes(report, card)
    left, right = st.columns([3, 2], vertical_alignment="center")
    left.download_button("Download Health Report (.xlsx)", data=data, key="dl_health", on_click="ignore",
                         file_name="Allocation_Health_Report.xlsx",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if right.toggle("View Here", key="health_view_report", help="Open the health report in the page."):
        file_viewer(data, "Allocation_Health_Report.xlsx", "health_report")
    if st.toggle(f"View The Uploaded Workbook ({ui_logic.clip(health['name'], 40)})", key="health_view_upload"):
        data = health.get("bytes")
        if data is None and s.get("audit_uploader") is not None:      # an audit made before the bytes were kept
            data = s["audit_uploader"].getvalue()
        if data:
            file_viewer(data, health["name"], f"health_upload_{ui_logic.sha256_hex(data)[:8]}")
        else:
            st.info("Run the health check again to view the workbook.")
