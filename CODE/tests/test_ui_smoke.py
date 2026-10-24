"""Smoke-test the Streamlit app headlessly with Streamlit's own AppTest (no browser)."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from io_sudoku.ui.state import VIEWS

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def run(view: str | None = None, sample: bool = False) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["view"] = view or VIEWS[0]
    at.run()
    if sample:
        next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    return at


def test_every_view_renders_empty_without_exceptions():
    for view in VIEWS:
        at = run(view)
        assert not at.exception, (view, [e.value for e in at.exception])
        assert not at.error, (view, [e.value for e in at.error])


def test_sample_button_solves_and_all_views_render():
    at = run("Upload", sample=True)
    assert at.session_state["result"] is not None and at.session_state["result"].readiness.status == "ISSUE-READY"
    for view in VIEWS:
        at.session_state["view"] = view
        at.run()
        assert not at.exception, (view, [e.value for e in at.exception])
        assert not at.error, (view, [e.value for e in at.error])


def test_rule_proposal_and_approval_flow(monkeypatch):
    monkeypatch.setenv("APPROVER_PASSCODE", "letmein")
    at = run("Rules")
    at.text_input(key="rule_author").set_value("alice")
    at.selectbox(key="rule_tpl").set_value("high_current_keyword")
    at.run()
    at.text_input(key="rf_high_current_keyword_keyword").set_value("psv")
    next(b for b in at.button if b.label == "Propose Rule").click().run()
    assert not at.exception
    (p,) = at.session_state["proposals"]
    assert p.status == "pending" and "psv" in p.statement
    at.text_input(key=f"rv_{p.id}").set_value("alice")            # author may not approve their own rule
    at.text_input(key=f"pc_{p.id}").set_value("letmein")
    next(b for b in at.button if b.label == "Approve Rule").click().run()
    assert p.status == "pending"
    at.text_input(key=f"rv_{p.id}").set_value("bob")
    next(b for b in at.button if b.label == "Approve Rule").click().run()
    assert at.session_state["proposals"][0].status == "approved" and not at.exception


def test_wrong_passcode_is_refused(monkeypatch):
    monkeypatch.setenv("APPROVER_PASSCODE", "letmein")
    at = run("Rules")
    at.text_input(key="rule_author").set_value("alice")
    at.selectbox(key="rule_tpl").set_value("spare_pct")
    at.run()
    at.number_input(key="rf_spare_pct_value").set_value(12)
    next(b for b in at.button if b.label == "Propose Rule").click().run()
    (p,) = at.session_state["proposals"]
    at.text_input(key=f"rv_{p.id}").set_value("bob")
    at.text_input(key=f"pc_{p.id}").set_value("wrong")
    next(b for b in at.button if b.label == "Approve Rule").click().run()
    assert at.session_state["proposals"][0].status == "pending"


def test_ai_box_is_disabled_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = run("Rules")
    assert next(b for b in at.button if b.label == "Draft Rule With AI").disabled


def test_pin_and_stale_banner():
    at = run("TQ Board", sample=True)
    cable = at.selectbox(key="pin_cable").options[0]
    next(b for b in at.button if b.label == "Add Pin").click().run()
    assert at.session_state["pins"] and at.session_state["stale"] and not at.exception
    next(b for b in at.button if b.label == "Re-solve").click().run()
    assert not at.session_state["stale"] and cable in at.session_state["pins"]


def test_simulator_runs_on_the_sample():
    at = run("Simulator", sample=True) if False else run("Upload", sample=True)
    at.session_state["view"] = "Simulator"
    at.run()
    next(b for b in at.button if b.label == "Run Simulation").click().run()
    assert at.session_state["sim"] is not None and not at.exception


def test_reset_needs_confirmation():
    at = run("Upload", sample=True)
    assert next(b for b in at.button if b.label == "Reset Session").disabled
    at.checkbox(key="confirm_reset").check().run()
    next(b for b in at.button if b.label == "Reset Session").click().run()
    assert at.session_state["result"] is None
