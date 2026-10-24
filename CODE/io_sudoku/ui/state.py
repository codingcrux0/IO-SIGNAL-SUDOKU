"""Session-state contract (BLUEPRINT 7.1): results live in st.session_state, solve runs only in a callback.

Why: Streamlit re-runs the whole script on every click.  If a view computed the result, every
click would recompute it and the grid would reset.  Here views only READ `result`; the single
writer is `on_solve`, which a button triggers with on_click."""
from __future__ import annotations

import copy
import json
import os

import streamlit as st

from io_sudoku.core.overrides import overrides_to_json
from io_sudoku.core.rulepack import default_pack, pack_hash
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui import ui_logic

VIEWS = ("Upload", "Preflight", "Solve", "Grid", "TQ Board", "Health", "Drawings", "Parts", "Revision", "Simulator", "Rules",
         "Downloads")
SAMPLE_NAME = "Sample_MDB.xlsx"

KEYS = {"mdb_bytes": None, "mdb_name": None, "mdb_sha": None, "template_bytes": None, "pack": None, "overrides": [],
        "pins": {}, "column_overrides": {}, "rev_label": "00", "result": None, "result_key": None, "stale": False,
        "last_good": None, "rev_a_rows": None, "rev_b_bytes": None, "impact": None, "proposals": [], "lite": False,
        "selected_cabinet": None, "tq_page": 0, "tq_filter": "all", "ui_error": None, "view": VIEWS[0],
        "confirm_reset": False, "health": None, "rev_b_result": None, "flash": None, "rev_key": "", "sim": None,
        "rule_preview": None}

# Widget-bound keys must survive a view change (Streamlit forgets a widget's value when the widget is not drawn).
_PERSIST = ("lite", "rev_label", "tq_filter", "tq_page", "selected_cabinet")


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
        s.update(mdb_bytes=data, mdb_name=name, mdb_sha=sha, column_overrides={}, impact=None, rev_a_rows=None)
        s["stale"] = s["result"] is not None


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
                     "Upload the MDB again, or use the rows as Rev A on the Revision view.")


def mark_stale() -> None:
    if st.session_state["result"] is not None:
        st.session_state["stale"] = True


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
        s.update(result=result, result_key=key, last_good=result, stale=False, ui_error=None)
        if s["selected_cabinet"] not in ui_logic.cabinet_names(result.rows):
            s["selected_cabinet"] = (ui_logic.cabinet_names(result.rows) or [None])[0]
    except Exception:  # noqa: BLE001
        s["ui_error"] = "The solve stopped unexpectedly. Your last good result is still shown. Download the Support Bundle and report it."
        if s["last_good"] is not None:
            s["result"] = s["last_good"]


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
