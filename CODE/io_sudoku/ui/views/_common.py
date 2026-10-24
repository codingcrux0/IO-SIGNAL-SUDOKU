"""Small widgets shared by several views: empty state, stale banner, readiness block, download button."""
from __future__ import annotations

from typing import Any

import streamlit as st

from io_sudoku.ui import state, theme, ui_logic


def md_escape(text: str) -> str:
    """Plain text for st.markdown: customer data must never be read as Markdown (HTML is already off)."""
    return "".join("\\" + ch if ch in "\\`*_[]<>#|~" else ch for ch in str(text))


def tq_table(tqs: list[Any]) -> None:
    """The questions as a table, each row coloured by severity: red error, amber warning, blue info."""
    import pandas as pd

    frame = pd.DataFrame(ui_logic.tq_rows(tqs))
    if frame.empty:
        return
    colours = [ui_logic.SEVERITY_COLOURS.get(t.severity, ("", "", "")) for t in tqs]

    def paint(row: pd.Series) -> list[str]:
        bg, fg, strong = colours[row.name]
        if not bg:
            return [""] * len(row)
        return [f"background-color: {bg}; color: {strong if col == 'Severity' else fg}"
                + ("; font-weight: 700" if col == "Severity" else "") for col in row.index]

    st.dataframe(frame.style.apply(paint, axis=1), hide_index=True, width="stretch",
                 height=min(560, 38 + 35 * len(frame)))


def result_or_empty(what: str, key: str):
    """The current SolveResult, or None after showing the empty state (with the sample button)."""
    result = st.session_state["result"]
    if result is None:
        st.info(f"No result yet. Upload an MDB on the Upload view, or load the sample data to see {what}.")
        st.button("Try With Sample Data", key=f"sample_{key}", on_click=state.on_sample)
        return None
    stale_banner(key)
    return result


def stale_banner(key: str) -> None:
    if st.session_state.get("stale"):
        st.warning("Your inputs changed after the last solve, so these results are out of date.")
        st.button("Re-solve", key=f"resolve_{key}", on_click=state.on_solve, type="primary")


def readiness_block(result) -> None:
    status, reasons = ui_logic.readiness_text(result)
    st.markdown(theme.badge(status), unsafe_allow_html=True)
    if reasons:
        st.markdown("\n".join(f"- {r}" for r in reasons))
    if status != "ISSUE-READY":
        questions = ui_logic.blocking_questions(result)
        if questions:
            with st.expander("What needs fixing first", expanded=status == "BLOCKED"):
                st.markdown("\n".join(f"- {md_escape(q)}" for q in questions))
                st.caption("Every question, with a suggested fix, is on the TQ Board.")


def download_button(spec: ui_logic.DownloadSpec, ctx: dict[str, Any], result_key: str, key_prefix: str = "dl") -> None:
    """One download button; the file is built once per (solve, kind) and cached."""
    try:
        data, name, mime = ui_logic.cached_download(result_key, spec.key, ctx)
    except Exception:  # noqa: BLE001 - one broken report must not hide the others
        st.caption(f"{spec.label} is not available right now.")
        return
    st.download_button(spec.label, data=data, file_name=name, mime=mime, key=f"{key_prefix}_{spec.key}")


def file_card(spec: ui_logic.DownloadSpec, ctx: dict[str, Any], result_key: str, key_prefix: str = "dl") -> None:
    """A download button with a "View Here" switch that opens the same file in the page."""
    from io_sudoku.ui.views._viewer import file_viewer

    try:
        data, name, mime = ui_logic.cached_download(result_key, spec.key, ctx)
    except Exception:  # noqa: BLE001 - one broken report must not hide the others
        st.caption(f"{spec.label} is not available right now.")
        return
    left, right = st.columns([3, 2], vertical_alignment="center")
    left.download_button(spec.label, data=data, file_name=name, mime=mime, key=f"{key_prefix}_{spec.key}", on_click="ignore")
    if right.toggle("View Here", key=f"{key_prefix}_view_{spec.key}", help=f"Open {spec.title} in the page without downloading it."):
        file_viewer(data, name, f"{key_prefix}_v_{spec.key}_{result_key[:8]}", trusted_html=True)


def main_ctx() -> dict[str, Any]:
    s = st.session_state
    return {"result": s["result"], "mdb_bytes": s["mdb_bytes"], "pack": s["pack"], "overrides": s["overrides"],
            "pins": s["pins"], "rev_label": s["rev_label"], "template_bytes": s["template_bytes"]}


def cabinet_picker(rows: list[dict[str, Any]], key: str) -> str | None:
    """A cabinet dropdown whose choice is shared by Grid and Drawings (and the URL)."""
    names = ui_logic.cabinet_names(rows)
    if not names:
        st.info("This result has no cabinets to show.")
        return None
    s = st.session_state
    if s.get("selected_cabinet") not in names:
        s["selected_cabinet"] = names[0]
    return st.selectbox("Cabinet", names, key="selected_cabinet")
