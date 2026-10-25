"""Suggested Fixed File (on Preflight): the tool's own repaired copy of the file, every change explained.

The fixing is done by core.autofix (fixed rules, no AI).  This page only shows it: what would get better, a switch
per kind of fix, a scroll box that explains every change, what still needs a person, and the buttons to use or
download the suggested file.  Using it saves it as a file revision and makes it the input; nothing else changes,
and the allocation is out of date (DRAFT) until you re-allocate.
"""
from __future__ import annotations

import json

import streamlit as st

from io_sudoku.core import autofix
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.views._common import heading, md_escape

TITLE = "Suggested Fixed File"
MAX_LINES_PER_GROUP = 300


@st.cache_data(max_entries=8, show_spinner="Working out the suggested fixed file…")
def _suggest(mdb_bytes: bytes, file_name: str, pack_text: str, column_text: str, skip: tuple[str, ...]) -> autofix.Suggestion:
    from io_sudoku.core.rulepack import pack_from_dict
    cfg = ui_logic.config_for_pack(pack_from_dict(json.loads(pack_text)))
    return autofix.suggest(mdb_bytes, file_name, cfg, json.loads(column_text), skip)


def _key(group: str) -> str:
    return f"afx_on_{group}"


def _inputs(skip: tuple[str, ...] = ()) -> autofix.Suggestion:
    s = st.session_state
    return _suggest(s["mdb_bytes"], s["mdb_name"] or "MDB.xlsx", ui_logic.pack_json(s["pack"]),
                    json.dumps(s["column_overrides"], sort_keys=True), skip)


def _use(skip: tuple[str, ...]) -> None:
    """Make the suggested file the input: saved as a file revision first, then used (DRAFT until re-allocated)."""
    s = st.session_state
    sg = _inputs(skip)
    if sg.data is None:
        state.flash("error", "There is no suggested file to use.", TITLE)
        return
    n = len(sg.changes)
    rev = state.save_file_rev("suggested", f"{n:,} fixes", data=sg.data, file_name=sg.file_name,
                              origin_sha=state.upload_sha())
    if rev is None:
        return
    rev.edit_log = [dict(x) for x in s["edit_log"]]
    state.use_file_rev(rev.id)
    state.flash("success", f"Now using the suggested file ({n:,} fixes), saved as the file revision “{rev.name}”. "
                           "Press Re-allocate to allocate it. You can go back to any earlier file under Saved File "
                           "Revisions (Upload or Edit File).", TITLE)


def _measure_cards(sg: autofix.Suggestion) -> list[tuple[str, str]]:
    b, a = sg.before, sg.after
    if b is None or a is None:
        return []
    return [("Readiness", f"{b.status} → {a.status}"), ("Errors", f"{b.errors:,} → {a.errors:,}"),
            ("Warnings", f"{b.warnings:,} → {a.warnings:,}"), ("Held Back", f"{b.held_back:,} → {a.held_back:,}"),
            ("Signals Placed", f"{b.placed:,} → {a.placed:,}")]


def _value(v) -> str:
    """A cell value in quotes, with spaces at its ends shown as ␣ (otherwise a 'spaces removed' fix looks empty)."""
    text = "" if v is None else str(v)
    if not text.strip():
        return "(empty)"
    core = text.strip()
    lead, trail = len(text) - len(text.lstrip()), len(text) - len(text.rstrip())
    return "“" + "␣" * lead + md_escape(core) + "␣" * trail + "”"


def _better(sg: autofix.Suggestion) -> bool:
    """True when the suggested file does better than the original on at least one count."""
    b, a = sg.before, sg.after
    if b is None or a is None:
        return False
    return (a.errors < b.errors or a.warnings < b.warnings or a.held_back < b.held_back or a.placed > b.placed
            or a.status != b.status)


def _explain(sg: autofix.Suggestion) -> None:
    """The scroll box: every group, why it exists, and every change with its own evidence."""
    with st.container(height=440, border=True, key="afx_explain"):
        by_group: dict[str, list[autofix.Change]] = {}
        for c in sg.changes:
            by_group.setdefault(c.group, []).append(c)
        for g, changes in by_group.items():
            group = autofix.GROUPS[g]
            kind = "✔ only how it is written" if group.sure else "🔎 worked out from your file"
            st.markdown(f"**{md_escape(group.title)}** · {len(changes):,} · <small>{kind}</small>", unsafe_allow_html=True)
            st.caption(group.why)
            lines = []
            for c in changes[:MAX_LINES_PER_GROUP]:
                where = f"Sheet {md_escape(c.sheet)} · row {c.row}"
                if c.new == autofix.REMOVED:
                    lines.append(f"- {where}: row removed. {md_escape(c.why)}")
                else:
                    lines.append(f"- {where} · “{md_escape(c.column)}”: {_value(c.old)} → **{_value(c.new)}**. "
                                 f"{md_escape(c.why)}")
            if len(changes) > MAX_LINES_PER_GROUP:
                lines.append(f"- … and {len(changes) - MAX_LINES_PER_GROUP:,} more of the same kind (all are in the file).")
            st.markdown("\n".join(lines))


def _left(sg: autofix.Suggestion) -> None:
    if not sg.left:
        st.success("Nothing is left for a person: no error and no warning remains.")
        return
    errors = sum(1 for x in sg.left if x[1] == "error")
    st.markdown(f"**Still Needs A Person** · {errors:,} error(s), {len(sg.left) - errors:,} warning(s)",
                help="These were NOT changed, on purpose: the file cannot answer them, so a guess could be wrong. Each "
                     "line says why. Fix them on Edit File or the TQ Board after using the suggested file.")
    with st.container(height=min(300, 60 + 34 * len(sg.left)), border=True, key="afx_left"):
        st.markdown("\n".join(f"- **{md_escape(tq_id)}** ({sev}) · {md_escape(ref or '-')}: {md_escape(why)}"
                              for tq_id, sev, ref, why in sg.left))


def _unused(sg: autofix.Suggestion) -> None:
    """Columns the allocation does not read: kept as they are, and any of them can become a project column."""
    if not sg.unused:
        return
    from io_sudoku.ui.views import columns
    with st.expander(f"Columns The Allocation Does Not Read ({len(sg.unused):,})", icon=":material/view_column:"):
        st.caption("These columns are kept in the file exactly as they are; the allocation never uses them. To use one "
                   "for your signals, turn it into a project column: its value for each tag is copied into the "
                   "Columns And Checks form on the Rules page, where you can add checks (for example a maximum) "
                   "and propose it like any other rule.")
        by_name = {h: (n, v) for h, n, v in sg.unused}
        names = sorted(by_name, key=lambda h: (-by_name[h][0], h.casefold()))
        pick = st.selectbox("Column", names, key="afx_unused_pick",
                            format_func=lambda h: f"{h} · {by_name[h][0]:,} signals have a value")
        if pick:
            sample = list(by_name[pick][1].items())[:3]
            st.caption("For example: " + "; ".join(f"{md_escape(k.upper())} = {md_escape(v)}" for k, v in sample))
            st.button("Use As A Project Column", key="afx_unused_go", icon=":material/add_column_right:",
                      on_click=columns.start_from_values, args=(pick, by_name[pick][1]),
                      help="Opens Rules › Columns And Checks with this column's values already filled in.")


def render() -> None:
    s = st.session_state
    heading(TITLE, "The tool's own repaired copy of your file. It fixes only what the file itself can answer, by fixed "
                   "rules (no AI, no guessing): spellings the solver already understands, your own column choices, exact "
                   "copies of a row, and values that the rest of the file shows with unanimous evidence. Every change "
                   "is explained below. The original stays as it is; the suggestion is used only if you press Use The "
                   "Suggested File, and then it is saved as a file revision you can go back from.")
    full = _inputs()
    groups = [g for g in autofix.GROUPS if g in full.counts()]
    for g in groups:
        s.setdefault(_key(g), True)
    skip = tuple(g for g in groups if not s.get(_key(g), True))
    sg = _inputs(skip) if skip else full
    for note in sg.notes:
        st.info(note)
    if not groups:
        st.success("Nothing in this file can be fixed automatically. " + ("Every problem left needs a person (listed "
                   "below)." if full.left else "And nothing needs fixing."))
        _left(full)
        _unused(full)
        return
    if not _better(full):
        st.success("Nothing to fix: no problem the file itself can answer was found. Only tidying is possible, which "
                   "changes no result (open the box below to see it).")
        with st.expander(f"Optional Tidying ({len(full.changes):,} cells)", icon=":material/cleaning_services:"):
            _body(full, sg, groups, skip)
        _left(full)
        _unused(full)
        return
    _body(full, sg, groups, skip)
    _left(sg)
    _unused(sg)


def _body(full: autofix.Suggestion, sg: autofix.Suggestion, groups: list[str], skip: tuple[str, ...]) -> None:
    """The before → after boxes, the switches, the explanation scroll box and the buttons."""
    cards = _measure_cards(sg)
    if cards:
        st.markdown(theme.kpi_html(cards), unsafe_allow_html=True)
    sure = sum(1 for c in sg.changes if autofix.GROUPS[c.group].sure)
    st.caption(f"{len(sg.changes):,} changes: {sure:,} only change how a value is written (✔), "
               f"{len(sg.changes) - sure:,} are worked out from your own file (🔎). Switch off any kind you do not want.")
    with st.container(border=True, key="afx_groups"):
        cols = st.columns(2)
        for i, g in enumerate(groups):
            group = autofix.GROUPS[g]
            cols[i % 2].checkbox(f"{'✔' if group.sure else '🔎'} {group.title} ({full.counts()[g]:,})", key=_key(g),
                                 help=group.why)
    if sg.data is None:
        st.warning("With these switches there is nothing left to change.")
    else:
        _explain(sg)
        with st.container(horizontal=True, gap="small", vertical_alignment="center", key="afx_buttons"):
            st.button("Use The Suggested File", key="afx_use", type="primary", icon=":material/auto_fix_high:",
                      on_click=_use, args=(skip,),
                      help="Saves it as a file revision and makes it your input. Re-allocate afterwards.")
            st.download_button("Download Suggested File", data=sg.data, file_name=sg.file_name, key="afx_download",
                               on_click="ignore", icon=":material/download:")
