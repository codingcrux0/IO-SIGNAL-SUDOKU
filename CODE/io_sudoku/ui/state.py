"""Session-state contract (BLUEPRINT 7.1): results live in st.session_state, solve runs only in a callback.

Why: Streamlit re-runs the whole script on every click.  If a view computed the result, every
click would recompute it and the grid would reset.  Here views only READ `result`; the single
writer is `on_solve`, which a button triggers with on_click."""
from __future__ import annotations

import copy
import json
import os
import time

import streamlit as st

from io_sudoku.core import readiness as readiness_mod
from io_sudoku.core.overrides import overrides_to_json
from io_sudoku.core.rulepack import default_pack, pack_hash
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui import editing, history, ui_logic
from io_sudoku.ui.nav import link

VIEWS = ("Upload", "Edit File", "Preflight", "Solve", "Cabinet Layout", "TQ Board", "Health", "Parts", "Revision", "Simulator", "Rules",
         "Files")
NEEDS_FILE = ("Edit File",)                  # views that are greyed out until a file is uploaded
OLD_VIEW_NAMES = {"Downloads": "Files", "Grid": "Cabinet Layout", "Drawings": "Cabinet Layout"}   # old links keep working
CAB_TAB_KEY = "cab_tab"                      # which tab of Cabinet Layout is open
OLD_VIEW_TABS = {"Grid": "Slot Map", "Drawings": "Front & Rear Drawings"}
SAMPLE_NAME = "Sample_MDB.xlsx"

KEYS = {"mdb_bytes": None, "mdb_name": None, "mdb_sha": None, "template_bytes": None, "pack": None, "overrides": [],
        "pins": {}, "column_overrides": {}, "rev_label": "00", "result": None, "result_key": None, "stale": False,
        "last_good": None, "rev_a_rows": None, "rev_b_bytes": None, "impact": None, "proposals": [], "lite": False,
        "selected_cabinet": None, "tq_page": 0, "tq_filter": "all", "ui_error": None, "view": VIEWS[0],
        "confirm_reset": False, "health": None, "rev_b_result": None, "flash": None, "rev_key": "", "sim": None,
        "rule_preview": None, "files_pick": None, "signoffs": {}, "solve_key": None,
        "history": [], "edit_target": None, "edit_return": None, "mdb_original": None, "edit_log": [], "scroll_to": None}
STALE_REASON = "Your inputs changed after this allocation (for example the file was edited). Re-allocate to check them."

# Widget-bound keys must survive a view change (Streamlit forgets a widget's value when the widget is not drawn).
_PERSIST = ("lite", "rev_label", "tq_filter", "tq_page", "selected_cabinet", "files_pick")


def init_state() -> None:
    """Fill missing keys once, then read the view and cabinet from the URL so a link reopens the same page."""
    s = st.session_state
    for key, default in KEYS.items():
        if key not in s:
            s[key] = copy.deepcopy(default)
    if s["pack"] is None:
        s["pack"] = default_pack()
    for key in _PERSIST:
        s[key] = s[key]
    if not s.get("_url_read"):
        s["_url_read"] = True
        view = st.query_params.get("view")
        if view in OLD_VIEW_TABS:
            s[CAB_TAB_KEY] = OLD_VIEW_TABS[view]
        view = OLD_VIEW_NAMES.get(view, view)
        if view in VIEWS:
            s["view"] = view
        cab = st.query_params.get("cab")
        if cab:
            s["selected_cabinet"] = cab


def sync_url() -> None:
    """Write the selected view and cabinet into the URL (does not trigger a re-run)."""
    s = st.session_state
    params = {"view": s["view"]}
    if s.get("selected_cabinet"):
        params["cab"] = s["selected_cabinet"]
    if dict(st.query_params) != params:
        st.query_params.from_dict(params)


def inputs_key() -> str:
    s = st.session_state
    return ui_logic.sha256_hex("|".join([
        s["mdb_sha"] or "", pack_hash(s["pack"]), overrides_to_json(s["overrides"]),
        json.dumps({k: list(v) for k, v in sorted(s["pins"].items())}), json.dumps(s["column_overrides"], sort_keys=True),
        s["rev_label"]]))


def _set_mdb(data: bytes, name: str) -> None:
    s = st.session_state
    sha = ui_logic.sha256_hex(data)
    if sha != s["mdb_sha"]:
        s.update(mdb_bytes=data, mdb_name=name, mdb_sha=sha, column_overrides={}, impact=None, rev_a_rows=None,
                 signoffs={}, mdb_original=(data, name), edit_log=[], edit_target=None)
        mark_stale()


def replace_mdb(data: bytes) -> None:
    """The edited copy of the uploaded file becomes the input (name, answers and sign-offs are kept)."""
    s = st.session_state
    s.update(mdb_bytes=data, mdb_sha=ui_logic.sha256_hex(data))
    mark_stale()


def on_upload() -> None:
    uploaded = st.session_state.get("mdb_uploader")
    if uploaded is not None:
        _set_mdb(uploaded.getvalue(), uploaded.name)


def on_template_upload() -> None:
    uploaded = st.session_state.get("template_uploader")
    st.session_state["template_bytes"] = uploaded.getvalue() if uploaded is not None else None


def on_workspace_upload() -> None:
    """Continue a saved project: replaces rules, answers and pins (the Upload view asks for confirmation first)."""
    from io_sudoku.core.workspace import import_workspace
    s = st.session_state
    uploaded = s.get("workspace_uploader")
    if uploaded is None:
        return
    if not s.get("workspace_ok"):
        flash("error", "Tick \u201cI understand\u201d first: loading a workspace replaces your saved rules, answers and pins.")
        return
    ws, why = import_workspace(uploaded.getvalue())
    if ws is None:
        flash("error", why)
        return
    s.update(pack=ws.pack, overrides=list(ws.overrides), pins=dict(ws.pins), rev_label=ws.rev_label, rev_a_rows=ws.rows)
    mark_stale()
    flash("success", f"Workspace loaded: {len(ws.rows):,} rows, {len(ws.overrides):,} answers, {len(ws.pins):,} pins. "
                     f"Upload the MDB again, or use the rows as Rev A on the "
                     f"{link('Revision', 'Revision', 'Compare With A New MDB')} view.")


def mark_stale() -> None:
    """Out of date = the inputs no longer match the ones of the last allocation.  An out-of-date
    result is shown as DRAFT (it was not checked against the current inputs)."""
    s = st.session_state
    s["stale"] = s["result"] is not None and inputs_key() != s.get("solve_key")
    refresh_readiness()


def is_up_to_date() -> bool:
    """True when the last allocation used exactly the current inputs (the allocate buttons turn grey)."""
    s = st.session_state
    return s["result"] is not None and not s.get("stale") and s.get("solve_key") == inputs_key()


def on_solve() -> None:
    """The ONLY place a solve is started.  A failure keeps the last good result on screen."""
    s = st.session_state
    if not s["mdb_bytes"]:
        s["ui_error"] = "Upload an MDB file or load the sample data first."
        return
    try:
        key = inputs_key()
        result = ui_logic.cached_solve(
            s["mdb_bytes"], ui_logic.pack_json(s["pack"]), overrides_to_json(s["overrides"]),
            json.dumps({k: list(v) for k, v in s["pins"].items()}), json.dumps(s["column_overrides"], sort_keys=True),
            s["rev_label"])
        s.update(result=result, solve_key=key, last_good=result, stale=False, ui_error=None)
        refresh_readiness()
        remember(result, "Allocation run", s["mdb_name"] or "MDB", s["mdb_sha"] or "", key)
        if s["selected_cabinet"] not in ui_logic.cabinet_names(result.rows):
            s["selected_cabinet"] = (ui_logic.cabinet_names(result.rows) or [None])[0]
    except Exception:  # noqa: BLE001
        s["ui_error"] = "The solve stopped unexpectedly. Your last good result is still shown. Download the Support Bundle and report it."
        if s["last_good"] is not None:
            s["result"] = s["last_good"]


def refresh_readiness() -> None:
    """Re-classify the current result with the engineer's warning sign-offs (no re-solve needed).

    The result key gets the sign-offs too, so every file is rebuilt with the new status in its name."""
    s = st.session_state
    result = s["result"]
    if result is None:
        return
    verdict = readiness_mod.assess(result, s["signoffs"])
    if s.get("stale"):                            # out of date: never better than DRAFT (BLOCKED stays BLOCKED)
        verdict = readiness_mod.Readiness("BLOCKED" if verdict.status == "BLOCKED" else "DRAFT",
                                          (STALE_REASON,) + verdict.reasons)
    result.readiness = verdict
    s["result_key"] = ui_logic.sha256_hex((s["solve_key"] or "") + "|" + json.dumps(s["signoffs"], sort_keys=True)
                                          + ("|stale" if s.get("stale") else ""))
    past = s.get("history") or []
    if past and past[-1].solve_key == s["solve_key"] and not s.get("stale"):
        past[-1].status, past[-1].reasons = verdict.status, verdict.reasons      # keep the latest summary current


def remember(result, source: str, file_name: str, input_sha: str, solve_key: str) -> None:
    """Store a run in the revision history ('Original', 'Revision 1' ...)."""
    s = st.session_state
    snap = history.make_snapshot(s["history"], result, source=source, file_name=file_name, input_sha=input_sha,
                                 solve_key=solve_key, created=time.strftime("%H:%M:%S"))
    s["history"] = history.add(s["history"], snap)


def signoff_widget_key(warning_key: str) -> str:
    return "signoff_" + ui_logic.sha256_hex(warning_key)[:12]


SIGNOFF_LABELS = {readiness_mod.APPROVED: "✓ Approve", readiness_mod.PROBLEM: "✗ Problem"}


def on_signoff(warning_key: str) -> None:
    """One warning's Approve / Problem buttons changed (pressing the chosen one again clears it)."""
    s = st.session_state
    picked = s.get(signoff_widget_key(warning_key))
    decision = next((d for d, label in SIGNOFF_LABELS.items() if label == picked), None)
    signoffs = {k: v for k, v in s["signoffs"].items() if k != warning_key}
    if decision:
        signoffs[warning_key] = decision
    s["signoffs"] = signoffs
    refresh_readiness()


def approve_all_warnings() -> None:
    s = st.session_state
    if s["result"] is None:
        return
    keys = {readiness_mod.warning_key(w) for w in readiness_mod.warnings_of(s["result"])}
    s["signoffs"] = {**s["signoffs"], **{k: readiness_mod.APPROVED for k in keys}}
    s["approve_all_ok"] = False
    refresh_readiness()
    flash("success", f"{len(keys):,} warnings approved.")


# ------------------------------------------------------------------ editing the uploaded file
def open_editor(target: editing.Target | None = None, return_view: str | None = None) -> None:
    """Every edit happens on the Edit File view; it remembers where you came from to send you back."""
    s = st.session_state
    s["edit_return"] = return_view or s.get("view")
    s["edit_target"] = target
    if target is not None and target.row is None and target.search:
        s["edit_search"], s["edit_row"] = target.search, 0
    s["view"] = "Edit File"
    s["scroll_to"] = "__top__"                   # start at the top of the editor, not where the last page was


def edit_for_tq(tq_id: str, ref: str, nth: int = 0) -> None:
    """The Edit button of a TQ: open the exact cell it is about."""
    s = st.session_state
    target = editing.Target(None, None, None, ref or "", f"{tq_id} · {ref or '(no tag)'}")
    if s["mdb_bytes"] and s["result"] is not None:
        try:
            index = ui_logic.edit_index(s["mdb_bytes"], json.dumps(s["column_overrides"], sort_keys=True),
                                        ui_logic.pack_json(s["pack"]))
            target = editing.cell_for_tq(tq_id, ref, index, s["result"].quarantined, nth)
        except Exception:  # noqa: BLE001 - without an exact cell the editor still opens with a search
            pass
    open_editor(target, s.get("view"))


def leave_editor() -> None:
    s = st.session_state
    back = s.get("edit_return")
    s["edit_target"] = None
    s["view"] = back if back in VIEWS and back != "Edit File" else "Upload"
    s["scroll_to"] = "__top__"                   # the saved message and the Re-allocate button are at the top


def apply_cell_edits(edits: list[editing.CellEdit], go_back: bool) -> None:
    """Write the changed cells into the input file, log them, mark the result out of date."""
    s = st.session_state
    edits = [e for e in edits if not editing.same(e.old, e.new)]
    if not edits:
        flash("info", "Nothing was changed.")
        if go_back:
            leave_editor()
        return
    try:
        data = editing.apply_edits(s["mdb_bytes"], s["mdb_name"] or "input.xlsx", edits)
    except Exception:  # noqa: BLE001
        flash("error", "The change could not be written into this file. Fix it in Excel and upload it again.")
        return
    replace_mdb(data)
    stamp = time.strftime("%H:%M:%S")
    s["edit_log"] = s["edit_log"] + [{"Sheet": e.sheet, "Row": e.row, "Column": e.header, "Old Value": "" if e.old is None else str(e.old),
                                      "New Value": "" if e.new is None else str(e.new), "Time": stamp} for e in edits]
    where = f"row {edits[0].row}, “{edits[0].header}”" if len(edits) == 1 else f"{len(edits)} cells"
    flash("success", f"Saved: {where}. The allocation is now DRAFT until you press Re-allocate.")
    if go_back:
        leave_editor()


def save_jump(sheet: str, row: int, col: int, header: str, widget: str, old) -> None:
    s = st.session_state
    apply_cell_edits([editing.CellEdit(sheet, row, col, header, old, editing.typed_value(s.get(widget), old))], go_back=True)


def undo_all_edits() -> None:
    s = st.session_state
    original = s.get("mdb_original")
    if original:
        replace_mdb(original[0])
        s["edit_log"] = []
        s["undo_edits_ok"] = False
        flash("success", "Every change was undone: the file is back to the one you uploaded.")


def go_to(view: str, tab: str | None = None) -> None:
    """Open another view (used by the clickable summary boxes); `tab` opens a tab of Cabinet Layout."""
    if view in VIEWS:
        st.session_state["view"] = view
        if tab:
            st.session_state[CAB_TAB_KEY] = tab


def on_sample() -> None:
    _set_mdb(sample_mdb_bytes(), SAMPLE_NAME)
    on_solve()


def reset_session() -> None:
    s = st.session_state
    for key, default in KEYS.items():
        s[key] = copy.deepcopy(default)
    s["pack"] = default_pack()
    s["_url_read"] = True
    st.cache_data.clear()


def flash(kind: str, message: str) -> None:
    """Queue one message for the next run (callbacks run before the page is drawn)."""
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    pending = st.session_state.get("flash")
    if pending:
        kind, message = pending
        {"error": st.error, "warning": st.warning}.get(kind, st.success)(message)
        st.session_state["flash"] = None


def secret(name: str) -> str | None:
    """A deployment secret (Streamlit secrets, then environment); None when it is not configured."""
    try:
        value = st.secrets.get(name)
    except Exception:  # noqa: BLE001 - no secrets file is normal on a laptop
        value = None
    return str(value) if value else os.environ.get(name)
