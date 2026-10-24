"""Revision Simulator - the third tab of the Revision page: how much rework does a small client revision cause?

It makes a pretend revision of your file (a seeded, repeatable share of the tags deleted, renamed, added or moved
to another pair, core.simulate) and handles it two ways: starting again from scratch, and IO Sudoku's pinned
re-solve that keeps every unchanged tag in its slot.  It counts the tags each way moves and turns them into an
ESTIMATE of rework hours from the minutes per change you set.  The hours update as soon as you change the
minutes (no new run needed).  Nothing here changes your file or your allocation.
"""
from __future__ import annotations

import csv
import io

import pandas as pd
import streamlit as st

from io_sudoku.core.rulepack import pack_hash
from io_sudoku.core.simulate import ChurnResult, ReworkMinutes, make_revision, rework_hours, simulate_churn
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.nav import link
from io_sudoku.ui.views._common import heading, md_escape

SIM = state.SIM_TAB
SIZES = (1, 2, 5, 10, 15, 20)
NAIVE, OURS = "Starting Again", "IO Sudoku"
COLOURS = ["#d95926", "#3987e5"]                       # orange / blue: checked for colour-blind readers on dark
CHANGES = (("Moved", "per_moved_tag"), ("Renamed", "per_renamed_tag"), ("Added", "per_added_tag"),
           ("Deleted", "per_deleted_tag"))
EDIT_NAMES = {"deleted": "deleted", "renamed": "renamed", "added": "added", "pair_change": "moved to another pair"}
MINUTE_KEYS = {"per_moved_tag": "sim_moved", "per_renamed_tag": "sim_renamed", "per_added_tag": "sim_added",
               "per_deleted_tag": "sim_deleted"}


@st.cache_data(max_entries=32, show_spinner=False)
def _simulate(mdb_sha: str, pct: float, seed: int, pack_key: str, _mdb: bytes, _pack) -> ChurnResult:
    """One pretend revision, handled both ways (cached: the hours are worked out later from the minutes)."""
    return simulate_churn(_mdb, pct, seed, ReworkMinutes(), ui_logic.config_for_pack(_pack))


@st.cache_data(max_entries=8, show_spinner=False)
def _pretend_file(mdb_sha: str, pct: float, seed: int, _mdb: bytes) -> bytes:
    return make_revision(_mdb, pct, seed)


def _settings() -> tuple:
    s = st.session_state
    return s["mdb_sha"] or "", float(s.get("sim_pct", 5)), int(s.get("sim_seed", 1)), pack_hash(s["pack"])


def _minutes() -> ReworkMinutes:
    s, d = st.session_state, ReworkMinutes()
    return ReworkMinutes(**{field: float(s.get(key, getattr(d, field))) for field, key in MINUTE_KEYS.items()})


def _run() -> None:
    s = st.session_state
    sha, pct, seed, pack_key = _settings()
    s["sim"] = {"key": (sha, pct, seed, pack_key), "pct": pct, "seed": seed,
                "result": _simulate(sha, pct, seed, pack_key, s["mdb_bytes"], s["pack"])}


def _another() -> None:
    """A new seed (so a different pretend revision of the same size), then run it."""
    s = st.session_state
    s["sim_seed"] = (int(s.get("sim_seed", 1)) * 7919 + 13) % 10000
    _run()


def _run_sizes() -> None:
    s = st.session_state
    sha, _, seed, pack_key = _settings()
    s["sim_sweep"] = {"key": (sha, seed, pack_key), "seed": seed,
                      "rows": [(pct, _simulate(sha, float(pct), seed, pack_key, s["mdb_bytes"], s["pack"])) for pct in SIZES]}


def render() -> None:
    """The tab's content (the Revision page draws the header)."""
    s = st.session_state
    st.caption("Clients change their IO list after the first issue. This makes a pretend revision of your file and "
               "handles it two ways: starting the allocation again from scratch, and IO Sudoku keeping every unchanged "
               "tag in its slot. It counts the tags each way moves; the hours are an estimate from the minutes per "
               "change you set. Nothing here changes your file or your allocation.")
    state.show_flash(SIM)
    if not s["mdb_bytes"]:
        st.info(f"Upload an MDB on the {link('Upload', 'Upload')} view, or load the sample data, to simulate a revision.")
        return
    heading("Make A Pretend Revision", "The share of tags changed is split 30% deleted, 20% renamed, 30% added and "
                                       "20% moved to another pair of the same cable. The same seed always makes the "
                                       "same pretend revision, so a result can be shown again.")
    with st.container(border=True, key="sim_settings"):
        c1, c2, c3 = st.columns([3, 1.4, 1.4], vertical_alignment="bottom")
        c1.slider("Share Of Tags Changed (%)", 1, 20, key="sim_pct",
                  help="A typical client revision changes about 5% of the tags.")
        c2.number_input("Random Seed", min_value=0, max_value=9999, step=1, key="sim_seed",
                        help="Which tags are changed. The same seed always picks the same tags.")
        c3.button("\U0001F3B2 Another Revision", key="sim_another", on_click=_another, width="stretch",
                  help="Pick other tags to change (a new seed) and run it straight away.")
        with st.expander("Minutes Of Rework Per Change (edit to match your team)"):
            st.caption("How long an engineer spends on one change: drawings, termination lists and checks. The hours "
                       "below update as soon as you change these.")
            for col, (name, field) in zip(st.columns(4), CHANGES):
                col.number_input(f"Per {name} Tag", 0.0, 240.0, step=1.0, key=MINUTE_KEYS[field])
        st.button("Run Simulation", key="sim_run", on_click=_run, type="primary")
    sim = s["sim"]
    if not sim:
        st.info("No simulation yet. Press Run Simulation (it takes about a second).")
        return
    if sim.get("key") != _settings():
        st.warning("The share, the seed, the rules or the file changed after this simulation. Press Run Simulation to "
                   "see the new numbers.")
    _results(sim["result"], sim["pct"], sim["seed"])
    _sizes()


def _hours(result: ChurnResult, m: ReworkMinutes) -> tuple[float, float]:
    return rework_hours(result.naive, m), rework_hours(result.incremental, m)


def _results(result: ChurnResult, pct: float, seed: int) -> None:
    m = _minutes()
    edits = " · ".join(f"{n:,} {EDIT_NAMES.get(k, k)}" for k, n in result.edits.items())
    st.markdown(f"**The pretend revision** ({pct:g}% of the tags, seed {seed}): {md_escape(edits)}")
    if not any(result.edits.values()):
        st.info("No tag was changed: the file has too few field tags for this share. Raise the share and run it again.")
        return
    naive_h, ours_h = _hours(result, m)
    saved = round(naive_h - ours_h, 2)
    less = f" ({100 * saved / naive_h:.0f}% less)" if naive_h > 0 else ""
    moved_naive, moved_ours = result.naive.counts.get("Moved", 0), result.incremental.counts.get("Moved", 0)
    st.markdown(theme.kpi_html([
        (f"Tags Moved: {NAIVE}", f"{moved_naive:,} ({result.naive_moved_pct:g}%)"),
        (f"Tags Moved: {OURS}", f"{moved_ours:,} ({result.incremental_moved_pct:g}%)"),
        (f"Rework: {NAIVE}", f"{naive_h:,.1f} h"), (f"Rework: {OURS}", f"{ours_h:,.1f} h"),
        ("Estimated Hours Saved", f"{saved:,.1f} h{less}")]), unsafe_allow_html=True)
    if moved_ours < moved_naive:
        st.success(f"Keeping the unchanged tags in their slots avoids moving {moved_naive - moved_ours:,} tags: about "
                   f"{saved:,.1f} hours of rework saved on this revision.")

    heading("Where The Hours Go", "Each change of the revision costs the minutes you set. Starting again moves many "
                                  "tags that the client never touched; IO Sudoku moves only what really changed.")
    lines = []
    for name, field in CHANGES:
        minutes = getattr(m, field)
        a, b = result.naive.counts.get(name, 0), result.incremental.counts.get(name, 0)
        lines.append({"Change": name, "Minutes Each": minutes, f"Tags: {NAIVE}": a, f"Tags: {OURS}": b,
                      f"Hours: {NAIVE}": round(a * minutes / 60, 2), f"Hours: {OURS}": round(b * minutes / 60, 2)})
    st.dataframe(lines, hide_index=True, width="stretch", height=38 + 35 * len(lines) + 3)
    frame = pd.DataFrame({NAIVE: [x[f"Hours: {NAIVE}"] for x in lines], OURS: [x[f"Hours: {OURS}"] for x in lines]},
                         index=pd.Index([x["Change"] for x in lines], name="Change"))
    st.bar_chart(frame, horizontal=True, stack=False, color=COLOURS, height=240, x_label="Rework (hours)", y_label="")

    heading("Which Tags Moved", "A tag that moved to another slot needs new drawings and terminations. Pick a list to "
                                "see where each one went.")
    naive_moves = [c for c in result.naive.changes if c.category == "Moved"]
    our_moves = [c for c in result.incremental.changes if c.category == "Moved"]
    first, second = st.tabs([f"{NAIVE} ({len(naive_moves):,})", f"{OURS} ({len(our_moves):,})"])
    for tab, moves in ((first, naive_moves), (second, our_moves)):
        with tab:
            if not moves:
                st.success("No tag moved.")
                continue
            st.dataframe([{"Tag": c.tag, "From": _loc(c.a_loc), "To": _loc(c.b_loc), "Note": c.note or "-"} for c in moves],
                         hide_index=True, width="stretch", height=min(360, 38 + 35 * len(moves)))

    s = st.session_state
    left, right = st.columns(2)
    left.download_button("Download These Results (.csv)", data=_csv(lines, result, pct, seed, naive_h, ours_h),
                         file_name=f"Revision_Simulation_{pct:g}pct_seed{seed}.csv", mime="text/csv", key="sim_csv",
                         on_click="ignore", width="stretch")
    right.download_button("Download The Pretend Revision (.xlsx)", key="sim_mdb", on_click="ignore", width="stretch",
                          data=_pretend_file(s["mdb_sha"] or "", float(pct), int(seed), s["mdb_bytes"]),
                          file_name=f"Pretend_Revision_{pct:g}pct_seed{seed}.xlsx",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          help="The edited copy of your file. Use it as Rev B on the Compare With A New MDB tab to "
                               "see every change in detail.")


def _sizes() -> None:
    s = st.session_state
    heading("Try Several Sizes", f"Runs the same seed at {', '.join(f'{p}%' for p in SIZES)} of the tags, to show how "
                                 "the rework grows with the size of the revision each way.")
    st.button("Run For Every Size", key="sim_sizes", on_click=_run_sizes,
              help="About one second per size.")
    sweep = s["sim_sweep"]
    if not sweep:
        st.caption("Press Run For Every Size to compare small and large revisions.")
        return
    sha, _, seed, pack_key = _settings()
    if sweep.get("key") != (sha, seed, pack_key):
        st.warning("The seed, the rules or the file changed. Press Run For Every Size again to update this.")
    m = _minutes()
    rows = []
    for pct, result in sweep["rows"]:
        naive_h, ours_h = _hours(result, m)
        rows.append({"Share Changed (%)": pct, "Tags Changed": sum(result.edits.values()),
                     f"Moved: {NAIVE}": result.naive.counts.get("Moved", 0),
                     f"Moved: {OURS}": result.incremental.counts.get("Moved", 0),
                     f"Hours: {NAIVE}": naive_h, f"Hours: {OURS}": ours_h, "Hours Saved": round(naive_h - ours_h, 2)})
    frame = pd.DataFrame({NAIVE: [r[f"Hours: {NAIVE}"] for r in rows], OURS: [r[f"Hours: {OURS}"] for r in rows]},
                         index=pd.Index([r["Share Changed (%)"] for r in rows], name="Share of tags changed (%)"))
    st.line_chart(frame, color=COLOURS, height=260, x_label="Share of tags changed (%)", y_label="Rework (hours)")
    st.dataframe(rows, hide_index=True, width="stretch", height=38 + 35 * len(rows) + 3)


def _loc(loc) -> str:
    return "-" if not loc else f"{loc[0]} / {loc[1]} / {loc[2]} / ch {loc[3]}"


def _csv(lines: list[dict], result: ChurnResult, pct: float, seed: int, naive_h: float, ours_h: float) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Revision simulation", f"{pct:g}% of tags", f"seed {seed}"])
    w.writerow(["Pretend edits"] + [f"{EDIT_NAMES.get(k, k)}: {n}" for k, n in result.edits.items()])
    w.writerow([])
    w.writerow(list(lines[0].keys()))
    for line in lines:
        w.writerow(list(line.values()))
    w.writerow([])
    w.writerow(["Total hours", "", "", "", naive_h, ours_h])
    w.writerow(["Estimated hours saved", round(naive_h - ours_h, 2)])
    return out.getvalue().encode("utf-8")
