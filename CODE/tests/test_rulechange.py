from __future__ import annotations

import pytest

from io_sudoku.core import rulechange as rc
from io_sudoku.core.config import load_config
from io_sudoku.core.pipeline import solve
from io_sudoku.core.rulepack import LOCKED_RULES, apply_pack, default_pack, validate_pack
from io_sudoku.core.tq import TQLog

ROOMS = ["PIB-30", "PIB-24"]
SECRET = "s3cret-passcode"


def propose(template, args, author="alice", now="2026-10-24T10:00:00", **kw):
    p, errors = rc.build_proposal(template, args, author, now=now, **kw)
    assert errors == [] and p is not None, errors
    return p


def test_the_fixed_list_of_templates():
    assert set(rc.TEMPLATES) == {"io_alias", "high_current_keyword", "instrument_profile", "segregation_family",
                                 "spare_pct", "future_pct", "end_reserve_bps", "alarm_baseplate", "add_cabinet",
                                 "project_column", "expect_hardware", "require_filled", "column_rule"}
    assert set(rc.PROJECT_TEMPLATES) == {"project_column", "expect_hardware", "require_filled", "column_rule"}
    cat = rc.template_catalogue(ROOMS)
    assert len(cat) == 12 and "column_rule" not in {t["key"] for t in cat}       # built on its own form
    room = next(a for t in cat if t["key"] == "add_cabinet" for a in t["args"] if a["name"] == "room")
    assert room["choices"] == ROOMS


def test_statements_are_generated_by_code():
    p = propose("high_current_keyword", {"keyword": "Siren"})
    assert p.statement == "Treat 'Siren' loads as high-current DOR (SE4302T02 / SE4502)." and p.status == "pending" and p.source == "form"
    assert p.id.startswith("RC-") and len(p.id) == 11
    texts = {
        ("io_alias", ("alias", "DOX"), ("io", "DOR")): "Treat IO type 'DOX' as DOR.",
        ("spare_pct", ("value", 12)): "Allocate 12% wired spares per IO type per controller.",
        ("future_pct", ("value", 15)): "Keep 15% of each cabinet as future Spare Slots.",
        ("end_reserve_bps", ("value", 3)): "Keep the last 3 baseplates of CIOC 4 empty.",
        ("segregation_family", ("code", "C"), ("family", "A")): "Treat segregation code 'C' as family A.",
        ("instrument_profile", ("instrument", "Pump"), ("profile", "DOR_T02")): "Use hardware profile DOR_T02 for instrument type 'Pump'.",
    }
    for (template, *pairs), expected in texts.items():
        assert propose(template, dict(pairs)).statement == expected
    assert propose("add_cabinet", {"room": "pib-30"}, known_rooms=ROOMS).statement == "Add one more marshalling cabinet in PIB-30."


@pytest.mark.parametrize("template,args", [
    ("nope", {}), ("spare_pct", {}), ("spare_pct", {"value": 31}), ("spare_pct", {"value": -1}), ("spare_pct", {"value": "abc"}),
    ("spare_pct", {"value": True}), ("spare_pct", {"value": 5, "extra": 1}), ("io_alias", {"alias": "X", "io": "ZZZ"}),
    ("io_alias", {"alias": "", "io": "AIR"}), ("io_alias", {"alias": "A" * 21, "io": "AIR"}),
    ("high_current_keyword", {"keyword": "x" * 41}), ("high_current_keyword", {"keyword": "a\x00b"}),
    ("instrument_profile", {"instrument": "p", "profile": "AIR_RTD"}), ("segregation_family", {"code": "C", "family": "Z"}),
    ("add_cabinet", {"room": "NOWHERE"}),
])
def test_invalid_proposals_are_refused(template, args):
    p, errors = rc.build_proposal(template, args, "alice", known_rooms=ROOMS)
    assert p is None and errors


def test_author_is_required():
    assert rc.build_proposal("spare_pct", {"value": 12}, "  ")[0] is None


def test_locked_rules_have_no_template():
    for locked in LOCKED_RULES:
        words = locked.lower()
        assert not any(key.split("_")[0] in words and key in ("capacity", "charm") for key in rc.TEMPLATES)
    # the cabinet-alarm baseplate is a project choice (the VIT guide), so it HAS a template; the locked rules have none
    assert not any(any(w in key for w in ("capacity", "charm", "cioc1", "slot", "naming")) for key in rc.TEMPLATES)
    p, errors = rc.build_proposal("slots_per_cabinet", {"value": 400}, "alice")
    assert p is None and errors


def test_passcode_check():
    assert rc.is_approver(SECRET, SECRET)
    assert not rc.is_approver("wrong", SECRET) and not rc.is_approver(None, SECRET) and not rc.is_approver("", SECRET)
    assert not rc.is_approver(SECRET, None) and not rc.is_approver(SECRET, "") and not rc.is_approver(None, None)


def test_approval_rules():
    p = propose("spare_pct", {"value": 12})
    assert rc.approve(p, "bob", "wrong", SECRET, "t") and p.status == "pending"
    assert rc.approve(p, "bob", SECRET, None, "t") and p.status == "pending"             # no secret configured: nobody can approve
    assert rc.approve(p, "Alice ", SECRET, SECRET, "t") and p.status == "pending"        # author cannot approve (case/space-insensitive)
    assert rc.approve(p, "", SECRET, SECRET, "t") and p.status == "pending"
    assert rc.approve(p, "bob", SECRET, SECRET, "2026-10-24T11:00:00") == []
    assert (p.status, p.reviewer, p.decided) == ("approved", "bob", "2026-10-24T11:00:00")
    assert rc.approve(p, "carol", SECRET, SECRET, "t")                                    # already decided
    assert rc.reject(p, "carol", "no", SECRET, SECRET, "t")


def test_rejection_needs_a_reason():
    p = propose("spare_pct", {"value": 12})
    assert rc.reject(p, "bob", "  ", SECRET, SECRET, "t") and p.status == "pending"
    assert rc.reject(p, "bob", "Client says 10%", SECRET, SECRET, "t2") == []
    assert (p.status, p.reason) == ("rejected", "Client says 10%")


def test_only_approved_proposals_change_the_pack(mdb_path):
    base = default_pack()
    pending = propose("spare_pct", {"value": 15})
    rejected = propose("future_pct", {"value": 20}, now="2026-10-24T10:01:00")
    rc.reject(rejected, "bob", "no", SECRET, SECRET, "t")
    assert rc.apply_approved(base, [pending, rejected]) is base                           # nothing approved: same object
    assert solve(mdb_path, apply_pack(rc.apply_approved(base, [pending, rejected]), load_config())).rows == solve(mdb_path).rows
    rc.approve(pending, "bob", SECRET, SECRET, "t")
    new = rc.apply_approved(base, [pending, rejected])
    assert (new.version, new.read_only, new.params["spare_pct"], new.params["future_pct"]) == (2, False, 15, 10)
    assert new.parent == "VIT-2026 v1" and base.params["spare_pct"] == 10                 # the default pack is untouched
    assert validate_pack(new) == []


def test_every_template_can_be_applied():
    cfg = load_config()
    proposals = [
        propose("io_alias", {"alias": "dox", "io": "DOR"}, now="1"), propose("high_current_keyword", {"keyword": "Siren Horn"}, now="2"),
        propose("instrument_profile", {"instrument": "Fan", "profile": "DOR_T02"}, now="3"),
        propose("segregation_family", {"code": "c", "family": "B"}, now="4"), propose("spare_pct", {"value": 12}, now="5"),
        propose("future_pct", {"value": 12}, now="6"), propose("end_reserve_bps", {"value": 5}, now="7"),
        propose("add_cabinet", {"room": "PIB-24"}, now="8", known_rooms=cfg.known_rooms())]
    for p in proposals:
        assert rc.approve(p, "bob", SECRET, SECRET, "9") == []
    pack = rc.apply_approved(default_pack(), proposals)
    out = apply_pack(pack, cfg)
    assert out.rules.io_aliases == {"DOX": "DOR"} and "siren horn" in out.rules.high_current_keywords
    assert out.rules.instrument_profiles == {"Fan": "DOR_T02"} and "C" in out.rules.b_codes
    assert (out.rules.spare_pct, out.rules.future_pct, out.rules.end_reserve_bps) == (12, 12, 5)
    assert [c.marshalling for c in out.cabinets][-1] == "P24-DCM-50002-02" and len(out.cabinets) == 4


def test_a_rule_really_changes_the_allocation_only_where_expected(mdb_path):
    base = solve(mdb_path)
    p = propose("spare_pct", {"value": 20})
    rc.approve(p, "bob", SECRET, SECRET, "t")
    changed = solve(mdb_path, apply_pack(rc.apply_approved(default_pack(), [p]), load_config()))
    summary = rc.row_diff_summary(base.rows, changed.rows)
    assert summary and set(summary) <= {"Tag Status", "Tag Name", "DSTName", "Service Description", "IO Type", "Signal Type", "Signal Level",
                                        "CHARM Type", "Charm Description", "CHARM TB Part No", "CHARM TB Description", "CHARM TB1",
                                        "CHARM TB2", "CHARM TB3", "HW Loop Typical", "Location", "NON-IS / IS", "Unit"}
    assert changed.violations == [] and changed.kpis["wired_spare"] > base.kpis["wired_spare"]


def test_row_diff_summary_edges():
    rows = [{"Electronic/ Marshalling Cabinet": "C", "CIOC/CSLS Name": "I", "Baseplate": "B", "Channel_No": 1, "X": "a"}]
    assert rc.row_diff_summary(rows, [dict(r) for r in rows]) == {} and rc.row_diff_summary([], []) == {}
    other = [dict(rows[0], X="b")]
    assert rc.row_diff_summary(rows, other) == {"X": 1}
    assert rc.row_diff_summary(rows, []) == {"(slots only in one result)": 1}


def test_audit_log_records_every_state_change():
    a = propose("spare_pct", {"value": 12}, now="2026-10-24T10:00:00", rationale="client asked")
    b = propose("future_pct", {"value": 12}, now="2026-10-24T10:05:00")
    rc.approve(a, "bob", SECRET, SECRET, "2026-10-24T11:00:00")
    rc.reject(b, "carol", "too much", SECRET, SECRET, "2026-10-24T11:30:00")
    log = rc.audit_entries([b, a])
    assert [(e["event"], e["by"]) for e in log] == [("proposed", "alice"), ("proposed", "alice"), ("approved", "bob"), ("rejected", "carol")]
    assert log[0]["detail"] == "client asked" and log[3]["detail"] == "too much"
    assert rc.audit_entries([]) == []


def test_ai_proposals_are_marked_and_rationale_is_not_the_rule():
    p = propose("high_current_keyword", {"keyword": "beacon"}, source="ai", rationale="The engineer wrote: treat beacons as heavy loads")
    assert p.source == "ai" and p.statement == "Treat 'beacon' loads as high-current DOR (SE4302T02 / SE4502)."
    assert "heavy loads" not in p.statement and p.status == "pending"
