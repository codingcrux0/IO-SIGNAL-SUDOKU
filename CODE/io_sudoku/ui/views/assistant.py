"""The suggestion assistant in the sidebar: talk a TQ's fix through, then send the final wording for approval.

The AI behind it is NOT connected yet (when and how is still being decided with the project owner).  Until
then the box works as a scratch pad: you write, the last message becomes the final wording, and "Send For
Approval" turns it into a pending suggestion.  When the AI is added it gets core.suggestion.ASSISTANT_RULES:
it may only discuss and reword the suggestion.  It has no tools and no way to change a file, rule or code.
"""
from __future__ import annotations

import time

import streamlit as st

from io_sudoku.core.suggestion import make_suggestion
from io_sudoku.ui import state
from io_sudoku.ui.views._common import md_escape

NOT_CONNECTED = ("I am not connected yet, so I cannot answer. When I am switched on I will only help you word "
                 "this suggestion: I cannot change any file, rule, allocation or code.")


def _send() -> None:
    s = st.session_state
    chat, text = s.get("chat"), (s.get("assistant_input") or "").strip()
    if not chat or not text:
        return
    messages = list(chat["messages"]) + [{"role": "user", "text": text}]
    if not any(m["role"] == "assistant" for m in messages):
        messages.append({"role": "assistant", "text": NOT_CONNECTED})
    s["chat"] = {**chat, "messages": messages}
    s["assistant_final"] = text                        # your latest message is the proposed wording


def _submit() -> None:
    s = st.session_state
    chat = s.get("chat")
    if not chat:
        return
    sg, errors = make_suggestion(chat["tq_id"], chat["ref"], s.get("assistant_final") or "", s.get("assistant_by") or "",
                                 time.strftime("%Y-%m-%d %H:%M"))
    if sg is None:
        state.flash("error", " ".join(errors), "assistant")
        return
    s["suggestions"] = s["suggestions"] + [sg]
    s["tq_notes"] = {**s["tq_notes"], chat["tq_key"]: {"text": sg.text, "by": sg.author, "time": sg.created}}
    state.flash("success", "Sent for approval. A different person approves it on the Rules page.", "assistant")


def _close() -> None:
    st.session_state["chat"] = None


def render_sidebar() -> None:
    """Call inside `with st.sidebar:`.  Shows nothing until a TQ's ▸ panel opens the assistant."""
    s = st.session_state
    chat = s.get("chat")
    if not chat:
        return
    with st.container(border=True, key="assistant_box"):
        st.markdown("**\U0001F4AC Suggestion Assistant**",
                    help="Helps you decide whether your suggested fix is good and word it better. It only talks "
                         "about words: it cannot change any file, rule, allocation or code. The final wording still "
                         "needs a different person's approval.")
        st.caption(f"{md_escape(chat['tq_id'])} · {md_escape(chat['ref'] or '-')}")
        state.show_flash("assistant")
        st.caption("⚠️ The AI is not connected yet. You can still draft here and send the final wording for approval.")
        with st.container(height=200, key="assistant_log"):
            if chat.get("fix"):
                st.markdown(f"<small>Tool's suggested fix: {md_escape(chat['fix'])}</small>", unsafe_allow_html=True)
            for m in chat["messages"]:
                who = "You" if m["role"] == "user" else "Assistant"
                st.markdown(f"<small><b>{who}:</b> {md_escape(m['text'])}</small>", unsafe_allow_html=True)
        st.chat_input("Write your suggestion…", key="assistant_input", on_submit=_send, max_chars=1000)
        st.text_area("Final Wording", key="assistant_final", max_chars=1000, height=90)
        st.text_input("Your Name", key="assistant_by", autocomplete="off")
        with st.container(horizontal=True, gap="small"):
            st.button("Send For Approval", key="assistant_submit", type="primary", on_click=_submit)
            st.button("Close", key="assistant_close", on_click=_close)
