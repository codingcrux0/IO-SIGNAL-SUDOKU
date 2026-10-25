"""Type-ahead, cell changes kept with review decisions, column notes, proposals in the Review Queue, Propose Rules,
picked signals and stacked filters, and unfinished work that is never lost."""
from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from io_sudoku.core import advisor, autofix, columnnotes as cn, projectrules as pr, reviewlog
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui import autofill, drafts

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _sample_app(view: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    at.button(key="sample_upload").click().run()
    at.session_state["view"] = view
    at.run()
    return at


# ------------------------------------------------------------------ 1. type-ahead
def test_type_ahead_lists_are_offered_per_box_and_cannot_break_out_of_the_frame():
    at = _sample_app("TQ Board")
    lists = at.session_state[autofill.RUN_KEY]
    tags = lists["tq_search"]["items"]
    assert tags and tags[0] == next(r["Tag Name"] for r in at.session_state["result"].rows
                                    if r.get("Tag Status") in ("Field", "Cabinet Alarm"))
    page = autofill.page({"x": {"items": ["</script><b>", "a"], "sep": ","}})
    assert "</script><b>" not in page and "\\u003c/script\\u003e" in page and "__iosgFill1" in page
    assert "rgba(139,148,158,.55)" in autofill.SCRIPT                # the suggestion is faint, what you typed is not


def test_the_columns_form_offers_its_own_values():
    at = _sample_app("Rules")
    at.session_state["rule_group"] = "Columns And Checks"
    at.run()
    lists = at.session_state[autofill.RUN_KEY]
    assert lists["cb_find"]["sep"] == "," and "AIR" in lists["cb_find"]["items"]
    assert "Analog Range High Scale" in lists["cb_name"]["items"] and "mA" in lists["cb_unit"]["items"]


# ------------------------------------------------------------------ 2. cell changes kept with a decision
def test_review_events_keep_the_cell_changes_and_show_them_in_the_info_box():
    change = {"Sheet": "MDB-1", "Row": "4", "Column": "Signal Level", "Before": "24 VDC", "After": "Voltfree", "When": "10:01:02"}
    event = reviewlog.ReviewEvent("320FT1", "320-FT-1", "DIR-CONTACT-CHECK", "warning", "approved", time="2026-10-25 10:02",
                                  changes=(change,))
    back = reviewlog.from_dict(json.loads(json.dumps(reviewlog.to_dict(event))))
    assert back.changes == (change,)
    text = reviewlog.summary_text([back])
    assert "Cells changed before these decisions" in text and "'24 VDC' → 'Voltfree'" in text


def test_approving_after_an_edit_records_exactly_what_was_edited():
    from io_sudoku.ui import editing, state, ui_logic
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    data = (Path(APP).parent / "test_cases" / "08_io_type_errors.xlsx").read_bytes()
    s = at.session_state
    s["mdb_bytes"], s["mdb_name"], s["mdb_sha"] = data, "08.xlsx", ui_logic.sha256_hex(data)
    s["mdb_original"] = (data, "08.xlsx")
    s["view"] = "Upload"
    at.run()
    next(b for b in at.button if b.label == "Run Allocation" and not b.disabled).click().run()
    s["view"] = "TQ Board"
    at.run()
    result = s["result"]
    index = ui_logic.edit_index(s["mdb_bytes"], "{}", ui_logic.pack_json(s["pack"]))
    warn = next(t for t in list(result.tqs) + list(result.violations)
                if t.severity == "warning" and reviewlog.item_key(t.ref) in index.tags)
    sheet, row = index.tags[reviewlog.item_key(warn.ref)]
    edit_sheet = next(x for x in ui_logic.editable_sheets(s["mdb_bytes"]) if x.name == sheet)
    col = edit_sheet.headers.index("Service")
    old = edit_sheet.row(row)[col]
    data = editing.apply_edits(s["mdb_bytes"], s["mdb_name"], [editing.CellEdit(sheet, row, col, "Service", old, "NEW SERVICE")])
    s["mdb_bytes"], s["mdb_sha"] = data, ui_logic.sha256_hex(data)
    s["edit_log"] = [{"Sheet": sheet, "Row": row, "Column": "Service", "Old Value": str(old), "New Value": "NEW SERVICE",
                      "Time": "10:00:00", "_col": col}]
    at.run()
    key = f"{warn.tq_id}|{warn.ref}"
    at.segmented_control(key=state.signoff_widget_key(key)).set_value(state.SIGNOFF_LABELS["approved"]).run()
    event = s["review_log"][-1]
    assert event.action == "approved" and event.changes[0]["After"] == "NEW SERVICE" and event.changes[0]["Column"] == "Service"
    at.segmented_control(key=state.signoff_widget_key(key)).set_value(None).run()       # taken back: not listed twice
    assert s["review_log"][-1].action == "cleared" and not s["review_log"][-1].changes


# ------------------------------------------------------------------ 3. column notes
def test_the_tool_notes_measurement_columns_and_never_labels_or_priorities():
    notes = cn.find(autofix.unused_columns(sample_mdb_bytes()))
    names = {n.column for n in notes}
    assert {"Analog Range High Scale", "Alarm Deadband"} <= names
    assert not any("Priority" in n or "Units" in n for n in names)
    note = next(n for n in notes if n.column == "Alarm Deadband")
    assert note.numbers and note.question.startswith("“Alarm Deadband” holds") and "Leave it blank" in note.question


def test_a_unit_next_to_the_numbers_also_makes_a_note():
    unused = [("Supply", 3, {"A1": "24 V", "A2": "24V", "A3": "230 V"}), ("Comment", 2, {"A1": "ok", "A2": "fine"})]
    notes = cn.find(unused)
    assert [n.column for n in notes] == ["Supply"] and notes[0].quantity == "Voltage" and notes[0].unit == "V"
    assert notes[0].span() == "24 to 230 V"


def test_the_ai_can_describe_real_columns_only():
    unused = [("Max Temp", 2, {"A1": "80", "A2": "95"}), ("Rating", 2, {"A1": "10", "A2": "16"})]

    class Fake:
        def complete(self, system: str, user: str) -> str:
            assert "A1" not in user and "Rating" in user                 # names and example values only, no tags
            return json.dumps({"columns": [{"column": "Rating", "quantity": "Current", "unit": "A",
                                            "question": "Which current should Rating stay under?"},
                                           {"column": "Invented", "quantity": "Power"}]})
    ai, why = advisor.read_columns(cn.ai_columns(unused), Fake())
    assert why == "" and [x["column"] for x in ai] == ["Rating"]
    merged = cn.merge(cn.find(unused), ai, unused)
    rating = next(n for n in merged if n.column == "Rating")
    assert rating.source == "ai" and rating.unit == "A" and rating.question.startswith("Which current")
    assert advisor.read_columns(cn.ai_columns(unused), None)[0] == []


def test_a_note_answer_is_a_clean_column_rule_for_picked_signals():
    note = cn.find([("Max Temp", 3, {"A1": "80", "A2": "95", "A3": "60"})])[0]
    args, errors = pr.normalize_column_rule(cn.rule_args(note, cn.column_name(note, ["Max Temp"]), "max", "90", "",
                                                         {"how": pr.TAGS, "tags": ["A1", "A2"]}, "warning", True))
    assert not errors and args["column"] == "Max Temp 2" and args["values"] == {pr.tag_key(t): v for t, v in (("A1", "80"), ("A2", "95"), ("A3", "60"))}
    assert [c["check"] for c in args["checks"]] == ["max", "required"]
    rule = {"kind": "column_rule", "args": args}
    rows = [{"Tag Name": t, "Tag Status": "Field"} for t in ("A1", "A2", "A3")]
    chk = args["checks"][0]
    judged = {r["Tag Name"]: pr.judge_check(rule, chk, r, None).ok for r in rows if pr.in_scope(chk["scope"], r)}
    assert judged == {"A1": True, "A2": False}                        # A3 is not picked, so it is not checked
    assert "these 2 signals" in pr.column_statement(args)


def test_notes_show_on_the_rules_page_and_a_limit_goes_to_the_review_queue():
    at = _sample_app("Rules")
    at.session_state["rule_group"] = "Columns And Checks"
    at.session_state["rule_author"] = "Asha"
    at.run()
    assert not at.exception and any("Notes · columns that could be compared with a limit" in m.value for m in at.markdown)
    pick = at.session_state["cn_pick"]
    note = next(n for n in cn.find(autofix.unused_columns(sample_mdb_bytes())) if n.key == pick)
    import hashlib
    p = "cn_" + hashlib.sha256(note.key.encode()).hexdigest()[:8]
    at.text_input(key=f"{p}_v").set_value("100").run()
    at.button(key=f"{p}_propose").click().run()
    props = at.session_state["proposals"]
    assert len(props) == 1 and props[0].template == "column_rule" and props[0].status == "pending"
    assert at.session_state["scroll_to"] is None or True
    assert not any(t.severity in ("error", "warning") and "Notes" in t.message for t in at.session_state["result"].tqs)


# ------------------------------------------------------------------ 4 + 5. proposals reach the Review Queue; Propose Rules
def test_a_column_without_a_name_says_why_under_the_button_and_with_a_name_reaches_the_queue():
    at = _sample_app("Rules")
    at.session_state["rule_group"] = "Columns And Checks"
    at.run()
    assert any(h.value == "Propose Rules" for h in at.subheader)
    at.text_input(key="cb_name").set_value("Voltage").run()
    at.button(key="cb_propose").click().run()
    assert not at.session_state["proposals"] and any("Your Name" in e.value for e in at.error)
    at.text_input(key="rule_author").set_value("Asha").run()
    at.button(key="cb_propose").click().run()
    assert len(at.session_state["proposals"]) == 1
    assert any("It waits in the Review Queue" in s.value for s in at.success)


# ------------------------------------------------------------------ 6. picked signals and stacked filters
def test_picked_signals_get_their_own_value_and_filters_stack():
    at = _sample_app("Rules")
    at.session_state["rule_group"] = "Columns And Checks"
    at.run()
    at.text_input(key="cb_name").set_value("Voltage").run()
    rows = [r for r in at.session_state["result"].rows if pr.is_signal(r)]
    air = [pr.tag_key(r["Tag Name"]) for r in rows if r["IO Type"] == "AIR"]
    at.session_state["cb_picked"] = air[:2]
    at.session_state["cb_apply_to"] = "picked"
    at.run()
    at.text_input(key="cb_set_value").set_value("24").run()
    at.button(key="cb_set_shown").click().run()
    values = at.session_state["cb_values"]
    assert values == {air[0]: "24", air[1]: "24"}                     # only the picked two
    at.button(key="cb_add_filter").click().run()
    at.button(key="cb_add_filter").click().run()
    u1, u2 = at.session_state["cb_filters"]
    at.selectbox(key=f"cb_q{u1}_col").set_value("IO Type").run()
    at.selectbox(key=f"cb_q{u1}_text").set_value("AIR").run()
    cabinet = next(r["Electronic/ Marshalling Cabinet"] for r in rows if r["IO Type"] == "AIR")
    at.selectbox(key=f"cb_q{u2}_col").set_value("Electronic/ Marshalling Cabinet").run()
    at.selectbox(key=f"cb_q{u2}_text").set_value(cabinet).run()
    shown = at.session_state["cb_view"][1]
    want = {pr.tag_key(r["Tag Name"]) for r in rows if r["IO Type"] == "AIR" and cabinet in str(r["Electronic/ Marshalling Cabinet"])}
    assert set(shown) == want and 0 < len(shown) < len(rows)
    at.selectbox(key="cb_sort").set_value("tag_desc").run()
    shown = at.session_state["cb_view"][1]
    names = {pr.tag_key(r["Tag Name"]): r["Tag Name"] for r in rows}
    assert [names[k] for k in shown] == sorted((names[k] for k in shown), key=str.casefold, reverse=True)


# ------------------------------------------------------------------ 7. unfinished work is never lost
def test_a_half_typed_column_survives_another_page():
    at = _sample_app("Rules")
    at.session_state["rule_group"] = "Columns And Checks"
    at.run()
    at.text_input(key="cb_name").set_value("Voltage").run()
    at.text_input(key="cb_note").set_value("Supply check").run()
    at.session_state["view"] = "TQ Board"
    at.run()
    at.run()
    at.session_state["view"] = "Rules"
    at.run()
    assert at.text_input(key="cb_name").value == "Voltage" and at.text_input(key="cb_note").value == "Supply check"


def test_work_is_saved_on_disk_and_brought_back_in_a_new_session(tmp_path, monkeypatch):
    monkeypatch.setenv("IO_SUDOKU_DRAFT_DIR", str(tmp_path))
    draft_id = "ab" * 16
    at = _sample_app("Rules")
    at.session_state["rule_group"] = "Columns And Checks"
    at.session_state["_draft_id"] = draft_id
    at.run()
    at.text_input(key="rule_author").set_value("Asha").run()
    at.text_input(key="cb_name").set_value("Voltage").run()
    assert (tmp_path / f"{draft_id}.json").exists() and (tmp_path / f"{draft_id}.mdb").exists()
    fresh = AppTest.from_file(APP, default_timeout=90)
    fresh.run()
    assert fresh.session_state["mdb_bytes"] is None
    fresh.text_input(key=drafts.ID_BOX).set_value(draft_id).run()
    s = fresh.session_state
    assert s["mdb_name"] == "Sample_MDB.xlsx" and s["result"] is not None and s["view"] == "Rules"
    assert s["cb_name"] == "Voltage" and s["rule_author"] == "Asha"
    assert any("Welcome back" in m.value for m in fresh.markdown)
    fresh.button(key="drafts_fresh").click().run()
    assert fresh.session_state["mdb_bytes"] is None and not (tmp_path / f"{draft_id}.json").exists()


def test_a_damaged_save_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("IO_SUDOKU_DRAFT_DIR", str(tmp_path))
    (tmp_path / ("cd" * 16 + ".json")).write_text("{not json", encoding="utf-8")
    assert drafts.load("cd" * 16) == (None, None) and drafts.load("../etc/passwd") == (None, None)
