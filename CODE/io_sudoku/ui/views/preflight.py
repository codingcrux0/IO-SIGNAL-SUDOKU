"""Preflight: how clean is the file before we allocate it."""
from __future__ import annotations

import json

import streamlit as st

from io_sudoku.core.preflight import PreflightReport, preflight
from io_sudoku.ui import ui_logic
from io_sudoku.ui.nav import link
from io_sudoku.ui.state import on_sample
from io_sudoku.ui.views._common import stale_banner


@st.cache_data(max_entries=8, show_spinner=False)
def _preflight(mdb_bytes: bytes, pack_text: str, column_text: str) -> PreflightReport:
    from io_sudoku.core.rulepack import pack_from_dict
    cfg = ui_logic.config_for_pack(pack_from_dict(json.loads(pack_text)))
    return preflight(mdb_bytes, cfg, json.loads(column_text))


def render() -> None:
    s = st.session_state
    st.header("Preflight Check")
    if not s["mdb_bytes"]:
        st.info(f"Upload an MDB on the {link('Upload', 'Upload')} view, or load the sample data, to see how clean it is.")
        st.button("Try With Sample Data", key="sample_preflight", on_click=on_sample)
        return
    stale_banner("preflight")
    report = _preflight(s["mdb_bytes"], ui_logic.pack_json(s["pack"]), json.dumps(s["column_overrides"], sort_keys=True))
    a, b = st.columns(2)
    a.metric("Data Quality Score", f"{report.score}/100")
    b.metric("Rows Read", f"{report.total_rows:,}")
    st.progress(min(100, max(0, report.score)) / 100, text="Data quality")
    st.caption(f"Every problem in the file becomes a question on the {link('TQ Board', 'TQ Board')} when you "
               "allocate, with a suggested fix and an ✎ Edit button.")
    if report.auto_fixed:
        st.subheader("Fixed Automatically")
        labels = {"whitespace_fixed": "Cells with stray spaces cleaned", "io_alias_fixed": "IO type spellings normalised",
                  "deleted_excluded": "Deleted rows left out", "io_type2_rows": "Rows with a second IO type"}
        st.dataframe([{"What": labels.get(k, k), "Count": v} for k, v in report.auto_fixed.items()], hide_index=True, width="stretch")
    st.subheader("Column Completeness")
    if report.columns:
        st.dataframe([{"Field": c.field, "Column In Your File": c.header or "-", "Matched By": c.method,
                       "Filled": f"{c.filled:,} of {c.total:,}", "Filled (%)": c.pct} for c in report.columns],
                     hide_index=True, width="stretch")
    else:
        st.info(f"No columns could be matched. Check the file on the {link('Upload', 'Upload', 'Check How Your Columns Were Understood')} view.")
