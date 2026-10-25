"""Unfinished work is never lost: what you were typing is kept when you open another page or tab, and saved on
this computer so it comes back after the browser, the laptop or the app was closed.

Two parts:
  keep_alive()   every run, the half-typed forms (Columns And Checks, Add A Signal, Engineering Settings, the
                 Notes, your name ...) are kept in the session.  Streamlit forgets a widget's value when the widget
                 is not drawn (another page, another tab); writing the value back each run stops that.
  autosave       the browser keeps a random id (localStorage).  On the first run of a new session a tiny frame
                 types that id into a hidden box; the work saved under that id is brought back (the file, the
                 answers, sign-offs, rules waiting in the Review Queue, the review memory and the half-typed
                 forms) and the allocation is re-run (the solver is deterministic, so it is the same result).  After
                 every run the work is saved again when it changed (DRAFT_DIR/<id>.json, the file next to it).

What is kept is only what you made in this app; a damaged or strange save is ignored, never a crash.  The
saved revisions list, the Revision Library and the earlier file versions stay in the session only (download the
workspace to keep those).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import streamlit as st

ID_BOX = "draft_id_box"
BOX_KEY = "iosg_drafts"
VERSION = 1
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_AGE_DAYS = 30
_ID = re.compile(r"^[a-f0-9]{32}$")

# The half-typed forms: widget keys (written back every run) ...
DRAFT_KEYS = re.compile(
    r"^(rule_author|rule_group|rule_tpl|ai_request|"
    r"cb_(target|name|type|unit|note|find|show|default|set_value|paste|ai_request|match|sort|apply_to)|"
    r"cb_[fcq]\d+_(col|how|text|val|kind|v|v2|list|sev|scope)|"
    r"ns_(tag|io_type|tech_room|cable_no|pair_no|cable_size|segregation|instrument_type|signal_type|service)|"
    r"rf_[a-z_]+|cn_pick|cn_[0-9a-f]{8}_(check|v|v2|unit|who|tags|blank|sev|how|col|text)|"
    r"note_by|answer_by|assistant_by)$")
# ... and plain session values that belong to them (kept by Streamlit anyway; saved to disk with the forms).
FORM_DATA = ("cb_values", "cb_fills", "cb_checks", "cb_filters", "cb_picked", "cb_uid", "cb_type_last",
             "rule_group_last", "col_notes")


def draft_dir() -> Path:
    return Path(os.environ.get("IO_SUDOKU_DRAFT_DIR") or (Path.home() / ".io_sudoku" / "drafts"))


# ------------------------------------------------------------------------------------------- in the session
def keep_alive() -> None:
    """Write every half-typed form value back, so Streamlit keeps it while its page or tab is not drawn."""
    s = st.session_state
    for key in [k for k in list(s.keys()) if isinstance(k, str) and DRAFT_KEYS.match(k)]:
        try:
            s[key] = s[key]
        except Exception:  # noqa: BLE001 - a value Streamlit will not take back is simply not kept
            pass


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def forms() -> dict[str, Any]:
    s = st.session_state
    out = {}
    for key in list(s.keys()):
        if isinstance(key, str) and (DRAFT_KEYS.match(key) or key in FORM_DATA) and _json_safe(s[key]):
            out[key] = s[key]
    return out


def has_form_work(saved: dict[str, Any]) -> bool:
    """Is anything really typed in the saved forms (not just their empty defaults)?"""
    settings = ("rule_group", "cb_target", "cb_type", "cb_show", "cb_match", "cb_sort", "cb_apply_to", "cb_uid",
                "cb_type_last", "rule_group_last", "cn_pick", "rule_tpl", "rule_author", "note_by", "answer_by", "assistant_by")
    for key, value in (saved or {}).items():
        if key in settings or key.startswith("rf_") or key.endswith(("_how", "_col", "_sev", "_scope", "_kind", "_who", "_blank", "_check")) \
                or (key.startswith("cn_") and key.endswith("_unit")):
            continue
        if value not in (None, "", [], {}, 0, False):
            return True
    return False


# ------------------------------------------------------------------------------------------- the whole session
def collect() -> tuple[dict[str, Any], bytes | None]:
    """(what is saved, the input file's bytes)."""
    from io_sudoku.core import reviewlog
    from io_sudoku.core.overrides import overrides_to_json
    from io_sudoku.core.rulepack import pack_to_dict
    from io_sudoku.core.suggestion import to_dict as suggestion_dict
    s = st.session_state
    work = {
        "version": VERSION, "saved_at": time.strftime("%Y-%m-%d %H:%M"), "view": s.get("view"),
        "mdb_name": s.get("mdb_name"), "mdb_sha": s.get("mdb_sha"), "edit_log": list(s.get("edit_log") or []),
        "column_overrides": dict(s.get("column_overrides") or {}), "rev_label": s.get("rev_label") or "00",
        "pack": pack_to_dict(s["pack"]) if s.get("pack") is not None else None,
        "overrides": overrides_to_json(s.get("overrides") or []),
        "pins": {k: list(v) for k, v in (s.get("pins") or {}).items()}, "signoffs": dict(s.get("signoffs") or {}),
        "proposals": [asdict(p) for p in s.get("proposals") or []],
        "signal_requests": list(s.get("signal_requests") or []),
        "suggestions": [suggestion_dict(x) for x in s.get("suggestions") or []],
        "tq_notes": dict(s.get("tq_notes") or {}),
        "review_log": [reviewlog.to_dict(e) for e in s.get("review_log") or []],
        "forms": forms(),
    }
    return work, (s.get("mdb_bytes") or None)


def worth_saving(work: dict[str, Any], data: bytes | None) -> bool:
    return bool(data or work.get("proposals") or work.get("signal_requests") or work.get("review_log")
                or work.get("tq_notes") or has_form_work(work.get("forms") or {}))


def _paths(draft_id: str) -> tuple[Path, Path]:
    base = draft_dir()
    return base / f"{draft_id}.json", base / f"{draft_id}.mdb"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def save() -> None:
    """Save the work under this browser's id when it changed (end of every run).  Never raises."""
    s = st.session_state
    draft_id = s.get("_draft_id")
    if not draft_id or not _ID.match(draft_id):
        return
    try:
        work, data = collect()
        body = json.dumps(work, sort_keys=True, default=str).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        if digest == s.get("_draft_hash"):
            return
        page, blob = _paths(draft_id)
        if not worth_saving(work, data):
            for p in (page, blob):
                p.unlink(missing_ok=True)
        else:
            if data and len(data) <= MAX_FILE_BYTES and work.get("mdb_sha") != s.get("_draft_file_sha"):
                _write(blob, data)
                s["_draft_file_sha"] = work.get("mdb_sha")
            if not data:
                blob.unlink(missing_ok=True)
            _write(page, body)
        s["_draft_hash"] = digest
    except Exception:  # noqa: BLE001 - saving is a convenience; the app must never break because of it
        pass


def _prune() -> None:
    try:
        cutoff = time.time() - MAX_AGE_DAYS * 86400
        for path in draft_dir().glob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def load(draft_id: str) -> tuple[dict[str, Any] | None, bytes | None]:
    """The work saved under this id (None when there is none or it is damaged)."""
    if not _ID.match(draft_id or ""):
        return None, None
    page, blob = _paths(draft_id)
    try:
        work = json.loads(page.read_text(encoding="utf-8"))
        if not isinstance(work, dict) or work.get("version") != VERSION:
            return None, None
        data = blob.read_bytes() if blob.exists() else None
        if data is not None and work.get("mdb_sha"):
            from io_sudoku.ui import ui_logic
            if ui_logic.sha256_hex(data) != work["mdb_sha"]:
                data = None
        return work, data
    except Exception:  # noqa: BLE001
        return None, None


def restore(work: dict[str, Any], data: bytes | None) -> list[str]:
    """Put the saved work back into this (fresh) session; returns what came back, in words."""
    from io_sudoku.core import reviewlog
    from io_sudoku.core.overrides import overrides_from_json
    from io_sudoku.core.rulechange import RuleProposal
    from io_sudoku.core.rulepack import pack_from_dict, validate_pack
    from io_sudoku.core.suggestion import from_dict as suggestion_from
    from io_sudoku.ui import state, ui_logic
    s = st.session_state
    back: list[str] = []

    def attempt(what, fn):
        try:
            fn()
        except Exception:  # noqa: BLE001 - one damaged part does not stop the rest from coming back
            pass

    def pack():
        if work.get("pack"):
            p = pack_from_dict(work["pack"])
            if not validate_pack(p):
                s["pack"] = p

    def inputs():
        s["overrides"] = list(overrides_from_json(work.get("overrides") or "[]"))
        s["pins"] = {str(k): (str(v[0]), int(v[1])) for k, v in (work.get("pins") or {}).items()}
        s["signoffs"] = {str(k): str(v) for k, v in (work.get("signoffs") or {}).items()}
        s["column_overrides"] = {str(k): str(v) for k, v in (work.get("column_overrides") or {}).items()}
        s["rev_label"] = str(work.get("rev_label") or "00")[:8]

    def queue():
        fields = set(RuleProposal.__dataclass_fields__)
        s["proposals"] = [RuleProposal(**{k: v for k, v in p.items() if k in fields}) for p in work.get("proposals") or []
                          if isinstance(p, dict)]
        s["signal_requests"] = [r for r in work.get("signal_requests") or [] if isinstance(r, dict) and r.get("id")]
        if s["proposals"] or s["signal_requests"]:
            back.append(f"{len(s['proposals']) + len(s['signal_requests']):,} proposals in the Review Queue")

    def memory():
        s["suggestions"] = [x for x in (suggestion_from(d) for d in work.get("suggestions") or [] if isinstance(d, dict)) if x]
        s["tq_notes"] = {str(k): v for k, v in (work.get("tq_notes") or {}).items() if isinstance(v, dict)}
        s["review_log"] = [e for e in (reviewlog.from_dict(d) for d in work.get("review_log") or []) if e is not None]

    def forms_back():
        saved = work.get("forms") or {}
        for key, value in saved.items():
            if isinstance(key, str) and (DRAFT_KEYS.match(key) or key in FORM_DATA):
                s[key] = value
        if has_form_work(saved):
            back.append("the forms you were filling in")

    for what, fn in (("pack", pack), ("inputs", inputs), ("queue", queue), ("memory", memory), ("forms", forms_back)):
        attempt(what, fn)
    if data:
        def file_back():
            name = str(work.get("mdb_name") or "MDB.xlsx")
            sha = ui_logic.sha256_hex(data)
            s.update(mdb_bytes=data, mdb_name=name, mdb_sha=sha, mdb_original=(data, name),
                     edit_log=[dict(x) for x in work.get("edit_log") or [] if isinstance(x, dict)])
            state.save_file_rev("upload", "brought back after the app was closed")
            state.on_solve(review=False)
            back.insert(0, f"your file {name}" + (" and its allocation" if s.get("result") is not None else ""))
        attempt("file", file_back)
    view = work.get("view")
    if view in state.VIEWS and (view not in state.NEEDS_FILE or s.get("mdb_bytes")):
        s["view"] = view
    return back


def on_id() -> None:
    """The hidden box got this browser's id: remember it and bring back the work saved under it."""
    s = st.session_state
    draft_id = str(s.get(ID_BOX) or "").strip().lower()
    if not _ID.match(draft_id) or s.get("_draft_id"):
        return
    s["_draft_id"] = draft_id
    _prune()
    if s.get("mdb_bytes") or s.get("proposals") or s.get("signal_requests"):
        return                                       # this session already has work of its own: keep it
    work, data = load(draft_id)
    if not work:
        return
    back = restore(work, data)
    if back:
        s["_restored"] = (work.get("saved_at") or "", back)


def start_fresh() -> None:
    """Forget the work that was brought back: an empty session, and nothing saved under this browser any more."""
    from io_sudoku.ui import state
    s = st.session_state
    draft_id = s.get("_draft_id")
    if draft_id and _ID.match(draft_id):
        for p in _paths(draft_id):
            p.unlink(missing_ok=True)
    state.reset_session()
    s["_restored"] = None
    s["_draft_hash"] = None


def dismiss() -> None:
    st.session_state["_restored"] = None


def banner() -> None:
    """After work was brought back: what came back, with OK and Start Fresh Instead."""
    info = st.session_state.get("_restored")
    if not info:
        return
    saved_at, back = info
    with st.container(border=True, key="drafts_banner"):
        a, b, c = st.columns([5, 1, 1.6], vertical_alignment="center")
        a.markdown(f"↺ **Welcome back.** Your unfinished work from {saved_at} was brought back: {', '.join(back)}.",
                   help="The app saves your work on this computer after every change, so closing the browser, the "
                        "laptop or the app loses nothing.")
        b.button("OK", key="drafts_ok", on_click=dismiss)
        c.button("Start Fresh Instead", key="drafts_fresh", on_click=start_fresh,
                 help="Empties the app and forgets the saved work.")


def render_bridge() -> None:
    """Until this browser's id is known: the hidden box and the tiny frame that types the id into it (sidebar)."""
    if st.session_state.get("_draft_id"):
        return
    with st.container(key=BOX_KEY):
        st.text_input("Draft id", key=ID_BOX, on_change=on_id, label_visibility="collapsed")
    st.iframe(BRIDGE, height=1)


# Reads this browser's id from the app page's localStorage (making one the first time) and types it into the hidden
# box, then presses Enter, which runs on_id.  Nothing else is read or written.
BRIDGE = r"""<!DOCTYPE html><html><body><script>(function(){
var w, d, id;
try { w = window.parent; d = w.document; } catch (e) { return; }
try {
  id = w.localStorage.getItem('iosg_draft_id');
  if (!id || !/^[a-f0-9]{32}$/.test(id)) {
    var b = new Uint8Array(16); w.crypto.getRandomValues(b);
    id = Array.prototype.map.call(b, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
    w.localStorage.setItem('iosg_draft_id', id);
  }
} catch (e) { return; }
var n = 0;
(function put() {
  var i = d.querySelector('.st-key-draft_id_box input');
  if (!i) { if (++n < 60) setTimeout(put, 100); return; }
  if (i.value === id) return;
  var set = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, 'value').set;
  set.call(i, id); i.dispatchEvent(new w.Event('input', {bubbles: true}));
  setTimeout(function () {
    i.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
  }, 30);
})();
})();</script></body></html>"""
