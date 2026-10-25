"""An error or warning you have to fix is brought into view and glows, wherever it is on the page."""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from io_sudoku.ui import state

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _scripts(at: AppTest) -> int:
    return sum("__iosgAlert" in str(f.proto) for f in at.get("iframe"))


def _app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["view"] = "Upload"
    at.run()
    return at


def test_an_error_message_is_brought_into_view_every_time_it_is_raised():
    at = _app()
    for _ in range(2):                                         # the same mistake twice: brought into view twice
        at.session_state["flash"] = ("error", "Type your name first.", "")
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        assert [e.value for e in at.error] == ["Type your name first."] and _scripts(at) == 1
    at.session_state["flash"] = ("warning", "Pick a column first.", "")
    at.run()
    assert [w.value for w in at.warning][-1] == "Pick a column first." and _scripts(at) == 1


def test_a_lasting_error_is_brought_into_view_only_when_it_first_appears():
    at = _app()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    at.session_state["ui_error"] = "The solve stopped unexpectedly."
    at.run()
    assert _scripts(at) == 1
    at.run()                                                   # still on the page, but you have seen it
    assert any("stopped unexpectedly" in e.value for e in at.error) and _scripts(at) == 0


def test_information_and_success_messages_do_not_move_the_page():
    at = _app()
    at.session_state["flash"] = ("info", "Nothing was changed.", "")
    at.run()
    assert _scripts(at) == 0 and at.info


def test_the_script_only_scrolls_when_the_message_is_out_of_sight_and_respects_less_motion():
    script = state._ALERT_SCRIPT
    assert "r.top < 70 || r.bottom > h - 16" in script and "prefers-reduced-motion" in script
    assert "requestAnimationFrame" not in script and "setInterval" not in script
