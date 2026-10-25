"""Add A Signal (Rules › Propose Rules): a short form for a signal that arrives later.

Only the basic facts are asked, each with a dropdown of the values your file already uses (you can type a new
one).  Picking a cable fills in its room, its size and its next free pair.  Propose This Signal sends it to the
Review Queue, like every other proposal: nothing is written until someone presses Verify there.  Verify writes the
new row into your file (saved as a file revision, listed under Your Changes), and Open It On Edit File shows that
row so every other column can be filled in.  Nothing is allocated until you press Re-allocate.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from io_sudoku.core.constants import IO_TYPES
from io_sudoku.core.textnorm import match_key
from io_sudoku.ui import autofill, editing, newsignal, state, ui_logic
from io_sudoku.ui.views._common import md_escape

GROUP = "Add A Signal"
WHERE = "Propose Rules"
BUTTON_WHERE = "ns_propose"                      # messages about the Propose button are shown right under it
QUEUE = "Review Queue"
KEYS = {f: f"ns_{f}" for f, _ in newsignal.FIELDS}
LIST_KEY = "signal_requests"


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def statement(values: dict[str, Any]) -> str:
    """The proposal's wording, written from the form (never typed free-hand)."""
    v = {k: str(values.get(k) or "").strip() for k, _ in newsignal.FIELDS}
    parts = [x for x in (v["io_type"].upper(), v["tech_room"]) if x]
    cable = f"cable {v['cable_no']}" + (f" pair {v['pair_no']}" if v["pair_no"] else "") if v["cable_no"] else "no cable yet"
    return f"Add the new signal {v['tag']} ({', '.join(parts + [cable])}) to the input file."


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f, _ in newsignal.FIELDS:
        value = values.get(f)
        out[f] = int(value) if f == "pair_no" and value not in (None, "") else (str(value).strip() if value not in (None, "") else None)
    return out


def _propose() -> None:
    """Send the signal to the Review Queue (it is written into the file only after Verify)."""
    s = st.session_state
    opts = _opts()
    values = _values()
    if opts is None or opts.sheet is None:
        state.flash("error", "Your file cannot be read as a table, so a signal cannot be added to it.", BUTTON_WHERE)
        return
    problems = newsignal.problems(values, opts)
    pending = {str(r["values"].get("tag") or "").strip().casefold() for r in s.get(LIST_KEY) or [] if r["status"] == "pending"}
    if str(values.get("tag") or "").strip().casefold() in pending:
        problems.append(f"{values.get('tag')} is already waiting in the Review Queue.")
    author = str(s.get("rule_author") or "").strip()
    if not author:
        problems.append("Please write your name in Your Name (at the top of Propose Rules): every proposal needs an author.")
    if problems:
        state.flash("error", " ".join(problems), BUTTON_WHERE)
        return
    clean = _clean(values)
    created = _now()
    digest = hashlib.sha256((json.dumps(clean, sort_keys=True) + author + created + str(time.time())).encode()).hexdigest()[:8]
    request = {"id": f"NS-{digest}", "values": clean, "statement": statement(clean), "author": author,
               "created": created, "status": "pending", "reviewer": None, "decided": None, "reason": None,
               "sheet": None, "row": None, "file": s.get("mdb_name") or ""}
    s[LIST_KEY] = list(s.get(LIST_KEY) or []) + [request]
    for k in KEYS.values():
        s[k] = None
    s["scroll_to"] = QUEUE
    state.flash("success", f"Proposed: {request['statement']} It waits in the Review Queue: press Verify there to add it "
                           "to your file.", QUEUE)


def find(request_id: str) -> dict[str, Any] | None:
    return next((r for r in st.session_state.get(LIST_KEY) or [] if r["id"] == request_id), None)


def decide(request_id: str, action: str) -> None:
    """Verify (write the row into the file) or reject a proposed signal: one button, no passcode (a prototype)."""
    s = st.session_state
    req = find(request_id)
    if req is None or req["status"] != "pending":
        return
    if action != "approve":
        req.update(status="rejected", reviewer="Reviewer", decided=_now(), reason=str(s.get(f"nsrs_{request_id}") or "").strip())
        s[LIST_KEY] = list(s[LIST_KEY])
        state.flash("success", f"Signal {req['values'].get('tag')} rejected. Nothing was added to your file.", QUEUE)
        return
    if not s.get("mdb_bytes"):
        state.flash("error", "Upload the file first: the signal is added to it when you press Verify.", QUEUE)
        return
    opts = _opts()
    values = dict(req["values"])
    if opts is None or opts.sheet is None:
        state.flash("error", "Your file cannot be read as a table, so the signal cannot be added to it.", QUEUE)
        return
    problems = newsignal.problems(values, opts)
    if problems:
        state.flash("error", f"Signal {values.get('tag')} cannot be added to the file as it is now: " + " ".join(problems)
                    + " Reject it, and propose it again with the right values.", QUEUE)
        return
    sheets = ui_logic.editable_sheets(s["mdb_bytes"])
    sheet, row, cells = newsignal.plan(values, opts, sheets)
    tag = str(values["tag"]).strip()
    edits = [editing.CellEdit(sheet, row, col, header, None, value) for col, header, value in cells]
    before = s["mdb_sha"]
    s["edit_tq"] = None
    state.apply_cell_edits(edits, go_back=False, kind="signal", note=f"new signal {tag}")
    if s["mdb_sha"] == before:                       # it could not be written (the message says why)
        return
    req.update(status="approved", reviewer="Reviewer", decided=_now(), sheet=sheet, row=row)
    s[LIST_KEY] = list(s[LIST_KEY])
    state.flash("success", f"Verified: signal {tag} was added to your file (sheet {sheet}, row {row}) and saved as a file "
                           "revision. Press Open It On Edit File to fill in its other columns. Re-allocate to place it.",
                QUEUE)


def open_row(request_id: str) -> None:
    req = find(request_id)
    if req is None or req.get("row") is None:
        return
    tag = req["values"].get("tag")
    state.open_editor(editing.Target(req["sheet"], int(req["row"]), None, "", f"New signal {tag}: fill in its other "
                                                                              "columns, then press Save Row"), "Rules")


def render() -> None:
    s = st.session_state
    st.caption("For a signal that arrives after the file was made. Give its basic facts; every dropdown lists the values "
               "your file already uses (with how many signals have each), and you can type a new one. Picking a cable "
               "fills in its room, size and next free pair. The new row is added to your file and opened on Edit File "
               "to fill in every other column. Propose This Signal sends it to the Review Queue below: it is written "
               "into your file only when someone presses Verify there. Then re-allocate to place it.")
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
    autofill.offer(KEYS["tag"], autofill.tags())
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
    autofill.offer(KEYS["service"], [v for v, _ in opts.values["service"].most_common()])
    st.text_input("Service", key=KEYS["service"], max_chars=120, autocomplete="off", placeholder="What the signal does")
    values = _values()
    problems = newsignal.problems(values, opts) if any(values.values()) else []
    for p in problems:
        st.caption(f"✗ {md_escape(p)}")
    for w in newsignal.warnings(values, opts) if values.get("tag") else []:
        st.caption(f"⚠ {md_escape(w)}")
    if not str(s.get("rule_author") or "").strip():
        st.caption("⚠ Write your name in Your Name at the top of Propose Rules first: every proposal needs an author.")
    st.button("Propose This Signal", key="ns_add", type="primary", icon=":material/add:", on_click=_propose,
              disabled=bool(problems) or not all(values.get(f) for f in newsignal.REQUIRED),
              help="Sends the signal to the Review Queue. It is added to your file when someone presses Verify there.")
    state.show_flash(BUTTON_WHERE)


def card(req: dict[str, Any], status_html: str, buttons) -> None:
    """A proposed signal in the Review Queue: its wording, who proposed it, and Verify / Reject (or Open It)."""
    with st.container(border=True, key=f"proposal_{req['id']}"):
        box, right = st.columns([4, 1.6], vertical_alignment="center")
        box.markdown(f"**{md_escape(req['statement'])}**  \n<small>New signal · proposed by {md_escape(req['author'])} · "
                     f"{status_html}" + (f" · by {md_escape(req['reviewer'])}" if req.get("reviewer") else "") + "</small>",
                     unsafe_allow_html=True,
                     help="Every fact of the new row: " + "; ".join(f"{label}: {req['values'].get(f)}"
                                                                    for f, label in newsignal.FIELDS
                                                                    if req["values"].get(f) not in (None, "")))
        if req["status"] == "pending":
            with right:
                buttons(req["id"], "ns", decide, "signal")
        elif req["status"] == "approved" and req.get("row") is not None:
            right.button("Open It On Edit File", key=f"ns_open_{req['id']}", icon=":material/edit:", on_click=open_row,
                         args=(req["id"],), help=f"Row {req['row']} of sheet {req['sheet']}: fill in its other columns.")
        elif req["status"] == "rejected" and req.get("reason"):
            right.caption(f"Reason: {md_escape(req['reason'])}")
