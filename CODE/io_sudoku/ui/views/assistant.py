"""The Helpdesk: a customer-support chat panel that slides in on the RIGHT of the page.

  * A round "Help" button sits at the bottom right of every page.  An "Ask The Helpdesk" button next to a TQ, the
    Answer A Question box, a cell on Rule Check, a rule on Rule Impact, a tag on Why Is It Here?, a revision change
    or the Rules page opens the panel ABOUT that thing: it already knows the details (core.helpcontext), shown at
    the top of the chat, so you can ask straight away.  The page shrinks to make room while it is open.
  * Every topic is its own conversation, kept separately: opening another question starts a fresh chat that knows
    nothing of the others, and going back to the first one brings back only its own messages.
  * The answers come from core.helpdesk (Google Gemini, advice in words only - no tools, no edits, no files).
    The chat itself runs as a fragment, so typing and waiting for an answer never re-runs the page behind it.
  * About a TQ, the panel also keeps the Final Wording of your suggestion and sends it for verification.  On any
    page it can turn your request into a rule PROPOSAL (checked by the same form rules, verified on the Rules page).
Nothing in here changes the allocation, the file or the rules by itself.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import streamlit as st

from io_sudoku.core import helpdesk
from io_sudoku.core.suggestion import make_suggestion
from io_sudoku.ui import state, ui_logic
from io_sudoku.ui.views._common import md_escape

WIDTH = 420                 # px, the panel on a wide screen (it covers the whole width on a phone)
MAX_CHATS = 40              # conversations kept per session (the oldest are dropped first)
GENERAL = "general"
GREETING = ("Hello, I am the IO Sudoku Helpdesk. I can explain any page, question (TQ) or rule, suggest how to fix a "
            "problem, and help you word a suggestion or a rule. I give advice only: you make every change yourself.")
QUICK = {"tq": ("Why was this question raised?", "How do I fix it in the app?", "Please word my suggestion better."),
         "answer": ("Which answer should I give?", "Is this answer right for the question?", "What happens when I verify?"),
         "cell": ("Explain the rules on this cell.", "Why is this signal here?", "How do I fix what is broken?"),
         "impact": ("Explain this rule in simple words.", "Why is it broken or flagged here?", "How do I fix those cells?"),
         "tag": ("Explain why it was placed here.", "Could it go somewhere else?", "Are there questions about it?"),
         "change": ("Why did this signal change?", "Is this change safe?", "What should I check next?"),
         "history": ("Why did this problem come back?", "What was decided before?", "Should I decide the same way?"),
         "preview": ("Is this revision better?", "What should I check before saving it?", "Where does the rework come from?"),
         "rule": ("Which kind of rule do I need?", "Help me word this rule.", "What will this rule change?"),
         GENERAL: ("What should I do next?", "Explain my readiness status.", "How do the TQ warnings get signed off?")}


# ------------------------------------------------------------------ the conversations (one per topic)
def _chats() -> dict[str, dict]:
    return dict(st.session_state.get("chats") or {})


def _save(chat: dict) -> None:
    """The open conversation is s['chat']; every conversation (open or not) is also kept in s['chats']."""
    s = st.session_state
    chats = _chats()
    chats[chat["key"]] = {k: v for k, v in chat.items() if k != "open"}
    if len(chats) > MAX_CHATS:                   # drop the oldest, never the open one
        for key in sorted(chats, key=lambda k: chats[k].get("used", 0))[:len(chats) - MAX_CHATS]:
            if key != chat["key"]:
                chats.pop(key)
    s["chats"], s["chat"] = chats, chat


def _topic_key(topic: dict) -> str:
    return str(topic.get("key") or (f"tq|{topic['tq_key']}" if topic.get("tq_key") else topic.get("kind") or GENERAL))


def open_chat(topic: dict | None = None) -> None:
    """Open the panel.  A topic (a TQ, a cell, a rule ...) opens ITS conversation: a new one the first time, or the
    same one again with only its own messages.  Its details (title, context) are refreshed from the latest result."""
    s = st.session_state
    current = s.get("chat") or None
    if current and current.get("key"):
        _save({**current, "open": False})        # keep the conversation being left
    if topic is None:
        base = current if current and current.get("key") else (_chats().get(GENERAL) or {"key": GENERAL, "kind": GENERAL})
        chat = {**base}
    else:
        key = _topic_key(topic)
        old = _chats().get(key) or {}
        chat = {**old, **topic, "key": key}
    chat = {"kind": GENERAL, "title": "General help", **chat, "messages": list(chat.get("messages") or []),
            "open": True, "used": time.monotonic()}
    if not current or current.get("key") != chat["key"]:
        s["help_pending"] = None                 # an answer still waiting belongs to the other conversation
    _save(chat)


def _open_general() -> None:
    open_chat(None)


def _switch(key: str) -> None:
    chat = _chats().get(key)
    if chat:
        open_chat(chat)


def _on_switch() -> None:
    s = st.session_state
    _switch((s.get("_helpdesk_conv_keys") or {}).get(s.get("helpdesk_conv")) or GENERAL)


def _close() -> None:
    s = st.session_state
    if s.get("chat"):
        _save({**s["chat"], "open": False})


def _new_chat() -> None:
    """Clear the messages of THIS conversation only (its topic and details stay)."""
    s = st.session_state
    chat = s.get("chat") or {"key": GENERAL, "kind": GENERAL}
    _save({**chat, "messages": [], "open": True})
    s["help_pending"] = None


def _key() -> str | None:
    return state.secret("GEMINI_API_KEY")


def _ask(build: Callable[..., dict | None], args: tuple) -> None:
    try:
        topic = build(*args)
    except Exception:  # noqa: BLE001 - without its details the Helpdesk still opens
        topic = None
    open_chat(topic)


def ask_button(key: str, build: Callable[..., dict | None], args: tuple = (), *, label: str = "Ask The Helpdesk",
               in_fragment: bool = False, help: str | None = None, width: Any = "content") -> None:
    """The button that opens the Helpdesk about one thing.  `build(*args)` returns the topic (key, kind, title,
    context ...) when it is pressed, so nothing is worked out until then.  Inside a fragment the whole page is
    re-run, so the panel appears."""
    tip = help or "Opens the Helpdesk on the right. It already knows the details of this, so you can just ask. Advice only."
    if in_fragment:
        if st.button(label, key=key, icon=":material/arrow_forward:", help=tip, width=width):
            _ask(build, args)
            st.rerun()
    else:
        st.button(label, key=key, icon=":material/arrow_forward:", help=tip, on_click=_ask, args=(build, args), width=width)


def topic(key: str, kind: str, title: str, context: str, **extra: Any) -> dict:
    """A Helpdesk topic: what the conversation is about and what the Helpdesk is told about it."""
    return {"key": key, "kind": kind, "title": title, "context": context, **extra}


# ------------------------------------------------------------------ what the helpdesk may read
def page_summary() -> str:
    """A short, read-only description: FIRST the one thing the user opened the Helpdesk from (the focus), then
    where the user is and what the whole result says (never the whole file)."""
    s = st.session_state
    lines: list[str] = []
    chat = s.get("chat") or {}
    if chat.get("context"):
        lines += ["FOCUS OF THIS CONVERSATION (the user opened the Helpdesk from here; answer about it unless asked "
                  "otherwise):", str(chat["context"]), "", "THE WHOLE PROJECT:"]
    elif chat.get("kind") == "rule":
        lines += ["FOCUS: the user wants help with a project rule (Settings, New Columns or Constraints).", ""]
    lines.append(f"Page open: {s.get('view')}.")
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
        lines.append("Rules waiting for verification: " + " | ".join(pending[:5]))
    if chat.get("kind") == "tq" and chat.get("note"):
        lines.append(f"The user's own suggestion so far: \"{chat['note']}\".")
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
    _save({**chat, "messages": list(chat["messages"]) + [{"role": "user", "text": text[:helpdesk.MAX_MESSAGE_CHARS]}]})
    s["help_pending"] = (chat["key"], text[:helpdesk.MAX_MESSAGE_CHARS])


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
    state.flash("success", "Sent for verification. Press Verify on the Rules page (Suggested Fixes) to accept it.", "helpdesk")


def _draft_rule() -> None:
    """Turn the user's last request into a PENDING rule proposal (validated like the form; verified on the Rules page)."""
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
        state.flash("success", f"Proposed: {draft.proposal.statement} Verify it in the Review Queue on the Rules page.", "helpdesk")
    else:
        state.flash("warning", draft.message + (" " + " ".join(draft.errors) if draft.errors else ""), "helpdesk")


# ------------------------------------------------------------------ drawing
def _conv_label(key: str) -> str:
    chat = _chats().get(key) or {}
    n = sum(1 for m in chat.get("messages", []) if m.get("role") == "user")
    return f"{chat.get('title') or 'General help'}" + (f" · {n} asked" if n else "")


def render() -> None:
    """Call once at the end of every run.  Draws the Help button, or the open panel (and shrinks the page)."""
    s = st.session_state
    chat = s.get("chat")
    if not chat or not chat.get("open"):
        with st.container(key="helpdesk_launcher"):
            st.button("\U0001F4AC  Help", key="helpdesk_open", on_click=_open_general,
                      help="Open the IO Sudoku Helpdesk: ask about any page, question or rule.")
        return
    if not chat.get("key"):                      # a conversation from before conversations were kept apart
        open_chat(None if chat.get("kind") == GENERAL else {**chat})
        chat = s["chat"]
    st.markdown(f"<style>{OPEN_CSS}</style>", unsafe_allow_html=True)
    with st.container(key="helpdesk_drawer"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small", key="helpdesk_head"):
            online = bool(_key())
            st.markdown(f"**\U0001F4AC {helpdesk.NAME}**  \n<small style='color:{'#3fb950' if online else '#9da7b3'}'>"
                        f"● {'Online' if online else 'AI not set up'}</small>", unsafe_allow_html=True,
                        help="Advice in words only. It cannot change your file, the allocation, the rules or any code. "
                             "It reads the details of what you opened it from and a summary of the project.")
            st.button("↺", key="helpdesk_new", on_click=_new_chat, help="Clear this conversation and start it again")
            st.button("✕", key="helpdesk_close", on_click=_close, help="Close the Helpdesk (every conversation is kept)")
        chats = _chats()
        if len(chats) > 1:
            labels: dict[str, str] = {}
            for key in sorted(chats, key=lambda k: -chats[k].get("used", 0)):
                label = _conv_label(key)
                while label in labels:           # two conversations with the same title stay apart
                    label += " ·"
                labels[label] = key
            s["_helpdesk_conv_keys"] = labels
            s["helpdesk_conv"] = next(label for label, key in labels.items() if key == chat["key"])
            st.selectbox("Conversation", list(labels), key="helpdesk_conv", on_change=_on_switch,
                         help="Every question, cell or rule you open the Helpdesk from is its own conversation. "
                              "Pick one to go back to it: it remembers only its own messages.")
        _focus(chat)
        _body()


def _focus(chat: dict) -> None:
    """What this conversation is about, highlighted, with what the Helpdesk was told about it."""
    if chat.get("kind") == GENERAL or not chat.get("title"):
        return
    with st.container(key="helpdesk_focus"):
        st.markdown(f"\U0001F4CC **About:** {md_escape(chat['title'])}")
        if chat.get("context"):
            with st.expander("What The Helpdesk Already Knows"):
                with st.container(height=180, key="helpdesk_context"):
                    st.markdown("  \n".join(md_escape(line) for line in str(chat["context"]).splitlines()))


def _rerun_panel() -> None:
    """Show the new answer: re-run only the panel when this is a panel re-run, else the whole page."""
    from streamlit.errors import StreamlitAPIException
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:                # the panel was drawn as part of a whole-page run
        st.rerun()


@st.fragment
def _body() -> None:
    """The conversation.  A fragment: sending a message re-runs only this panel, never the page behind it."""
    s = st.session_state
    chat = s.get("chat") or {}
    kind = chat.get("kind", GENERAL)
    state.show_flash("helpdesk")
    with st.container(key="helpdesk_log", height=420):
        with st.chat_message("assistant", avatar="\U0001F4AC"):
            st.markdown(GREETING if kind == GENERAL or not chat.get("title") else
                        f"Hello, I am the IO Sudoku Helpdesk. I already have the details of **{md_escape(chat['title'])}**, "
                        "so you can ask your question straight away. I give advice only: you make every change yourself.")
        for m in chat.get("messages", []):
            with st.chat_message("user" if m["role"] == "user" else "assistant",
                                 avatar="\U0001F464" if m["role"] == "user" else "\U0001F4AC"):
                st.markdown(m["text"] if m["role"] == "assistant" else md_escape(m["text"]))
        pending = s.get("help_pending")
        if pending and isinstance(pending, tuple) and pending[0] == chat.get("key"):
            with st.chat_message("assistant", avatar="\U0001F4AC"), st.spinner("Thinking…"):
                reply = helpdesk.ask(pending[1], chat.get("messages", [])[:-1], page_summary(), _key())
            s["help_pending"] = None
            chat = s.get("chat") or chat
            _save({**chat, "messages": list(chat.get("messages", [])) + [{"role": "assistant", "text": reply.text}]})
            _rerun_panel()
    if not chat.get("messages"):
        with st.container(horizontal=True, gap="small", key="helpdesk_quick"):
            for i, text in enumerate(QUICK.get(kind, QUICK[GENERAL])):
                st.button(text, key=f"helpdesk_quick_{i}", on_click=_quick, args=(text,))
    st.chat_input("Ask the Helpdesk…", key="assistant_input", on_submit=_on_input, max_chars=helpdesk.MAX_MESSAGE_CHARS)
    if kind == "tq":
        with st.expander("Your Suggestion For This Question", expanded=True):
            st.text_area("Final Wording", key="assistant_final", max_chars=1000, height=90,
                         help="What you send for verification. Use the Helpdesk's last answer, or write your own.")
            st.text_input("Your Name", key="assistant_by", autocomplete="off")
            with st.container(horizontal=True, gap="small"):
                st.button("Use Last Answer", key="assistant_use_reply", on_click=_use_reply)
                st.button("Send For Verification", key="assistant_submit", type="primary", on_click=_submit)
    elif kind in (GENERAL, "rule", "impact"):
        with st.expander("Turn My Request Into A Rule Proposal"):
            st.caption("Describe the rule in the chat first. The Helpdesk fills in the same form as the Rules page; "
                       "the proposal is checked like any other and waits in the Review Queue until it is verified.")
            st.text_input("Your Name", key="assistant_by", autocomplete="off")
            st.button("Draft A Rule Proposal", key="assistant_draft_rule", on_click=_draft_rule, disabled=not _key())
    st.caption("\U0001F512 Advice only. The Helpdesk can read the details shown above, but it cannot change your file, "
               "the rules or any code.")


# The open panel: fixed on the right, full height; the page (and its top bar) shrink by the same width.
OPEN_CSS = f"""
[data-testid=stMain]{{padding-right:{WIDTH}px}}
[data-testid=stHeader]{{width:calc(100% - {WIDTH}px)!important}}
.st-key-helpdesk_drawer{{position:fixed!important;top:0;right:0;bottom:0;width:{WIDTH}px!important;z-index:1000050;
background:#0f141b;border-left:1px solid var(--line);box-shadow:-12px 0 32px rgba(0,0,0,.45);padding:14px 16px 64px;
overflow-y:auto;overscroll-behavior:contain;animation:iosg-drawer-in .26s cubic-bezier(.2,.8,.2,1) both}}
.st-key-helpdesk_log{{height:calc(100vh - 380px)!important;min-height:220px}}
.st-key-helpdesk_focus{{border:1px solid rgba(57,135,229,.55);border-left:4px solid #3987e5;border-radius:10px;
background:rgba(57,135,229,.10);padding:8px 12px 4px}}
@media (max-width:900px){{[data-testid=stMain]{{padding-right:0}}[data-testid=stHeader]{{width:100%!important}}
.st-key-helpdesk_drawer{{width:100vw!important}}}}
"""
