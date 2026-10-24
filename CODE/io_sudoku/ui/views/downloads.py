"""Files: open any output in the page, or download it (one at a time or all together).

The viewer is read-only.  File names carry the readiness suffix, so a draft is never issued by mistake.
"""
from __future__ import annotations

import streamlit as st

from io_sudoku.ui import ui_logic
from io_sudoku.ui.nav import link
from io_sudoku.ui.views._common import download_button, main_ctx, readiness_block, result_or_empty
from io_sudoku.ui.views._viewer import file_viewer

INPUT = "input"


def render() -> None:
    s = st.session_state
    st.header("Files")
    result = result_or_empty("the files", "dl")
    if result is None:
        return
    readiness_block(result)
    st.caption("Open any file right here, or download it. Files from a draft result carry _DRAFT in the name, "
               f"so nobody issues them by mistake. Revision reports are on the {link('Revision', 'Revision')} view.")
    ctx = main_ctx()
    key = s["result_key"] or ""
    specs = ui_logic.available_downloads(False)
    titles = {spec.key: spec.title for spec in specs}
    if s["mdb_bytes"]:
        titles[INPUT] = f"Your Input File ({ui_logic.clip(s['mdb_name'] or 'MDB', 40)})"
    if s.get("files_pick") not in titles:
        s["files_pick"] = specs[0].key
    st.subheader("View A File")
    pick = st.selectbox("Choose A File To View", list(titles), format_func=titles.get, key="files_pick")
    if pick == INPUT:
        data, name, mime = s["mdb_bytes"], s["mdb_name"] or "input.xlsx", "application/octet-stream"
    else:
        try:
            data, name, mime = ui_logic.cached_download(key, pick, ctx)
        except Exception:  # noqa: BLE001 - one broken report must not hide the others
            st.warning(f"{titles[pick]} is not available right now.")
            data = None
    if data:
        st.download_button(f"Download {titles[pick]}", data=data, file_name=name, mime=mime, key="files_dl_one",
                           type="primary", on_click="ignore")
        file_viewer(data, name, f"files_{pick}_{key[:8]}", trusted_html=pick != INPUT)

    st.divider()
    st.subheader("Download Files")
    st.download_button("Download Everything (.zip)", data=lambda: ui_logic.bundle_all(key, ctx),
                       file_name=ui_logic.bundle_all_name(ctx), mime="application/zip", key="files_dl_all",
                       on_click="ignore", help="Every file below in one ZIP.")
    for left, right in zip(specs[0::2], list(specs[1::2]) + [None]):
        c1, c2 = st.columns(2)
        with c1:
            download_button(left, ctx, key)
        with c2:
            if right is not None:
                download_button(right, ctx, key)
