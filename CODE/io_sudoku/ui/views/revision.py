"""Revision: Rev A + a new MDB -> Added / Deleted / Moved / Renamed, with positions kept."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.allocio import looks_like_allocation, read_allocation
from io_sudoku.core.revision import solve_incremental
from io_sudoku.core.tqlife import diff_tqs
from io_sudoku.core.workspace import import_workspace
from io_sudoku.core.overrides import overrides_to_json
from io_sudoku.ui import state, ui_logic
from io_sudoku.ui.views._common import download_button, stale_banner

SOURCES = ("Current Result", "Allocation Workbook (.xlsx)", "Workspace (.zip)")


def _loc(loc) -> str:
    return "-" if not loc else f"{loc[0]} / {loc[1]} / {loc[2]} / ch {loc[3]}"


def _run_compare() -> None:
    s = st.session_state
    source, up_a, up_b = s.get("rev_a_source"), s.get("reva_uploader"), s.get("revb_uploader")
    rows_a = None
    if source == SOURCES[0]:
        rows_a = s["result"].rows if s["result"] is not None else None
    elif up_a is not None:
        if source == SOURCES[2]:
            ws, why = import_workspace(up_a.getvalue())
            if ws is None:
                state.flash("error", why)
                return
            rows_a = ws.rows
        else:
            rows_a = read_allocation(up_a.getvalue())
    if not rows_a or not looks_like_allocation(rows_a):
        state.flash("error", "Rev A could not be read as an IO Allocation. Pick the 76-column workbook, a workspace, or solve first.")
        return
    if up_b is None:
        state.flash("error", "Upload the new MDB (Rev B) first.")
        return
    label = (s.get("rev_b_label") or "B").strip() or "B"
    result_b, report = solve_incremental(up_b.getvalue(), rows_a, ui_logic.config_for_pack(s["pack"]), label,
                                         overrides=s["overrides"], pins=s["pins"])
    s.update(rev_b_result=result_b, impact=report, rev_a_rows=rows_a, rev_b_bytes=up_b.getvalue(),
             rev_key=ui_logic.sha256_hex(up_b.getvalue() + str(len(rows_a)).encode() + label.encode()
                                         + overrides_to_json(s["overrides"]).encode()))
    s["rev_a_tqs"] = list(s["result"].tqs) if (source == SOURCES[0] and s["result"] is not None) else None
    state.flash("success", "Revision compared. Scroll down for the changes.")


def render() -> None:
    s = st.session_state
    st.header("Revision Impact")
    stale_banner("rev")
    st.radio("Rev A Comes From", SOURCES, key="rev_a_source", horizontal=True)
    if s.get("rev_a_source") != SOURCES[0]:
        st.file_uploader("Rev A File", type=["xlsx", "zip"], key="reva_uploader")
    elif s["result"] is None:
        st.info("There is no current result yet. Run an allocation first, or choose another Rev A source.")
    st.file_uploader("Rev B MDB (.xlsx or .csv)", type=["xlsx", "xlsm", "csv"], key="revb_uploader")
    st.text_input("Rev B Label", value="B", key="rev_b_label", max_chars=8, autocomplete="off")
    st.button("Compare Revisions", key="rev_compare", on_click=_run_compare, type="primary")
    report, result_b = s["impact"], s["rev_b_result"]
    if report is None or result_b is None:
        st.info("No comparison yet. Choose Rev A and Rev B, then press Compare Revisions.")
        return
    mode = "Pinned: surviving cables stay where Rev A had them." if report.mode == "pinned" else \
        "Compare only: Rev A could not be mapped to cabinets, so positions were not pinned."
    (st.success if report.mode == "pinned" else st.warning)(mode)
    cols = st.columns(5)
    for col, name in zip(cols, ("Added", "Deleted", "Moved", "Renamed")):
        col.metric(name, f"{report.counts.get(name, 0):,}")
    cols[4].metric("Unchanged", f"{report.unchanged:,}")
    for warning in report.warnings:
        st.warning(warning)
    tabs = st.tabs(["Added", "Deleted", "Moved", "Renamed"])
    for tab, name in zip(tabs, ("Added", "Deleted", "Moved", "Renamed")):
        with tab:
            items = [c for c in report.changes if c.category == name]
            if items:
                st.dataframe([{"Tag": c.tag, "Old Tag": c.old_tag or "-", "From": _loc(c.a_loc), "To": _loc(c.b_loc),
                               "Note": c.note or "-"} for c in items], hide_index=True, width="stretch")
            else:
                st.info(f"No tags were {name.lower()}.")
    with st.expander("Hardware Changes And Spare Conversions"):
        st.dataframe([{"Tag": c.tag, "Note": c.note} for c in report.hardware_changes], hide_index=True, width="stretch")
        st.dataframe([{"Deleted Tag": c.tag, "Slot": _loc(c.a_loc), "Note": c.note} for c in report.conversions],
                     hide_index=True, width="stretch")
    previous = s.get("rev_a_tqs")
    if previous is not None:
        diff = diff_tqs(previous, result_b.tqs)
        st.subheader("Question Lifecycle")
        a, b, c = st.columns(3)
        a.metric("Still Open", f"{len(diff.still_open):,}")
        b.metric("New", f"{len(diff.new):,}")
        c.metric("Resolved", f"{len(diff.resolved):,}")
    ctx = {"result": result_b, "mdb_bytes": s["rev_b_bytes"], "pack": s["pack"], "overrides": s["overrides"], "pins": s["pins"],
           "rev_label": (s.get("rev_b_label") or "B"), "template_bytes": s["template_bytes"], "impact": report,
           "rev_a_rows": s["rev_a_rows"]}
    st.subheader("Downloads For This Revision")
    for key in ("impact", "redline", "allocation"):
        download_button(next(d for d in ui_logic.DOWNLOADS if d.key == key), ctx, s["rev_key"], "rev")
