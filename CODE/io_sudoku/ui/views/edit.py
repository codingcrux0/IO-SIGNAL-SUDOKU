"""Edit File: the ONE place where the uploaded file is changed.

Every Edit button in the app (Upload, the TQ Board's errors and warnings) opens this view - at the exact
cell when it knows one - and "Save" sends you back where you came from.  A change goes into the session's
copy of the file (the formatting and other sheets stay as they were), is listed under Your Changes, and
makes the allocation out of date (DRAFT) until you re-allocate.  Nothing else changes: the solver and
its rules read the edited file exactly as they read an upload.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from io_sudoku.ui import autofill, editing, state, ui_logic
from io_sudoku.ui.nav import link
from io_sudoku.ui.views import _filerev
from io_sudoku.ui.views._common import allocate_button, ask_first, heading, md_escape


def _sheet(sheets: list[editing.EditSheet], name: str | None) -> editing.EditSheet:
    return next((x for x in sheets if x.name == name), sheets[0])


def _search_values(sheet: editing.EditSheet) -> list[str]:
    """What the search box can complete: the sheet's cells exactly as written (tags and cables first)."""
    s = st.session_state
    first: list[int] = []
    try:
        mapping = ui_logic.edit_index(s["mdb_bytes"], json.dumps(s["column_overrides"], sort_keys=True),
                                      ui_logic.pack_json(s["pack"])).mapping
        first = [m.index for f in ("tag", "cable_no") if (m := mapping.get(f)) is not None and m.index is not None]
    except Exception:  # noqa: BLE001 - without the mapping every column is offered in its order
        first = []
    order = first + [i for i in range(len(sheet.headers)) if i not in first]
    out: list[str] = []
    for col in order:
        for _, row in sheet.rows:
            if col < len(row) and row[col] not in (None, ""):
                out.append(str(row[col]).strip())
        if len(out) > 6000:
            break
    return out


def render() -> None:
    s = st.session_state
    st.header("Edit Your File")
    if not s["mdb_bytes"]:
        st.info(f"Upload an MDB on the {link('Upload', 'Upload')} view, or load the sample data, to edit it here.")
        st.button("Try With Sample Data", key="sample_edit", on_click=state.on_sample)
        return
    back = s.get("edit_return")
    top_left, top_right = st.columns([3, 2], vertical_alignment="center")
    top_left.caption(f"Editing **{md_escape(s['mdb_name'] or 'your file')}**. Every Save keeps the new file as a saved "
                     f"file revision (pick any of them below); download it under "
                     f"{link('Your Changes', 'Edit File', 'Your Changes')} to keep it. "
                     "After a change the allocation is DRAFT until you re-allocate.")
    if back and back != "Edit File":
        top_right.button(f"← Back To {back}", key="edit_back", on_click=state.leave_editor)
    if s.get("edit_target") is None:
        _filerev.picker("edit")
    sheets = ui_logic.editable_sheets(s["mdb_bytes"])
    if not sheets:
        st.warning("This file cannot be shown as a table, so it cannot be edited here. Fix it in Excel and upload it again.")
        return
    target = s.get("edit_target")
    if target is not None and target.row is not None:
        _jump(target, sheets)
    elif target is not None:
        if target.show:
            st.info(f"**{md_escape(target.why)}**: this is about the whole cable, so every row of it is listed below "
                    "(only the useful columns). Change the cell that is wrong, then press Save Table Changes.")
        else:
            st.info(f"**{md_escape(target.why)}**: no single cell holds this, so the search below is filled in with it.")
    _find(sheets)
    _changes()
    st.divider()
    allocate_button("edit_allocate")


def _jump(target: editing.Target, sheets: list[editing.EditSheet]) -> None:
    """The exact cell an Edit button pointed at."""
    s = st.session_state
    sheet = _sheet(sheets, target.sheet)
    values = sheet.row(target.row)
    with st.container(border=True):
        st.markdown(f"**Fix: {md_escape(target.why)}**")
        if values is None:
            st.warning(f"Row {target.row} is no longer in the file. Use the search below.")
            return
        stamp = (s["mdb_sha"] or "")[:8]
        if target.col is not None and target.col < len(sheet.headers):
            header = sheet.headers[target.col]
            old = values[target.col]
            st.caption(f"Sheet {sheet.name} · row {target.row} · column “{header}”")
            widget = f"jump_{stamp}_{sheet.name}_{target.row}_{target.col}"
            st.text_input(f"New value for “{header}”", value="" if old is None else str(old), key=widget,
                          help="Leave it empty to clear the cell.")
            a, b, _ = st.columns([2, 1, 3])
            a.button("Save Change", key="jump_save", type="primary", on_click=state.save_jump,
                     args=(sheet.name, target.row, target.col, header, widget, old))
            b.button("Cancel", key="jump_cancel", on_click=state.leave_editor)
            with st.expander("See The Whole Row"):
                st.dataframe(pd.DataFrame({"Column": list(sheet.headers), "Value": ["" if v is None else str(v) for v in values]}),
                             hide_index=True, width="stretch", height=320)
        else:
            st.caption(f"Sheet {sheet.name} · row {target.row}. Change any value, then save.")
            frame = pd.DataFrame({"Column": list(sheet.headers), "Value": ["" if v is None else str(v) for v in values]})
            widget = f"jumprow_{stamp}_{sheet.name}_{target.row}"
            st.data_editor(frame, key=widget, disabled=["Column"], hide_index=True, width="stretch", height=360,
                           num_rows="fixed")
            a, b, _ = st.columns([2, 1, 3])
            a.button("Save Row", key="jumprow_save", type="primary", on_click=_save_row,
                     args=(sheet.name, target.row, widget))
            b.button("Cancel", key="jumprow_cancel", on_click=state.leave_editor)


def _save_row(sheet_name: str, row: int, widget: str) -> None:
    s = st.session_state
    sheet = _sheet(ui_logic.editable_sheets(s["mdb_bytes"]), sheet_name)
    values = sheet.row(row) or ()
    changed = (s.get(widget) or {}).get("edited_rows", {})
    edits = [editing.CellEdit(sheet.name, row, int(i), sheet.headers[int(i)], values[int(i)],
                              editing.typed_value(cells.get("Value"), values[int(i)]))
             for i, cells in changed.items() if "Value" in cells and int(i) < len(values)]
    state.apply_cell_edits(edits, go_back=True)


def _find(sheets: list[editing.EditSheet]) -> None:
    s = st.session_state
    heading("Find A Cell", "The search is case-sensitive, so you land on exactly the cell you typed: "
                           "'320-FT' does not find '320-ft'. It looks in every column of the sheet.")
    names = [x.name for x in sheets]
    if len(names) > 1:
        st.radio("Sheet", names, horizontal=True, key="edit_sheet")
    sheet = _sheet(sheets, s.get("edit_sheet"))
    if s.get("edit_cols"):                       # columns picked on another sheet are not offered here
        s["edit_cols"] = [h for h in s["edit_cols"] if h in sheet.headers]
    c1, c2 = st.columns([3, 1])
    autofill.offer("edit_search", _search_values(sheet))
    needle = c1.text_input("Search (case-sensitive)", key="edit_search", autocomplete="off",
                           placeholder="A tag, cable or any text, exactly as written")
    row_no = c2.number_input("Or Go To Row", min_value=0, step=1, key="edit_row", help="The row number as in Excel (0 = off).")
    cols = st.multiselect("Show Only These Columns", list(sheet.headers), key="edit_cols", placeholder="All columns")
    rows = editing.find_rows(sheet, needle, int(row_no) or None)
    shown = rows[:editing.MAX_SHOWN_ROWS]
    note = f"{len(rows):,} of {len(sheet.rows):,} rows"
    if len(rows) > len(shown):
        note += f" · showing the first {len(shown):,}; search to narrow it down"
    st.caption(note + ". Double-click a cell to change it, then press Save Table Changes. "
                      "Save before you change the search, or the unsaved changes are dropped.")
    if not shown:
        st.info("No row matches. Clear the search or the row number.")
        return
    picked = [h for h in cols if h in sheet.headers] or list(sheet.headers)
    idx = [sheet.headers.index(h) for h in picked]
    frame = pd.DataFrame({"Row": [r for r, _ in shown],
                          **{h: ["" if v[i] is None else str(v[i]) for _, v in shown] for h, i in zip(picked, idx)}})
    widget = f"edit_grid_{(s['mdb_sha'] or '')[:8]}_{abs(hash((sheet.name, needle, int(row_no), tuple(picked)))) % 10**9}"
    st.data_editor(frame, key=widget, disabled=["Row"], hide_index=True, width="stretch", num_rows="fixed",
                   height=min(520, 38 + 35 * len(frame)))
    st.button("Save Table Changes", key="edit_grid_save", type="primary", on_click=_save_grid,
              args=(sheet.name, needle, int(row_no), tuple(picked), widget))


def _save_grid(sheet_name: str, needle: str, row_no: int, picked: tuple[str, ...], widget: str) -> None:
    s = st.session_state
    sheet = _sheet(ui_logic.editable_sheets(s["mdb_bytes"]), sheet_name)
    shown = editing.find_rows(sheet, needle, row_no or None)[:editing.MAX_SHOWN_ROWS]
    edits = []
    for i, cells in (s.get(widget) or {}).get("edited_rows", {}).items():
        i = int(i)
        if i >= len(shown):
            continue
        excel_row, values = shown[i]
        for header, new in cells.items():
            if header in sheet.headers and header != "Row":
                col = sheet.headers.index(header)
                edits.append(editing.CellEdit(sheet.name, excel_row, col, header, values[col], editing.typed_value(new, values[col])))
    state.apply_cell_edits(edits, go_back=False)


def _changes() -> None:
    s = st.session_state
    heading("Your Changes")
    log = s["edit_log"]
    if not log:
        st.caption("No changes yet. The file is exactly as you uploaded it.")
        return
    st.dataframe(log, hide_index=True, width="stretch", height=min(320, 38 + 35 * len(log)),
                 column_order=[c for c in log[0] if not c.startswith("_")])
    name = s["mdb_name"] or "MDB.xlsx"
    stem, _, ext = name.rpartition(".")
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.download_button("Download Edited File", data=s["mdb_bytes"], file_name=f"{stem or name}_edited.{ext or 'xlsx'}",
                           key="edit_download", on_click="ignore", help="Your file with every change above.")
        last = log[-1]
        ask_first("undo_last_edit", "↶ Undo Last Change",
                  f"Undo the last change (row {last['Row']}, “{last['Column']}” back to "
                  f"“{last['Old Value'] or '(empty)'}”)?", state.undo_last_edit, yes="Yes, undo it")
        ask_first("undo_all_edits", "🗑 Delete All Changes",
                  f"Delete all {len(log):,} changes? The file goes back to exactly the one you uploaded.",
                  state.undo_all_edits, yes="Yes, delete them all")
