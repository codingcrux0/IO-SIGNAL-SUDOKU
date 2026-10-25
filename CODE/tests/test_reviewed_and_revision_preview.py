"""Review memory (Reviewed Before on the TQ Board) and Check Allocation First (the revision preview pop-up and the
Revision Library on the Revision page)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from io_sudoku.core import helpcontext, reviewlog, revpreview
from io_sudoku.core.pipeline import solve
from io_sudoku.core.revision import compare, solve_incremental
from io_sudoku.core.simulate import ReworkMinutes, make_revision
from io_sudoku.samples import load_sample_result, sample_mdb_bytes
from io_sudoku.ui import nav, revlibrary, search, state

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(view: str = "Upload") -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "Upload"
    at.run()
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    at.session_state["view"] = view
    at.run()
    return at


def _tq(tq_id, ref, severity="warning", message="msg"):
    return SimpleNamespace(tq_id=tq_id, ref=ref, severity=severity, message=message)


def _result(*tqs, rows=()):
    return SimpleNamespace(tqs=list(tqs), violations=[], rows=list(rows), quarantined=[])


# ------------------------------------------------------------------ review memory (pure)
def test_an_event_remembers_the_question_and_where_the_signal_was():
    result = load_sample_result()
    warning = next(t for t in result.tqs if t.severity == "warning")
    event = reviewlog.make_event(result, warning.tq_id, warning.ref, "approved", by="ann", time="t1", revision="Original")
    assert event.question == warning.message and event.severity == "warning" and event.revision == "Original"
    row = next(r for r in result.rows if r["Tag Status"] == "Field")
    where, facts = reviewlog.facts_of(result, row["Tag Name"])
    assert facts["Tag Name"] == row["Tag Name"] and str(row["Channel_No"]) in where
    assert reviewlog.make_event(result, "", "X", "approved") is None and reviewlog.make_event(result, "A", "X", "nope") is None


def test_counts_and_the_small_hover_summary():
    log = reviewlog.record([], *[reviewlog.make_event(None, "SEG", "TAG-1", a, time=f"t{i}", revision="Rev 1")
                                 for i, a in enumerate(("approved", "problem", "edited", "suggestion-rejected", "resolved"))])
    n = reviewlog.counts(log)
    assert (n["reviewed"], n["approved"], n["rejected"], n["fixed"], n["resolved"]) == (4, 1, 2, 1, 1)
    text = reviewlog.summary_text(log)
    assert "Reviewed 4" in text and "Approved 1" in text and "Rev 1" in text and "Marked as a problem" in text


def test_returning_tells_a_new_problem_from_one_that_came_back_and_skips_settled_warnings():
    log = reviewlog.record([], reviewlog.make_event(None, "SEG", "TAG-1", "approved"),
                           reviewlog.make_event(None, "SIZE", "TAG-2", "edited"))
    result = _result(_tq("SEG", "TAG-1"), _tq("OTHER", "TAG-1", "error"), _tq("SIZE", "TAG-2", "error"),
                     _tq("SEG", "TAG-9"), _tq("INFO", "TAG-2", "info"))
    back = {r.ref: r for r in reviewlog.returning(log, result)}
    assert set(back) == {"TAG-1", "TAG-2"}                                         # TAG-9 was never reviewed
    kinds = {q[0]: q[3] for q in back["TAG-1"].open_now}
    assert kinds == {"SEG": "Came back", "OTHER": "New problem"} and back["TAG-1"].is_new
    assert [q[0] for q in back["TAG-2"].open_now] == ["SIZE"]                      # info is not a problem
    settled = reviewlog.returning(log, result, {"SEG|TAG-1": "approved"})
    assert {q[0] for r in settled for q in r.open_now if r.ref == "TAG-1"} == {"OTHER"}


def test_after_a_re_allocation_resolved_and_raised_are_written_for_reviewed_items_only():
    log = reviewlog.record([], reviewlog.make_event(None, "SEG", "TAG-1", "approved"))
    before = _result(_tq("SEG", "TAG-1"), _tq("X", "TAG-5"))
    after = _result(_tq("NEW", "TAG-1"), _tq("Y", "TAG-5"))
    out = reviewlog.after_solve(log, before, after, "Revision 2", "t")
    assert [(e.tq_id, e.action, e.revision) for e in out[1:]] == [("SEG", "resolved", "Revision 2"), ("NEW", "raised", "Revision 2")]
    assert reviewlog.after_solve([], before, after, "r", "t") == []
    assert reviewlog.counts(out)["reviewed"] == 1                                 # automatic events are not reviews


def test_saved_events_load_back_and_bad_data_never_raises():
    event = reviewlog.make_event(None, "SEG", "TAG-1", "approved", detail="ok")
    again = reviewlog.from_dict(json.loads(json.dumps(reviewlog.to_dict(event))))
    assert again == event
    assert reviewlog.from_dict({"action": "bad"}) is None and reviewlog.from_dict("x") is None
    assert reviewlog.returning(None, None) == [] and reviewlog.after_solve(None, None, None, "", "") == []
    assert reviewlog.facts_of(None, None) == ("", {})


def test_the_helpdesk_is_told_the_whole_history():
    log = reviewlog.record([], reviewlog.make_event(None, "SEG", "TAG-1", "problem", detail="wrong cabinet", by="bo"))
    title, text = helpcontext.history_focus(None, "TAG-1", log, [("NEW", "error", "boom", "New problem")])
    assert "TAG-1" in title and "wrong cabinet" in text and "NEW" in text and "Marked as a problem" in text


# ------------------------------------------------------------------ review memory on the TQ Board
def _signoff(at: AppTest, index: int, label: str) -> None:
    boxes = [w for w in at.segmented_control if w.key and w.key.startswith("signoff_") and w.key != "signoff_show"]
    boxes[index].set_value(label).run()


def test_the_tq_board_has_a_reviewed_before_tab_and_a_sign_off_is_remembered():
    at = _app("TQ Board")
    assert [t.label for t in at.tabs][:2] == list(state.TQ_TABS) and not at.exception
    _signoff(at, 0, "✗ Problem")
    log = at.session_state["review_log"]
    assert len(log) == 1 and log[0].action == "problem" and log[0].revision.startswith("Original")
    _signoff(at, 0, None)                                                         # pressed again: taken back
    assert [e.action for e in at.session_state["review_log"]] == ["problem", "cleared"]


def test_a_reviewed_item_with_a_problem_again_is_listed_with_its_history():
    at = _app("TQ Board")
    _signoff(at, 0, "✓ Approve")
    at.session_state["signoffs"] = {}                                              # e.g. the next revision of the file
    at.run()
    assert any("reviewed before have a problem again" in w.value for w in at.warning)
    assert any("reviewed 1× before" in m.value for m in at.markdown)
    at.session_state["tq_tab"] = state.REVIEWED_TAB
    at.run()
    assert any("CAME BACK" in m.value for m in at.markdown) and not at.exception
    at.button(key=next(b.key for b in at.button if b.key and b.key.startswith("rb_more_"))).click().run()
    assert any(s.label == "See The Signal Exactly As It Was At" for s in at.selectbox) and not at.exception
    at.button(key=next(b.key for b in at.button if b.key and b.key.startswith("rb_") and b.key.endswith("_ask"))).click().run()
    assert at.session_state["chat"]["kind"] == "history" and not at.exception


def test_approve_all_and_an_edit_from_a_question_are_remembered():
    at = _app("TQ Board")
    at.checkbox(key="approve_all_ok").check().run()
    at.button(key="approve_all").click().run()
    assert {e.action for e in at.session_state["review_log"]} == {"approved"}
    edit = next(b for b in at.button if b.key and b.key.startswith("edit_warn_"))
    edit.click().run()
    assert at.session_state["edit_tq"] is not None or at.session_state["view"] != "Edit File"


def test_the_review_memory_goes_into_the_workspace_and_comes_back():
    from io_sudoku.core.rulepack import default_pack
    from io_sudoku.core.workspace import export_workspace, import_workspace
    event = reviewlog.make_event(load_sample_result(), "SEG", "TAG-1", "approved", by="ann", time="t")
    data = export_workspace(load_sample_result(), default_pack(), [], {}, "sha", "00",
                            {"notes": {}, "suggestions": [], "reviews": [reviewlog.to_dict(event)]})
    ws, _ = import_workspace(data)
    assert [reviewlog.from_dict(x) for x in ws.notes["reviews"]] == [event]


def test_search_and_links_open_the_right_tq_board_tab():
    place = search.BY_LABEL["TQ Board › Reviewed Before"]
    assert place.heading in nav.REVIEWED_HEADINGS
    at = _app("Upload")
    at.button(key="navgo_" + nav.slug(place.label)).click().run()
    assert at.session_state["view"] == "TQ Board" and at.session_state["tq_tab"] == state.REVIEWED_TAB
    at.button(key="navgo_" + nav.slug("TQ Board › Answer A Question")).click().run()
    assert at.session_state["tq_tab"] == state.QUESTIONS_TAB


# ------------------------------------------------------------------ check a revision first
def test_the_verdict_follows_errors_then_set_aside_then_warnings():
    a = {"error": 2, "quarantined": 0, "warning": 1, "cabinets_used": 3, "status": "BLOCKED"}
    assert revpreview.verdict(a, {**a, "error": 0, "status": "DRAFT"})[0] == "better"
    assert revpreview.verdict(a, {**a, "warning": 4})[0] == "worse"
    assert revpreview.verdict(a, {**a, "error": 1, "warning": 3})[0] == "mixed"
    assert revpreview.verdict(a, dict(a)) == ("same", [])
    unknown = revpreview.measures([{"Tag Status": "Field"}])
    assert unknown["error"] is None and unknown["field"] == 1
    assert revpreview.verdict(unknown, {**unknown, "error": 5})[0] == "same"        # unknown on one side: not compared


@pytest.fixture(scope="module")
def revision():
    a = solve(sample_mdb_bytes())
    data_b = make_revision(sample_mdb_bytes(), 5, 1)
    b, report = solve_incremental(data_b, a.rows, None, "B")
    fresh = compare(a.rows, solve(data_b, None, "B").rows)
    entry = revlibrary.make_entry("Rev B check", created="", file_name="rev_b.xlsx", label="B", source="Current Result",
                                  rows_a=a.rows, a_tqs=a.tqs, a_status=a.readiness.status, a_quarantined=0, result_b=b,
                                  report=report, fresh_report=fresh, minutes=ReworkMinutes())
    return a, b, report, data_b, entry


def test_a_checked_revision_carries_everything_about_it(revision):
    a, b, report, _, entry = revision
    assert entry.rows() == b.rows and entry.rows_a() == a.rows and len(entry.tqs) == len(b.tqs)
    assert entry.check.hours.fresh > entry.check.hours.keep and entry.check.hours.saved > 0
    assert entry.check.counts == report.counts and len(entry.changes()) == len(report.changes)
    assert any("Rework estimate" in x for x in entry.check.lines())
    lib = revlibrary.add([], entry)
    assert lib[0].id == 1 and revlibrary.default_name(lib, "B", "rev_b.xlsx") == "Rev B · rev_b.xlsx"
    assert revlibrary.default_name(revlibrary.add(lib, revlibrary.make_entry(
        "Rev B · rev_b.xlsx", created="", file_name="x", label="B", source="-", rows_a=a.rows, a_tqs=None, a_status=None,
        a_quarantined=None, result_b=b, report=report, fresh_report=None, minutes=ReworkMinutes())), "B",
        "rev_b.xlsx") == "Rev B · rev_b.xlsx (2)"
    assert revlibrary.name_problem(lib, "Rev B check") and revlibrary.name_problem(lib, "Rev B check", 1) == ""
    assert revlibrary.name_problem(lib, "  ")


def _preview(at: AppTest, revision) -> revlibrary.Entry:
    a, b, report, data_b, entry = revision
    entry = revlibrary.make_entry(entry.name, created="", file_name="rev_b.xlsx", label="B", source="Current Result",
                                  rows_a=a.rows, a_tqs=a.tqs, a_status=None, a_quarantined=None, result_b=b,
                                  report=report, fresh_report=None, minutes=ReworkMinutes())
    at.session_state["rev_preview"] = {"entry": entry, "result": b, "report": report, "rows_a": a.rows, "bytes": data_b,
                                       "name": "rev_b.xlsx", "label": "B"}
    at.session_state["rev_preview_name"] = entry.name
    at.session_state["rev_preview_open"] = True
    at.run()
    return entry


def test_the_preview_pop_up_saves_nothing_until_save_is_pressed(revision):
    at = _app("Revision")
    assert [t.label for t in at.tabs][:4] == ["Compare With A New MDB", "Revision Library", "Revision History",
                                              "Revision Simulator"]
    history_before = len(at.session_state["history"])
    _preview(at, revision)
    assert not at.exception and at.button(key="pv_save") and at.session_state["rev_library"] == []
    assert len(at.session_state["history"]) == history_before
    at.button(key="pv_save").click().run()
    assert not at.exception, [e.value for e in at.exception]
    lib = at.session_state["rev_library"]
    assert [e.name for e in lib] == ["Rev B check"] and at.session_state["rev_preview"] is None
    assert at.session_state["impact"] is not None and len(at.session_state["history"]) == history_before + 1


def test_a_preview_can_be_discarded_and_a_taken_name_is_refused(revision):
    at = _app("Revision")
    _preview(at, revision)
    at.button(key="pv_discard").click().run()
    assert at.session_state["rev_preview"] is None and at.session_state["rev_library"] == [] and not at.exception
    _preview(at, revision)
    at.button(key="pv_save").click().run()
    _preview(at, revision)                                                          # the same name again
    at.button(key="pv_save").click().run()
    assert len(at.session_state["rev_library"]) == 1 and at.session_state["rev_preview"] is not None
    assert "already called" in (at.session_state["rev_preview_error"] or "")


def test_a_closed_preview_waits_and_can_be_opened_again(revision):
    at = _app("Revision")
    _preview(at, revision)
    at.session_state["rev_preview_open"] = False
    at.run()
    assert any("A preview is waiting" in m.value for m in at.markdown)
    at.button(key="pv_reopen").click().run()
    assert at.session_state["rev_preview_open"] and not at.exception


def test_the_library_opens_a_revision_by_name_and_renames_and_deletes_it(revision):
    at = _app("Revision")
    at.session_state["rev_library"] = revlibrary.add([], revision[4])
    at.session_state["rev_tab"] = "Revision Library"
    at.run()
    assert not at.exception and any("Rev B check" in m.value for m in at.markdown)
    assert any(d for d in at.dataframe)
    entry_id = at.session_state["rev_library"][0].id
    at.text_input(key=f"lib_name_{entry_id}").set_value("Client Rev C").run()
    at.button(key=f"lib_rename_{entry_id}").click().run()
    assert at.session_state["rev_library"][0].name == "Client Rev C"
    at.button(key=f"ask_lib_delete_{entry_id}").click().run()
    next(b for b in at.button if b.label == "Yes, delete it").click().run()
    assert at.session_state["rev_library"] == [] and not at.exception


def test_the_preview_helpdesk_is_told_the_comparison(revision):
    title, text = helpcontext.preview_focus("Rev B check", revision[4].check.lines())
    assert "Rev B check" in title and "Rework estimate" in text and "Nothing is saved yet" in text
    assert search.BY_LABEL["Revision › Revision Library"].tab == "Revision Library"


def test_both_sides_are_judged_with_the_same_sign_offs(revision):
    a, b, report, _, _ = revision
    entry = revlibrary.make_entry("x", created="", file_name="f", label="B", source="Current Result", rows_a=a.rows,
                                  a_tqs=a.tqs, a_status="DRAFT", a_quarantined=0, result_b=b, report=report,
                                  fresh_report=None, minutes=ReworkMinutes(), b_status="DRAFT")
    assert entry.check.b["status"] == "DRAFT" and not any("readiness" in r for r in entry.check.reasons)
