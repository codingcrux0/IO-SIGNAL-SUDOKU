"""Reviewed Before - the second tab of the TQ Board: items you reviewed before that have a problem again.

Every Approve, Problem, Edit, answer, note and verified or rejected fix is remembered (core.reviewlog).  When a
re-allocation or a new revision raises a question again on such an item - a new problem (another signal, a
changed rule) or the same one coming back - the item is listed here.  Hover the (?) of a row for the small box
with how often it was reviewed, approved, rejected and fixed; press ▸ for the exact history: every decision,
who made it, in which revision, and the signal exactly as it was then next to how it is now.
Read-only: nothing here changes a sign-off, the file or the allocation (Edit opens the editor as usual).
"""
from __future__ import annotations

import streamlit as st

from io_sudoku.core import helpcontext, reviewlog
from io_sudoku.ui import state, ui_logic
from io_sudoku.ui.views import assistant
from io_sudoku.ui.views._common import heading, md_escape, pager

ROWS_PER_PAGE = 20
OPEN_KEY = "rb_open"


def render(result, back: list[reviewlog.Returning]) -> None:
    s = st.session_state
    log = s["review_log"]
    heading("Problems Again On Items You Reviewed Before",
            "Every decision on the Questions tab is remembered: Approve, Problem, Edit, an answer, a note, a suggested "
            "fix that was verified or rejected. When a later allocation or a new revision raises a question again on "
            "the same signal, cable or cabinet, it is listed here. NEW PROBLEM = a question it never had before (for "
            "example caused by another signal or a changed rule). CAME BACK = the same question again. A warning you "
            "have already signed off in this allocation is not listed.")
    if not log:
        st.info("Nothing has been reviewed yet. Approve or mark a warning, fix a question with Edit, give an answer or "
                "write a note on the Questions tab, and it is remembered here for the next revisions.")
        return
    if not back:
        st.success("No item you reviewed before has an open problem right now.")
    else:
        new = sum(1 for r in back if r.is_new)
        st.caption(f"{len(back):,} item{'s' if len(back) != 1 else ''} · {new:,} with a new problem · {len(back) - new:,} "
                   "where the same question came "
                   "back. Hover the (?) for the summary; ▸ shows the whole history.")
        page_items, page, pages = ui_logic.page_slice(back, s.get("rb_page", 0), ROWS_PER_PAGE)
        s["rb_page"] = page
        pager("rb_page", pages)
        box = st.container(height=520, key="rb_box") if len(page_items) > 6 else st.container(key="rb_box")
        with box:
            for item in page_items:
                _row(result, item)
    _everything(result, log)


def _badge(kind: str) -> str:
    colour = "#ff7b72" if kind == "New problem" else "#e3b341"
    return f'<span style="color:{colour};font-weight:700">{md_escape(kind.upper())}</span>'


def _row(result, item: reviewlog.Returning) -> None:
    s = st.session_state
    h = ui_logic.sha256_hex(item.item)[:10]
    n = reviewlog.counts(item.events)
    first = item.open_now[0]
    with st.container(border=True, key=f"rb_row_{h}"):
        left, mid, right, more = st.columns([5, 2.6, 1.1, .45], vertical_alignment="center")
        kinds = list(dict.fromkeys(k for *_, k in item.open_now))
        now = "; ".join(f"{q[0]} ({q[1]})" for q in item.open_now[:3]) + (" …" if len(item.open_now) > 3 else "")
        left.markdown(f"↺ **{md_escape(item.ref) or '-'}** · " + " · ".join(_badge(k) for k in kinds)
                      + f"  \n<small>Now: {md_escape(now)}</small>", unsafe_allow_html=True,
                      help=reviewlog.summary_text(item.events))
        mid.markdown(f"<small>Reviewed **{n['reviewed']}** · approved **{n['approved']}** · rejected "
                     f"**{n['rejected']}** · fixed **{n['fixed']}**</small>", unsafe_allow_html=True)
        plan = state.fix_plan(first[0], item.ref)
        right.button("✎ Edit", key=f"rb_edit_{h}", on_click=state.edit_for_tq, args=(first[0], item.ref),
                     disabled=plan.kind == "none", help=plan.why or f"Open {item.ref} on the Edit File page to fix {first[0]}.")
        is_open = s.get(OPEN_KEY) == item.item
        more.button("▾" if is_open else "▸", key=f"rb_more_{h}", on_click=_toggle, args=(item.item,),
                    help="The whole history of this item: every decision and the signal exactly as it was then.")
        if is_open:
            _history(result, item.item, item.ref, item.events, item.open_now, "rb")


def _toggle(key: str) -> None:
    s = st.session_state
    s[OPEN_KEY] = None if s.get(OPEN_KEY) == key else key


def _history(result, key: str, ref: str, events: list[reviewlog.ReviewEvent], open_now: list[tuple],
             prefix: str) -> None:
    """The exact past of one item: the questions open now, every decision, and the signal then and now."""
    h = prefix + "_" + ui_logic.sha256_hex(key)[:10]
    if open_now:
        st.markdown("**Open now**")
        st.markdown("\n".join(f"- {_badge(kind)} **{md_escape(tq_id)}** ({sev}): {md_escape(msg)}"
                              for tq_id, sev, msg, kind in open_now), unsafe_allow_html=True)
    st.markdown(f"**Everything decided about {md_escape(ref)}** ({reviewlog.count_line(events)})")
    st.dataframe([{"When": e.time, "Revision": e.revision or "-", "Question": e.tq_id, "What Happened": e.label,
                   "By": e.by or "-", "Detail": e.detail or "-", "Where It Was": e.where or "-",
                   "Question Text": e.question or "-"} for e in reversed(events)],
                 hide_index=True, width="stretch", height=min(330, 38 + 35 * len(events)))
    labels = [f"{e.time} · {e.tq_id} · {e.label}" for e in events]
    pick = st.selectbox("See The Signal Exactly As It Was At", range(len(events)), index=len(events) - 1,
                        format_func=lambda i: labels[i], key=f"{h}_at",
                        help="The signal's own values at the moment of that decision, next to how it is now.")
    then = events[pick].facts
    _, now = reviewlog.facts_of(result, ref)
    columns = list(dict.fromkeys([*then, *now]))
    if columns:
        st.dataframe([{"Column": c, "Then": then.get(c, "-"), "Now": now.get(c, "-"),
                       "Changed": "●" if then.get(c, "-") != now.get(c, "-") else ""} for c in columns],
                     hide_index=True, width="stretch", height=min(330, 38 + 35 * len(columns)))
    else:
        st.caption("No allocated row was found for this item (it may be a cabinet, a page or a set-aside signal).")
    title, context = helpcontext.history_focus(result, ref, events, open_now)
    assistant.ask_button(f"{h}_ask", _same, (assistant.topic(f"history|{key}", "history", title, context),),
                         help="Opens the Helpdesk on the right, already told this item's whole review history and the "
                              "problem it has now. Advice only: it cannot change anything.")


def _same(topic: dict) -> dict:
    return topic


def _everything(result, log: list[reviewlog.ReviewEvent]) -> None:
    """Every item ever reviewed, searchable: pick one to see its whole history."""
    s = st.session_state
    heading("Everything Reviewed So Far", "Every signal, cable or cabinet that was ever reviewed, with how often. "
                                          "It is kept with the project: the workspace download saves it, so it "
                                          "comes back when the project is continued later.")
    items = reviewlog.by_item(log)
    text = st.text_input("Search The Reviewed Items", key="rb_search", autocomplete="off", label_visibility="collapsed",
                         placeholder="\U0001F50E Search a tag, a cable or a question…")
    needle = (text or "").strip().casefold()
    keys = [k for k, ev in items.items() if not needle or needle in k.casefold()
            or any(needle in f"{e.ref} {e.tq_id} {e.question}".casefold() for e in ev)]
    keys.sort(key=lambda k: items[k][-1].time, reverse=True)
    if not keys:
        st.info("No reviewed item matches your search.")
        return
    table = []
    for k in keys:
        ev = items[k]
        n = reviewlog.counts(ev)
        table.append({"Item": ev[-1].ref or k, "Reviewed": n["reviewed"], "Approved": n["approved"],
                      "Rejected": n["rejected"], "Fixed": n["fixed"], "Came Back": n["raised"],
                      "Last": f"{ev[-1].tq_id}: {ev[-1].label}", "When": ev[-1].time})
    event = st.dataframe(table, hide_index=True, width="stretch", key=f"rb_all_{len(log)}", on_select="rerun",
                         selection_mode="single-row", height=min(380, 38 + 35 * len(table)))
    rows = event.selection.rows if event is not None else []
    if rows and rows[0] < len(keys):
        key = keys[rows[0]]
        current = next((r.open_now for r in reviewlog.returning(log, result, s["signoffs"]) if r.item == key), [])
        with st.container(border=True, key="rb_pick_panel"):
            _history(result, key, items[key][-1].ref or key, items[key], current, "rbp")
    else:
        st.caption("Pick a row (tick its box) to see that item's whole history.")
