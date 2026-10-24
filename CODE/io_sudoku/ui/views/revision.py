"""Revision: Rev A + a new MDB -> Added / Deleted / Moved / Renamed, with positions kept; the Revision History
of the session (every allocation is stored, named, summarised and comparable); and the Revision Simulator
(a pretend client revision: how much rework starting again would cost, versus keeping positions)."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.allocio import looks_like_allocation, read_allocation
from io_sudoku.core.revision import solve_incremental
from io_sudoku.core.tqlife import diff_tqs
from io_sudoku.core.workspace import import_workspace
from io_sudoku.core.overrides import overrides_to_json
from io_sudoku.ui import history, impact, state, theme, ui_logic
from io_sudoku.ui.nav import link
from io_sudoku.ui.views._common import ask_first, file_card, heading, md_escape, stale_banner

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
                state.flash("error", why, COMPARE_NEW)
                return
            rows_a = ws.rows
        else:
            rows_a = read_allocation(up_a.getvalue())
    if not rows_a or not looks_like_allocation(rows_a):
        state.flash("error", "Rev A could not be read as an IO Allocation. Pick the 76-column workbook, a workspace, or solve first.",
                    COMPARE_NEW)
        return
    if up_b is None:
        state.flash("error", "Upload the new MDB (Rev B) first.", COMPARE_NEW)
        return
    label = (s.get("rev_b_label") or "B").strip() or "B"
    result_b, report = solve_incremental(up_b.getvalue(), rows_a, ui_logic.config_for_pack(s["pack"]), label,
                                         overrides=s["overrides"], pins=s["pins"])
    s.update(rev_b_result=result_b, impact=report, rev_a_rows=rows_a, rev_b_bytes=up_b.getvalue(),
             rev_key=ui_logic.sha256_hex(up_b.getvalue() + str(len(rows_a)).encode() + label.encode()
                                         + overrides_to_json(s["overrides"]).encode()))
    s["rev_a_tqs"] = list(s["result"].tqs) if (source == SOURCES[0] and s["result"] is not None) else None
    state.remember(result_b, f"Revision compare (Rev {label})", getattr(up_b, "name", "Rev B MDB"),
                   ui_logic.sha256_hex(up_b.getvalue()), s["rev_key"])
    state.flash("success", f"Revision compared and saved in the {link('Revision History', 'Revision', 'Revision History')}. "
                           "Scroll down for the changes.", COMPARE_NEW)


COMPARE_NEW, HISTORY, SIMULATOR = "Compare With A New MDB", "Revision History", state.SIM_TAB


def render() -> None:
    from io_sudoku.ui.views import simulator
    st.header("Revision Impact")
    stale_banner("rev")
    new_tab, history_tab, sim_tab = st.tabs([COMPARE_NEW, HISTORY, SIMULATOR], key=state.REV_TAB_KEY, on_change="rerun")
    with new_tab:
        _compare_new()
    with history_tab:
        _history()
    with sim_tab:
        simulator.render()


def _compare_new() -> None:
    s = st.session_state
    state.show_flash(COMPARE_NEW)
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
    _categories(report, s["rev_a_rows"], result_b)
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
    st.subheader("Downloads For This Revision", help="The impact report opens right here in the page, or download it "
                                                     "as a web page (.html) and open it in any browser to read or print.")
    html = impact.impact_html(report, s["rev_a_rows"], result_b.rows,
                              f"Revision Impact Report (Rev A \u2192 Rev {s.get('rev_b_label') or 'B'})")
    left, right = st.columns([3, 2], vertical_alignment="center")
    left.download_button("Download Impact Report (.html)", data=html.encode("utf-8"), mime="text/html", on_click="ignore",
                         file_name=f"Impact_Report_Rev{s.get('rev_b_label') or 'B'}.html", key="rev_impact_html",
                         help="A web page: open it in any browser to read or print it.")
    if right.toggle("View In The Browser", key="rev_impact_view", help="Show the whole impact report in the page."):
        st.iframe(html, height=720)
    for key in ("impact", "redline", "allocation"):
        file_card(next(d for d in ui_logic.DOWNLOADS if d.key == key), ctx, s["rev_key"], "rev")


CATEGORIES = ("Added", "Deleted", "Moved", "Renamed")


def _open_category(name: str) -> None:
    st.session_state["rev_cat"] = name
    st.session_state["scroll_to"] = "Changes In Detail"


def _categories(report, rows_a, result_b) -> None:
    """The four counts, each with a View In Detail button, then one tab per category: pick a signal to see
    exactly what changed in it, which rules decided its new place, and open it on Rule Check."""
    s = st.session_state
    cols = st.columns(5)
    for col, name in zip(cols, CATEGORIES):
        with col:
            st.metric(name, f"{report.counts.get(name, 0):,}")
            st.button("View In Detail", key=f"rev_detail_{name}", on_click=_open_category, args=(name,),
                      help=f"Show every {name.lower()} signal and what changed in it.")
    cols[4].metric("Unchanged", f"{report.unchanged:,}")
    for warning in report.warnings:
        st.warning(warning)
    st.subheader("Changes In Detail", help="Pick a row to see every column that changed in that CHARM signal, the "
                                           "rules and decisions behind its new place, and open it on Rule Check.")
    if s.get("rev_cat") not in CATEGORIES:
        s["rev_cat"] = CATEGORIES[0]
    tabs = st.tabs(list(CATEGORIES), key="rev_cat", on_change="rerun")
    a_index, b_index = impact.by_location(rows_a), impact.by_location(result_b.rows)
    for tab, name in zip(tabs, CATEGORIES):
        with tab:
            items = [c for c in report.changes if c.category == name]
            if not items:
                st.info(f"No tags were {name.lower()}.")
                continue
            widget = f"rev_pick_{name}_{(s.get('rev_key') or '')[:8]}"
            event = st.dataframe([{"Tag": c.tag, "Old Tag": c.old_tag or "-", "From": _loc(c.a_loc), "To": _loc(c.b_loc),
                                   "Note": c.note or "-"} for c in items], hide_index=True, width="stretch", key=widget,
                                 height=min(400, 38 + 35 * len(items)), on_select="rerun", selection_mode="single-row")
            rows = event.selection.rows if event is not None else []
            if rows:
                _change_panel(items[rows[0]], rows_a, result_b, a_index, b_index)
            else:
                st.caption("Pick a row (tick its box) to see the change in detail.")


def _open_in_rule_check(sid: str) -> None:
    from io_sudoku.ui.views import rulecheck
    rulecheck.pick(sid)
    st.session_state["rc_source"] = rulecheck.REV_B


def _change_panel(change, rows_a, result_b, a_index, b_index) -> None:
    from io_sudoku.core import cellcheck
    detail = impact.change_detail(change, rows_a, result_b.rows, a_index, b_index)
    with st.container(border=True, key="rev_change_panel"):
        st.markdown(f"**{md_escape(change.category)}: {md_escape(change.tag)}**"
                    + (f" (was {md_escape(change.old_tag)})" if change.old_tag else "")
                    + f"  \n<small>{md_escape(_loc(change.a_loc))} \u2192 {md_escape(_loc(change.b_loc))}</small>",
                    unsafe_allow_html=True)
        what, why = st.columns([3, 2])
        with what:
            st.markdown("**What changed in this signal**")
            if detail.diffs:
                st.dataframe([{"Column": c, "Rev A": a, "Rev B": b} for c, a, b in detail.diffs], hide_index=True,
                             width="stretch", height=min(330, 38 + 35 * len(detail.diffs)))
            else:
                st.caption("Every column is the same.")
        with why:
            st.markdown("**Rules and decisions**")
            if detail.row_b is not None:
                checks = cellcheck.check_cell(result_b, detail.row_b, overrides=st.session_state["overrides"],
                                              pins=st.session_state["pins"])
                n = cellcheck.summary(checks)
                st.caption(f"\u2713 {n['pass']} rules met \u00b7 \u2717 {n['fail']} broken \u00b7 \u25b2 {n['warn']} to check")
                shown = [c for c in checks if c.status in ("fail", "warn") or c.rule in ("Decision", "Project rule", "Answer", "Pin")]
                st.markdown("\n".join(f"- {md_escape(c.line)}" for c in shown[:10]) or "No decisions were recorded.")
                sid = cellcheck.slot_id(detail.row_b)
                if sid:
                    st.button("Open In Rule Check", key="rev_to_rulecheck", on_click=_open_in_rule_check, args=(sid,),
                              help="See every rule that applies to this signal in Rev B, with its signal path.")
            else:
                st.caption("This signal is not in Rev B, so no rule applies to it any more. Its slot became free "
                           "(see Spare Conversions).")


# ------------------------------------------------------------------ revision history
def _history() -> None:
    s = st.session_state
    past: list[history.Snapshot] = s["history"]
    st.caption("Every allocation of this session is saved here automatically: the first one is the Original, then "
               "Revision 1, 2 ... (also every Rev B compared on the other tab). Pick one to see its summary, rename it, "
               "or compare several. The history lasts for this browser session.")
    if not past:
        st.info("Nothing saved yet. Run an allocation, and it appears here as the Original.")
        return
    by_id = {snap.id: snap for snap in past}
    ids = [snap.id for snap in past]
    if s.get("hist_pick") not in ids:
        s["hist_pick"] = ids[-1]
    heading("Saved Revisions", "Undo Last Revision goes back to the revision before the newest one: its file, answers, "
                               "pins, rules and sign-offs come back and are allocated again. Delete removes revisions "
                               "from this list only; the allocation on screen stays as it is. Both ask first.")
    pick = st.selectbox(f"Saved Revisions ({len(past):,})", ids, key="hist_pick", format_func=lambda i: by_id[i].label)
    _summary(by_id[pick])
    _manage(past, by_id)
    st.subheader("Compare Revisions")
    if len(past) < 2:
        st.info("Run the allocation again after a change (an edit, an answer, a rule) to have two revisions to compare.")
        return
    if "hist_compare" in s:                          # a deleted revision must not stay selected
        s["hist_compare"] = [i for i in s["hist_compare"] if i in by_id]
        extra = {}
    else:
        extra = {"default": ids[-2:]}
    chosen = st.multiselect("Revisions To Compare (two or more, in the order you pick them)", ids,
                            key="hist_compare", format_func=lambda i: by_id[i].name, **extra)
    mode = st.radio("Compare", ("Each with the one before it", "Each with the first one picked"), horizontal=True,
                    key="hist_mode")
    snaps = [by_id[i] for i in chosen if i in by_id]
    couples = history.pairs(snaps, "first" if mode.endswith("first one picked") else "previous")
    if not couples:
        st.caption("Pick at least two revisions.")
        return
    reports = [(a, b, ui_logic.compare_snapshots(a.id, a.output_sha, b.id, b.output_sha, a, b)) for a, b in couples]
    st.dataframe([history.summary_row(a, b, r) for a, b, r in reports], hide_index=True, width="stretch",
                 height=min(300, 38 + 35 * len(reports)))
    names = [f"{a.name} \u2192 {b.name}" for a, b, _ in reports]
    if s.get("hist_detail", 0) >= len(reports):
        s["hist_detail"] = 0
    which = st.selectbox("Show The Changes Of", range(len(reports)), format_func=lambda i: names[i], key="hist_detail")
    a, b, report = reports[min(which, len(reports) - 1)]
    changes = [{"Change": c.category, "Tag": c.tag, "Old Tag": c.old_tag or "-", "From": _loc(c.a_loc), "To": _loc(c.b_loc),
                "Note": c.note or "-"} for c in report.changes]
    if changes:
        st.dataframe(changes, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(changes)))
    else:
        st.success(f"Nothing changed between {a.name} and {b.name}: every tag is in the same slot.")


def _summary(snap: history.Snapshot) -> None:
    with st.container(border=True):
        st.markdown(theme.badge(snap.status), unsafe_allow_html=True)
        k = snap.kpis
        cards = [("Field Signals", f"{k.get('field', 0):,}"), ("Wired Spares", f"{k.get('wired_spare', 0):,}"),
                 ("Cabinets Used", f"{k.get('cabinets_used', 0):,}"), ("Cabinet Alarms", f"{k.get('cabinet_alarm', 0):,}"),
                 ("Errors / Warnings", f"{snap.tq_counts.get('error', 0):,} / {snap.tq_counts.get('warning', 0):,}"),
                 ("Set Aside", f"{k.get('quarantined', 0):,}")]
        st.markdown(theme.kpi_html(cards), unsafe_allow_html=True)
        st.markdown(f"**{md_escape(snap.name)}** · {md_escape(snap.source)} · file {md_escape(snap.file_name)} · saved at {snap.created}  \n"
                    f"Input fingerprint `{snap.input_sha[:12] or '-'}` · output fingerprint `{snap.output_sha[:12] or '-'}`")
        if snap.reasons:
            st.markdown("\n".join(f"- {md_escape(r)}" for r in snap.reasons))
        a, b = st.columns([3, 1], vertical_alignment="bottom")
        a.text_input("Rename This Revision", value=snap.name, key=f"hist_name_{snap.id}", max_chars=40)
        b.button("Rename", key=f"hist_rename_{snap.id}", on_click=_rename, args=(snap.id,))


def _manage(past: list, by_id: dict) -> None:
    """Undo the newest revision, or delete chosen ones - each asks for a confirmation first."""
    s = st.session_state
    newest = past[-1]
    with st.container(border=True, key="rev_manage"):
        st.markdown("**Undo Or Delete Revisions**")
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            earlier = next((x for x in reversed(past[:-1]) if x.solve_key in s["inputs_by_key"]), None)
            ask_first("undo_revision", "\u21b6 Undo Last Revision",
                      f"Undo {newest.name}? It is removed, and you go back to {earlier.name if earlier else 'the one before'}: "
                      "its file, answers, pins, rules and sign-offs come back and are allocated again.",
                      state.undo_last_revision, yes="Yes, undo it", disabled=not state.can_undo_revision(),
                      help="Go back to the revision before the newest one." if state.can_undo_revision()
                      else "There is no earlier allocation to go back to.")
        if "hist_delete" in s:
            s["hist_delete"] = [i for i in s["hist_delete"] if i in by_id]
        chosen = st.multiselect("Revisions To Delete", [x.id for x in past], key="hist_delete",
                                format_func=lambda i: by_id[i].name, placeholder="Pick one or more revisions")
        names = ", ".join(by_id[i].name for i in chosen)
        ask_first("delete_revisions", "\U0001F5D1 Delete Selected Revisions",
                  f"Delete {len(chosen):,} revision(s): {names}? This cannot be undone.", state.delete_revisions,
                  args=(list(chosen),), yes="Yes, delete them", disabled=not chosen,
                  help="Removes the picked revisions from the history. The allocation on screen stays as it is.")


def _rename(snap_id: int) -> None:
    s = st.session_state
    name = (s.get(f"hist_name_{snap_id}") or "").strip()
    if not name:
        state.flash("error", "A revision needs a name.", "Saved Revisions")
        return
    if any(x.name == name and x.id != snap_id for x in s["history"]):
        state.flash("error", f"Another revision is already called “{name}”.", "Saved Revisions")
        return
    for snap in s["history"]:
        if snap.id == snap_id:
            snap.name = name
    state.flash("success", f"Renamed to “{name}”.", "Saved Revisions")
