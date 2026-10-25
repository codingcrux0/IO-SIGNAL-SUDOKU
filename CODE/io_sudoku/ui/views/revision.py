"""Revision: Rev A + a new MDB -> Added / Deleted / Moved / Renamed, with positions kept; Check Allocation First (a
pop-up preview of Rev B next to the allocation you have now - better or worse, and the rework hours - before you
decide to save it); the Revision Library (every saved revision, opened by its name, with all its data); the
Revision History of the session (every allocation is stored, named, summarised and comparable); and the Revision
Simulator (a pretend client revision: how much rework starting again would cost, versus keeping positions)."""
from __future__ import annotations

import time

import streamlit as st

from io_sudoku.core import helpcontext, readiness as readiness_mod
from io_sudoku.core.allocio import allocation_bytes, looks_like_allocation, read_allocation
from io_sudoku.core.pipeline import solve
from io_sudoku.core.revision import compare, solve_incremental
from io_sudoku.core.rulepack import pack_hash
from io_sudoku.core.tqlife import diff_tqs
from io_sudoku.core.workspace import import_workspace
from io_sudoku.core.overrides import overrides_to_json
from io_sudoku.ui import history, impact, revlibrary, state, theme, ui_logic
from io_sudoku.ui.nav import link, link_to
from io_sudoku.ui.views import assistant
from io_sudoku.ui.views._common import ask_first, file_card, heading, md_escape, stale_banner

SOURCES = ("Current Result", "Allocation Workbook (.xlsx)", "Workspace (.zip)", "A Saved Revision (Revision History)")
B_SOURCES = ("Upload A New MDB", "A Saved File Revision")


def _loc(loc) -> str:
    return "-" if not loc else f"{loc[0]} / {loc[1]} / {loc[2]} / ch {loc[3]}"


def _read_inputs():
    """(rows of Rev A, Rev B bytes, Rev B file name, label), or None after saying what is missing."""
    s = st.session_state
    source, up_a, up_b = s.get("rev_a_source"), s.get("reva_uploader"), s.get("revb_uploader")
    rows_a = None
    if source == SOURCES[0]:
        rows_a = s["result"].rows if s["result"] is not None else None
    elif source == SOURCES[3]:
        snap = next((x for x in s["history"] if x.id == s.get("rev_a_snap")), None)
        rows_a = snap.rows() if snap is not None else None
    elif up_a is not None:
        if source == SOURCES[2]:
            ws, why = import_workspace(up_a.getvalue())
            if ws is None:
                state.flash("error", why, COMPARE_NEW)
                return None
            rows_a = ws.rows
        else:
            rows_a = read_allocation(up_a.getvalue())
    if not rows_a or not looks_like_allocation(rows_a):
        state.flash("error", "Rev A could not be read as an IO Allocation. Pick the 76-column workbook, a workspace, or solve first.",
                    COMPARE_NEW)
        return None
    label = (s.get("rev_b_label") or "B").strip() or "B"
    if s.get("rev_b_source") == B_SOURCES[1]:
        rev = next((r for r in s["file_revs"] if r.id == s.get("rev_b_file")), None)
        data = s["blobs"].get(rev.sha) if rev is not None else None
        if data is None:
            state.flash("error", "Pick the saved file to use as Rev B first.", COMPARE_NEW)
            return None
        return rows_a, data, rev.file_name, label
    if up_b is None:
        state.flash("error", "Upload the new MDB (Rev B) first.", COMPARE_NEW)
        return None
    return rows_a, up_b.getvalue(), getattr(up_b, "name", "Rev B MDB"), label


def _solve_b(rows_a, data_b: bytes, label: str):
    s = st.session_state
    return solve_incremental(data_b, rows_a, ui_logic.config_for_pack(s["pack"]), label, overrides=s["overrides"],
                             pins=s["pins"])


def _adopt(rows_a, data_b: bytes, name_b: str, label: str, result_b, report) -> None:
    """Rev B becomes the compared revision shown below (and is saved in the Revision History)."""
    s = st.session_state
    s.update(rev_b_result=result_b, impact=report, rev_a_rows=rows_a, rev_b_bytes=data_b,
             rev_key=ui_logic.sha256_hex(data_b + str(len(rows_a)).encode() + label.encode()
                                         + overrides_to_json(s["overrides"]).encode()))
    s["rev_a_tqs"] = list(s["result"].tqs) if (s.get("rev_a_source") == SOURCES[0] and s["result"] is not None) else None
    state.remember(result_b, f"Revision compare (Rev {label})", name_b, ui_logic.sha256_hex(data_b), s["rev_key"])
    state.save_file_rev("revision", f"compared as Rev {label}", data=data_b, file_name=name_b)


def _entry(rows_a, data_b: bytes, name_b: str, label: str, result_b, report, name: str = "") -> revlibrary.Entry:
    """Everything about this revision, for the preview and the Revision Library.  Also allocates Rev B again from
    scratch (nothing is kept from it) only to estimate how much rework keeping positions saves."""
    from io_sudoku.ui.views.simulator import _minutes
    s = st.session_state
    current = s.get("rev_a_source") == SOURCES[0] and s["result"] is not None
    try:
        fresh = solve(data_b, ui_logic.config_for_pack(s["pack"]), label, overrides=s["overrides"], pins=s["pins"])
        fresh_report = compare(rows_a, fresh.rows)
    except Exception:  # noqa: BLE001 - the check still works without the from-scratch estimate
        fresh_report = None
    a_result = s["result"] if current else None
    inputs = {"Rev A From": s.get("rev_a_source") or "-", "Rev A Rows": f"{len(rows_a):,}", "Rev B File": name_b,
              "Rev B Fingerprint": ui_logic.sha256_hex(data_b)[:12], "Rev B Label": label,
              "Answers Used": f"{len(s['overrides']):,}", "Pins Used": f"{len(s['pins']):,}",
              "Rule Pack": f"{s['pack'].name} v{s['pack'].version} ({pack_hash(s['pack'])[:12]})",
              "Positions": "kept from Rev A (pinned)" if report.mode == "pinned" else "compare only (Rev A could not be mapped)"}
    return revlibrary.make_entry(
        name or revlibrary.default_name(s["rev_library"], label, name_b), created=time.strftime("%Y-%m-%d %H:%M"),
        file_name=name_b, label=label, source=s.get("rev_a_source") or "-", rows_a=rows_a,
        a_tqs=list(a_result.tqs) if a_result is not None else None,
        a_status=readiness_mod.assess(a_result, s["signoffs"]).status if a_result is not None else None,
        b_status=readiness_mod.assess(result_b, s["signoffs"]).status,
        a_quarantined=len(a_result.quarantined or []) if a_result is not None else None, result_b=result_b,
        report=report, fresh_report=fresh_report, minutes=_minutes(), review_log=s["review_log"], inputs=inputs)


def _run_compare() -> None:
    s = st.session_state
    got = _read_inputs()
    if got is None:
        return
    rows_a, data_b, name_b, label = got
    result_b, report = _solve_b(rows_a, data_b, label)
    _adopt(rows_a, data_b, name_b, label, result_b, report)
    s["rev_library"] = revlibrary.add(s["rev_library"], _entry(rows_a, data_b, name_b, label, result_b, report))
    state.flash("success", f"Revision compared and saved in the {link('Revision History', 'Revision', 'Revision History')} "
                           f"and the {link_to('Revision Library', 'Revision › Revision Library')}. Scroll down for the changes.",
                COMPARE_NEW)


# ------------------------------------------------------------------ Check Allocation First (the preview pop-up)
def _run_preview() -> None:
    """Allocate Rev B and compare it with what you have now, WITHOUT saving anything: the pop-up shows it."""
    s = st.session_state
    got = _read_inputs()
    if got is None:
        return
    rows_a, data_b, name_b, label = got
    result_b, report = _solve_b(rows_a, data_b, label)
    entry = _entry(rows_a, data_b, name_b, label, result_b, report)
    s["rev_preview"] = {"entry": entry, "result": result_b, "report": report, "rows_a": rows_a, "bytes": data_b,
                        "name": name_b, "label": label}
    s["rev_preview_name"] = entry.name
    s["rev_preview_open"] = True


def _close_preview() -> None:
    st.session_state["rev_preview_open"] = False


def _open_preview() -> None:
    st.session_state["rev_preview_open"] = True


def _discard_preview() -> None:
    s = st.session_state
    s["rev_preview"], s["rev_preview_open"] = None, False
    state.flash("info", "Preview discarded. Nothing was saved and nothing changed.", COMPARE_NEW)


def _save_preview() -> bool:
    """Keep the previewed revision: it goes into the Revision Library and becomes the compared revision here."""
    s = st.session_state
    pv = s.get("rev_preview")
    if not pv:
        return False
    name = (s.get("rev_preview_name") or "").strip()
    problem = revlibrary.name_problem(s["rev_library"], name)
    if problem:
        st.session_state["rev_preview_error"] = problem
        return False
    entry = pv["entry"]
    entry.name = name
    _adopt(pv["rows_a"], pv["bytes"], pv["name"], pv["label"], pv["result"], pv["report"])
    s["rev_library"] = revlibrary.add(s["rev_library"], entry)
    s["lib_pick"] = entry.id
    s["rev_preview"], s["rev_preview_open"], s["rev_preview_error"] = None, False, None
    state.flash("success", f"Saved as “{name}” in the {link_to('Revision Library', 'Revision › Revision Library')} (and the "
                           "Revision History). Its changes are shown below.", COMPARE_NEW)
    return True


def _preview_topic() -> dict:
    s = st.session_state
    pv = s.get("rev_preview") or {}
    entry = pv.get("entry")
    s["rev_preview_open"] = False                  # the pop-up closes so the Helpdesk on the right can be seen
    title, context = helpcontext.preview_focus(entry.name if entry else "Rev B", entry.check.lines() if entry else [])
    return assistant.topic(f"preview|{entry.name if entry else ''}|{entry.inputs.get('Rev B Fingerprint', '') if entry else ''}",
                           "preview", title, context)


@st.dialog("Check Allocation · Preview Of The Revision", width="large", on_dismiss=_close_preview)
def _preview_dialog() -> None:
    s = st.session_state
    pv = s.get("rev_preview")
    if not pv:
        st.info("There is no preview any more.")
        return
    entry = pv["entry"]
    st.caption(f"Rev B **{md_escape(entry.file_name)}** (label {md_escape(entry.label)}) allocated and compared with "
               f"the allocation you have now ({md_escape(entry.source)}). **Nothing is saved yet**: save it to keep it in "
               "the Revision Library and see its changes on this page, or discard it.")
    _detail(entry, "pv")
    st.divider()
    if s.get("rev_preview_error"):
        st.error(s["rev_preview_error"])
    st.text_input("Name For This Revision", key="rev_preview_name", max_chars=60, autocomplete="off",
                  help="The name it gets in the Revision Library. Click the name there later to see everything about it.")
    with st.container(horizontal=True, gap="small", vertical_alignment="center", key="pv_buttons"):
        if st.button("Save This Revision", key="pv_save", type="primary", icon=":material/check:",
                     help="Keep it: it goes into the Revision Library and becomes the compared revision on this page."):
            if _save_preview():
                st.rerun()
            else:
                st.rerun(scope="fragment")
        if st.button("Discard", key="pv_discard", icon=":material/close:",
                     help="Forget this preview. Nothing is saved and nothing changes."):
            _discard_preview()
            st.rerun()
        assistant.ask_button("pv_ask", _preview_topic, in_fragment=True, label="Ask The Helpdesk",
                             help="Closes the pop-up and opens the Helpdesk on the right, already told this whole "
                                  "comparison. Advice only: it cannot change anything.")


def _preview_waiting() -> None:
    """A preview that was closed without a decision stays here until it is saved or discarded."""
    s = st.session_state
    pv = s.get("rev_preview")
    if not pv or s.get("rev_preview_open"):
        return
    with st.container(border=True, key="pv_waiting"):
        st.markdown(f"\U0001F50D **A preview is waiting:** {md_escape(pv['entry'].name)}. "
                    f"{md_escape(pv['entry'].check.headline)} Nothing is saved yet.")
        with st.container(horizontal=True, gap="small"):
            st.button("Open The Preview", key="pv_reopen", on_click=_open_preview, type="primary")
            st.button("Discard It", key="pv_drop", on_click=_discard_preview)


# ------------------------------------------------------------------ one revision, whole (preview and library)
DETAIL_TABS = ("Summary", "Whole Allocation", "Questions", "Changes", "Inputs And Files")
KEY_COLUMNS = ("Tag Name", "Tag Status", "IO Type", "Segregation", "Electronic/ Marshalling Cabinet", "CIOC/CSLS Name",
               "Baseplate", "Channel_No", "CHARM Type", "Field Cable No", "Field Cable Pair", "Revision", "Service Description")


def _detail(entry: revlibrary.Entry, prefix: str) -> None:
    """Everything about one revision: the better/worse check, the whole allocation, its questions, its changes,
    and what it was made from (with its files)."""
    chk = entry.check
    show = {"better": st.success, "worse": st.error, "mixed": st.warning}.get(chk.word, st.info)
    h = chk.hours
    time_line = (f"Rework to adopt it: about **{h.keep:g} h** keeping positions, against {h.fresh:g} h if Rev B were "
                 f"allocated again from scratch (**{h.saved:g} h saved**).")
    show(f"**{chk.headline}**" + ("\n\n" + "\n".join(f"- {md_escape(r)}" for r in chk.reasons) if chk.reasons else "")
         + "\n\n" + time_line)
    summary, rows_tab, questions, changes, inputs = st.tabs(list(DETAIL_TABS))
    with summary:
        cards = [("Rework Keeping Positions", f"{h.keep:g} h"), ("Rework From Scratch", f"{h.fresh:g} h"),
                 ("Time Saved", f"{h.saved:g} h"), ("Tags Moved", f"{h.keep_moved:,} vs {h.fresh_moved:,}")]
        st.markdown(theme.kpi_html(cards), unsafe_allow_html=True)
        st.caption("Rework is an ESTIMATE from the minutes per moved, renamed, added and deleted tag set on the "
                   "Revision Simulator tab. Keeping positions = this revision (every surviving tag stays in its Rev A "
                   "slot). From scratch = Rev B allocated again with nothing kept.")
        st.dataframe(chk.table(), hide_index=True, width="stretch", height=38 + 35 * len(chk.table()))
        c = st.columns(5)
        for col, name in zip(c, CATEGORIES):
            col.metric(name, f"{chk.counts.get(name, 0):,}")
        c[4].metric("Unchanged", f"{chk.unchanged:,}")
    with rows_tab:
        rows = entry.rows()
        left, right = st.columns([3, 1], vertical_alignment="bottom")
        needle = left.text_input("Search The Allocation", key=f"{prefix}_rows_q", autocomplete="off",
                                 placeholder="\U0001F50E A tag, a cable, a cabinet…").strip().casefold()
        every = right.toggle("All Columns", key=f"{prefix}_allcols", help="Show every column of the allocation.")
        shown = [r for r in rows if not needle or any(needle in str(v).casefold() for v in r.values())]
        cols = list(rows[0]) if (rows and every) else [c for c in KEY_COLUMNS if rows and c in rows[0]]
        st.caption(f"{len(shown):,} of {len(rows):,} rows")
        st.dataframe([{c: r.get(c) for c in cols} for r in shown[:3000]], hide_index=True, width="stretch", height=420)
        st.download_button("Download This Allocation (.xlsx)", data=lambda: allocation_bytes(rows)[0], on_click="ignore",
                           file_name=f"Allocation_{_file_safe(entry.name)}.xlsx", key=f"{prefix}_dl_rows",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with questions:
        new = sum(1 for t in entry.tqs if t["Status"] == "New")
        a, b, c3, d = st.columns(4)
        a.metric("Questions In Rev B", f"{len(entry.tqs):,}")
        b.metric("New", f"{new:,}" if entry.tqs and entry.tqs[0]["Status"] != "-" else "-")
        c3.metric("Resolved", f"{len(entry.resolved):,}")
        d.metric("Reviewed Before", f"{len(entry.reviewed_again):,}",
                 help="Items you reviewed before on the TQ Board that have an error or warning in this revision.")
        if entry.reviewed_again:
            st.markdown("**↺ Items you reviewed before with a problem in this revision**")
            st.dataframe(entry.reviewed_again, hide_index=True, width="stretch",
                         height=min(260, 38 + 35 * len(entry.reviewed_again)))
        if entry.tqs:
            st.dataframe(entry.tqs, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(entry.tqs)))
        else:
            st.success("Rev B raises no questions.")
        if entry.resolved:
            with st.expander(f"Resolved By This Revision ({len(entry.resolved):,})"):
                st.dataframe(entry.resolved, hide_index=True, width="stretch")
    with changes:
        items = entry.changes()
        pick = st.pills("Show", ("All",) + CATEGORIES, key=f"{prefix}_cat", default="All") or "All"
        shown = [x for x in items if pick == "All" or x["Change"] == pick]
        if shown:
            st.dataframe(shown, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(shown)))
        else:
            st.info("No changes of this kind.")
        if entry.report.hardware_changes or entry.report.conversions:
            with st.expander("Hardware Changes And Spare Conversions"):
                st.dataframe([{"Tag": x.tag, "Note": x.note} for x in entry.report.hardware_changes], hide_index=True,
                             width="stretch")
                st.dataframe([{"Deleted Tag": x.tag, "Slot": _loc(x.a_loc), "Note": x.note} for x in entry.report.conversions],
                             hide_index=True, width="stretch")
        for warning in entry.report.warnings:
            st.warning(warning)
    with inputs:
        st.dataframe([{"What": k, "Value": v} for k, v in {"Name": entry.name, "Saved At": entry.created or "not saved yet",
                                                           **entry.inputs}.items()],
                     hide_index=True, width="stretch")
        html = impact.impact_html(entry.report, entry.rows_a(), entry.rows(), f"Revision Impact Report ({entry.name})")
        st.download_button("Download Impact Report (.html)", data=html.encode("utf-8"), mime="text/html", on_click="ignore",
                           file_name=f"Impact_Report_{_file_safe(entry.name)}.html", key=f"{prefix}_dl_impact")


def _file_safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:60] or "Revision"


# ------------------------------------------------------------------ revision library
def _library() -> None:
    s = st.session_state
    state.show_flash(LIBRARY)
    st.caption("Every revision you saved: from the preview of Check Allocation First (Save This Revision), and every "
               "Compare Revisions. Pick one in the dropdown to see everything about that revision: whether it was better or worse, "
               "the rework estimate, the whole allocation, its questions, its changes and what it was made from. The "
               "library lasts for this browser session.")
    lib: list[revlibrary.Entry] = s["rev_library"]
    if not lib:
        st.info("No revision saved yet. On Compare With A New MDB, press Check Allocation First, look at the preview, "
                "then press Save This Revision.")
        return
    by_id = {e.id: e for e in lib}
    if s.get("lib_pick") not in by_id:
        s["lib_pick"] = lib[-1].id
    st.selectbox(f"Saved Revisions ({len(lib):,})", [e.id for e in reversed(lib)], key="lib_pick",
                 format_func=lambda i: f"{by_id[i].name} · saved {by_id[i].created}",
                 help="Pick a revision to open it (newest first).")
    entry = by_id.get(s.get("lib_pick")) or lib[-1]
    with st.container(border=True, key="lib_entry"):
        st.markdown(f"#### {md_escape(entry.name)}  \n<small>Saved {md_escape(entry.created)} · Rev B "
                    f"{md_escape(entry.file_name)} (label {md_escape(entry.label)}) · Rev A from {md_escape(entry.source)}"
                    "</small>", unsafe_allow_html=True)
        _detail(entry, f"lib{entry.id}")
        st.divider()
        a, b, c = st.columns([3, 1, 2], vertical_alignment="bottom")
        a.text_input("Rename This Revision", value=entry.name, key=f"lib_name_{entry.id}", max_chars=60)
        b.button("Rename", key=f"lib_rename_{entry.id}", on_click=_rename_entry, args=(entry.id,))
        with c:
            ask_first(f"lib_delete_{entry.id}", "\U0001F5D1 Delete This Revision",
                      f"Delete “{entry.name}” from the Revision Library? This cannot be undone.", _delete_entry,
                      args=(entry.id,), yes="Yes, delete it",
                      help="Removes it from the library only. The allocation on screen stays as it is.")


def _rename_entry(entry_id: int) -> None:
    s = st.session_state
    name = (s.get(f"lib_name_{entry_id}") or "").strip()
    problem = revlibrary.name_problem(s["rev_library"], name, entry_id)
    if problem:
        state.flash("error", problem, LIBRARY)
        return
    for e in s["rev_library"]:
        if e.id == entry_id:
            e.name = name
    s["rev_library"] = list(s["rev_library"])
    state.flash("success", f"Renamed to “{name}”.", LIBRARY)


def _delete_entry(entry_id: int) -> None:
    s = st.session_state
    gone = next((e.name for e in s["rev_library"] if e.id == entry_id), "")
    s["rev_library"] = [e for e in s["rev_library"] if e.id != entry_id]
    s["lib_pick"] = None
    state.flash("success", f"Deleted “{gone}” from the Revision Library.", LIBRARY)


COMPARE_NEW, LIBRARY, HISTORY, SIMULATOR = "Compare With A New MDB", "Revision Library", "Revision History", state.SIM_TAB


def render() -> None:
    from io_sudoku.ui.views import simulator
    st.header("Revision Impact")
    stale_banner("rev")
    new_tab, library_tab, history_tab, sim_tab = st.tabs([COMPARE_NEW, LIBRARY, HISTORY, SIMULATOR], key=state.REV_TAB_KEY,
                                                         on_change="rerun")
    with new_tab:
        _compare_new()
    with library_tab:
        _library()
    with history_tab:
        _history()
    with sim_tab:
        simulator.render()


def _compare_new() -> None:
    s = st.session_state
    state.show_flash(COMPARE_NEW)
    if s.get("rev_a_source") not in SOURCES:
        s["rev_a_source"] = SOURCES[0]
    if s.get("rev_b_source") not in B_SOURCES:
        s["rev_b_source"] = B_SOURCES[0]
    a_col, b_col = st.columns(2)
    with a_col:
        st.selectbox("Rev A Comes From", SOURCES, key="rev_a_source",
                     help="Rev A is the allocation you compare against: the one on screen, a saved revision of this "
                          "session, an allocation workbook or a workspace.")
        if s["rev_a_source"] == SOURCES[3]:
            past = {x.id: x for x in s["history"]}
            if not past:
                st.info("No saved revision yet. Run an allocation first.")
            else:
                if s.get("rev_a_snap") not in past:
                    s["rev_a_snap"] = list(past)[-1]
                st.selectbox("Saved Revision To Use As Rev A", list(reversed(list(past))), key="rev_a_snap",
                             format_func=lambda i: past[i].label, help="Every allocation of this session, newest first.")
        elif s["rev_a_source"] != SOURCES[0]:
            st.file_uploader("Rev A File", type=["xlsx", "zip"], key="reva_uploader")
        elif s["result"] is None:
            st.info("There is no current result yet. Run an allocation first, or choose another Rev A source.")
    with b_col:
        st.selectbox("Rev B Comes From", B_SOURCES, key="rev_b_source",
                     help="Rev B is the new MDB: upload it, or pick one of the saved file revisions of this session "
                          "(the uploaded file, every edited version, a suggested fixed file ...).")
        if s["rev_b_source"] == B_SOURCES[1]:
            files = {r.id: r for r in s["file_revs"]}
            if not files:
                st.info("No saved file yet. Upload a file or load the sample data first.")
            else:
                if s.get("rev_b_file") not in files:
                    s["rev_b_file"] = list(files)[-1]
                st.selectbox("Saved File To Use As Rev B", list(reversed(list(files))), key="rev_b_file",
                             format_func=lambda i: files[i].label, help="Every saved version of the input file, newest first.")
        else:
            st.file_uploader("Rev B MDB (.xlsx or .csv)", type=["xlsx", "xlsm", "csv"], key="revb_uploader")
    st.text_input("Rev B Label", value="B", key="rev_b_label", max_chars=8, autocomplete="off")
    with st.container(horizontal=True, gap="small", vertical_alignment="center", key="rev_buttons"):
        st.button("Check Allocation First", key="rev_preview_go", on_click=_run_preview, type="primary",
                  icon=":material/visibility:",
                  help="Allocate Rev B and see it in a pop-up next to the allocation you have now: errors, warnings, "
                       "the whole allocation, its changes and the rework hours. Nothing is saved until you press "
                       "Save This Revision.")
        st.button("Compare Revisions", key="rev_compare", on_click=_run_compare,
                  help="Allocate Rev B and save it straight away (Revision Library and Revision History).")
    _preview_waiting()
    if s.get("rev_preview_open") and s.get("rev_preview"):
        _preview_dialog()
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


def _same(topic: dict) -> dict:
    return topic


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
                checks = []
                st.caption("This signal is not in Rev B, so no rule applies to it any more. Its slot became free "
                           "(see Spare Conversions).")
            title, context = helpcontext.change_focus(change, detail.diffs, checks, _loc(change.a_loc), _loc(change.b_loc))
            assistant.ask_button("rev_ask", _same, (assistant.topic(f"change|{st.session_state.get('rev_key') or ''}|"
                                                                    f"{change.category}|{change.tag}", "change", title,
                                                                    context),),
                                 help="Opens the Helpdesk on the right, already told what changed in this signal and "
                                      "why it sits where it does in Rev B. Advice only: it cannot change anything.")


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
