"""Small widgets shared by several views: empty state, stale banner, readiness block, download button."""
from __future__ import annotations

import re
from typing import Any

import streamlit as st

from io_sudoku.core import readiness as readiness_mod
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.nav import link


def md_escape(text: str) -> str:
    """Plain text for st.markdown: customer data must never be read as Markdown (HTML is already off)."""
    return "".join("\\" + ch if ch in "\\`*_[]<>#|~" else ch for ch in str(text))


SIGNOFF_COLOURS = {"\u2713": "#3fb950", "\u2717": "#ff7b72"}     # Sign-Off cell: green approved, red problem


def tq_table(tqs: list[Any], signoffs: dict[str, str] | None = None, notes: dict[str, dict] | None = None) -> None:
    """The questions as a table, each row coloured by severity: red error, amber warning, blue info.
    With `signoffs`, a Sign-Off column says whether each warning is approved, a problem or waiting."""
    import pandas as pd

    frame = pd.DataFrame(ui_logic.tq_rows(tqs, signoffs, notes))
    if frame.empty:
        return
    colours = [ui_logic.SEVERITY_COLOURS.get(t.severity, ("", "", "")) for t in tqs]

    def cell(col: str, value: Any, fg: str, strong: str) -> str:
        if col == "Severity":
            return f"color: {strong}; font-weight: 700"
        if col == "Sign-Off" and value:
            return f"color: {SIGNOFF_COLOURS.get(str(value)[:1], fg)}; font-weight: 700"
        return f"color: {fg}"

    def paint(row: pd.Series) -> list[str]:
        bg, fg, strong = colours[row.name]
        if not bg:
            return [""] * len(row)
        return [f"background-color: {bg}; " + cell(col, row[col], fg, strong) for col in row.index]

    st.dataframe(frame.style.apply(paint, axis=1), hide_index=True, width="stretch",
                 height=min(560, 38 + 35 * len(frame)),
                 column_config={"Sign-Off": st.column_config.TextColumn(width="medium")})


def result_or_empty(what: str, key: str):
    """The current SolveResult, or None after showing the empty state (with the sample button)."""
    result = st.session_state["result"]
    if result is None:
        st.info(f"No result yet. Upload an MDB on the {link('Upload', 'Upload')} view, or load the sample data to see {what}.")
        st.button("Try With Sample Data", key=f"sample_{key}", on_click=state.on_sample)
        return None
    stale_banner(key)
    return result


def stale_banner(key: str) -> None:
    if st.session_state.get("stale"):
        st.warning("Your inputs changed after the last allocation (for example the file was edited), so these "
                   "results are out of date and marked DRAFT. Press Re-allocate to check them.")
        allocate_button(f"resolve_{key}")


def allocate_button(key: str) -> None:
    """THE allocate button, used everywhere.  Blue when something changed (or nothing was run yet);
    grey and disabled once the allocation matches the current inputs, so nobody presses it twice."""
    s = st.session_state
    if not s["mdb_bytes"]:
        st.button("Run Allocation", key=key, disabled=True, help="Upload an MDB or load the sample data first.")
    elif state.is_up_to_date():
        st.button("\u2713 Allocation Up To Date", key=key, disabled=True,
                  help="Nothing changed since the last allocation. Edit the file, answer a question, pin a cable "
                       "or change a rule, and this button turns blue again.")
    else:
        st.button("Re-allocate" if s["result"] is not None else "Run Allocation", key=key, type="primary",
                  on_click=state.on_solve, help="Runs the allocation with your current file, answers, pins and rules.")


# Readiness reasons that name questions get a link to exactly those questions on the TQ Board.
_REASON_LINKS = ((re.compile(r"^(\d+ warnings?) (were|was) signed off"), "TQ Board › Warnings Already Signed Off"),
                 (re.compile(r"^(\d+ warnings?) (are|is) waiting for sign-off"), "TQ Board › Warnings Still Waiting For Sign-Off"),
                 (re.compile(r"^(\d+ warnings?) (were|was) marked as a problem"), "TQ Board › Warnings Marked As A Problem By You"),
                 (re.compile(r"^(\d+ error TQs?)"), "TQ Board › Errors To Fix"),
                 (re.compile(r"^(\d+ signals?) (were|was) set aside"), "TQ Board › Errors To Fix"),
                 (re.compile(r"^(\d+ warnings?) to review"), "TQ Board › Sign Off The Warnings"))


def reason_md(reason: str) -> str:
    """A readiness reason as Markdown: '2 warnings were signed off' -> '[2 warnings](link) were signed off'."""
    from io_sudoku.ui.nav import link_to
    for pattern, label in _REASON_LINKS:
        match = pattern.match(reason)
        if match:
            words = match.group(1)
            return link_to(words, label) + md_escape(reason[len(words):])
    return md_escape(reason)


def readiness_block(result) -> None:
    status, reasons = ui_logic.readiness_text(result)
    st.markdown(theme.badge(status), unsafe_allow_html=True)
    if reasons:
        st.markdown("\n".join(f"- {reason_md(r)}" for r in reasons))
    if status != "ISSUE-READY":
        questions = ui_logic.blocking_questions(result)
        if questions:
            with st.expander("What needs fixing first", expanded=status == "BLOCKED"):
                st.markdown("\n".join(f"- {md_escape(ui_logic.short_text(q))}" for q in questions))
                st.caption(f"Every question, with a suggested fix, is on the {link('TQ Board', 'TQ Board', 'All Questions')}. "
                           f"To fix an error, press its Edit button under "
                           f"{link('Sign Off The Warnings', 'TQ Board', 'Sign Off The Warnings')}.")
        signed = readiness_mod.signoff_counts(result, st.session_state.get("signoffs") or {})
        if signed["waiting"] or signed[readiness_mod.PROBLEM]:
            st.button("Sign Off Warnings On The TQ Board", key=f"signoff_go_{st.session_state.get('view', '')}",
                      on_click=state.go_to, args=("TQ Board",),
                      help="Warnings must be approved before the allocation can be ISSUE-READY.")


def download_button(spec: ui_logic.DownloadSpec, ctx: dict[str, Any], result_key: str, key_prefix: str = "dl") -> None:
    """One download button; the file is built once per (solve, kind) and cached."""
    try:
        data, name, mime = ui_logic.cached_download(result_key, spec.key, ctx)
    except Exception:  # noqa: BLE001 - one broken report must not hide the others
        st.caption(f"{spec.label} is not available right now.")
        return
    st.download_button(spec.label, data=data, file_name=name, mime=mime, key=f"{key_prefix}_{spec.key}")


def file_card(spec: ui_logic.DownloadSpec, ctx: dict[str, Any], result_key: str, key_prefix: str = "dl",
              view_label: str = "View Here") -> None:
    """A download button with a "View Here" switch (or `view_label`) that opens the same file in the page."""
    from io_sudoku.ui.views._viewer import file_viewer

    try:
        data, name, mime = ui_logic.cached_download(result_key, spec.key, ctx)
    except Exception:  # noqa: BLE001 - one broken report must not hide the others
        st.caption(f"{spec.label} is not available right now.")
        return
    left, right = st.columns([3, 2], vertical_alignment="center")
    left.download_button(spec.label, data=data, file_name=name, mime=mime, key=f"{key_prefix}_{spec.key}", on_click="ignore")
    if right.toggle(view_label, key=f"{key_prefix}_view_{spec.key}", help=f"Open {spec.title} in the page without downloading it."):
        file_viewer(data, name, f"{key_prefix}_v_{spec.key}_{result_key[:8]}", trusted_html=True)


def main_ctx() -> dict[str, Any]:
    s = st.session_state
    return {"result": s["result"], "mdb_bytes": s["mdb_bytes"], "pack": s["pack"], "overrides": s["overrides"],
            "pins": s["pins"], "rev_label": s["rev_label"], "template_bytes": s["template_bytes"], "notes": state.notes_for_export()}


ALL_DRAWINGS = "📐 All Cabinet Drawings"


def cabinet_picker(rows: list[dict[str, Any]], key: str) -> str | None:
    """The cabinet dropdown of Cabinet Layout; its choice is kept in the URL too.  The first option shows
    the drawings of every cabinet at once (ALL_DRAWINGS)."""
    names = ui_logic.cabinet_names(rows)
    if not names:
        st.info("This result has no cabinets to show.")
        return None
    s = st.session_state
    if s.get("selected_cabinet") not in names + [ALL_DRAWINGS]:
        s["selected_cabinet"] = names[0]
    return st.selectbox("Cabinet", [ALL_DRAWINGS] + names, key="selected_cabinet",
                        help="Pick one cabinet, or All Cabinet Drawings to see the front and rear of every cabinet in one scroll box.")


# ------------------------------------------------------------------ page numbers
def page_numbers(page: int, pages: int) -> list[int | None]:
    """Which page buttons to show (1-based; None = a '…' gap): the first, the last, and the pages around the
    current one.  page_numbers(5, 12) -> [1, None, 4, 5, 6, None, 12]."""
    if pages <= 7:
        return list(range(1, pages + 1))
    wanted = sorted({1, pages, page - 1, page, page + 1} & set(range(1, pages + 1)))
    out: list[int | None] = []
    for n in wanted:
        if out and n - out[-1] > 1:
            out.append(None if n - out[-1] > 2 else n - 1)
        out.append(n)
    return out


def _set_page(key: str, page: int) -> None:
    st.session_state[key] = page


def _jump_page(key: str, pages: int) -> None:
    s = st.session_state
    s[key] = min(max(int(s.get(f"{key}_jump") or 1), 1), pages) - 1


def pager(key: str, pages: int) -> None:
    """The classic page buttons  ‹ 1 2 3 … 9 ›  (page 1 is the first).  '…' opens a box to type a page.
    `st.session_state[key]` holds the page, counted from 0 inside the code."""
    s = st.session_state
    if pages <= 1:
        return
    current = min(max(int(s.get(key) or 0), 0), pages - 1) + 1
    with st.container(horizontal=True, gap="small", horizontal_alignment="right", key=f"pager_{key}"):
        st.button("‹", key=f"{key}_prev", disabled=current == 1, on_click=_set_page, args=(key, current - 2),
                  help="Previous page")
        for i, n in enumerate(page_numbers(current, pages)):
            if n is None:
                with st.popover("…", key=f"{key}_more_{i}", help=f"Type a page number from 1 to {pages:,}"):
                    st.number_input(f"Go to page (1 to {pages:,})", min_value=1, max_value=pages, value=current, step=1,
                                    key=f"{key}_jump")
                    st.button("Go", key=f"{key}_go_{i}", type="primary", on_click=_jump_page, args=(key, pages))
            else:
                st.button(f"{n:,}", key=f"{key}_p{n}", type="primary" if n == current else "secondary",
                          on_click=_set_page, args=(key, n - 1))
        st.button("›", key=f"{key}_next", disabled=current == pages, on_click=_set_page, args=(key, current),
                  help="Next page")


# ------------------------------------------------------------------ "are you sure?"
def _ask(key: str) -> None:
    st.session_state["confirm"] = key


def _cancel() -> None:
    st.session_state["confirm"] = None


def _confirmed(action, args: tuple) -> None:
    st.session_state["confirm"] = None
    action(*args)


def ask_first(key: str, label: str, question: str, action, args: tuple = (), *, yes: str = "Yes",
              help: str | None = None, disabled: bool = False) -> None:
    """A button that asks before it acts: pressing it shows the question with Yes and Cancel in its place."""
    if st.session_state.get("confirm") != key:
        st.button(label, key=f"ask_{key}", help=help, disabled=disabled, on_click=_ask, args=(key,))
        return
    with st.container(border=True, key=f"confirm_{key}"):
        st.markdown(f"**{question}**")
        with st.container(horizontal=True, gap="small"):
            st.button(yes, key=f"yes_{key}", type="primary", on_click=_confirmed, args=(action, args))
            st.button("Cancel", key=f"no_{key}", on_click=_cancel)


def heading(title: str, info: str = "", where: str | None = None, anchor: str | None = None) -> None:
    """A section heading with an optional (i) for the long explanation, then any message for this section."""
    st.subheader(title, anchor=anchor, help=info or None)
    state.show_flash(where if where is not None else title)
