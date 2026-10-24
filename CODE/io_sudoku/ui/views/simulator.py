"""Simulator: how much rework does a small revision cause - naive re-allocation vs pinned."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.simulate import ReworkMinutes, simulate_churn
from io_sudoku.ui import state, ui_logic


def _run() -> None:
    s = st.session_state
    if not s["mdb_bytes"]:
        state.flash("error", "Upload an MDB or load the sample data first.", "simulator")
        return
    minutes = ReworkMinutes(per_moved_tag=float(s["sim_moved"]), per_renamed_tag=float(s["sim_renamed"]),
                            per_added_tag=float(s["sim_added"]), per_deleted_tag=float(s["sim_deleted"]))
    s["sim"] = simulate_churn(s["mdb_bytes"], float(s["sim_pct"]), int(s["sim_seed"]), minutes,
                              ui_logic.config_for_pack(s["pack"]))


def render() -> None:
    s = st.session_state
    st.header("Revision Simulator")
    state.show_flash("simulator")
    st.caption("Makes a pretend revision of your file and compares two ways of handling it. The hours are an estimate.")
    c1, c2 = st.columns(2)
    c1.slider("Share Of Tags Changed (%)", 0, 20, 5, key="sim_pct")
    c2.number_input("Random Seed", min_value=0, max_value=9999, value=1, step=1, key="sim_seed")
    with st.expander("Minutes Of Rework Per Change (edit to match your team)"):
        d = ReworkMinutes()
        a, b, c, e = st.columns(4)
        a.number_input("Per Moved Tag", 0.0, 240.0, d.per_moved_tag, key="sim_moved")
        b.number_input("Per Renamed Tag", 0.0, 240.0, d.per_renamed_tag, key="sim_renamed")
        c.number_input("Per Added Tag", 0.0, 240.0, d.per_added_tag, key="sim_added")
        e.number_input("Per Deleted Tag", 0.0, 240.0, d.per_deleted_tag, key="sim_deleted")
    st.button("Run Simulation", key="sim_run", on_click=_run, type="primary")
    sim = s["sim"]
    if sim is None:
        st.info("No simulation yet. Press Run Simulation.")
        return
    st.markdown("**Pretend edits made:** " + ", ".join(f"{k} {v}" for k, v in sim.edits.items()))
    st.dataframe([
        {"Approach": "Start again from scratch", "Tags Moved (%)": sim.naive_moved_pct, "Estimated Rework (hours)": sim.hours_naive},
        {"Approach": "IO Sudoku (keep positions)", "Tags Moved (%)": sim.incremental_moved_pct,
         "Estimated Rework (hours)": sim.hours_incremental}], hide_index=True, width="stretch")
    st.metric("Estimated Hours Saved", f"{sim.hours_saved:,.1f}")
