"""The Helpdesk's live answer (streamed, with the model's own thinking steps and a ticking status), its strict scope,
and earlier conversations shown as questions and answers."""
from __future__ import annotations

import io
import urllib.error
from pathlib import Path

from streamlit.testing.v1 import AppTest

from io_sudoku.core import helpdesk
from io_sudoku.ui import aistatus, faqview

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _chunk(text: str, thought: bool = False, finish: str = "") -> dict:
    part = {"text": text, **({"thought": True} if thought else {})}
    return {"candidates": [{"content": {"parts": [part]}, **({"finishReason": finish} if finish else {})}]}


class Stream:
    """A fake streamed transport: each call yields the next script (a list of chunks, or an exception)."""

    def __init__(self, *scripts) -> None:
        self.scripts, self.calls = list(scripts), []

    def __call__(self, model, body, key, timeout):
        self.calls.append((model, body))
        script = self.scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        for item in script:
            if isinstance(item, Exception):
                raise item
            yield item


def _http(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def setup_function():
    helpdesk.BREAKER.until.clear()


# ------------------------------------------------------------------ scope
def test_only_the_project_is_in_scope():
    for text in ("write me a poem about love", "what's the weather today", "help me with my python homework",
                 "tell me a joke", "how do I cook pasta", "who is the president of USA"):
        assert helpdesk.off_topic(text), text
    for text in ("Why was ALARMS-MISSING raised?", "what should I do next?", "hi", "explain wired spares",
                 "what is the AI signal on DO cable", "write a poem about CHARMs"):
        assert not helpdesk.off_topic(text), text            # project words go to the model, whose rules decide
    rules = helpdesk.RULES
    assert "SCOPE (strict)" in rules and helpdesk.REFUSAL in rules and "HOW YOU THINK" in rules and "{" not in rules
    stream = Stream()
    reply = helpdesk.ask_stream("tell me a joke", [], "page", "key", transport=stream)
    assert reply.ok and reply.text == helpdesk.REFUSAL and reply.model == "scope" and not stream.calls   # never sent
    assert helpdesk.ask("tell me a joke", [], "page", "key").text == helpdesk.REFUSAL


# ------------------------------------------------------------------ streaming
def test_a_streamed_answer_reports_the_models_own_steps_then_the_text():
    events = []
    stream = Stream([_chunk("**Checking the cable pairs**\n\nThe user asks ...", thought=True),
                     _chunk("**Drafting the answer**", thought=True),
                     _chunk("Press **Edit** "), _chunk("on the TQ Board.", finish="STOP")])
    reply = helpdesk.ask_stream("How do I fix it?", [], "page", "key", lambda k, t: events.append((k, t)),
                                transport=stream, clock=lambda: 50.0)
    assert reply.ok and reply.text == "Press **Edit** on the TQ Board." and reply.model == helpdesk.MODELS[0]
    assert reply.steps == ["Checking the cable pairs", "Drafting the answer"]
    assert events == [("thought", "Checking the cable pairs"), ("thought", "Drafting the answer"),
                      ("text", "Press **Edit** "), ("text", "Press **Edit** on the TQ Board.")]
    body = stream.calls[0][1]
    assert body["generationConfig"]["thinkingConfig"] == {"includeThoughts": True} and "tools" not in body


def test_streaming_falls_back_cleanly():
    # a model that cannot show its thinking (400) answers without it; one out of quota is skipped
    stream = Stream(_http(429), _http(400), [_chunk("Answer.")])
    reply = helpdesk.ask_stream("q", [], "p", "k", transport=stream, clock=lambda: 10.0)
    assert reply.ok and reply.text == "Answer." and reply.model == helpdesk.MODELS[1]
    assert "thinkingConfig" in stream.calls[1][1]["generationConfig"] and "thinkingConfig" not in stream.calls[2][1]["generationConfig"]
    # the network drops after part of the answer arrived: the part is kept
    reply = helpdesk.ask_stream("q", [], "p", "k", transport=Stream([_chunk("Half an "), _chunk("answer"), TimeoutError()]))
    assert reply.ok and reply.text == "Half an answer"
    # a blocked answer, every model down, a crashing progress callback: polite, never raises
    assert helpdesk.ask_stream("q", [], "p", "k", transport=Stream([_chunk("", finish="SAFETY")])).text == helpdesk.SAFE_REPLY
    down = Stream(*[TimeoutError()] * len(helpdesk.MODELS))
    assert not helpdesk.ask_stream("q", [], "p", "k", transport=down).ok
    helpdesk.BREAKER.until.clear()

    def boom(kind, text):
        raise RuntimeError("drawing failed")
    assert helpdesk.ask_stream("q", [], "p", "k", boom, transport=Stream([_chunk("Fine.")])).text == "Fine."
    assert not helpdesk.ask_stream("q", [], "p", None).ok and "not set up" in helpdesk.ask_stream("q", [], "p", None).text


def test_thought_headings_are_plain_and_short():
    assert helpdesk.heading('**Defining "Wired Spare"**\n\nmore') == 'Defining "Wired Spare"'
    assert helpdesk.heading("<b>Looking</b> at `x`") == "Looking at x"
    assert len(helpdesk.heading("**" + "word " * 40 + "**")) <= 70


# ------------------------------------------------------------------ the live status
def test_the_status_shows_the_real_step_and_a_ticking_timer():
    assert aistatus.phase("Checking the cable") == "researching" and aistatus.phase("Assessing the risk") == "analyzing"
    assert aistatus.phase("Drafting the answer") == "writing" and aistatus.phase('Defining "Wired Spare"') == "thinking"
    live = aistatus.status_html("researching", "Checking <cable> & pairs", 7.4)
    assert "Researching" in live and "&lt;cable&gt; &amp; pairs" in live and "data-active" in live
    assert "--aist-from:-7s" in live and "--aist-minute:53s" in live          # the CSS clock resumes at 7 seconds
    done = aistatus.status_html("done", "", 64)
    assert "Worked for 1m 04s" in done and "data-active" not in done and "aist-timer" not in done
    assert "Failed after 3s" in aistatus.status_html("error", "", 3)
    assert "<details" in aistatus.history_html(4, ["Checking the cable"]) and "<details" not in aistatus.history_html(4, [])
    assert "@property --aist-t" in aistatus.CSS and "prefers-reduced-motion" in aistatus.CSS


# ------------------------------------------------------------------ earlier conversations as questions and answers
def test_an_earlier_conversation_becomes_safe_questions_and_answers():
    messages = [{"role": "user", "text": "Why <b>this</b>?"}, {"role": "assistant", "text": "Because:\n- **one**\n- two"},
                {"role": "user", "text": "And?"}]
    assert faqview.pairs(messages) == [("Why <b>this</b>?", "Because:\n- **one**\n- two"),
                                       ("And?", "No answer was given to this question.")]
    page = faqview.faq_page(messages)
    assert "Why &lt;b&gt;this&lt;/b&gt;?" in page and "<li><strong>one</strong></li>" in page
    assert 'aria-expanded="false"' in page and 'role="region"' in page and "ArrowDown" in page
    evil = faqview.safe_markdown('<script>alert(1)</script> [click](javascript:alert(1)) ![x](y.png)')
    assert "<script>" not in evil and "javascript:" not in evil and "&lt;script&gt;" in evil
    assert faqview.faq_page([]) == "" and faqview.faq_page(messages, accent="red;}") .count("--accent:#1f6feb") == 1


# ------------------------------------------------------------------ the panel, end to end (with a fake AI)
def _app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["view"] = "Upload"
    at.run()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    return at


def test_the_panel_streams_an_answer_and_reopens_old_logs_as_questions(monkeypatch):
    from io_sudoku.ui.views import assistant
    monkeypatch.setattr(assistant, "_key", lambda: "test-key")
    monkeypatch.setattr(helpdesk, "_stream_post", Stream(
        [_chunk("**Checking the readiness**", thought=True), _chunk("Sign off the two warnings.")],
        [_chunk("It is about cable 320-CE-0001.")]))
    at = _app()
    at.button(key="helpdesk_open").click().run()
    at.session_state["help_last"] = 0.0
    at.chat_input(key="assistant_input").set_value("What should I do next?").run()
    answer = at.session_state["chat"]["messages"][-1]
    assert answer["text"] == "Sign off the two warnings." and answer["steps"] == ["Checking the readiness"]
    assert answer["ok"] and answer["secs"] >= 0 and not at.exception, [e.value for e in at.exception]
    assert any("Worked for" in m.value and "Checking the readiness" in m.value for m in at.markdown)
    general = at.session_state["chat"]["key"]
    at.session_state["view"] = "TQ Board"
    at.run()
    at.button(key="fixmore_0_0").click().run()
    first = next(x.key for x in at.button if x.key and x.key.startswith("chat_open_"))
    at.button(key=first).click().run()
    assert at.session_state["chat"]["view"] == "chat"                      # a new topic starts as a chat
    box = at.selectbox(key="helpdesk_conv")
    box.select_index(next(i for i, o in enumerate(box.options) if o.startswith("General help"))).run()
    chat = at.session_state["chat"]
    assert chat["key"] == general and chat["view"] == "faq" and not at.exception   # an old log: questions and answers
    assert any(b.key == "helpdesk_as_chat" for b in at.button)
    at.button(key="helpdesk_as_chat").click().run()
    assert at.session_state["chat"]["view"] == "chat" and any(b.key == "helpdesk_as_faq" for b in at.button)
    at.session_state["help_last"] = 0.0
    at.chat_input(key="assistant_input").set_value("Which cable?").run()
    assert at.session_state["chat"]["messages"][-1]["text"] == "It is about cable 320-CE-0001" + "." and not at.exception


def test_the_helpdesk_is_told_each_cabinet_and_the_spares_so_it_never_guesses_them():
    from io_sudoku.core.pipeline import solve
    from io_sudoku.samples import sample_mdb_bytes
    from io_sudoku.ui.views.assistant import _cabinet_lines
    lines = _cabinet_lines(solve(sample_mdb_bytes()).rows)
    assert lines[0].startswith("Marshalling cabinets in the allocation (3)")
    first = next(x for x in lines if "P30-DCM-32001-01" in x)
    assert "controller P30DPK320101" in first and "system cabinet P30-DCS-32001-01" in first and "field signals" in first
    assert _cabinet_lines([]) == []
