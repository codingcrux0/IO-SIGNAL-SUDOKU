"""The 'Saved File Revisions' box (Upload and Edit File): pick any saved version of the input file in a dropdown and
use it instead of the current file.  The versions themselves are kept by state.save_file_rev (see ui/filerevs.py)."""
from __future__ import annotations

import streamlit as st

from io_sudoku.ui import state
from io_sudoku.ui.views._common import md_escape

WHERE = "Saved File Revisions"


def picker(prefix: str) -> None:
    """The dropdown of saved file revisions, with Use This File and Download This File."""
    s = st.session_state
    revs = list(s.get("file_revs") or [])
    current = state.current_file_rev()
    with st.container(border=True, key=f"{prefix}_file_revs"):
        st.markdown(f"**{WHERE}**", help="Every version of your input file in this session is kept as a revision: the "
                    "file you uploaded, the file after each Save on Edit File, a signal added on the Rules page, a "
                    "Suggested Fixed File you chose to use, and each Rev B MDB you compared. Pick one and press Use "
                    "This File to work on it instead of the current file. Nothing is lost: the current file stays in "
                    "the list.")
        state.show_flash(WHERE)
        if not revs:
            st.caption("No saved file yet. Upload a file or load the sample data.")
            return
        by_id = {r.id: r for r in revs}
        ids = [r.id for r in reversed(revs)]                         # newest first
        key = f"{prefix}_file_rev_pick"
        if s.get(key) not in by_id:
            s[key] = current.id if current is not None else ids[0]
        st.caption("You are working on: **" + md_escape(current.label if current else (s.get("mdb_name") or "your file"))
                   + "**")
        pick = st.selectbox(f"Pick A Saved File ({len(revs):,})", ids, key=key,
                            format_func=lambda i: ("● " if current is not None and i == current.id else "") + by_id[i].label,
                            help="● = the file you are working on now. Newest first.")
        rev = by_id.get(pick)
        if rev is None:
            return
        if rev.edit_log:
            st.caption(f"{len(rev.edit_log):,} change(s) made to the uploaded file in this version.")
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            in_use = current is not None and rev.id == current.id
            st.button("Use This File", key=f"{prefix}_file_rev_use", type="primary", on_click=state.use_file_rev,
                      args=(rev.id,), disabled=in_use, icon=":material/swap_horiz:",
                      help="You are already working on this file." if in_use else
                      "Work on this file instead of the current one. The allocation is out of date until you re-allocate.")
            data = s["blobs"].get(rev.sha)
            if data is not None:
                stem, _, ext = (rev.file_name or "MDB.xlsx").rpartition(".")
                safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rev.name)
                st.download_button("Download This File", data=data, file_name=f"{stem or rev.file_name}_{safe}.{ext or 'xlsx'}",
                                   key=f"{prefix}_file_rev_dl", on_click="ignore", icon=":material/download:")
