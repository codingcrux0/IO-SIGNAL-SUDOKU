"""Audit (was Rule Radar), saved file revisions, revision dropdowns, the Suggested Fixed File, Add A Signal, the project
column named after itself in 'Where It Applies', and the Show filter of Columns And Checks."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import openpyxl
from streamlit.testing.v1 import AppTest

from io_sudoku.core import autofix, projectrules as pr
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.pipeline import solve
from io_sudoku.core.tq import TQLog
from io_sudoku.samples import sample_mdb_bytes
from io_sudoku.ui import filerevs, newsignal, rulescope
from io_sudoku.ui.editing import build_index, read_editable
from io_sudoku.ui.state import VIEWS

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
CASES = ROOT / "test_cases"
sys.path.insert(0, str(ROOT / "scripts"))
from make_test_cases import Sheet, xlsx_bytes  # noqa: E402


def _sample_app(view: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    at.button(key="sample_upload").click().run()
    at.session_state["view"] = view
    at.run()
    return at


def _messy_extra_columns() -> bytes:
    """The user's case: renamed columns, many extra columns, blanks, a typo, a pasted copy of a row."""
    s = Sheet()
    room, io_c = s.col("Technical Room (Signal Location 2)"), s.col("I/O Type Name")
    headers = list(s.headers)
    headers[io_c] = "Signal Kind"                                  # no name the reader knows: BLOCKED, nothing placed
    rows = [list(r) for r in s.rows]
    full_rooms = [r[room] for r in rows]
    for i, r in enumerate(rows):
        if i % 7 == 0:
            r[room] = None                                         # blank rooms...
    rows[10][room] = "PIB-3O"                                      # ...and a typo (letter O)
    headers += [f"Extra {n}" for n in range(1, 29)] + ["Technical Room", "Voltage"]
    for i, r in enumerate(rows):
        r += [f"x{n}-{i}" for n in range(1, 29)] + [full_rooms[i], 24 if i % 2 else 12]
    rows.insert(20, list(rows[19]))                                # the same row pasted twice
    return xlsx_bytes(headers, rows)


# ------------------------------------------------------------------ 1. Audit
def test_rule_radar_is_now_called_audit_and_old_links_still_work():
    assert "Audit" in VIEWS and "Rule Radar" not in VIEWS
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["view"] = "Rule Radar"
    at.run()
    assert at.session_state["view"] == "Audit" and not at.exception


# ------------------------------------------------------------------ 6. the column's own name
def test_where_it_applies_names_the_column_after_the_project_column():
    rows = solve(sample_mdb_bytes()).rows
    old = {"column": "Current input", "value": "20A", "match_column": "IO Type", "match_text": "AI"}
    lines = rulescope.table("project_column", old, rulescope.applies_to("project_column", old, rows))
    assert lines and all(x["Current input"] == "20A" for x in lines)
    assert "Result" not in lines[0] and list(lines[0])[:2] == ["Tag", "Current input"]
    tag = next(r["Tag Name"] for r in rows if r.get("Tag Status") == "Field")
    new = {"new": True, "column": "Voltage", "type": "number", "unit": "V", "values": {pr.tag_key(tag): "30"},
           "fills": [], "default": "", "checks": [{"check": "max", "value": "24", "severity": "error", "scope": {"how": "all"}}]}
    lines = rulescope.table("column_rule", new, [r for r in rows if r.get("Tag Name") == tag], rows)
    assert lines[0]["Voltage (V)"] == "30" and lines[0]["Checks"].startswith("✗") and rulescope.broken(lines) == 1


# ------------------------------------------------------------------ 2/3. saved file revisions
def test_file_revisions_are_kept_once_and_named_per_kind():
    revs, a = filerevs.add([], kind="upload", file_name="A.xlsx", sha="a", origin_sha="a", created="t")
    revs, b = filerevs.add(revs, kind="edit", file_name="A.xlsx", sha="b", origin_sha="a", created="t", note="x")
    revs, again = filerevs.add(revs, kind="edit", file_name="A.xlsx", sha="b", origin_sha="a", created="t")
    assert [r.name for r in revs] == ["Uploaded", "Edit 1"] and again is b and filerevs.shas(revs) == {"a", "b"}


def test_every_save_is_a_file_revision_and_any_of_them_can_be_used_again():
    from io_sudoku.ui.editing import Target
    at = _sample_app("Edit File")
    sample_sha = at.session_state["mdb_sha"]
    assert [r.name for r in at.session_state["file_revs"]] == ["Sample Data"]
    sheet = read_editable(sample_mdb_bytes())[0]
    at.session_state["edit_target"] = Target(sheet.name, sheet.rows[0][0], sheet.headers.index("Location"), "", "test")
    at.run()
    next(t for t in at.text_input if t.label.startswith("New value for")).set_value("NEW PLACE").run()
    at.button(key="jump_save").click().run()
    at.session_state["view"] = "Edit File"
    at.run()
    revs = at.session_state["file_revs"]
    assert [r.name for r in revs] == ["Sample Data", "Edit 1"] and at.session_state["mdb_sha"] == revs[-1].sha
    assert any(b.key == "edit_file_rev_use" for b in at.button)                    # the dropdown is on Edit File
    at.session_state["edit_file_rev_pick"] = revs[0].id
    at.run()
    at.button(key="edit_file_rev_use").click().run()
    assert at.session_state["mdb_sha"] == sample_sha and at.session_state["edit_log"] == [] and not at.exception
    at.session_state["edit_file_rev_pick"] = revs[1].id
    at.run()
    at.button(key="edit_file_rev_use").click().run()
    assert at.session_state["mdb_sha"] == revs[1].sha and len(at.session_state["edit_log"]) == 1


def test_revisions_are_picked_in_dropdowns_and_a_saved_revision_can_be_rev_a_or_b():
    at = _sample_app("Revision")
    assert not any(r.key == "rev_a_source" for r in at.radio)
    at.selectbox(key="rev_a_source").set_value("A Saved Revision (Revision History)").run()
    at.selectbox(key="rev_b_source").set_value("A Saved File Revision").run()
    assert at.selectbox(key="rev_a_snap") and at.selectbox(key="rev_b_file")
    at.button(key="rev_compare").click().run()
    assert not at.exception and at.session_state["impact"] is not None
    assert at.session_state["impact"].counts.get("Moved", 0) == 0                # the same file against itself
    at.session_state["rev_tab"] = "Revision Library"
    at.run()
    assert at.selectbox(key="lib_pick") and not at.exception                      # the library is a dropdown too


# ------------------------------------------------------------------ 4. the Suggested Fixed File
def test_the_fixer_turns_a_blocked_messy_file_into_an_issue_ready_one():
    sg = autofix.suggest(_messy_extra_columns(), "messy.xlsx")
    assert sg.before.status == "BLOCKED" and sg.before.placed == 0
    assert sg.after.status == "ISSUE-READY" and sg.after.errors == 0 and sg.after.placed == 177
    counts = sg.counts()
    assert counts["column_found"] == 1 and counts["duplicate_row"] == 1 and counts["room_from_cable"] == 1
    assert counts["column_merge"] > 20
    found = next(c for c in sg.changes if c.group == "column_found")
    assert (found.old, found.new) == ("Signal Kind", "I/O Type Name") and "IO types" in found.why
    typo = next(c for c in sg.changes if c.group == "room_from_cable")
    assert (typo.old, typo.new) == ("PIB-3O", "PIB-30")
    ws = openpyxl.load_workbook(io.BytesIO(sg.data)).worksheets[0]
    headers = [c.value for c in ws[1]]
    assert "I/O Type Name" in headers and "Extra 7" in headers and "Voltage" in headers     # extra columns kept
    assert any(h == "Voltage" and n == 190 for h, n, _ in sg.unused)                      # ...and offered as project columns


def test_the_fixer_works_out_io_types_and_impossible_cable_sizes_from_the_file():
    sg = autofix.suggest((CASES / "08_io_type_errors.xlsx").read_bytes(), "08.xlsx")
    assert sg.before.status == "BLOCKED" and sg.after.status == "ISSUE-READY" and sg.counts()["io_from_peers"] == 3
    assert all("other signals of the kind" in c.why for c in sg.changes if c.group == "io_from_peers")
    sg = autofix.suggest((CASES / "09_cable_and_pair_errors.xlsx").read_bytes(), "09.xlsx")
    assert sg.after.held_back < sg.before.held_back and sg.counts()["size_conflict"] == 2
    assert {x[0] for x in sg.left} >= {"MISSING-CABLE", "MISSING-PAIR", "DUPLICATE-PAIR"}   # wiring facts: never guessed
    assert all(why for *_, why in sg.left)


def test_the_fixer_never_guesses_tags_pairs_or_out_of_scope_signals_and_keeps_standard_spellings():
    for name in ("07_tag_errors.xlsx", "10_segregation_errors.xlsx", "11_out_of_scope_signals.xlsx"):
        sg = autofix.suggest((CASES / name).read_bytes(), name)
        assert set(sg.counts()) <= {"spaces"}, (name, sg.counts())
        assert sg.after is None or sg.after.errors == sg.before.errors
    sg = autofix.suggest((CASES / "01_clean_full_sample.xlsx").read_bytes(), "01.xlsx")
    assert sg.counts() == {"spaces": 1}                                 # AI and AIR are both kept as written
    sg = autofix.suggest((CASES / "03_messy_but_fixable.xlsx").read_bytes(), "03.xlsx")
    assert {c.new for c in sg.changes if c.group == "io_spelling"} <= {"AI", "AO", "DI", "DO", "AIR", "AOR", "DIR", "DOR"}


def test_switching_a_kind_of_fix_off_and_unreadable_files():
    data = _messy_extra_columns()
    sg = autofix.suggest(data, "messy.xlsx", skip=("room_from_cable", "duplicate_row"))
    assert "room_from_cable" not in sg.counts() and "duplicate_row" not in sg.counts()
    for name in ("19_corrupt_file.xlsx", "20_old_excel_renamed.xlsx", "21_not_a_table.csv", "18_header_only.xlsx"):
        sg = autofix.suggest((CASES / name).read_bytes(), name)
        assert sg.data is None and not sg.changes


def test_the_safety_net_judges_by_signals_placed_first():
    m = lambda placed, errors=0, held=0, tags=(): autofix.Measures("X", errors, 0, held, placed, frozenset(tags))  # noqa: E731
    assert not autofix._worse(m(0, errors=1), m(177, errors=2, held=2, tags=("a",)))       # nothing read -> placed
    assert autofix._worse(m(5, tags=("a", "b")), m(5, tags=("a", "c")))                    # a placed signal was lost
    assert autofix._worse(m(5, errors=1), m(5, errors=2))
    assert not autofix._worse(m(5, errors=2), m(5, errors=1))


def test_using_the_suggested_file_saves_it_as_a_file_revision():
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["view"] = "Preflight"
    at.session_state["mdb_bytes"] = data = (CASES / "08_io_type_errors.xlsx").read_bytes()
    at.session_state["mdb_name"] = "08.xlsx"
    at.run()
    from io_sudoku.ui import ui_logic
    at.session_state["mdb_sha"] = ui_logic.sha256_hex(data)
    at.session_state["mdb_original"] = (data, "08.xlsx")
    at.run()
    assert any("BLOCKED → ISSUE-READY" in m.value for m in at.markdown)
    assert any("other signals of the kind" in m.value for m in at.markdown)              # the explanation box
    at.button(key="afx_use").click().run()
    revs = at.session_state["file_revs"]
    assert revs[-1].kind == "suggested" and at.session_state["mdb_sha"] == revs[-1].sha and not at.exception
    assert at.session_state["mdb_original"][0] == data                                   # Delete All Changes goes back


def test_an_unused_column_becomes_a_project_column_in_the_form():
    at = _sample_app("Preflight")
    at.session_state["mdb_bytes"] = _messy_extra_columns()
    at.run()
    at.selectbox(key="afx_unused_pick").set_value("Voltage").run()
    at.button(key="afx_unused_go").click().run()
    assert at.session_state["view"] == "Rules" and at.session_state["rule_group"] == "Columns And Checks"
    assert at.session_state["cb_name"] == "Voltage" and at.session_state["cb_type"] == "number"
    assert len(at.session_state["cb_values"]) == 190 and set(at.session_state["cb_values"].values()) == {"12", "24"}
    assert not at.exception


# ------------------------------------------------------------------ 7. Add A Signal
def test_add_a_signal_logic_uses_the_files_own_values_and_spelling():
    data = sample_mdb_bytes()
    sheets, index = read_editable(data), build_index(data)
    opts = newsignal.options(sheets, index)
    assert opts.sheet and opts.pair_word == "Pair" and opts.compact_ok and "PIB-30" in opts.values["tech_room"]
    cable = opts.cables["320-ce-0001"]
    taken = next(iter(cable.pairs))
    bad = {"tag": "320-FT   -20645-A", "io_type": "AIR", "tech_room": "PIB-30", "cable_no": "320-CE-0001", "pair_no": taken}
    problems = newsignal.problems(bad, opts)
    assert any("already in the file" in p for p in problems) and any("already used" in p for p in problems)
    good = {"tag": "320-FT   -29999", "io_type": "AIR", "tech_room": "PIB-30", "cable_no": "320-CE-0001",
            "pair_no": cable.next_pair(), "cable_size": cable.size}
    assert newsignal.problems(good, opts) == [] and newsignal.warnings(good, opts) == []
    sheet, row, cells = newsignal.plan(good, opts, sheets)
    assert row == max(r for r, _ in sheets[0].rows) + 1
    written = {h: v for _, h, v in cells}
    assert written["Pair Number"] == f"Pair {cable.next_pair()}" and written["TagNumber"] == "320FT29999"


def test_add_a_signal_writes_the_row_and_opens_it_on_edit_file():
    at = _sample_app("Rules")
    at.session_state["rule_group"] = "Add A Signal"
    at.run()
    assert not any(b.label == "Propose Rule" for b in at.button)          # Settings is no longer a tab...
    assert any(e.label.startswith("Engineering Settings") for e in at.expander)   # ...it is closed at the bottom
    at.text_input(key="ns_tag").set_value("320-FT   -29999").run()
    at.selectbox(key="ns_io_type").set_value("AIR").run()
    at.selectbox(key="ns_cable_no").set_value("320-CE-0001").run()
    assert at.session_state["ns_tech_room"] == "PIB-30" and at.session_state["ns_pair_no"] >= 1   # filled from the cable
    at.button(key="ns_add").click().run()
    assert at.session_state["view"] == "Edit File" and at.session_state["edit_target"].row is not None
    assert at.session_state["file_revs"][-1].kind == "signal" and not at.exception
    ing = read_mdb(at.session_state["mdb_bytes"], TQLog())
    sig = next(x for x in ing.signals if x.tag == "320-FT   -29999")
    assert sig.io_type == "AIR" and sig.cable_no == "320-CE-0001" and sig.tech_room == "PIB-30"


# ------------------------------------------------------------------ 5. the Show filter
def test_the_show_filter_explains_an_empty_view_and_finds_typed_values():
    at = _sample_app("Rules")
    at.session_state["rule_group"] = "Columns And Checks"
    at.run()
    at.text_input(key="cb_name").set_value("Voltage").run()
    at.session_state["cb_show"] = "Filled"                         # what pressing Filled does (it also refolds)
    at.session_state["cb_ver"] = at.session_state["cb_ver"] + 1
    at.session_state["cb_view"] = None
    at.run()
    assert any("Filled shows none (that is correct)" in i.value for i in at.info)
    tag = next(r["Tag Name"] for r in at.session_state["result"].rows if r.get("Tag Status") == "Field")
    at.session_state["cb_values"] = {pr.tag_key(tag): "24"}
    at.session_state["cb_ver"] = at.session_state["cb_ver"] + 1
    at.session_state["cb_view"] = None
    at.run()
    assert not any("Filled shows none" in i.value for i in at.info)
    assert any("showing 1" in c.value for c in at.caption)
