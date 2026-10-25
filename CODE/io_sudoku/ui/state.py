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

from io_sudoku.core import readiness as readiness_mod, reviewlog
from io_sudoku.core.overrides import overrides_to_json
from io_sudoku.core.rulepack import default_pack, pack_hash
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui import editing, filerevs, history, ui_logic
from io_sudoku.ui.nav import link

VIEWS = ("Upload", "Edit File", "Preflight", "Solve", "Cabinet Layout", "Audit", "TQ Board", "Parts", "Revision",
         "Rules", "Files")
NEEDS_FILE = ("Edit File",)                  # views that are greyed out until a file is uploaded
CAB_TAB_KEY = "cab_tab"                      # which tab of Cabinet Layout is open
REV_TAB_KEY = "rev_tab"                      # which tab of Revision is open
SIM_TAB = "Revision Simulator"
RULE_TAB_KEY = "rule_tab"                    # which tab of Audit is open
CHECK_TAB, IMPACT_TAB = "Rule Check", "Rule Impact"
RULE_TABS = (CHECK_TAB, IMPACT_TAB)
TQ_TAB_KEY = "tq_tab"                        # which tab of the TQ Board is open
QUESTIONS_TAB, REVIEWED_TAB = "Questions And Sign-Off", "↺ Reviewed Before"
TQ_TABS = (QUESTIONS_TAB, REVIEWED_TAB)
# Old links keep working: a page that became a tab opens that tab; a removed page (Health) opens Upload.
OLD_VIEW_NAMES = {"Downloads": "Files", "Grid": "Cabinet Layout", "Drawings": "Cabinet Layout", "Simulator": "Revision",
                  "Rule Check": "Audit", "Rule Impact": "Audit", "Rule Radar": "Audit"}
OLD_VIEW_TABS = {"Grid": (CAB_TAB_KEY, "Slot Map"), "Drawings": (CAB_TAB_KEY, "Front & Rear Drawings"),
                 "Simulator": (REV_TAB_KEY, SIM_TAB), "Rule Check": (RULE_TAB_KEY, CHECK_TAB),
                 "Rule Impact": (RULE_TAB_KEY, IMPACT_TAB)}
SAMPLE_NAME = "Sample_MDB.xlsx"

KEYS = {"mdb_bytes": None, "mdb_name": None, "mdb_sha": None, "template_bytes": None, "pack": None, "overrides": [],
        "pins": {}, "column_overrides": {}, "rev_label": "00", "result": None, "result_key": None, "stale": False,
        "last_good": None, "rev_a_rows": None, "rev_b_bytes": None, "impact": None, "proposals": [], "lite": False,
        "selected_cabinet": None, "tq_page": 0, "tq_sev": [], "ui_error": None, "view": VIEWS[0],
        "confirm_reset": False, "rev_b_result": None, "flash": None, "rev_key": "", "sim": None, "sim_sweep": None,
        "rule_preview": None, "files_pick": None, "signoffs": {}, "solve_key": None,
        "history": [], "edit_target": None, "edit_return": None, "mdb_original": None, "edit_log": [], "scroll_to": None,
        "rc_cells": [], "tq_notes": {}, "suggestions": [], "chat": None, "chats": {}, "answer_check": None, "confirm": None,
        "inputs_by_key": {}, "blobs": {}, "ri_pick": None, "review_log": [], "edit_tq": None, "rev_preview": None,
        "rev_library": [], "file_revs": [], "signal_requests": [], "col_notes": {},
        "sim_pct": 5, "sim_seed": 1, "sim_moved": 15.0, "sim_renamed": 3.0, "sim_added": 10.0, "sim_deleted": 5.0}
STALE_REASON = "Your inputs changed after this allocation (for example the file was edited). Re-allocate to check them."

# Widget-bound keys must survive a view change (Streamlit forgets a widget's value when the widget is not drawn).
_PERSIST = ("lite", "rev_label", "tq_page", "selected_cabinet", "files_pick", "sim_pct", "sim_seed", "sim_moved",
            "sim_renamed", "sim_added", "sim_deleted")


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
    from io_sudoku.ui import drafts
    drafts.keep_alive()                          # half-typed forms survive another page or tab
    if not s.get("_url_read"):
        s["_url_read"] = True
        _open_view(st.query_params.get("view"))
        cab = st.query_params.get("cab")
        if cab:
            s["selected_cabinet"] = cab
    if s["view"] not in VIEWS:                    # a page that was moved or removed while this session was open
        _open_view(s["view"])
        if s["view"] not in VIEWS:
            s["view"] = VIEWS[0]


def _open_view(view: str | None) -> None:
    """Open a view by name, also an old name (a page that became a tab opens that tab)."""
    s = st.session_state
    if view in OLD_VIEW_TABS:
        tab_key, tab = OLD_VIEW_TABS[view]
        s[tab_key] = tab
    view = OLD_VIEW_NAMES.get(view, view)
    if view in VIEWS:
        s["view"] = view


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


def _set_mdb(data: bytes, name: str, kind: str | None = "upload") -> None:
    """A new input file.  `kind` saves it as a file revision ('upload', 'sample'; None = do not save it)."""
    s = st.session_state
    sha = ui_logic.sha256_hex(data)
    if sha != s["mdb_sha"]:
        s.update(mdb_bytes=data, mdb_name=name, mdb_sha=sha, column_overrides={}, impact=None, rev_a_rows=None,
                 signoffs={}, mdb_original=(data, name), edit_log=[], edit_target=None, sim=None, sim_sweep=None,
                 rc_cells=[], ri_pick=None)          # cells and rules picked in the old file are not in the new one
        if kind:
            save_file_rev(kind)
        mark_stale()


# ------------------------------------------------------------------ saved file revisions (ui.filerevs)
def upload_sha() -> str:
    original = st.session_state.get("mdb_original")
    return ui_logic.sha256_hex(original[0]) if original else (st.session_state.get("mdb_sha") or "")


def save_file_rev(kind: str, note: str = "", data: bytes | None = None, file_name: str | None = None,
                  origin_sha: str | None = None) -> filerevs.FileRev | None:
    """Keep a file version as a revision (the current input when `data` is None).  The same bytes are kept once."""
    s = st.session_state
    data = s["mdb_bytes"] if data is None else data
    if not data:
        return None
    sha = ui_logic.sha256_hex(data)
    own = data is s["mdb_bytes"] or sha == s.get("mdb_sha")
    s["blobs"] = {**s["blobs"], sha: data}
    if own and s.get("mdb_original"):
        s["blobs"][upload_sha()] = s["mdb_original"][0]
    s["file_revs"], rev = filerevs.add(
        s["file_revs"], kind=kind, file_name=file_name or s["mdb_name"] or "MDB", sha=sha,
        origin_sha=origin_sha or (upload_sha() if own else sha), created=time.strftime("%Y-%m-%d %H:%M:%S"), note=note,
        edit_log=s["edit_log"] if own else [])
    if own:
        s["file_rev_pick"] = rev.id
    return rev


def current_file_rev() -> filerevs.FileRev | None:
    s = st.session_state
    return next((r for r in s.get("file_revs") or [] if r.sha == s.get("mdb_sha")), None)


def use_file_rev(rev_id: int | None = None) -> None:
    """Make a saved file revision the input again (the dropdown's 'Use This File').  The allocation is out of date
    (DRAFT) until you re-allocate; nothing else changes."""
    s = st.session_state
    rev_id = s.get("file_rev_pick") if rev_id is None else rev_id
    rev = next((r for r in s.get("file_revs") or [] if r.id == rev_id), None)
    where = "Saved File Revisions"
    if rev is None:
        flash("error", "Pick a saved file revision first.", where)
        return
    data = s["blobs"].get(rev.sha)
    if data is None:
        flash("error", "That file is no longer kept in this session, so it cannot be used.", where)
        return
    if rev.sha == s.get("mdb_sha"):
        flash("info", f"You are already working on {rev.name}.", where)
        return
    if rev.origin_sha == upload_sha() and s.get("mdb_original"):       # another version of the same upload
        s.update(mdb_bytes=data, mdb_sha=rev.sha, mdb_name=rev.file_name, edit_target=None)
        mark_stale()
    else:                                                                  # another file altogether
        _set_mdb(data, rev.file_name, kind=None)
        s["mdb_original"] = (s["blobs"].get(rev.origin_sha) or data, rev.file_name)
    s["edit_log"] = [dict(x) for x in rev.edit_log]
    s["file_rev_pick"] = rev.id
    flash("success", f"Now using {rev.name} ({rev.file_name}). The allocation is out of date until you press "
                     "Re-allocate.", where)


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
        flash("error", "Tick \u201cI understand\u201d first: loading a workspace replaces your saved rules, answers and pins.",
              "workspace")
        return
    ws, why = import_workspace(uploaded.getvalue())
    if ws is None:
        flash("error", why, "workspace")
        return
    s.update(pack=ws.pack, overrides=list(ws.overrides), pins=dict(ws.pins), rev_label=ws.rev_label, rev_a_rows=ws.rows)
    _load_notes(ws.notes)
    mark_stale()
    flash("success", f"Workspace loaded: {len(ws.rows):,} rows, {len(ws.overrides):,} answers, {len(ws.pins):,} pins. "
                     f"Upload the MDB again, or use the rows as Rev A on the "
                     f"{link('Revision', 'Revision', 'Compare With A New MDB')} view.", "workspace")


def notes_for_export() -> dict:
    """The engineers' TQ notes, suggestions and review memory, as saved in the workspace (notes.json)."""
    from io_sudoku.core.suggestion import to_dict
    s = st.session_state
    return {"notes": dict(s.get("tq_notes") or {}), "suggestions": [to_dict(x) for x in s.get("suggestions") or []],
            "reviews": [reviewlog.to_dict(e) for e in s.get("review_log") or []]}


def _load_notes(saved: dict) -> None:
    from io_sudoku.core.suggestion import from_dict
    s = st.session_state
    notes = saved.get("notes") if isinstance(saved, dict) else None
    if isinstance(notes, dict):
        s["tq_notes"] = {**s["tq_notes"], **{str(k): v for k, v in notes.items() if isinstance(v, dict)}}
    items = [from_dict(x) for x in (saved.get("suggestions") or []) if isinstance(x, dict)] if isinstance(saved, dict) else []
    known = {x.id for x in s["suggestions"]}
    s["suggestions"] = s["suggestions"] + [x for x in items if x is not None and x.id not in known]
    reviews = saved.get("reviews") if isinstance(saved, dict) else None
    if isinstance(reviews, list):
        seen = {json.dumps(reviewlog.to_dict(e), sort_keys=True) for e in s["review_log"]}
        fresh = [e for e in (reviewlog.from_dict(x) for x in reviews) if e is not None
                 and json.dumps(reviewlog.to_dict(e), sort_keys=True) not in seen]
        s["review_log"] = reviewlog.record(fresh, *s["review_log"])      # the saved past first, then this session


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


def on_solve(remember_run: bool = True, review: bool = True) -> None:
    """The ONLY place a solve is started.  A failure keeps the last good result on screen.  `review` = False when
    the work is only being brought back (nothing was re-allocated, so the review memory gets no new events)."""
    s = st.session_state
    if not s["mdb_bytes"]:
        s["ui_error"] = "Upload an MDB file or load the sample data first."
        return
    try:
        key = inputs_key()
        before = s["result"]
        result = ui_logic.cached_solve(
            s["mdb_bytes"], ui_logic.pack_json(s["pack"]), overrides_to_json(s["overrides"]),
            json.dumps({k: list(v) for k, v in s["pins"].items()}), json.dumps(s["column_overrides"], sort_keys=True),
            s["rev_label"])
        s.update(result=result, solve_key=key, last_good=result, stale=False, ui_error=None)
        refresh_readiness()
        if remember_run:
            remember(result, "Allocation run", s["mdb_name"] or "MDB", s["mdb_sha"] or "", key)
            _keep_inputs(key)
        if review:
            s["review_log"] = reviewlog.after_solve(s["review_log"], before, result, revision_name(), time.strftime("%Y-%m-%d %H:%M"))
        if s["selected_cabinet"] not in ui_logic.cabinet_names(result.rows) and not str(s["selected_cabinet"] or "").endswith("All Cabinet Drawings"):
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


# ------------------------------------------------------------------ review memory (core.reviewlog)
def revision_name() -> str:
    """The saved revision the allocation on screen belongs to, with its file ('Revision 2 · Sample_MDB.xlsx')."""
    s = st.session_state
    snap = next((x for x in reversed(s.get("history") or []) if x.solve_key == s.get("solve_key")), None)
    name = snap.name if snap is not None else "Not saved yet"
    return f"{name} · {s.get('mdb_name') or 'MDB'}"


def reviewer() -> str:
    s = st.session_state
    return (s.get("note_by") or s.get("answer_by") or "").strip()


def note_review(tq_id: str, ref: str, action: str, detail: str = "", by: str | None = None,
                changes: list[dict] | None = None) -> None:
    """Write one review decision down (what, who, when, which revision, where the signal sat) with the exact cells
    of the signal that were changed before it (`changes`; None = look them up in Your Changes)."""
    s = st.session_state
    if changes is None:
        changes = changes_before(ref)
    event = reviewlog.make_event(s["result"], tq_id, ref, action, detail=detail, by=reviewer() if by is None else by,
                                 time=time.strftime("%Y-%m-%d %H:%M"), revision=revision_name(), changes=changes)
    s["review_log"] = reviewlog.record(s["review_log"], event)


def _as_change(entry: dict) -> dict:
    """One line of Your Changes (edit_log) as a review change."""
    return {"Sheet": str(entry.get("Sheet", "")), "Row": str(entry.get("Row", "")), "Column": str(entry.get("Column", "")),
            "Before": str(entry.get("Old Value", "")), "After": str(entry.get("New Value", "")),
            "When": str(entry.get("Time", ""))}


def changes_before(ref: str) -> list[dict]:
    """The cells of this signal's own row that were changed (Your Changes) and that no earlier decision on it lists
    yet: so an Approve made after an edit shows exactly what was edited before it."""
    s = st.session_state
    if not s.get("mdb_bytes") or not s.get("edit_log"):
        return []
    try:
        index = ui_logic.edit_index(s["mdb_bytes"], json.dumps(s["column_overrides"], sort_keys=True), ui_logic.pack_json(s["pack"]))
        where = index.tags.get(reviewlog.item_key(ref))
    except Exception:  # noqa: BLE001 - without the index the decision is still written down
        return []
    if where is None:
        return []
    key = reviewlog.item_key(ref)
    listed = {reviewlog.change_key(c) for e in s["review_log"] if e.item == key for c in e.changes}
    out = [_as_change(x) for x in s["edit_log"] if (x.get("Sheet"), x.get("Row")) == tuple(where)]
    return [c for c in out if reviewlog.change_key(c) not in listed]


def remember(result, source: str, file_name: str, input_sha: str, solve_key: str) -> None:
    """Store a run in the revision history ('Original', 'Revision 1' ...)."""
    s = st.session_state
    snap = history.make_snapshot(s["history"], result, source=source, file_name=file_name, input_sha=input_sha,
                                 solve_key=solve_key, created=time.strftime("%H:%M:%S"))
    s["history"] = history.add(s["history"], snap)


# ------------------------------------------------------------------ undo / delete revisions
_INPUT_KEYS = ("mdb_sha", "mdb_name", "pack", "overrides", "pins", "column_overrides", "rev_label", "signoffs", "edit_log")


def _keep_inputs(solve_key: str) -> None:
    """Remember exactly what this allocation was made from, so Undo can go back to it.  Each file version is
    stored once (by fingerprint); versions no saved revision needs are let go."""
    s = st.session_state
    if not s["mdb_bytes"]:
        return
    s["blobs"] = {**s["blobs"], s["mdb_sha"]: s["mdb_bytes"]}
    s["inputs_by_key"] = {**s["inputs_by_key"], solve_key: copy.deepcopy({k: s[k] for k in _INPUT_KEYS})}
    _forget_unused()


def _forget_unused() -> None:
    s = st.session_state
    keys = {x.solve_key for x in s["history"]}
    s["inputs_by_key"] = {k: v for k, v in s["inputs_by_key"].items() if k in keys}
    wanted = {v["mdb_sha"] for v in s["inputs_by_key"].values()} | {s["mdb_sha"]} | filerevs.shas(s.get("file_revs") or [])
    s["blobs"] = {k: v for k, v in s["blobs"].items() if k in wanted}


def can_undo_revision() -> bool:
    s = st.session_state
    return len(s["history"]) >= 2 and any(x.solve_key in s["inputs_by_key"] for x in s["history"][:-1])


def undo_last_revision() -> None:
    """Remove the newest revision and go back to the one before it: its file, answers, pins, rules and
    sign-offs come back and are allocated again (the result is the same, the solver is deterministic)."""
    s = st.session_state
    if not can_undo_revision():
        flash("info", "There is no earlier revision to go back to.", "Saved Revisions")
        return
    last, rest = s["history"][-1], s["history"][:-1]
    target = next(x for x in reversed(rest) if x.solve_key in s["inputs_by_key"])
    inputs = copy.deepcopy(s["inputs_by_key"][target.solve_key])
    data = s["blobs"].get(inputs["mdb_sha"])
    if data is None:
        flash("error", "The file of that revision is no longer kept, so it cannot be restored.", "Saved Revisions")
        return
    s["history"] = rest
    s.update(mdb_bytes=data, **inputs)
    s["hist_pick"] = target.id
    on_solve(remember_run=False)
    s["stale"] = s["result"] is not None and inputs_key() != s.get("solve_key")
    refresh_readiness()
    _forget_unused()
    flash("success", f"Undone: {last.name} was removed. You are back on {target.name}, with its file, answers, pins and "
                     "rules.", "Saved Revisions")


def delete_revisions(ids: list[int]) -> None:
    """Remove saved revisions from the history (the current allocation on screen stays as it is)."""
    s = st.session_state
    wanted = set(ids)
    gone = [x.name for x in s["history"] if x.id in wanted]
    s["history"] = [x for x in s["history"] if x.id not in wanted]
    s["hist_delete"] = []
    _forget_unused()
    flash("success", f"Deleted {len(gone):,} revision(s): {', '.join(gone)}." if gone else "Nothing was deleted.",
          "Saved Revisions")


def signoff_widget_key(warning_key: str) -> str:
    return "signoff_" + ui_logic.sha256_hex(warning_key)[:12]


SIGNOFF_LABELS = {readiness_mod.APPROVED: "✓ Approve", readiness_mod.PROBLEM: "✗ Problem"}


def on_signoff(warning_key: str) -> None:
    """One warning's Approve / Problem buttons changed (pressing the chosen one again clears it)."""
    s = st.session_state
    picked = s.get(signoff_widget_key(warning_key))
    decision = next((d for d, label in SIGNOFF_LABELS.items() if label == picked), None)
    before = s["signoffs"].get(warning_key)
    signoffs = {k: v for k, v in s["signoffs"].items() if k != warning_key}
    if decision:
        signoffs[warning_key] = decision
    s["signoffs"] = signoffs
    if decision != before:
        tq_id, _, ref = warning_key.partition("|")
        note_review(tq_id, ref, decision or "cleared")
    refresh_readiness()


def approve_all_warnings() -> None:
    s = st.session_state
    if s["result"] is None:
        return
    keys = {readiness_mod.warning_key(w) for w in readiness_mod.warnings_of(s["result"])}
    for key in sorted(k for k in keys if s["signoffs"].get(k) != readiness_mod.APPROVED):
        tq_id, _, ref = key.partition("|")
        note_review(tq_id, ref, readiness_mod.APPROVED, "Approve All Warnings")
    s["signoffs"] = {**s["signoffs"], **{k: readiness_mod.APPROVED for k in keys}}
    s["approve_all_ok"] = False
    refresh_readiness()
    flash("success", f"{len(keys):,} warnings approved.", "Sign Off The Warnings")


# ------------------------------------------------------------------ editing the uploaded file
def open_editor(target: editing.Target | None = None, return_view: str | None = None) -> None:
    """Every edit happens on the Edit File view; it remembers where you came from to send you back."""
    s = st.session_state
    s["edit_return"] = return_view or s.get("view")
    s["edit_target"] = target
    s["edit_tq"] = None                          # edit_for_tq sets it again: which question this edit fixes
    s["edit_search"], s["edit_row"], s["edit_cols"] = "", 0, []    # never keep the search of an earlier visit
    if target is not None and target.row is None and target.search:
        s["edit_search"] = target.search
        sheets = ui_logic.editable_sheets(s["mdb_bytes"]) if s["mdb_bytes"] else []
        sheet = next((x for x in sheets if x.name == target.sheet), None)
        if sheet is not None:
            if len(sheets) > 1:
                s["edit_sheet"] = sheet.name
            s["edit_cols"] = _headers_for(sheet, target.show)
    s["view"] = "Edit File"
    s["scroll_to"] = "__top__"                   # start at the top of the editor, not where the last page was


def _headers_for(sheet: editing.EditSheet, fields: tuple[str, ...]) -> list[str]:
    """The sheet's own header names of some MDB fields (for 'Show Only These Columns')."""
    try:
        mapping = ui_logic.edit_index(st.session_state["mdb_bytes"], json.dumps(st.session_state["column_overrides"], sort_keys=True),
                                      ui_logic.pack_json(st.session_state["pack"])).mapping
    except Exception:  # noqa: BLE001
        return []
    out = []
    for f in fields:
        match = mapping.get(f)
        if match is not None and match.index is not None and match.index < len(sheet.headers):
            out.append(sheet.headers[match.index])
    return list(dict.fromkeys(out))


def fix_plan(tq_id: str, ref: str, nth: int = 0) -> editing.Fix:
    """Where the Edit button of a TQ leads (a cell, the rows of a cable, a cabinet or a page)."""
    s = st.session_state
    if not s["mdb_bytes"] or s["result"] is None:
        return editing.Fix("none", why="Upload a file first.")
    try:
        index = ui_logic.edit_index(s["mdb_bytes"], json.dumps(s["column_overrides"], sort_keys=True), ui_logic.pack_json(s["pack"]))
        return editing.where_to_fix(tq_id, ref, index, ui_logic.editable_sheets(s["mdb_bytes"]), s["result"].rows,
                                    s["result"].quarantined, nth)
    except Exception:  # noqa: BLE001 - without a plan the editor still opens with a search
        return editing.Fix("edit", editing.Target(None, None, None, ref or "", f"{tq_id} · {ref or '(no tag)'}"))


def edit_for_tq(tq_id: str, ref: str, nth: int = 0) -> None:
    """The Edit button of a TQ: open the exact cell (or the cable's rows, the cabinet, the page) it is about."""
    s = st.session_state
    plan = fix_plan(tq_id, ref, nth)
    if plan.kind == "cabinet":
        s.update(view="Cabinet Layout", selected_cabinet=plan.cabinet, scroll_to="__top__")
        s[CAB_TAB_KEY] = "Slot Map"
        flash("info", f"{tq_id}: {plan.why}", "Cabinet Layout")
    elif plan.kind == "place":
        from io_sudoku.ui import nav, search
        place = search.BY_LABEL.get(plan.place)
        if place is not None:
            nav.go(place)
            flash("info", f"{tq_id}: {plan.why}")
    elif plan.kind == "edit":
        open_editor(plan.target, s.get("view"))
        s["edit_tq"] = (tq_id, ref)


def leave_editor() -> None:
    s = st.session_state
    back = s.get("edit_return")
    s["edit_target"] = None
    s["edit_tq"] = None
    s["view"] = back if back in VIEWS and back != "Edit File" else "Upload"
    s["scroll_to"] = "__top__"                   # the saved message and the Re-allocate button are at the top


def apply_cell_edits(edits: list[editing.CellEdit], go_back: bool, kind: str = "edit", note: str = "") -> None:
    """Write the changed cells into the input file, log them, save the new file as a file revision, mark the result
    out of date."""
    s = st.session_state
    edits = [e for e in edits if not editing.same(e.old, e.new)]
    if not edits:
        flash("info", "Nothing was changed.", "" if go_back else "Find A Cell")
        if go_back:
            leave_editor()
        return
    try:
        data = editing.apply_edits(s["mdb_bytes"], s["mdb_name"] or "input.xlsx", edits)
    except Exception:  # noqa: BLE001
        flash("error", "The change could not be written into this file. Fix it in Excel and upload it again.",
              "Find A Cell")
        return
    replace_mdb(data)
    stamp = time.strftime("%H:%M:%S")
    s["edit_log"] = s["edit_log"] + [{"Sheet": e.sheet, "Row": e.row, "Column": e.header, "Old Value": "" if e.old is None else str(e.old),
                                      "New Value": "" if e.new is None else str(e.new), "Time": stamp, "_col": e.col}
                                     for e in edits]
    rev = save_file_rev(kind, filerevs.change_note(edits) if kind == "edit" else note)
    if s.get("edit_tq"):
        tq_id, ref = s["edit_tq"]
        note_review(tq_id, ref, "edited", "; ".join(f"row {e.row} {e.header}: '{'' if e.old is None else e.old}' → "
                                                   f"'{'' if e.new is None else e.new}'" for e in edits[:6]),
                    changes=[_as_change(x) for x in s["edit_log"][-len(edits):]])
    where = f"row {edits[0].row}, “{edits[0].header}”" if len(edits) == 1 else f"{len(edits)} cells"
    flash("success", f"Saved: {where}, as the file revision “{rev.name if rev else 'Edit'}”. The allocation is out of "
                     "date until you press Re-allocate.", "" if go_back else "Find A Cell")
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
        save_file_rev("edit")                    # the upload is already saved: this only selects it
        flash("success", "Every change was deleted: the file is back to the one you uploaded.", "Your Changes")


def undo_last_edit() -> None:
    """Put the last changed cell back to its old value (the change leaves the list)."""
    s = st.session_state
    if not s["edit_log"]:
        return
    last = s["edit_log"][-1]
    sheets = ui_logic.editable_sheets(s["mdb_bytes"])
    sheet = next((x for x in sheets if x.name == last["Sheet"]), None)
    col = last.get("_col")
    if col is None and sheet is not None and last["Column"] in sheet.headers:
        col = sheet.headers.index(last["Column"])
    values = sheet.row(last["Row"]) if sheet is not None else None
    if col is None or values is None:
        flash("error", "That change could not be undone here. Use Delete All Changes instead.", "Your Changes")
        return
    old = last["Old Value"]
    try:
        data = editing.apply_edits(s["mdb_bytes"], s["mdb_name"] or "input.xlsx",
                                   [editing.CellEdit(last["Sheet"], last["Row"], col, last["Column"], values[col],
                                                     editing.typed_value(old, values[col]) if old != "" else None)])
    except Exception:  # noqa: BLE001
        flash("error", "That change could not be undone here. Use Delete All Changes instead.", "Your Changes")
        return
    replace_mdb(data)
    s["edit_log"] = s["edit_log"][:-1]
    save_file_rev("edit", f"undo of row {last['Row']} “{last['Column']}”")
    flash("success", f"Undone: row {last['Row']}, “{last['Column']}” is “{old or '(empty)'}” again.", "Your Changes")


def reset_page(key: str) -> None:
    """Back to page 1 (after a filter changed)."""
    st.session_state[key] = 0


def go_to(view: str, tab: str | None = None) -> None:
    """Open another view (used by the clickable summary boxes); `tab` opens a tab of Cabinet Layout."""
    if view in VIEWS:
        st.session_state["view"] = view
        if tab:
            st.session_state[CAB_TAB_KEY] = tab
        if view == "TQ Board":
            st.session_state[TQ_TAB_KEY] = QUESTIONS_TAB


def on_sample() -> None:
    _set_mdb(sample_mdb_bytes(), SAMPLE_NAME, kind="sample")
    on_solve()


def reset_session() -> None:
    from io_sudoku.ui import drafts
    s = st.session_state
    for key in [k for k in list(s.keys()) if isinstance(k, str) and (drafts.DRAFT_KEYS.match(k) or k in drafts.FORM_DATA)]:
        try:
            del s[key]                           # the half-typed forms go too
        except Exception:  # noqa: BLE001
            pass
    for key, default in KEYS.items():
        s[key] = copy.deepcopy(default)
    s["pack"] = default_pack()
    s["_url_read"] = True
    st.cache_data.clear()


def flash(kind: str, message: str, where: str = "") -> None:
    """Queue one message for the next run (callbacks run before the page is drawn).

    `where` names the section it belongs to: the message is drawn right under that section's heading
    (by show_flash(where)), next to the boxes it is about.  '' = the top of the page."""
    st.session_state["flash"] = (kind, message, where)


def show_flash(where: str = "") -> None:
    """Draw the waiting message if it belongs here (call it right under a section heading)."""
    pending = st.session_state.get("flash")
    if pending and (pending[2] if len(pending) > 2 else "") == where:
        kind, message = pending[0], pending[1]
        {"error": st.error, "warning": st.warning, "info": st.info}.get(kind, st.success)(message)
        st.session_state["flash"] = None


def flush_flash() -> None:
    """End of a run: a message whose section was not drawn (you moved on) pops up as a small toast."""
    pending = st.session_state.get("flash")
    if pending:
        st.session_state["flash"] = None
        icon = {"error": "⚠️", "warning": "⚠️", "info": "ℹ️"}.get(pending[0], "✅")
        st.toast(pending[1], icon=icon)


AI_KEYS = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY")


def secret(name: str) -> str | None:
    """A deployment secret (Streamlit secrets, then environment); None when it is not configured.
    IO_SUDOKU_AI_OFF=1 hides the AI keys (the test suite sets it, so tests never call a real AI)."""
    if name in AI_KEYS and os.environ.get("IO_SUDOKU_AI_OFF"):
        return None
    try:
        value = st.secrets.get(name)
    except Exception:  # noqa: BLE001 - no secrets file is normal on a laptop
        value = None
    return str(value) if value else os.environ.get(name)
