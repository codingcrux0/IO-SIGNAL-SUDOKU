"""The in-browser file viewer: look inside any output (workbook, page, JSON, ZIP) without downloading it.

Read-only by design: the official files are produced and checked by the solver and verifier, so the
viewer can search, hide columns and export a view as CSV, but it never edits a file.  Changes go
through the governed paths (TQ answers, pins, approved rules) and a re-solve.
"""
from __future__ import annotations

import streamlit as st

from io_sudoku.ui import preview as pv
from io_sudoku.ui.errors import error_boundary


@st.cache_data(max_entries=16, show_spinner=False)
def cached_preview(data: bytes, name: str) -> pv.FilePreview:
    return pv.preview_bytes(data, name)


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0] if "." in name else name


@st.fragment
def file_viewer(data: bytes, name: str, key: str, trusted_html: bool = False) -> None:
    """Show one file in the page.  Runs as a fragment, so searching does not re-run the whole app.
    `trusted_html` is True only for pages this tool generated itself (all values already escaped)."""
    with error_boundary(f"The viewer for {name}"):
        preview = cached_preview(data, name)
        st.caption(f"Viewing **{name}** · {pv.size_text(preview.size)} · read-only")
        _render(preview, data, key, trusted_html, nested=False)


def _render(preview: pv.FilePreview, data: bytes, key: str, trusted_html: bool, nested: bool) -> None:
    if preview.note:
        st.info(preview.note)
    if preview.kind == "table":
        _table(preview, key)
    elif preview.kind == "html":
        if trusted_html:
            st.iframe(preview.html, height=720)
            st.caption("This is the same page as the download. Download it to print or share.")
        else:
            st.code(preview.html[:pv.MAX_TEXT_CHARS], language="html", wrap_lines=True)
    elif preview.kind == "json":
        st.json(preview.data, expanded=2)
    elif preview.kind == "text":
        st.code(preview.text, language=None, wrap_lines=True, height=480)
    elif preview.kind == "zip":
        _zip(preview, data, key, nested)


def _table(preview: pv.FilePreview, key: str) -> None:
    sheets = preview.sheets
    names = [s.name for s in sheets]
    if len(sheets) > 1:
        picked = st.radio("Sheet", names, horizontal=True, key=f"{key}_sheet")
        sheet = sheets[names.index(picked)] if picked in names else sheets[0]
    else:
        sheet = sheets[0]
    if not sheet.columns:
        st.info("This sheet is empty.")
        return
    left, right = st.columns([2, 3])
    needle = left.multiselect("Search (case-sensitive)", [], key=f"{key}_search", accept_new_options=True,
                              placeholder="Type a tag and press Enter; add more the same way",
                              help="Each search becomes a tag you can remove with its \u2715. Rows matching any of "
                                   "the tags are shown. Capital letters count, so you get exactly what you typed.")
    shown_cols = right.multiselect("Show Only These Columns", sheet.columns, key=f"{key}_cols",
                                   placeholder="All columns")
    mark = ""
    if sheet.marks:
        present = [m for m in pv.FILLS if m in set(sheet.marks)]
        choice = st.radio("Highlighted Changes", ["All Rows"] + present, horizontal=True, key=f"{key}_mark",
                          help="Colours match the redline workbook. The Change column says the same in words.")
        mark = "" if choice == "All Rows" else choice
    cols, rows, marks = pv.filter_rows(sheet, needle, shown_cols, mark)
    shown = rows[:pv.MAX_SHOW_ROWS]
    summary = f"{len(rows):,} of {sheet.total_rows:,} rows · {len(cols):,} columns"
    if len(rows) > len(shown):
        summary += f" · showing the first {len(shown):,}; search to narrow it down"
    if sheet.truncated:
        summary += f" · only the first {len(sheet.rows):,} rows of this sheet were read"
    st.caption(summary)
    if not rows:
        st.info("No row matches. Clear the search or pick other columns.")
        return
    frame = pv.to_frame(cols, shown, marks[:len(shown)] if marks else None)
    height = min(560, 38 + 35 * len(shown))
    if marks:
        colours = [pv.mark_colour(m) for m in marks[:len(shown)]]
        styled = frame.style.apply(lambda row: [f"background-color: {colours[row.name]}; color: #111" if colours[row.name] else ""
                                                for _ in row], axis=1)
        st.dataframe(styled, hide_index=True, width="stretch", height=height)
    else:
        st.dataframe(frame, hide_index=True, width="stretch", height=height)
    st.download_button("Download This View (.csv)", data=pv.rows_to_csv(cols, rows, marks or None),
                       file_name=f"{_stem(preview.name)}_{_stem(sheet.name)}.csv".replace(" ", "_"), mime="text/csv",
                       key=f"{key}_csv", on_click="ignore",
                       help="Exactly the rows and columns shown above, after your search.")


def _zip(preview: pv.FilePreview, data: bytes, key: str, nested: bool) -> None:
    st.dataframe(preview.entries, hide_index=True, width="stretch")
    if nested or not preview.entries:
        return
    files = [e["File"] for e in preview.entries]
    member = st.selectbox("Look Inside", [""] + files, key=f"{key}_member",
                          format_func=lambda f: "Choose a file in the bundle" if not f else f)
    if member:
        inner = pv.preview_member(data, member)
        st.caption(f"**{member}** · {pv.size_text(inner.size)}")
        _render(inner, b"", f"{key}_m", trusted_html=False, nested=True)
