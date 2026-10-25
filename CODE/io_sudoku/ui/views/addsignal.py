"""Add A Signal (Rules › Propose A Rule): a short form for a signal that arrives later.

Only the basic facts are asked, each with a dropdown of the values your file already uses (you can type a new
one).  Picking a cable fills in its room, its size and its next free pair.  Add Signal And Open It writes the new
row into your file (saved as a file revision, listed under Your Changes) and opens that row on Edit File, so you
can fill in every other column of it.  Nothing is allocated until you press Re-allocate.
"""
from __future__ import annotations

import json
from typing import Any

import streamlit as st

from io_sudoku.core.constants import IO_TYPES
from io_sudoku.core.textnorm import match_key
from io_sudoku.ui import editing, newsignal, state, ui_logic
from io_sudoku.ui.views._common import md_escape

GROUP = "Add A Signal"
WHERE = "Propose A Rule"
KEYS = {f: f"ns_{f}" for f, _ in newsignal.FIELDS}


def _opts() -> newsignal.Options | None:
    s = st.session_state
    try:
        index = ui_logic.edit_index(s["mdb_bytes"], json.dumps(s["column_overrides"], sort_keys=True), ui_logic.pack_json(s["pack"]))
        return newsignal.options(ui_logic.editable_sheets(s["mdb_bytes"]), index)
    except Exception:  # noqa: BLE001 - a file that cannot be read cannot get a new row either
        return None


def _values() -> dict[str, Any]:
    s = st.session_state
    return {f: s.get(k) for f, k in KEYS.items()}


def _on_cable() -> None:
    """Picking a cable fills in what the file already says about it: its room, its size and its next free pair."""
    s = st.session_state
    opts = _opts()
    cable = opts.cables.get(match_key(s.get(KEYS["cable_no"])) or "") if opts else None
    if cable is None:
        return
    s[KEYS["pair_no"]] = cable.next_pair()
    if cable.size:
        s[KEYS["cable_size"]] = cable.size
    if cable.room:
        s[KEYS["tech_room"]] = cable.room


def _pick(label: str, f: str, counts, help_text: str, rooms: list[str] | None = None) -> None:
    s = st.session_state
    choices = list(dict.fromkeys((rooms or []) + [v for v, _ in counts.most_common(400)]))
    current = s.get(KEYS[f])
    if current and current not in choices:
        choices = [current] + choices
    st.selectbox(label, choices, key=KEYS[f], accept_new_options=True, placeholder="Pick or type…",
                 format_func=lambda v: f"{v} · {counts[v]:,}" if counts.get(v) else str(v), help=help_text)


def _add() -> None:
    s = st.session_state
    opts = _opts()
    values = _values()
    if opts is None or opts.sheet is None:
        state.flash("error", "Your file cannot be read as a table, so a signal cannot be added to it.", WHERE)
        return
    problems = newsignal.problems(values, opts)
    if problems:
        state.flash("error", " ".join(problems), WHERE)
        return
    sheets = ui_logic.editable_sheets(s["mdb_bytes"])
    sheet, row, cells = newsignal.plan(values, opts, sheets)
    tag = str(values["tag"]).strip()
    edits = [editing.CellEdit(sheet, row, col, header, None, value) for col, header, value in cells]
    before = s["mdb_sha"]
    state.apply_cell_edits(edits, go_back=False, kind="signal", note=f"new signal {tag}")
    if s["mdb_sha"] == before:                       # it could not be written (the message says why)
        return
    for k in KEYS.values():
        s[k] = None
    state.open_editor(editing.Target(sheet, row, None, "", f"New signal {tag}: fill in its other columns, then press "
                                                            "Save Row"), "Rules")
    state.flash("success", f"Signal {tag} was added to your file (sheet {sheet}, row {row}) and saved as a file "
                           "revision. Fill in its other columns below, then press Save Row. Re-allocate to place it.")


def render() -> None:
    s = st.session_state
    st.caption("For a signal that arrives after the file was made. Give its basic facts; every dropdown lists the values "
               "your file already uses (with how many signals have each), and you can type a new one. Picking a cable "
               "fills in its room, size and next free pair. The new row is added to your file and opened on Edit File "
               "to fill in every other column. This changes your input file, not a rule: nothing goes to the Review "
               "Queue, and you re-allocate to place the signal.")
    if not s["mdb_bytes"]:
        st.info("Upload a file or load the sample data first: the new signal is added to that file.")
        return
    opts = _opts()
    if opts is None or opts.sheet is None:
        st.warning("Your file cannot be read as a table, so a signal cannot be added to it here.")
        return
    rooms = ui_logic.config_for_pack(s["pack"]).known_rooms()
    for k in KEYS.values():                          # empty until picked (no default value, no warning)
        if k not in s:
            s[k] = None
    a, b, c = st.columns(3)
    a.text_input("Tag", key=KEYS["tag"], max_chars=60, autocomplete="off", placeholder="For example 320-FT -20999",
                 help="Written exactly as you type it. It must not be in the file yet.")
    b.selectbox("IO Type", IO_TYPES, key=KEYS["io_type"], placeholder="Pick…",
                help="AIR analog in · AOR analog out · DIR digital in · DOR digital out")
    with c:
        _pick("Technical Room", "tech_room", opts.values["tech_room"], "The room the signal's cable runs to.", rooms)
    a, b, c = st.columns(3)
    cables = opts.cables
    with a:
        choices = [cab.text for cab in sorted(cables.values(), key=lambda x: x.text)]
        current = s.get(KEYS["cable_no"])
        if current and current not in choices:
            choices = [current] + choices
        st.selectbox("Cable Number", choices, key=KEYS["cable_no"], accept_new_options=True,
                     placeholder="Pick or type…", on_change=_on_cable,
                     format_func=lambda v: (f"{v} · {len(cables[match_key(v)].pairs)} pairs used"
                                            if match_key(v) in cables else str(v)),
                     help="Pick a cable of the file (its room, size and next free pair are filled in) or type a new one.")
    b.number_input("Pair Number", min_value=1, max_value=96, step=1, key=KEYS["pair_no"], placeholder="1 – 96", help="Picking a cable fills in its next free pair.")
    with c:
        _pick("Cable Size", "cable_size", opts.values["cable_size"], "For example 24PX1MM2/FR/IND&OS/ARM/NIS.")
    a, b, c = st.columns(3)
    with a:
        _pick("Segregation", "segregation", opts.values["segregation"], "A, B, a neutral code, or empty for none.")
    with b:
        _pick("Instrument Type", "instrument_type", opts.values["instrument_type"], "For example Pressure Transmitter.")
    with c:
        _pick("Signal Type", "signal_type", opts.values["signal_type"], "For example 4-20 ma HART.")
    st.text_input("Service", key=KEYS["service"], max_chars=120, autocomplete="off", placeholder="What the signal does")
    values = _values()
    problems = newsignal.problems(values, opts) if any(values.values()) else []
    for p in problems:
        st.caption(f"✗ {md_escape(p)}")
    for w in newsignal.warnings(values, opts) if values.get("tag") else []:
        st.caption(f"⚠ {md_escape(w)}")
    st.button("Add Signal And Open It", key="ns_add", type="primary", icon=":material/add:", on_click=_add,
              disabled=bool(problems) or not all(values.get(f) for f in newsignal.REQUIRED),
              help="Adds the row to your file and opens it on Edit File to fill in the rest.")
