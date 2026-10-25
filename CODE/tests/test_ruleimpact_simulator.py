"""Rule Impact (a rule -> every cell it touches), the Revision Simulator as a tab of Revision, the removed
Health page and Needs A Human / assumptions boxes, and the drawing fixes ('!' on alarms, readable spares)."""
from __future__ import annotations

import copy
from pathlib import Path

from streamlit.testing.v1 import AppTest

from io_sudoku.core import cellcheck, rulechange as rc, ruleimpact as ri
from io_sudoku.core.config import load_config
from io_sudoku.core.elevation import cabinet_svg
from io_sudoku.core.pipeline import solve
from io_sudoku.core.rulepack import apply_pack, default_pack
from io_sudoku.samples import load_sample_result, sample_mdb_bytes
from io_sudoku.ui import search, state, ui_logic

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


# ------------------------------------------------------------------ Rule Impact (core)
def test_the_shared_context_gives_exactly_the_same_checks():
    result = load_sample_result()
    ctx = cellcheck.context(result)
    for row in [r for r in result.rows if cellcheck.slot_id(r)][::23]:
        assert cellcheck.check_cell(result, row, ctx=ctx) == cellcheck.check_cell(result, row)


def test_every_rule_lists_the_cells_it_applies_to_and_agrees_with_rule_check():
    result = load_sample_result()
    impacts = ri.rule_impact(result)
    by_key = {x.key: x for x in impacts}
    slots = {cellcheck.slot_id(r) for r in result.rows if cellcheck.slot_id(r)}
    assert len(by_key["Locked|384 slots per cabinet"].hits) == len(slots)            # a locked rule covers every slot
    assert {x.group for x in impacts} >= {ri.LOCKED, ri.SETTINGS}
    assert all(not x.rule == "Decision" for x in impacts)                             # per-tag notes are not rules
    row = next(r for r in result.rows if r["Tag Status"] == "Field")
    sid = cellcheck.slot_id(row)
    for check in cellcheck.check_cell(result, row):                                   # the two pages always agree
        if check.rule != "Decision":
            hit = next(h for h in by_key[f"{check.rule}|{check.title}"].hits if h.sid == sid)
            assert (hit.status, hit.detail) == (check.status, check.detail)
    assert ri.summary(impacts)["broken"] == 0 and ri.summary(impacts)["rules"] == len(impacts)


def test_a_broken_cell_shows_up_under_its_rule():
    result = copy.copy(load_sample_result())
    rows = [dict(r) for r in result.rows]
    victim = next(r for r in rows if r["Tag Status"] == "Field")
    victim["CHARM_No"] = 999
    result.rows = rows
    v03 = next(x for x in ri.rule_impact(result) if x.title.startswith("CHARM_No"))
    assert v03.count(ri.FAIL) == 1 and v03.problems == 1 and victim["Tag Name"] in v03.signals
    assert ri.summary(ri.rule_impact(result))["broken"] == 1


def test_a_project_constraint_is_listed_with_the_signals_it_covers():
    proposal, errors = rc.build_proposal("require_filled", {"match_column": "IO Type", "match_text": "DOR",
                                                            "check_column": "Remarks"}, "alice", now="1")
    assert not errors
    proposal.status = "approved"
    result = solve(sample_mdb_bytes(), apply_pack(rc.apply_approved(default_pack(), [proposal]), load_config()))
    mine = [x for x in ri.rule_impact(result) if x.group == ri.PROJECT and "Remarks" in x.title]
    assert len(mine) == 1 and mine[0].hits and all(h.io == "DOR" for h in mine[0].hits)
    assert mine[0].charms and mine[0].cabinets


def test_rule_impact_never_raises():
    assert ri.rule_impact(None) == [] and ri.rule_impact(object()) == []


def test_the_slot_map_can_light_up_one_rules_cells():
    result = load_sample_result()
    cab = ui_logic.cabinet_names(result.rows)[0]
    sid = next(cellcheck.slot_id(r) for r in result.rows if r["Electronic/ Marshalling Cabinet"] == cab and r["Tag Status"] == "Field")
    html = ui_logic.cabinet_grid_html(result.rows, cab, {sid: "fail"})
    assert html.count("mk-fail") == 1 and html.count("mk-off") == 383 and "This rule: broken" in html
    assert "mk-" not in ui_logic.cabinet_grid_html(result.rows, cab)                 # the normal map is unchanged


# ------------------------------------------------------------------ Rule Impact (page)
def test_the_rule_impact_page_shows_where_a_rule_hits_and_opens_rule_check():
    at = _app("Audit")
    at.session_state["rule_tab"] = "Rule Impact"
    at.run()
    assert not at.exception and "Pick a rule in the list above" in _texts(at)
    at.session_state["ri_pick"] = "V06|Segregation A and B never share a CIOC"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    maps = [h for h in at.get("html") if "mk-" in h.proto.body]
    assert maps and "mk-pass" in maps[0].proto.body and "mk-off" in maps[0].proto.body
    assert "By CHARM Type" in _texts(at)
    assert at.button(key="ri_to_rc").disabled                                         # nothing ticked yet
    cab = at.selectbox(key=next(s.key for s in at.selectbox if s.key and s.key.startswith("ri_cab_")))
    assert cab.value in ui_logic.cabinet_names(at.session_state["result"].rows)


def test_rule_impact_search_and_filters_do_not_break():
    at = _app("Audit")
    at.text_input(key="ri_find").set_value("spares").run()
    assert not at.exception
    at.toggle(key="ri_problems").set_value(True).run()
    assert not at.exception and any("No rule matches" in i.value for i in at.info)    # the sample breaks nothing


# ------------------------------------------------------------------ the simulator is a tab of Revision
def test_the_simulator_moved_into_revision_and_old_links_still_work():
    assert "Simulator" not in state.VIEWS and "Health" not in state.VIEWS and "Audit" in state.VIEWS
    assert not [p for p in search.PLACES if p.view in ("Simulator", "Health")]
    at = AppTest.from_file(APP, default_timeout=90)
    at.query_params["view"] = "Simulator"
    at.run()
    assert at.session_state["view"] == "Revision" and at.session_state["rev_tab"] == "Revision Simulator"
    assert not at.exception
    old = AppTest.from_file(APP, default_timeout=90)
    old.query_params["view"] = "Health"
    old.run()
    assert old.session_state["view"] == "Upload" and not old.exception


def test_the_simulator_tab_estimates_hours_and_updates_them_live():
    at = _app("Revision")
    at.session_state["rev_tab"] = "Revision Simulator"
    at.run()
    at.button(key="sim_run").click().run()
    assert not at.exception, [e.value for e in at.exception]
    sim = at.session_state["sim"]["result"]
    assert sum(sim.edits.values()) > 0 and sim.incremental.counts.get("Moved", 0) < sim.naive.counts.get("Moved", 0)
    before = _texts(at)
    assert "Estimated Hours Saved" in before and "Which Tags Moved" in _texts(at)
    at.number_input(key="sim_moved").set_value(60.0).run()                            # no new run needed
    assert at.session_state["sim"]["result"] is sim and _texts(at) != before
    assert not any("changed after this simulation" in w.value for w in at.warning)
    at.button(key="sim_sizes").click().run()
    assert [p for p, _ in at.session_state["sim_sweep"]["rows"]] == [1, 2, 5, 10, 15, 20] and not at.exception
    seed = at.session_state["sim_seed"]
    at.button(key="sim_another").click().run()
    assert at.session_state["sim_seed"] != seed and at.session_state["sim"]["seed"] == at.session_state["sim_seed"]


# ------------------------------------------------------------------ removed boxes, all drawings
def test_needs_a_human_is_gone_and_assumptions_are_on_solve_and_in_the_downloads():
    at = _app("Preflight")
    assert "Needs A Human" not in _texts(at) and not at.exception
    at.session_state["view"] = "Solve"
    at.run()
    assert [e for e in at.expander if "Assumptions" in e.label] and not at.exception   # back on Solve
    assert load_sample_result().assumptions                                           # and in the TQ register file


def test_why_is_it_here_also_shows_under_all_cabinet_drawings():
    at = _app("Cabinet Layout")
    at.session_state["selected_cabinet"] = "\U0001F4D0 All Cabinet Drawings"
    at.session_state["cab"] = "\U0001F4D0 All Cabinet Drawings"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Why Is It Here?" in _texts(at)
    tags = at.selectbox(key="why_tag").options
    result = at.session_state["result"]
    cabinets_of_tags = {r["Electronic/ Marshalling Cabinet"] for r in result.rows if r["Tag Name"] in tags}
    assert len(cabinets_of_tags) > 1                                                  # tags of every cabinet


def test_alarm_cells_show_an_exclamation_mark_and_spares_a_dark_label():
    rows = load_sample_result().rows
    cab = next(r["Electronic/ Marshalling Cabinet"] for r in rows if r["Tag Status"] == "Cabinet Alarm")
    svg = cabinet_svg(rows, cab, "F")
    assert svg.count(">!</text>") == svg.count('data-status="Cabinet Alarm"') > 0 and ">A</text>" not in svg
    assert "paint-order" not in svg                                                   # no black outline on the numbers
    wired = [r for r in rows if r["Tag Status"] == "Wired Spare"]
    if wired:
        svg = cabinet_svg(rows, wired[0]["Electronic/ Marshalling Cabinet"], wired[0].get("Cabinet Side (F/R)") or "F")
        assert 'fill-opacity=".86"' in svg
