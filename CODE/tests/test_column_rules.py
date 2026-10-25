"""Columns And Checks: one project column with a value per signal and the checks those values must pass; the
Review Queue scroll box; the table scrollbar; the Assumptions box on Solve."""
from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from io_sudoku.core import advisor, assumptions, cellcheck, projectrules as pr, rulechange as rc
from io_sudoku.core.config import load_config
from io_sudoku.core.pipeline import solve
from io_sudoku.core.ruleimpact import rule_impact
from io_sudoku.core.rulepack import RulePack, apply_pack, default_pack, validate_pack
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui import theme

APP = str(Path(__file__).resolve().parents[1] / "app.py")
BASE = solve(sample_mdb_bytes())
SIGNALS = [r for r in BASE.rows if pr.is_signal(r)]


def _approved(args: dict, when: str = "1") -> rc.RuleProposal:
    p, errors = rc.build_proposal("column_rule", args, "alice", now=when)
    assert not errors, errors
    p.status = "approved"
    return p


def _voltage(**extra) -> dict:
    return {"column": "Voltage", "type": "number", "unit": "V",
            "fills": [{"column": "IO Type", "how": "is", "text": "AIR", "value": "24"}], "default": "",
            "checks": [{"check": "max", "value": "24", "severity": "error"}], **extra}


def _solve(*proposals, pack=None):
    pack = rc.apply_approved(pack or default_pack(), list(proposals))
    assert not validate_pack(pack)
    return pack, solve(sample_mdb_bytes(), apply_pack(pack, load_config()))


# ------------------------------------------------------------------ the rule itself
def test_a_value_comes_from_the_typed_value_then_the_last_fill_rule_then_the_default():
    air = next(r for r in SIGNALS if r["IO Type"] == "AIR")
    dir_ = next(r for r in SIGNALS if r["IO Type"] == "DIR")
    args, errors = pr.normalize_column_rule({"column": "Loop Check", "fills": [
        {"column": "IO Type", "how": "contains", "text": "R", "value": "first"},
        {"column": "IO Type", "how": "is", "text": "air", "value": "second"}], "default": "rest",
        "values": {air["Tag Name"].upper(): "typed"}})
    assert not errors
    rule = {"kind": "column_rule", "args": args}
    assert pr.column_value(rule, air) == ("typed", "typed for this signal")
    other_air = next(r for r in SIGNALS if r["IO Type"] == "AIR" and r is not air)
    assert pr.column_value(rule, other_air)[0] == "second"                      # the lower fill rule wins
    assert pr.column_value(rule, dir_)[0] == "first"
    no_r = next((r for r in SIGNALS if "R" not in r["IO Type"].upper()), None)
    if no_r is not None:
        assert pr.column_value(rule, no_r)[0] == "rest"


def test_the_form_is_checked_and_worded_by_code():
    args, errors = pr.normalize_column_rule(_voltage(values={"320-FT  -20645-A": "30"}))
    assert not errors and args["values"] == {"320-ft -20645-a": "30"}
    text = pr.column_statement(args)
    assert "Project column 'Voltage' (number, V)" in text and "at most 24 V" in text and "(error)" in text
    bad = [
        ({"column": "Voltage", "type": "number", "values": {"T1": "high"}}, "not a number"),
        ({"column": "Tag Name"}, "already a column of the allocation"),
        ({"column": "Voltage", "type": "number", "checks": [{"check": "between", "value": "9", "value2": "1"}]}, "bigger"),
        ({"column": "Voltage", "type": "text", "checks": [{"check": "max", "value": "9"}]}, "does not suit"),
        ({"column": "Voltage", "checks": [{"check": "move_signal"}]}, "not one of the known checks"),
        ({"new": False, "column": "Remarks"}, "at least one check"),
        ({"new": False, "column": "Not A Column", "checks": [{"check": "required"}]}, "not an allocation column"),
        ({"column": "Voltage", "fills": [{"column": "Password", "how": "is", "text": "x", "value": "1"}]}, "not a column"),
    ]
    for args, words in bad:
        assert any(words in e for e in pr.normalize_column_rule(args)[1]), (args, pr.normalize_column_rule(args)[1])


def test_an_error_check_blocks_and_a_warning_check_asks_for_a_sign_off_without_moving_a_signal():
    tag = next(r for r in SIGNALS if r["IO Type"] == "AIR")["Tag Name"]
    rule = _approved(_voltage(values={tag: "30"}, checks=[
        {"check": "max", "value": "24", "severity": "error"},
        {"check": "required", "severity": "warning", "scope": {"column": "IO Type", "how": "is", "text": "DIR"}}]))
    pack, ruled = _solve(rule)
    assert ruled.kpis["output_sha256"] == BASE.kpis["output_sha256"]           # placement untouched
    errors = [t for t in ruled.tqs if t.tq_id == "PROJECT-CHECK-ERROR"]
    warnings = [t for t in ruled.tqs if t.tq_id == "PROJECT-RULE-BROKEN"]
    assert len(errors) == 1 and errors[0].severity == "error" and tag in errors[0].message
    assert len(warnings) == 1 and warnings[0].ref.endswith("check 2")
    assert ruled.readiness.status == "BLOCKED"
    row = next(r for r in ruled.rows if r["Tag Name"] == tag)
    assert pr.project_columns(pack.overrides["project_rules"], row) == {"Voltage (V)": "30"}
    checks = cellcheck.check_cell(ruled, row)
    assert any(c.status == cellcheck.FAIL and "at most 24 V" in c.title for c in checks)
    impacts = {i.title: i for i in rule_impact(ruled) if i.rule == "Project rule"}
    assert impacts["Voltage must be at most 24 V on every signal"].count(cellcheck.FAIL) == 1
    assert "Project column 'Voltage'" in impacts


def test_no_two_signals_the_same_finds_duplicates():
    a, b, c = SIGNALS[:3]
    args = {"column": "Loop No", "values": {a["Tag Name"]: "L1", b["Tag Name"]: "l1", c["Tag Name"]: "L2"},
            "checks": [{"check": "unique", "severity": "warning"}]}
    _, ruled = _solve(_approved(args))
    (tq,) = [t for t in ruled.tqs if t.tq_id == "PROJECT-RULE-BROKEN"]
    assert a["Tag Name"] in tq.message and b["Tag Name"] in tq.message and c["Tag Name"] not in tq.message


def test_checks_on_an_allocation_column_replace_the_old_ones():
    first = _approved({"new": False, "column": "Instrument type", "checks": [{"check": "required", "severity": "warning"}]})
    second = _approved({"new": False, "column": "instrument type", "checks": [
        {"check": "max_length", "value": "200", "severity": "error"}]}, "2")
    pack = rc.apply_approved(default_pack(), [first, second])
    (only,) = pack.overrides["project_rules"]
    assert only["args"]["checks"][0]["check"] == "max_length"


def test_a_new_version_replaces_a_column_and_removal_takes_it_away():
    old = _approved({"column": "Loop Check", "default": "Pending"})
    legacy, _ = rc.build_proposal("project_column", {"column": "Loop Check", "value": "x", "match_column": "IO Type",
                                                     "match_text": "AIR"}, "bob", now="0")
    legacy.status = "approved"
    pack = rc.apply_approved(default_pack(), [legacy, old])
    assert [r["kind"] for r in pack.overrides["project_rules"]] == ["column_rule"]       # the old one-value column too
    gone = _approved({"column": "loop check", "remove": True}, "3")
    assert gone.statement.startswith("Remove the project column")
    assert rc.apply_approved(pack, [gone]).overrides["project_rules"] == []


def test_a_malformed_column_rule_cannot_be_loaded():
    bad = RulePack("x", 2, "p", {}, {"project_rules": [{"kind": "column_rule", "args": {"column": "V", "type": "colour"}}]})
    assert validate_pack(bad)


# ------------------------------------------------------------------ the optional AI
class _Fake:
    def __init__(self, reply: str) -> None:
        self.reply, self.seen = reply, []

    def complete(self, system: str, user: str) -> str:
        self.seen.append((system, user))
        return self.reply


def test_the_ai_only_fills_the_form_and_bad_parts_are_left_out():
    reply = json.dumps({"column": "Voltage", "type": "number", "unit": "V", "default": "",
                        "fills": [{"column": "IO Type", "how": "contains", "text": "AI", "value": "24"}],
                        "checks": [{"check": "max", "value": "250", "severity": "error", "scope": {"how": "all"}},
                                   {"check": "max", "value": "lots", "severity": "error"}],
                        "note": "Supply voltage of each signal.", "rationale": "AI signals are 24 V."})
    fake = _Fake(reply)
    draft = advisor.draft_column("Voltage column, AI is 24 V, never above 250 V", fake)
    assert draft.ok and draft.args["column"] == "Voltage" and len(draft.args["checks"]) == 1 and draft.errors
    system, user = fake.seen[0]
    assert "<request>" in user and "untrusted" in system and "320-" not in system + user   # no MDB data goes in
    assert not advisor.draft_column("x", _Fake("not json")).ok
    assert not advisor.draft_column("x", None).ok
    assert not advisor.draft_column("x", _Fake('{"column": null, "reason": "no"}')).ok
    assert advisor.parse_reply('{"template": "column_rule", "args": {}}')[0] is None   # never through the old box


def test_the_ai_can_make_the_purpose_clearer():
    text, why = advisor.polish_text("volts for the loops innit", _Fake('"Supply voltage of each loop."'))
    assert text == "Supply voltage of each loop." and not why
    assert advisor.polish_text("", _Fake("x"))[0] is None and advisor.polish_text("x", None)[0] is None


# ------------------------------------------------------------------ the form
def _rules_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "Upload"
    at.run()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    at.session_state["view"] = "Rules"
    at.session_state["rule_group"] = "Columns And Checks"
    at.run()
    at.text_input(key="rule_author").set_value("alice").run()
    return at


def test_make_a_column_give_values_add_a_check_and_propose_it():
    at = _rules_app()
    assert not at.exception
    at.text_input(key="cb_name").set_value("Voltage")
    at.button_group(key="cb_type").set_value("number").run()
    at.text_input(key="cb_unit").set_value("V").run()
    at.text_input(key="cb_find").set_value("AIR").run()                    # find signals, then give them one value
    at.text_input(key="cb_set_value").set_value("24").run()
    next(b for b in at.button if b.key == "cb_set_shown").click().run()
    typed = at.session_state["cb_values"]
    assert typed and set(typed.values()) == {"24"}
    next(b for b in at.button if b.key == "cb_add_check").click().run()
    (u,) = at.session_state["cb_checks"]
    at.selectbox(key=f"cb_c{u}_kind").set_value("max")
    at.text_input(key=f"cb_c{u}_v").set_value("12").run()
    assert not at.exception
    assert any("break it" in m.value for m in at.markdown)               # the live count while you type
    next(b for b in at.button if b.key == "cb_propose").click().run()
    (p,) = at.session_state["proposals"]
    assert p.template == "column_rule" and p.status == "pending" and "at most 12 V" in p.statement
    assert at.session_state["cb_name"] == "" and not at.exception          # the form starts again
    at.button(key=f"verify_{p.id}").click().run()
    assert at.session_state["proposals"][0].status == "approved"


def test_paste_values_and_fill_rules():
    at = _rules_app()
    at.text_input(key="cb_name").set_value("Loop Check").run()
    tags = [r["Tag Name"] for r in SIGNALS[:2]]
    at.text_area(key="cb_paste").set_value(f"{tags[0]}\tDone\n{tags[1]}, Pending\nNOT-A-TAG\tx").run()
    next(b for b in at.button if b.key == "cb_use_paste").click().run()
    typed = at.session_state["cb_values"]
    assert typed[pr.tag_key(tags[0])] == "Done" and typed[pr.tag_key(tags[1])] == "Pending" and len(typed) == 2
    assert any("NOT-A-TAG" in w.value for w in at.warning)
    next(b for b in at.button if b.key == "cb_add_fill").click().run()
    (u,) = at.session_state["cb_fills"]
    at.selectbox(key=f"cb_f{u}_how").set_value("all")
    at.text_input(key=f"cb_f{u}_val").set_value("Open").run()
    assert not at.exception
    assert "2 signals have their own value" in next(m.value for m in at.markdown if "Wording" in m.value)


def test_edit_and_remove_an_active_column():
    at = _rules_app()
    rule = _approved(_voltage())
    at.session_state["pack"] = rc.apply_approved(default_pack(), [rule])
    at.session_state["rule_group"] = "Settings"
    at.run()
    at.button(key="active_edit_0").click().run()
    assert at.session_state["rule_group"] == "Columns And Checks" and at.session_state["cb_target"] == "project:Voltage"
    assert len(at.session_state["cb_checks"]) == 1 and len(at.session_state["cb_fills"]) == 1 and not at.exception
    assert any(b.key == "cb_propose" and b.label == "Propose This Change" for b in at.button)
    at.button(key="ask_active_remove_0").click().run()
    at.button(key="yes_active_remove_0").click().run()
    (p,) = at.session_state["proposals"]
    assert p.args.get("remove") and p.status == "pending"


def test_the_review_queue_scrolls_inside_a_box():
    at = _rules_app()
    at.session_state["proposals"] = [_approved({"column": f"Col {i}", "default": "x"}, str(i)) for i in range(5)]
    at.run()
    assert not at.exception
    assert any("scroll inside the box" in c.value for c in at.caption)


def test_table_scrollbars_never_cover_the_last_column():
    assert ".dvn-scroller{scrollbar-width:auto" in theme.CSS and "::-webkit-scrollbar{width:10px" in theme.CSS


def test_assumptions_are_back_on_solve_without_tool_names_in_the_sources():
    for a in assumptions.ASSUMPTIONS:
        assert "claude" not in a.source.casefold() and a.source.endswith(".")
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "Upload"
    at.run()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    at.session_state["view"] = "Solve"
    at.run()
    assert any(e.label == "Assumptions Used In This Run" for e in at.expander)
    assert any("A01" in m.value for m in at.markdown) and not at.exception
