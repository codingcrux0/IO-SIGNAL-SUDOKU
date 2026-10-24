"""Strict readiness (an error blocks), links inside sentences, and short questions with an (i) hover."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from io_sudoku.core.readiness import assess
from io_sudoku.core.tq import TQ
from io_sudoku.ui import nav, search, ui_logic

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _tq(tq_id: str, severity: str, ref: str = "X", message: str = "m") -> TQ:
    return TQ(tq_id=tq_id, severity=severity, category="Data", owner="Instrument", ref=ref, message=message,
              resolution="Fix it.")


def _result(tqs=(), violations=(), quarantined=(), rows=({"Tag Name": "A"},)):
    return SimpleNamespace(rows=list(rows), tqs=list(tqs), violations=list(violations), quarantined=list(quarantined))


# ---------------------------------------------------------------- strict readiness
def test_an_error_blocks_even_when_signals_were_allocated():
    r = assess(_result([_tq("DUPLICATE-TAG", "error")]), {})
    assert r.status == "BLOCKED" and any("Fix every error" in x for x in r.reasons)


def test_a_broken_rule_or_a_held_back_signal_blocks():
    broken = SimpleNamespace(rule="V03", severity="error", ref="x", message="m")
    assert assess(_result(violations=[broken])).status == "BLOCKED"
    assert assess(_result(quarantined=[object()])).status == "BLOCKED"


def test_warnings_only_stay_draft_and_nothing_allocated_is_blocked():
    assert assess(_result([_tq("TOPOLOGY-INFERRED", "warning")]), {}).status == "DRAFT"
    assert assess(_result(rows=())).status == "BLOCKED"


# ---------------------------------------------------------------- short questions
def test_short_text_keeps_the_start_and_the_closing_question():
    names = " / ".join(f"P12-DCM-2100{i}-01 / P12-DCS-2100{i}-01" for i in range(9))
    long = f"Cabinets for technical room PIB-12 were inferred from names: {names}. Are they correct?"
    short = ui_logic.short_text(long)
    assert short == "Cabinets for technical room PIB-12 were inferred from names … Are they correct?"
    assert len(short) <= ui_logic.SHORT_TEXT
    assert ui_logic.short_text("Tag 850-TT   -20025 has no cable.") == "Tag 850-TT   -20025 has no cable."
    assert len(ui_logic.short_text("word " * 80)) <= ui_logic.SHORT_TEXT


def test_details_behind_the_info_mark_have_the_full_text_fix_and_owner():
    long = "x" * 300
    result = _result([_tq("BLANK-TAG", "error", "R1", long)])
    details = dict(ui_logic.question_details(result, "BLANK-TAG", "R1", long))
    assert details["Full text"] == long and details["Suggested fix"] == "Fix it." and details["Owner"] == "Instrument"


# ---------------------------------------------------------------- links in sentences
def test_links_point_at_search_places_and_slugs_are_unique():
    assert len(nav.SLUGS) == len(search.PLACES)
    assert nav.link("TQ Board", "TQ Board", "Pin A Cable") == "[TQ Board](#go-tq-board-pin-a-cable)"
    assert nav.link("Parts", "Parts", "No Such Heading") == "[Parts](#go-parts)"          # falls back to the page


def test_a_link_button_opens_the_page_tab_and_section():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["view"] = "Files"
    at.run()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    assert any("#go-revision" in m.value for m in [*at.markdown, *at.caption])            # the sentence has a link
    at.button(key="navgo_" + nav.slug("Revision › Revision History")).click().run()
    assert at.session_state["view"] == "Revision" and at.session_state["rev_tab"] == "Revision History"
    assert not at.exception, [e.value for e in at.exception]


def test_sign_off_rows_are_short_with_details_on_hover():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["view"] = "Upload"
    at.run()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    at.session_state["view"] = "TQ Board"
    at.run()
    rows = [m for m in at.markdown if m.value.startswith("▲ ")]
    assert rows and all(m.help and "**Full text:**" in m.help for m in rows)
    assert not at.exception
