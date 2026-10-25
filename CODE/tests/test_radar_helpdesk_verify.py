"""One-button Verify for rules and suggestions, Rule Radar (Rule Check + Rule Impact as tabs), picked cells from an
earlier file, and the Helpdesk that opens about one thing (with what it already knows) in its own conversation."""
from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from io_sudoku.core import cellcheck, helpcontext, helpdesk, rulechange as rc, ruleimpact as ri
from io_sudoku.core import suggestion as sg_mod
from io_sudoku.samples import load_sample_result
from io_sudoku.ui import search, state

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(view: str = "Upload") -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["view"] = "Upload"
    at.run()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    at.session_state["view"] = view
    at.run()
    return at


def _texts(at: AppTest) -> str:
    return " ".join(x.value for x in [*at.markdown, *at.caption, *at.info, *at.subheader, *at.header])


# ------------------------------------------------------------------ Verify (no passcode)
def test_verify_and_reject_need_no_passcode_and_decide_once():
    p, errors = rc.build_proposal("spare_pct", {"value": 12}, "alice", now="1")
    assert not errors and rc.verify(p, "2") == [] and p.status == "approved" and p.reviewer
    assert rc.verify(p, "3") and rc.dismiss(p, "3")                                  # already decided
    q, _ = rc.build_proposal("spare_pct", {"value": 15}, "alice", now="4")
    assert rc.dismiss(q, "5") == [] and q.status == "rejected" and q.reason             # the reason is optional
    sg, _ = sg_mod.make_suggestion("TQ-1", "TAG", "Add the alarm rows.", "bob", "1")
    assert sg_mod.verify(sg, "2") == [] and sg.status == "approved"


def test_the_review_queue_has_a_verify_button_and_no_passcode():
    at = _app("Rules")
    p, _ = rc.build_proposal("spare_pct", {"value": 12}, "alice", now="1")
    at.session_state["proposals"] = [p]
    at.run()
    assert not [w for w in at.text_input if "Passcode" in w.label]
    assert not any("switched off" in w.value for w in [*at.warning, *at.error])
    at.button(key=f"verify_{p.id}").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["proposals"][0].status == "approved" and "Rule verified" in " ".join(s.value for s in at.success)
    assert not [b for b in at.button if b.key == f"verify_{p.id}"]                     # decided: the button is gone


def test_a_rule_can_be_rejected_from_its_pop_up():
    at = _app("Rules")
    p, _ = rc.build_proposal("spare_pct", {"value": 12}, "alice", now="1")
    at.session_state["proposals"] = [p]
    at.run()
    at.text_input(key=f"rs_{p.id}").set_value("Not needed").run()
    at.button(key=f"reject_{p.id}").click().run()
    assert at.session_state["proposals"][0].status == "rejected" and at.session_state["proposals"][0].reason == "Not needed"


def test_a_suggested_fix_is_verified_with_one_button():
    at = _app("Rules")
    sg, _ = sg_mod.make_suggestion("ALARMS-MISSING-FOR-CABINET", "P30-DCS-32001-02", "Add the alarm rows.", "bob", "1")
    at.session_state["suggestions"] = [sg]
    at.run()
    at.button(key=f"sgverify_{sg.id}").click().run()
    assert at.session_state["suggestions"][0].status == "approved" and not at.exception


# ------------------------------------------------------------------ Rule Radar
def test_rule_check_and_rule_impact_are_tabs_of_rule_radar_and_old_links_work():
    assert "Rule Radar" in state.VIEWS and "Rule Check" not in state.VIEWS and "Rule Impact" not in state.VIEWS
    assert not [p for p in search.PLACES if p.view in ("Rule Check", "Rule Impact")]
    for old, tab in (("Rule Check", "Rule Check"), ("Rule Impact", "Rule Impact")):
        at = AppTest.from_file(APP, default_timeout=90)
        at.query_params["view"] = old
        at.run()
        assert at.session_state["view"] == "Rule Radar" and at.session_state["rule_tab"] == tab and not at.exception
    at = _app("Rule Radar")
    assert not at.exception and [t.label for t in at.tabs][:2] == ["Rule Check", "Rule Impact"]
    assert "Pick The Cells To Check" in _texts(at) and "Pick A Rule" in _texts(at)        # both tabs, unchanged


def test_cells_picked_in_an_earlier_file_are_explained_and_cleared():
    at = _app("Rule Radar")
    at.session_state["rc_cells"] = ["P99-DCM-00000-01|1|2|1"]
    at.run()
    assert "not in this allocation" in _texts(at) and "earlier file" in _texts(at) and not at.exception
    at.button(key="rc_drop_missing").click().run()
    assert at.session_state["rc_cells"] == []
    at.session_state["rc_cells"] = ["P99-DCM-00000-01|1|2|1"]
    state_keys = at.session_state["mdb_sha"]
    at.session_state["mdb_sha"] = "different"                                          # a new file clears the picks
    at.session_state["view"] = "Upload"
    at.run()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    assert at.session_state["rc_cells"] == [] and state_keys


# ------------------------------------------------------------------ what the Helpdesk is told
def test_each_focus_carries_the_details_of_its_thing_and_never_raises():
    result = load_sample_result()
    tq = next(t for t in result.tqs if t.severity == "warning")
    title, text = helpcontext.tq_focus(result, tq.tq_id, tq.ref)
    assert tq.tq_id in title and tq.message in text and tq.resolution in text
    row = next(r for r in result.rows if r["Tag Status"] == "Field")
    checks = cellcheck.check_cell(result, row)
    title, text = helpcontext.cell_focus(result, row, checks, cellcheck.signal_path(row), cellcheck.slot_label(row))
    assert row["Tag Name"] in text and "CHARM_No" in text and "Signal path" in text and "Why the solver" in text
    impact = next(x for x in ri.rule_impact(result) if x.rule == "V06")
    title, text = helpcontext.rule_focus(impact)
    assert "V06" in title and "cells" in text
    title, text = helpcontext.answer_focus(result, tag=row["Tag Name"], field="io_type", value="AIR")
    assert row["Tag Name"] in title and "Where it is in the allocation" in text
    title, text = helpcontext.tag_focus(result, row["Tag Name"])
    assert row["Tag Name"] in title and len(text) <= helpcontext.MAX_CHARS + 20
    for fn in (lambda: helpcontext.tq_focus(None, "X", "Y"), lambda: helpcontext.rule_focus(None),
               lambda: helpcontext.cell_focus(None, {}, [], [], "c"), lambda: helpcontext.answer_focus(None)):
        assert all(isinstance(x, str) for x in fn())


def test_the_focus_goes_first_and_the_request_still_has_no_tools():
    body = helpdesk.build_request("rules", [], "Why?", "FOCUS OF THIS CONVERSATION:\nquestion X on TAG-1\n\nTHE WHOLE PROJECT:")
    text = json.dumps(body)
    assert "question X on TAG-1" in text and "tools" not in body and "functionDeclarations" not in text
    assert "FOCUS" in helpdesk.RULES


# ------------------------------------------------------------------ one conversation per topic
def _send(at: AppTest, text: str) -> None:
    at.session_state["help_last"] = 0.0                                                 # past the 1-second limit
    at.chat_input(key="assistant_input").set_value(text).run()


def test_every_question_has_its_own_conversation():
    at = _app("TQ Board")
    at.button(key="fixmore_0_0").click().run()
    first = next(x.key for x in at.button if x.key and x.key.startswith("chat_open_"))
    at.button(key=first).click().run()
    key_a, title_a = at.session_state["chat"]["key"], at.session_state["chat"]["title"]
    _send(at, "Why was this raised?")
    assert len(at.session_state["chat"]["messages"]) == 2
    at.button(key="helpdesk_close").click().run()
    at.button(key="fixmore_0_1").click().run()                                        # another question
    second = next(x.key for x in at.button if x.key and x.key.startswith("chat_open_") and x.key != first)
    at.button(key=second).click().run()
    chat = at.session_state["chat"]
    assert chat["key"] != key_a and chat["messages"] == [] and chat["open"]           # a fresh conversation
    _send(at, "And this one?")
    assert [m["text"] for m in at.session_state["chat"]["messages"] if m["role"] == "user"] == ["And this one?"]
    box = at.selectbox(key="helpdesk_conv")
    box.select_index(next(i for i, o in enumerate(box.options) if o.startswith(title_a))).run()   # back to the first one
    chat = at.session_state["chat"]
    assert chat["key"] == key_a and [m["text"] for m in chat["messages"] if m["role"] == "user"] == ["Why was this raised?"]
    assert not at.exception, [e.value for e in at.exception]


def test_the_answer_box_opens_the_helpdesk_about_the_answer():
    at = _app("TQ Board")
    at.button(key="answer_ask").click().run()
    chat = at.session_state["chat"]
    assert chat["open"] and chat["kind"] == "answer" and "Answer A Question" in chat["context"] and not at.exception
    assert any("About:" in m.value for m in at.markdown)


def test_a_rule_check_cell_and_a_rule_impact_rule_open_the_helpdesk_with_their_details():
    at = _app("Rule Radar")
    row = next(r for r in at.session_state["result"].rows if r["Tag Status"] == "Field")
    at.session_state["rc_cells"] = [cellcheck.slot_id(row)]
    at.session_state["ri_pick"] = "V06|Segregation A and B never share a CIOC"
    at.run()
    at.button(key=next(b.key for b in at.button if b.key and b.key.startswith("rc_ask_"))).click().run()
    chat = at.session_state["chat"]
    assert chat["kind"] == "cell" and row["Tag Name"] in chat["context"] and not at.exception
    at.button(key="ri_ask").click().run()
    chat = at.session_state["chat"]
    assert chat["kind"] == "impact" and "V06" in chat["title"] and chat["messages"] == []
    assert len(at.session_state["chats"]) == 2 and not at.exception
