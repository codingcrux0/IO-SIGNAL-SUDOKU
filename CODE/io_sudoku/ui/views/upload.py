"""Upload: the MDB file, the optional template, the sample button and the column-mapping table."""
from __future__ import annotations

import streamlit as st

from io_sudoku.core.columnmap import load_aliases, map_columns, missing_mandatory
from io_sudoku.ui import state, ui_logic
from io_sudoku.ui.views._common import allocate_button
from io_sudoku.ui.views._viewer import file_viewer

AUTO = "(Choose automatically)"


def render() -> None:
    s = st.session_state
    st.markdown('<div class="iosg-hero"><h1>IO Signal Sudoku</h1><p>Upload your customer IO list and get a '
                'complete, rule-checked DeltaV IO allocation, a list of open questions, and a revision report. '
                'Every position is calculated by fixed rules, so the same file always gives the same answer.</p></div>',
                unsafe_allow_html=True)
    left, right = st.columns([3, 2])
    with left:
        st.file_uploader("MDB File (.xlsx or .csv)", type=["xlsx", "xlsm", "csv"], key="mdb_uploader", on_change=state.on_upload,
                         help="The customer IO list. Files up to the size limit are read; nothing is sent anywhere.")
        st.text_input("Revision Label", key="rev_label", max_chars=8, autocomplete="off",
                      on_change=state.mark_stale, help="Written into the Revision No column, for example 00 or A.")
    with right:
        st.markdown("**No file handy?**")
        st.button("Try With Sample Data", key="sample_upload", on_click=state.on_sample, type="primary")
        st.caption("Loads a small real-style IO list and solves it straight away.")

    with st.expander("Use Your Own Allocation Template (optional)"):
        st.file_uploader("Template Workbook (.xlsx)", type=["xlsx"], key="template_uploader", on_change=state.on_template_upload,
                         help="If you skip this, the built-in 76-column template is used.")
        if s["template_bytes"]:
            st.success("Your template will be used for the allocation download.")

    with st.expander("Continue A Saved Project (workspace .zip)"):
        st.checkbox("I understand this replaces my saved rules, answers and pins", key="workspace_ok")
        st.file_uploader("Workspace File", type=["zip"], key="workspace_uploader", on_change=state.on_workspace_upload)

    if not s["mdb_bytes"]:
        st.info("Upload a file above, or load the sample data, to continue.")
        return
    st.success(f"Loaded {s['mdb_name']} ({len(s['mdb_bytes']):,} bytes, fingerprint {s['mdb_sha'][:10]}).")
    if ui_logic.is_allocation_file(s["mdb_bytes"]):
        st.info("This file is a finished IO Allocation, not an MDB. It still works: its Field signals and cabinet "
                "alarms are allocated again by the rules, spares are rebuilt, and rows whose values slipped out of "
                "their columns are repaired and listed as TQs. To keep the old positions instead, use it as Rev A on "
                "the Revision view; to check it against the rules, use the Health view.")
    allocate_button("solve_upload")
    if s["ui_error"]:
        st.error(s["ui_error"])
    if s["edit_log"]:
        st.caption(f"Your file has {len(s['edit_log']):,} change(s) made on the Edit File page.")
    left, right = st.columns([3, 2], vertical_alignment="center")
    right.button("\u270e Edit Your File", key="upload_edit", on_click=state.open_editor, args=(None, "Upload"),
                 help="Change any cell of the uploaded file in the page, without uploading it again.")
    if left.toggle("Preview Your File", key="upload_view_input", help="See the rows and columns exactly as they were uploaded."):
        file_viewer(s["mdb_bytes"], s["mdb_name"] or "input.xlsx", f"upload_input_{(s['mdb_sha'] or '')[:8]}")
    _column_mapping()


def _column_mapping() -> None:
    s = st.session_state
    headers = ui_logic.list_headers(s["mdb_bytes"])
    with st.expander("Check How Your Columns Were Understood"):
        if not headers:
            st.info("The column headers could not be listed. The solver will still try to read the file.")
            return
        aliases = load_aliases()
        mapping = map_columns(list(headers), aliases, s["column_overrides"])
        missing = missing_mandatory(mapping)
        if missing:
            st.warning("These required columns were not found: " + ", ".join(missing) + ". Pick them below, then re-solve.")
        else:
            st.caption("Every required column was found. Change a dropdown only if a column was matched wrongly.")
        with st.form("column_form"):
            for fld in aliases:
                match = mapping.get(fld)
                current = s["column_overrides"].get(fld)
                options = [AUTO] + headers
                index = options.index(current) if current in options else 0
                note = f"found \u201c{ui_logic.clip(match.header, 30)}\u201d ({match.method})" if match and match.header else "not found"
                st.selectbox(f"{fld}  \u2014  {note}", options, index=index, key=f"colmap_{fld}")
            st.form_submit_button("Save Column Mapping", on_click=_save_columns, args=(list(aliases),))


def _save_columns(fields: list[str]) -> None:
    s = st.session_state
    chosen = {f: s.get(f"colmap_{f}", AUTO) for f in fields}
    s["column_overrides"] = {f: h for f, h in chosen.items() if h != AUTO}
    state.mark_stale()
    state.flash("success", "Column mapping saved. Run the allocation again to use it.")
