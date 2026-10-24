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
    assert at.session_state["result"] is not None and at.session_state["result"].readiness.status == "DRAFT"   # 2 warnings
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


def test_files_view_opens_files_in_the_page():
    at = run("Files", sample=True)
    at.session_state["view"] = "Files"
    at.run()
    assert not at.exception
    assert any(d.value.shape[0] == len(at.session_state["result"].rows) for d in at.dataframe)
    for pick in ("tq", "summary", "manifest", "workspace", "input"):
        at.selectbox(key="files_pick").set_value(pick).run()
        assert not at.exception, (pick, [e.value for e in at.exception])
        assert not at.error, pick


def test_viewer_search_narrows_rows():
    at = run("Files", sample=True)
    at.session_state["view"] = "Files"
    at.run()
    search = next(m for m in at.multiselect if m.label == "Search")
    search.set_value(["zzz-no-such-tag"]).run()
    assert not at.exception and any("No row matches" in i.value for i in at.info)
    rows = len(at.session_state["result"].rows)
    tags = [r["Tag Name"] for r in at.session_state["result"].rows if r.get("Tag Status") == "Field"][:2]
    next(m for m in at.multiselect if m.label == "Search").set_value(tags).run()     # two tags: rows of either
    assert not at.exception
    shown = [d.value for d in at.dataframe if 0 < d.value.shape[0] < rows]
    assert shown and set(shown[0]["Tag Name"]) >= set(tags)


def test_view_here_toggle_on_parts_and_upload():
    at = run("Parts", sample=True)
    at.session_state["view"] = "Parts"
    at.run()
    at.toggle(key="parts_view_parts").set_value(True).run()
    assert not at.exception and any(r.label == "Sheet" for r in at.radio)
    at.session_state["view"] = "Upload"
    at.run()
    at.toggle(key="upload_view_input").set_value(True).run()
    assert not at.exception


def test_old_downloads_link_opens_files():
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["view"] = "Downloads"
    at.run()
    assert at.session_state["view"] == "Files" and not at.exception


def test_viewer_renders_redline_colours():
    def app():
        from io_sudoku.core.revision import solve_incremental
        from io_sudoku.core.rulepack import default_pack
        from io_sudoku.core.simulate import make_revision
        from io_sudoku.samples import sample_mdb_bytes
        from io_sudoku.ui import ui_logic
        from io_sudoku.ui.views._viewer import file_viewer
        mdb = sample_mdb_bytes()
        a = ui_logic.solve_inputs(mdb, "", "[]", "{}", "{}", "00")
        b, report = solve_incremental(make_revision(mdb, 10, 3), a.rows, ui_logic.config_for_pack(default_pack()), "B")
        ctx = {"result": b, "mdb_bytes": mdb, "pack": default_pack(), "overrides": [], "pins": {}, "rev_label": "B",
               "template_bytes": None, "impact": report, "rev_a_rows": a.rows}
        data, name, _ = ui_logic.build_download("redline", ctx)
        file_viewer(data, name, "red")

    at = AppTest.from_function(app, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any(r.label == "Highlighted Changes" for r in at.radio)
    at.radio(key="red_mark").set_value("Moved").run()
    assert not at.exception


def _load(at: AppTest, data: bytes, name: str) -> None:
    import hashlib
    at.session_state["mdb_bytes"] = data
    at.session_state["mdb_name"] = name
    at.session_state["mdb_sha"] = hashlib.sha256(data).hexdigest()


def test_allocation_upload_is_explained_and_solves():
    from io_sudoku.core.allocio import allocation_bytes
    from io_sudoku.samples import sample_mdb_bytes
    from io_sudoku.ui import ui_logic
    rows = ui_logic.solve_inputs(sample_mdb_bytes(), "", "[]", "{}", "{}", "00").rows
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    _load(at, allocation_bytes(rows)[0], "old_allocation.xlsx")
    at.run()
    assert any("finished IO Allocation" in i.value for i in at.info)
    next(b for b in at.button if b.label == "Run Allocation").click().run()
    assert not at.exception and at.session_state["result"].kpis["field"] > 0


def test_blocked_result_says_what_to_fix():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    _load(at, b"Tag,Something\nT-1,x\n", "bad.csv")
    at.run()
    next(b for b in at.button if b.label == "Run Allocation").click().run()
    at.session_state["view"] = "Solve"
    at.run()
    assert not at.exception
    assert at.session_state["result"].readiness.status == "BLOCKED"
    assert any(e.label == "What needs fixing first" for e in at.expander)



def test_tq_board_colours_rows_by_severity():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    _load(at, (Path(__file__).resolve().parents[1] / "test_cases" / "13_everything_wrong.xlsx").read_bytes(), "bad.xlsx")
    at.run()
    next(b for b in at.button if b.label == "Run Allocation").click().run()
    at.session_state["view"] = "TQ Board"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("iosg-sev" in m.value for m in at.markdown)
    assert at.dataframe[0].value.iloc[0]["Severity"] == "● Error"


def test_summary_boxes_open_their_views():
    at = run("Solve", sample=True)
    at.session_state["view"] = "Solve"
    at.run()
    for key, view in (("kpigo_tqsraised", "TQ Board"), ("kpigo_fieldsignals", "Grid"), ("kpigo_cabinetsused", "Drawings")):
        at.session_state["view"] = "Solve"
        at.run()
        at.button(key=key).click().run()
        assert not at.exception and at.session_state["view"] == view


def test_warnings_must_be_signed_off_before_issue_ready():
    at = run("TQ Board", sample=True)
    at.session_state["view"] = "TQ Board"
    at.run()
    assert at.session_state["result"].readiness.status == "DRAFT"
    controls = [c for c in at.get("segmented_control")]
    assert len(controls) == 2
    controls[0].set_value("✓ Approve").run()
    assert at.session_state["result"].readiness.status == "DRAFT"                     # one still waiting
    [c for c in at.get("segmented_control")][1].set_value("✗ Problem").run()
    assert at.session_state["result"].readiness.status == "DRAFT"                     # a problem keeps it in draft
    [c for c in at.get("segmented_control")][1].set_value("✓ Approve").run()
    assert at.session_state["result"].readiness.status == "ISSUE-READY"
    at.button(key="reallocate_tq").click().run()                                      # approvals survive a re-allocation
    assert not at.exception and at.session_state["result"].readiness.status == "ISSUE-READY"


def test_approve_all_needs_the_checkbox():
    at = run("TQ Board", sample=True)
    at.session_state["view"] = "TQ Board"
    at.run()
    assert at.button(key="approve_all").disabled
    at.checkbox(key="approve_all_ok").check().run()
    at.button(key="approve_all").click().run()
    assert at.session_state["result"].readiness.status == "ISSUE-READY"
