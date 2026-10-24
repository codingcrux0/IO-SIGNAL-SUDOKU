"""The Helpdesk: a customer-support chat panel that slides in on the RIGHT of the page.

  * A round "Help" button sits at the bottom right of every page.  It (or "Open The Helpdesk" on a TQ, or on the
    Rules page) opens the panel; the page shrinks to make room, and goes back to full width when you close it.
  * The answers come from core.helpdesk (Google Gemini, advice in words only - no tools, no edits, no files).
    The chat itself runs as a fragment, so typing and waiting for an answer never re-runs the page behind it.
  * About a TQ, the panel also keeps the Final Wording of your suggestion and sends it for approval.  On any page
    it can turn your request into a rule PROPOSAL (checked by the same form rules, approved by another person).
Nothing in here changes the allocation, the file or the rules by itself.
"""
from __future__ import annotations

import time

import streamlit as st

from io_sudoku.core import helpdesk
from io_sudoku.core.suggestion import make_suggestion
from io_sudoku.ui import state, ui_logic
from io_sudoku.ui.views._common import md_escape

WIDTH = 420                 # px, the panel on a wide screen (it covers the whole width on a phone)
GREETING = ("Hello, I am the IO Sudoku Helpdesk. I can explain any page, question (TQ) or rule, suggest how to fix a "
            "problem, and help you word a suggestion or a rule. I give advice only: you make every change yourself.")
QUICK = {"tq": ("Why was this question raised?", "How do I fix it in the app?", "Please word my suggestion better."),
         "rule": ("Which kind of rule do I need?", "Help me word this rule.", "What will this rule change?"),
         "general": ("What should I do next?", "Explain my readiness status.", "How do the TQ warnings get signed off?")}


# ------------------------------------------------------------------ opening and closing
def open_chat(topic: dict | None = None) -> None:
    """Open the panel; a new topic (a TQ, a rule) starts a new conversation about it."""
    s = st.session_state
    chat = s.get("chat") or {}
    same = topic is None or (chat.get("tq_key") or chat.get("kind")) == (topic.get("tq_key") or topic.get("kind"))
    if topic is not None and not same:
        chat = {**topic, "messages": []}
    chat = {"kind": "general", "messages": [], **chat, "open": True}
    s["chat"] = chat


def _open_general() -> None:
    open_chat(None if (st.session_state.get("chat") or {}).get("messages") else {"kind": "general"})


def _close() -> None:
    s = st.session_state
    if s.get("chat"):
        s["chat"] = {**s["chat"], "open": False}


def _new_chat() -> None:
    s = st.session_state
    chat = s.get("chat") or {}
    s["chat"] = {**chat, "messages": [], "open": True}
    s["help_pending"] = None


def _key() -> str | None:
    return state.secret("GEMINI_API_KEY")


# ------------------------------------------------------------------ what the helpdesk may read about this page
def page_summary() -> str:
    """A short, read-only description of where the user is and what the result says (never the whole file)."""
    s = st.session_state
    lines = [f"Page open: {s.get('view')}."]
    if s.get("mdb_name"):
        lines.append(f"File: {s['mdb_name']}" + (f", {len(s['edit_log'])} cell(s) edited in the app." if s.get("edit_log") else "."))
    result = s.get("result")
    if result is None:
        lines.append("No allocation has been run yet.")
    else:
        status, reasons = ui_logic.readiness_text(result)
        k = result.kpis or {}
        lines.append(f"Readiness: {status}" + (f" ({'; '.join(reasons)})" if reasons else "") +
                     (" The result is out of date: inputs changed after it." if s.get("stale") else ""))
        lines.append(f"Field signals {k.get('field', 0)}, wired spares {k.get('wired_spare', 0)}, cabinets "
                     f"{k.get('cabinets_used', 0)}, set aside {k.get('quarantined', 0)}; questions: {k.get('tq_error', 0)} "
                     f"errors, {k.get('tq_warning', 0)} warnings, {k.get('tq_info', 0)} info.")
        shown = [t for t in result.tqs if t.severity in ("error", "warning")][:25]
        if shown:
            lines.append("Open errors and warnings (first 25):")
            lines += [f"- {t.severity} {t.tq_id} on {t.ref or '-'}: {ui_logic.short_text(t.message, 160)}" for t in shown]
    pack = s.get("pack")
    if pack is not None:
        rules = [r.get("statement", "") for r in (pack.overrides or {}).get("project_rules", [])]
        lines.append(f"Active rule pack: {pack.name} v{pack.version}; settings {dict(pack.params)}"
                     + (f"; project rules: {' | '.join(rules)}" if rules else "."))
    pending = [p.statement for p in s.get("proposals") or [] if p.status == "pending"]
    if pending:
        lines.append("Rules waiting for approval: " + " | ".join(pending[:5]))
    chat = s.get("chat") or {}
    if chat.get("kind") == "tq":
        lines.append(f"TOPIC: the question {chat.get('tq_id')} on {chat.get('ref') or '-'}: \"{chat.get('question', '')}\" "
                     f"The tool's suggested fix: \"{chat.get('fix', '')}\"."
                     + (f" The user's own suggestion so far: \"{chat['note']}\"." if chat.get("note") else ""))
    elif chat.get("kind") == "rule":
        lines.append("TOPIC: the user wants help with a project rule (Settings, New Columns or Constraints).")
    return "\n".join(lines)


# ------------------------------------------------------------------ chat actions (inside the fragment)
def _queue(text: str) -> None:
    """Add the user's message and mark an answer as wanted (it is fetched on the next fragment run)."""
    s = st.session_state
    chat = s.get("chat")
    text = (text or "").strip()
    if not chat or not text:
        return
    count, last = s.get("help_count", 0), s.get("help_last", 0.0)
    if count >= helpdesk.MAX_MESSAGES_PER_SESSION:
        state.flash("info", "This session has reached its question limit. Reload the page to start a new session.", "helpdesk")
        return
    if time.monotonic() - last < helpdesk.MIN_SECONDS_BETWEEN:
        return
    s["help_count"], s["help_last"] = count + 1, time.monotonic()
    s["chat"] = {**chat, "messages": list(chat["messages"]) + [{"role": "user", "text": text[:helpdesk.MAX_MESSAGE_CHARS]}]}
    s["help_pending"] = text[:helpdesk.MAX_MESSAGE_CHARS]


def _on_input() -> None:
    _queue(st.session_state.get("assistant_input") or "")


def _quick(text: str) -> None:
    _queue(text)


def _use_reply() -> None:
    s = st.session_state
    replies = [m["text"] for m in (s.get("chat") or {}).get("messages", []) if m["role"] == "assistant"]
    if replies:
        s["assistant_final"] = replies[-1][:1000]


def _submit() -> None:
    s = st.session_state
    chat = s.get("chat")
    if not chat or chat.get("kind") != "tq":
        return
    sg, errors = make_suggestion(chat["tq_id"], chat["ref"], s.get("assistant_final") or "", s.get("assistant_by") or "",
                                 time.strftime("%Y-%m-%d %H:%M"))
    if sg is None:
        state.flash("error", " ".join(errors), "helpdesk")
        return
    s["suggestions"] = s["suggestions"] + [sg]
    s["tq_notes"] = {**s["tq_notes"], chat["tq_key"]: {"text": sg.text, "by": sg.author, "time": sg.created}}
    state.flash("success", "Sent for approval. A different person approves it on the Rules page.", "helpdesk")


def _draft_rule() -> None:
    """Turn the user's last request into a PENDING rule proposal (validated like the form; approved by another person)."""
    from datetime import datetime, timezone

    from io_sudoku.core import advisor
    s = st.session_state
    asked = [m["text"] for m in (s.get("chat") or {}).get("messages", []) if m["role"] == "user"]
    key = _key()
    if not asked:
        state.flash("info", "First describe the rule you want in the chat.", "helpdesk")
        return
    client = helpdesk.GeminiClient(key) if key else None
    draft = advisor.draft_rule(asked[-1][:advisor.MAX_REQUEST_CHARS], s.get("assistant_by") or s.get("rule_author") or "",
                               client, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               ui_logic.config_for_pack(s["pack"]).known_rooms())
    if draft.ok:
        s["proposals"] = s["proposals"] + [draft.proposal]
        state.flash("success", f"Proposed: {draft.proposal.statement} It waits for approval on the Rules page.", "helpdesk")
    else:
        state.flash("warning", draft.message + (" " + " ".join(draft.errors) if draft.errors else ""), "helpdesk")


# ------------------------------------------------------------------ drawing
def render() -> None:
    """Call once at the end of every run.  Draws the Help button, or the open panel (and shrinks the page)."""
    s = st.session_state
    chat = s.get("chat")
    if not chat or not chat.get("open"):
        with st.container(key="helpdesk_launcher"):
            st.button("\U0001F4AC  Help", key="helpdesk_open", on_click=_open_general,
                      help="Open the IO Sudoku Helpdesk: ask about any page, question or rule.")
        return
    st.markdown(f"<style>{OPEN_CSS}</style>", unsafe_allow_html=True)
    with st.container(key="helpdesk_drawer"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small", key="helpdesk_head"):
            online = bool(_key())
            st.markdown(f"**\U0001F4AC {helpdesk.NAME}**  \n<small style='color:{'#3fb950' if online else '#9da7b3'}'>"
                        f"● {'Online' if online else 'AI not set up'}</small>", unsafe_allow_html=True,
                        help="Advice in words only. It cannot change your file, the allocation, the rules or any code, "
                             "and it never sees your whole file: only the summary of this page.")
            st.button("↺", key="helpdesk_new", on_click=_new_chat, help="Start a new conversation")
            st.button("✕", key="helpdesk_close", on_click=_close, help="Close the Helpdesk")
        if chat.get("kind") == "tq":
            st.caption(f"About **{md_escape(chat.get('tq_id', ''))}** · {md_escape(chat.get('ref') or '-')}")
        _body()


@st.fragment
def _body() -> None:
    """The conversation.  A fragment: sending a message re-runs only this panel, never the page behind it."""
    s = st.session_state
    chat = s.get("chat") or {}
    kind = chat.get("kind", "general")
    state.show_flash("helpdesk")
    with st.container(key="helpdesk_log", height=420):
        with st.chat_message("assistant", avatar="\U0001F4AC"):
            st.markdown(GREETING)
        for m in chat.get("messages", []):
            with st.chat_message("user" if m["role"] == "user" else "assistant",
                                 avatar="\U0001F464" if m["role"] == "user" else "\U0001F4AC"):
                st.markdown(m["text"] if m["role"] == "assistant" else md_escape(m["text"]))
        pending = s.get("help_pending")
        if pending:
            with st.chat_message("assistant", avatar="\U0001F4AC"), st.spinner("Thinking…"):
                reply = helpdesk.ask(pending, chat.get("messages", [])[:-1], page_summary(), _key())
            s["help_pending"] = None
            chat = s.get("chat") or chat
            s["chat"] = {**chat, "messages": list(chat.get("messages", [])) + [{"role": "assistant", "text": reply.text}]}
            st.rerun(scope="fragment")
    if not chat.get("messages"):
        with st.container(horizontal=True, gap="small", key="helpdesk_quick"):
            for i, text in enumerate(QUICK.get(kind, QUICK["general"])):
                st.button(text, key=f"helpdesk_quick_{i}", on_click=_quick, args=(text,))
    st.chat_input("Ask the Helpdesk…", key="assistant_input", on_submit=_on_input, max_chars=helpdesk.MAX_MESSAGE_CHARS)
    if kind == "tq":
        with st.expander("Your Suggestion For This Question", expanded=True):
            st.text_area("Final Wording", key="assistant_final", max_chars=1000, height=90,
                         help="What you send for approval. Use the Helpdesk's last answer, or write your own.")
            st.text_input("Your Name", key="assistant_by", autocomplete="off")
            with st.container(horizontal=True, gap="small"):
                st.button("Use Last Answer", key="assistant_use_reply", on_click=_use_reply)
                st.button("Send For Approval", key="assistant_submit", type="primary", on_click=_submit)
    else:
        with st.expander("Turn My Request Into A Rule Proposal"):
            st.caption("Describe the rule in the chat first. The Helpdesk fills in the same form as the Rules page; "
                       "the proposal is checked like any other and waits for a different person's approval.")
            st.text_input("Your Name", key="assistant_by", autocomplete="off")
            st.button("Draft A Rule Proposal", key="assistant_draft_rule", on_click=_draft_rule, disabled=not _key())
    st.caption("\U0001F512 Advice only. The Helpdesk cannot change your file, the rules or any code.")


# The open panel: fixed on the right, full height; the page (and its top bar) shrink by the same width.
OPEN_CSS = f"""
[data-testid=stMain]{{padding-right:{WIDTH}px}}
[data-testid=stHeader]{{width:calc(100% - {WIDTH}px)!important}}
.st-key-helpdesk_drawer{{position:fixed!important;top:0;right:0;bottom:0;width:{WIDTH}px!important;z-index:1000050;
background:#0f141b;border-left:1px solid var(--line);box-shadow:-12px 0 32px rgba(0,0,0,.45);padding:14px 16px 64px;
overflow-y:auto;overscroll-behavior:contain;animation:iosg-drawer-in .26s cubic-bezier(.2,.8,.2,1) both}}
.st-key-helpdesk_log{{height:calc(100vh - 330px)!important;min-height:220px}}
@media (max-width:900px){{[data-testid=stMain]{{padding-right:0}}[data-testid=stHeader]{{width:100%!important}}
.st-key-helpdesk_drawer{{width:100vw!important}}}}
"""
