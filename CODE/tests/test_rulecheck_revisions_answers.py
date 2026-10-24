"""Rule Check, project rules, answer verification, TQ notes and suggestions, undo/delete revisions, page buttons,
the Edit buttons of the TQ Board, case-sensitive searches and the revision impact in detail."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from io_sudoku.core import cellcheck, projectrules, rulechange as rc, suggestion
from io_sudoku.core.config import load_config
from io_sudoku.core.overrides import Override
from io_sudoku.core.pipeline import solve
from io_sudoku.core.revision import compare
from io_sudoku.core.rulepack import apply_pack, default_pack, validate_pack, RulePack
from io_sudoku.core.workspace import export_workspace, import_workspace
from io_sudoku.samples import case_bytes, load_sample_result, sample_mdb_bytes
from io_sudoku.ui import editing, impact, rulescope
from io_sudoku.ui.views._common import page_numbers

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(view: str = "Upload", sample: bool = True) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["view"] = "Upload"
    at.run()
    if sample:
        next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    at.session_state["view"] = view
    at.run()
    return at


def _load(at: AppTest, name: str) -> None:
    data = case_bytes(name)
    at.session_state["mdb_bytes"], at.session_state["mdb_name"] = data, name
    at.session_state["mdb_sha"] = hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ page buttons
def test_page_numbers_start_at_one_and_skip_with_dots():
    assert page_numbers(1, 5) == [1, 2, 3, 4, 5]
    assert page_numbers(5, 12) == [1, None, 4, 5, 6, None, 12]
    assert page_numbers(1, 12) == [1, 2, None, 12]
    assert page_numbers(3, 12) == [1, 2, 3, 4, None, 12]                  # no '…' for a single missing page


# ------------------------------------------------------------------ the Edit buttons of the TQ Board
def test_edit_buttons_never_search_for_something_that_is_not_in_the_file():
    for name in ("01_clean_full_sample.xlsx", "09_cable_and_pair_errors.xlsx", "10_segregation_errors.xlsx",
                 "13_everything_wrong.xlsx", "17_missing_io_type_column.xlsx"):
        data = case_bytes(name)
        result = solve(data)
        index, sheets = editing.build_index(data), editing.read_editable(data)
        for t in result.tqs:
            if t.severity == "info":
                continue
            fix = editing.where_to_fix(t.tq_id, t.ref, index, sheets, result.rows, result.quarantined)
            if fix.kind == "edit" and fix.target.row is None:                # a search must find rows
                assert any(editing.find_rows(s, fix.target.search) for s in sheets), (name, t.tq_id, t.ref)
            if t.tq_id == "ALARMS-MISSING-FOR-CABINET":
                assert fix.kind == "cabinet" and fix.cabinet.startswith(t.ref[:3])
            if t.tq_id == "MISSING-COLUMN":
                assert fix.kind == "place" and fix.place == "Upload › Column Mapping"
            if t.tq_id in ("MIXED-SEGREGATION", "CABLE-SIZE-CONFLICT"):    # every row of the cable, useful columns
                assert fix.kind == "edit" and fix.target.show and len(editing.find_rows(sheets[0], fix.target.search)) > 1


def test_a_cabinet_warning_opens_the_cabinet():
    at = _app("TQ Board")
    button = next(b for b in at.button if b.key and b.key.startswith("edit_warn_"))
    assert button.label.endswith("Cabinet")
    button.click().run()
    assert at.session_state["view"] == "Cabinet Layout" and not at.exception
    assert at.session_state["selected_cabinet"].startswith("P")


def test_searches_for_cells_are_case_sensitive():
    sheet = editing.EditSheet("s", 1, ("Tag",), ((2, ("FT-1",)), (3, ("ft-1",))))
    assert [r for r, _ in editing.find_rows(sheet, "FT-1")] == [2]
    assert [r for r, _ in editing.find_rows(sheet, "ft-1")] == [3]


# ------------------------------------------------------------------ answers are verified
def test_an_answer_that_does_not_clear_its_question_raises_a_new_warning():
    data = case_bytes("08_io_type_errors.xlsx")
    good = Override("320-FT   -83010", "io_type", "AIR", "me", "Answers MISSING-IO-TYPE")
    wrong = Override("320-LT   -83005", "cable_no", "X1", "me", "Answers UNKNOWN-IO-TYPE")
    r = solve(data, overrides=[good, wrong])
    unresolved = [t.ref for t in r.tqs if t.tq_id == "ANSWER-UNRESOLVED"]
    assert unresolved == ["320-LT   -83005"] and not any(t.tq_id == "MISSING-IO-TYPE" for t in r.tqs)
    assert not any(t.tq_id == "ANSWER-UNRESOLVED" for t in solve(data).tqs)          # no answers, no check


def test_answer_box_shows_errors_on_itself_and_asks_to_verify():
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    _load(at, "08_io_type_errors.xlsx")
    at.run()
    at.button(key="solve_upload").click().run()
    at.session_state["view"] = "TQ Board"
    at.run()
    at.selectbox(key="manual_tag").set_value("320-FT   -83010").run()
    at.button(key="answer_apply").click().run()                        # a tag but no value: refused here
    assert any("give a value" in e.value for e in at.error) and not at.session_state["overrides"]
    at.text_input(key="answer_by").set_value("Asha")
    at.selectbox(key="manual_field").set_value("io_type").run()
    at.selectbox(key="manual_value_io_type").set_value("AIR").run()
    at.button(key="answer_apply").click().run()
    assert at.session_state["answer_check"]["state"] == "waiting"
    assert at.session_state["overrides"][0].note == "Answers MISSING-IO-TYPE"
    at.button(key="answer_verify_go").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["answer_check"]["state"] == "ok"
    assert any("Verified" in m.value for m in at.success)


# ------------------------------------------------------------------ project rules on CHARM signals
def _approved(template: str, args: dict, when: str = "1") -> rc.RuleProposal:
    p, errors = rc.build_proposal(template, args, "alice", now=when)
    assert not errors, errors
    p.status = "approved"
    return p


def test_constraints_become_one_warning_and_never_move_a_signal():
    rule = _approved("require_filled", {"match_column": "IO Type", "match_text": "DOR", "check_column": "Remarks"})
    column = _approved("project_column", {"column": "Loop Check", "value": "Pending", "match_column": "IO Type",
                                          "match_text": "AIR"}, "2")
    pack = rc.apply_approved(default_pack(), [rule, column])
    assert not validate_pack(pack) and len(pack.overrides["project_rules"]) == 2
    base, ruled = solve(sample_mdb_bytes()), solve(sample_mdb_bytes(), apply_pack(pack, load_config()))
    assert base.kpis["output_sha256"] == ruled.kpis["output_sha256"]          # placement untouched
    broken = [t for t in ruled.tqs if t.tq_id == "PROJECT-RULE-BROKEN"]
    assert len(broken) == 1 and broken[0].severity == "warning" and "Remarks" in broken[0].message
    row = next(r for r in ruled.rows if r["Tag Status"] == "Field" and r["IO Type"] == "AIR")
    assert projectrules.project_columns(pack.overrides["project_rules"], row) == {"Loop Check": "Pending"}


def test_a_malformed_project_rule_is_refused():
    bad = RulePack("x", 2, "p", {}, {"project_rules": [{"kind": "move_signal", "args": {}}]})
    assert validate_pack(bad)
    worse = RulePack("x", 2, "p", {}, {"project_rules": [{"kind": "expect_hardware", "args": {
        "match_column": "Tag Name", "match_text": "x", "charm_type": "SE9999"}}]})
    assert validate_pack(worse)


def test_where_a_rule_applies():
    rows = load_sample_result().rows
    wired = rulescope.applies_to("spare_pct", {"value": 10}, rows)
    assert wired and all(r["Tag Status"] == "Wired Spare" for r in wired)
    lines = rulescope.table("expect_hardware", {"match_column": "IO Type", "match_text": "AIR", "charm_type": "SE4303T01"},
                            rulescope.applies_to("expect_hardware", {"match_column": "IO Type", "match_text": "AIR"}, rows))
    assert lines and all(x["Result"][0] in "✓✗" for x in lines)
    assert rulescope.signal_changes(rows, rows) == []
    moved = [dict(r) for r in rows]
    moved[20]["CHARM Type"] = "SE0000"
    assert [c["Column"] for c in rulescope.signal_changes(rows, moved)] == ["CHARM Type"]


# ------------------------------------------------------------------ Rule Check
def test_rule_check_of_one_cell():
    result = load_sample_result()
    row = next(r for r in result.rows if r["Tag Status"] == "Field")
    checks = cellcheck.check_cell(result, row)
    n = cellcheck.summary(checks)
    assert n["fail"] == 0 and n["pass"] >= 8 and any(c.rule == "Decision" for c in checks)
    broken = dict(row, CHARM_No=999)
    assert any(c.rule == "V03" and c.status == "fail" for c in cellcheck.check_cell(result, broken))
    steps = dict(cellcheck.signal_path(row))
    assert steps["CIOC"] == row["CIOC/CSLS Name"] and row["Field Cable No"] in steps["Field cable"]
    sid = cellcheck.slot_id(row)
    assert cellcheck.index_rows(result.rows)[sid] is row


def test_clicking_a_slot_opens_rule_check_with_its_log():
    at = _app("Cabinet Layout")
    sid = cellcheck.slot_id(next(r for r in at.session_state["result"].rows if r["Tag Status"] == "Field"))
    at.text_input(key="cellpick_box").set_value(f"{sid}@123").run()
    assert at.session_state["view"] == "Rule Check" and at.session_state["rc_cells"][0] == sid
    assert not at.exception, [e.value for e in at.exception]
    assert any("met" in m.value and "broken" in m.value for m in at.markdown)


def test_slot_map_and_drawings_link_to_rule_check():
    from io_sudoku.core.elevation import cabinet_svg
    from io_sudoku.ui import ui_logic
    rows = load_sample_result().rows
    cab = rows[0]["Electronic/ Marshalling Cabinet"]
    assert ui_logic.cabinet_grid_html(rows, cab).count('href="#cell-') >= 300
    assert cabinet_svg(rows, cab, "F").count("data-slot=") == 192


# ------------------------------------------------------------------ notes and suggestions on TQs
def test_a_suggestion_needs_another_person_and_the_passcode():
    sg, errors = suggestion.make_suggestion("X", "T1", "Add the rows.", "alice", "now")
    assert not errors and sg.status == "pending"
    assert suggestion.approve(sg, "alice", "pw", "pw", "t")                  # not your own
    assert suggestion.approve(sg, "bob", "nope", "pw", "t")                 # wrong passcode
    assert not suggestion.approve(sg, "bob", "pw", "pw", "t") and sg.status == "approved"
    assert suggestion.make_suggestion("X", "T1", "  ", "alice")[0] is None
    assert "cannot read, write, run or change any code" in suggestion.ASSISTANT_RULES


def test_notes_travel_in_the_workspace():
    result = load_sample_result()
    notes = {"notes": {"X|T1": {"text": "Check with Bob", "by": "Asha", "time": "t"}}, "suggestions": []}
    ws, why = import_workspace(export_workspace(result, default_pack(), [], {}, "sha", "00", notes))
    assert not why and ws.notes["notes"]["X|T1"]["text"] == "Check with Bob"
    plain, _ = import_workspace(export_workspace(result, default_pack(), [], {}, "sha", "00"))
    assert plain.notes == {}


def test_the_fix_panel_saves_a_note_and_opens_the_assistant():
    at = _app("TQ Board")
    at.button(key="fixmore_0_0").click().run()
    h = next(x.key for x in at.text_area if x.key.startswith("note_text_"))[len("note_text_"):]
    at.text_area(key=f"note_text_{h}").set_value("Ask Electrical for the alarm rows.")
    at.text_input(key="note_by").set_value("Asha")
    at.button(key=f"note_save_{h}").click().run()
    assert list(at.session_state["tq_notes"].values())[0]["text"] == "Ask Electrical for the alarm rows."
    at.button(key=f"chat_open_{h}").click().run()
    assert at.session_state["chat"] is not None and not at.exception
    assert at.text_area(key="assistant_final").value == "Ask Electrical for the alarm rows."


# ------------------------------------------------------------------ undo and delete revisions
def test_undo_last_revision_brings_back_the_earlier_inputs():
    at = _app("Upload")
    at.text_input(key="rev_label").set_value("01").run()
    at.button(key="solve_upload").click().run()
    assert [s.name for s in at.session_state["history"]] == ["Original", "Revision 1"]
    at.session_state["view"] = "Revision"
    at.session_state["rev_tab"] = "Revision History"
    at.run()
    at.button(key="ask_undo_revision").click().run()
    at.button(key="yes_undo_revision").click().run()                     # asked first, then done
    assert not at.exception, [e.value for e in at.exception]
    assert [s.name for s in at.session_state["history"]] == ["Original"]
    assert at.session_state["rev_label"] == "00" and not at.session_state["stale"]


def test_delete_revisions_asks_first():
    at = _app("Upload")
    at.text_input(key="rev_label").set_value("01").run()
    at.button(key="solve_upload").click().run()
    at.session_state["view"] = "Revision"
    at.session_state["rev_tab"] = "Revision History"
    at.run()
    first = at.session_state["history"][0].id
    at.multiselect(key="hist_delete").set_value([first]).run()
    at.button(key="ask_delete_revisions").click().run()
    assert len(at.session_state["history"]) == 2                          # nothing yet: it asks
    at.button(key="yes_delete_revisions").click().run()
    assert [s.name for s in at.session_state["history"]] == ["Revision 1"]


# ------------------------------------------------------------------ revision impact in detail
def test_impact_detail_lists_the_changed_columns():
    rows_a = load_sample_result().rows
    rows_b = [dict(r) for r in rows_a]
    field = next(i for i, r in enumerate(rows_b) if r["Tag Status"] == "Field")
    rows_b[field]["Tag Name"] = rows_b[field]["Tag Name"] + "-NEW"
    report = compare(rows_a, rows_b)
    change = next(c for c in report.changes)
    detail = impact.change_detail(change, rows_a, rows_b)
    assert detail.diffs and (detail.row_a is not None or detail.row_b is not None)
    page = impact.impact_html(report, rows_a, rows_b)
    assert "<script" not in page and "Added" in page and "-NEW" in page


# ------------------------------------------------------------------ links, health, signed-off warnings
def test_signed_off_warnings_link_to_exactly_those():
    at = _app("TQ Board")
    at.checkbox(key="approve_all_ok").check().run()
    at.button(key="approve_all").click().run()
    at.session_state["view"] = "Solve"
    at.run()
    md = " ".join(m.value for m in at.markdown)
    assert "[2 warnings](#go-tq-board-warnings-already-signed-off) were signed off" in md
    at.button(key="navgo_tq-board-warnings-already-signed-off").click().run()
    assert at.session_state["view"] == "TQ Board" and at.session_state["signoff_show"] == "Signed Off"
    assert not at.exception
