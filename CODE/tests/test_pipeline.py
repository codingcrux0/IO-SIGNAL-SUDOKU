from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from io_sudoku.core import pipeline
from io_sudoku.core.allocio import CANONICAL_COLUMNS
from io_sudoku.core.config import load_config
from io_sudoku.core.overrides import Override
from io_sudoku.core.pipeline import compute_kpis, output_hash, solve
from tests.mutate import col, mutated, read_table, row_of, to_xlsx_bytes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def result(mdb_path):
    return solve(mdb_path)


def test_fixture_is_fully_allocated_and_clean(result):
    r = result
    assert len(r.rows) == 1152 and all(list(row) == CANONICAL_COLUMNS for row in r.rows)
    counts = Counter(row["Tag Status"] for row in r.rows)
    assert counts["Field"] == 177 and counts["Cabinet Alarm"] == 12
    assert counts["Wired Spare"] == sum(l.quota for l in r.spare_lines) > 0
    assert not [t for t in r.tqs if t.severity == "error"]
    assert r.violations == [] and r.quarantined == []
    assert r.kpis["spare_compliance_pct"] == 100 and r.kpis["cabinets_used"] == 3
    assert r.readiness.status == "ISSUE-READY"
    assert [a.id for a in r.assumptions][:3] == ["A01", "A02", "A03"] and "A11" not in [a.id for a in r.assumptions]
    assert set(r.stages_ms) >= {"ingest", "validate", "place", "spares", "rows", "verify", "total"}
    assert r.cfg_used is not None and len(r.cfg_used.cabinets) == 3


def test_expected_tqs_on_the_sample(result):
    ids = Counter(t.tq_id for t in result.tqs)
    assert ids["ALARMS-MISSING-FOR-CABINET"] == 2 and ids["DELETED-IN-MDB"] == 1 and ids["IO-TYPE2-NOTED"] == 1
    assert ids["HIGH-CURRENT-VERIFY"] >= 2 and "INTERNAL" not in ids


def test_kpis_are_complete_and_sensible(result):
    k = result.kpis
    assert (k["field"], k["cabinet_alarm"], k["quarantined"], k["rows"]) == (177, 12, 0, 1152)
    assert k["field"] + k["wired_spare"] + k["spare_slot"] + k["cabinet_alarm"] == 1152
    for cab, pct in k["future_space_pct_per_cabinet"].items():
        assert pct >= 10.0, cab                       # at least 10% future space everywhere
    assert all(n >= 3 for n in k["empty_baseplates_per_cabinet"].values())
    assert k["output_sha256"] == output_hash(result.rows) and len(k["overrides_sha256"]) == 64


def test_solving_twice_gives_identical_rows(mdb_path, mdb_bytes, result):
    again = solve(mdb_path)
    assert again.rows == result.rows and output_hash(again.rows) == output_hash(result.rows)
    assert solve(mdb_bytes).rows == result.rows


def test_callers_config_is_never_changed(mdb_path):
    cfg = load_config()
    before = [c.marshalling for c in cfg.cabinets]
    r = solve(mdb_path, cfg)
    assert [c.marshalling for c in cfg.cabinets] == before and r.cfg_used is not cfg


def test_a_crashing_stage_becomes_an_internal_tq_and_the_run_continues(mdb_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(pipeline, "plan_and_place", boom)
    r = solve(mdb_path)
    internal = [t for t in r.tqs if t.tq_id == "INTERNAL"]
    assert internal and "boom" in internal[0].message and internal[0].ref == "place"
    assert "place" in r.diagnostics["tracebacks"] and "RuntimeError" in r.diagnostics["tracebacks"]["place"]
    assert r.readiness.status in ("DRAFT", "BLOCKED") and r.rows == []
    assert r.violations                                   # conservation (V01) notices the missing signals
    assert isinstance(r.kpis["rows"], int)


def test_every_stage_is_guarded(mdb_path, monkeypatch):
    for name in ("read_mdb", "infer_cabinets", "validate", "build_blocks", "apply_spares", "build_rows", "verify"):
        monkeypatch.setattr(pipeline, name, lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
        r = solve(mdb_path)
        assert any(t.tq_id == "INTERNAL" for t in r.tqs), name
        monkeypatch.undo()


def test_only_alarm_rows_still_work(mdb_path):
    headers, rows = read_table(mdb_path)
    kind = col(headers, "Instrument Type Description")
    data = to_xlsx_bytes(headers, [r for r in rows if r[kind] == "Cabinet Diagnostic Alarm"])
    r = solve(data)
    c = Counter(row["Tag Status"] for row in r.rows)
    assert c["Cabinet Alarm"] == 12 and c["Field"] == 0 and len(r.rows) == 1152
    assert r.kpis["spare_compliance_pct"] == 100 and r.violations == []


def test_garbage_and_empty_inputs_give_a_blocked_result(mdb_path):
    for junk, tq in ((b"garbage", "UNREADABLE-FILE"), (b"", "UNREADABLE-FILE"), (b"\xd0\xcf\x11\xe0xxxx", "UNSUPPORTED-FORMAT")):
        r = solve(junk)
        assert r.rows == [] and any(t.tq_id == tq for t in r.tqs)
        assert r.readiness.status == "BLOCKED" and r.kpis["rows"] == 0 and r.kpis["field"] == 0
        assert r.kpis["spare_compliance_pct"] == 100.0 and r.violations == []
    assert solve(ROOT / "no_such_file.xlsx").readiness.status == "BLOCKED"


def test_header_only_file_is_blocked_not_a_crash():
    data = to_xlsx_bytes(["Tag Number", "I/O Type Name", "Technical Room (Signal Location 2)"], [])
    r = solve(data)
    assert r.rows == [] and r.readiness.status == "BLOCKED"


def test_one_bad_row_makes_a_draft_with_a_tq_and_everything_else_allocated(mdb_path):
    def change(headers, rows):
        rows[row_of(headers, rows, "320-FT   -20645-A")][col(headers, "I/O Type Name")] = None
    r = solve(mutated(mdb_path, change))
    assert r.readiness.status == "DRAFT"
    assert [q.tq_id for q in r.quarantined] == ["MISSING-IO-TYPE"]
    assert Counter(row["Tag Status"] for row in r.rows)["Field"] == 176
    assert r.violations == []                              # what was allocated is still perfectly valid


def test_engineer_answer_repairs_the_bad_row(mdb_path):
    def change(headers, rows):
        rows[row_of(headers, rows, "320-FT   -20645-A")][col(headers, "I/O Type Name")] = None
    data = mutated(mdb_path, change)
    fixed = solve(data, overrides=[Override("320-FT   -20645-A", "io_type", "AIR", "eng1")])
    assert fixed.quarantined == [] and fixed.readiness.status == "ISSUE-READY"
    assert Counter(row["Tag Status"] for row in fixed.rows)["Field"] == 177
    assert any(t.tq_id == "OVERRIDE-APPLIED" for t in fixed.tqs)
    assert fixed.kpis["overrides_sha256"] != solve(data).kpis["overrides_sha256"]


def test_a_pin_moves_a_cable_and_keeps_every_rule(mdb_path):
    r = solve(mdb_path, pins={"320-ce-0001": ("P30-DCM-32001-04", 4)})
    rows = [x for x in r.rows if x["Field Cable No"] == "320-CE-0001"]
    assert {x["Electronic/ Marshalling Cabinet"] for x in rows} == {"P30-DCM-32001-04"}
    assert {x["CIOC/CSLS Name"] for x in rows} == {"P30DCIOC3201016"}
    assert r.violations == [] and r.readiness.status == "ISSUE-READY"
    assert r.kpis["pins_sha256"] != solve(mdb_path).kpis["pins_sha256"]


def test_column_override_works_through_the_pipeline(mdb_path):
    headers, rows = read_table(mdb_path)
    h2 = ["Instrument Tag" if h == "Tag Number" else h for h in headers]
    r = solve(to_xlsx_bytes(h2, rows), column_overrides={"tag": "Instrument Tag"})
    assert Counter(row["Tag Status"] for row in r.rows)["Field"] == 177 and r.mapping["tag"].method == "override"


def test_unknown_room_is_inferred_so_the_run_stays_useful(mdb_path):
    headers, rows = read_table(mdb_path)
    room = col(headers, "Technical Room (Signal Location 2)")
    cfg = load_config()
    cfg.cabinets = cfg.cabinets[:2]                        # topology no longer knows PIB-24
    r = solve(mdb_path, cfg)
    assert any(t.tq_id == "TOPOLOGY-INFERRED" for t in r.tqs)
    assert Counter(row["Tag Status"] for row in r.rows)["Field"] == 177
    assert "A11" in [a.id for a in r.assumptions]
    again = solve(mdb_path)
    p24 = lambda res: [x for x in res.rows if x["Electronic/ Marshalling Cabinet"] == "P24-DCM-50002-01"]
    assert p24(r) == p24(again)                            # inferred cabinet == the configured one


def test_compute_kpis_on_nothing_is_all_zeros():
    k = compute_kpis([], [], [], [])
    assert k["rows"] == 0 and k["field"] == 0 and k["spare_compliance_pct"] == 100.0 and k["cabinets_used"] == 0


def test_output_hash_is_order_independent_and_sensitive():
    a = [{"x": 1, "y": 2}]
    assert output_hash(a) == output_hash([{"y": 2, "x": 1}])
    assert output_hash(a) != output_hash([{"x": 1, "y": 3}])


def test_result_is_identical_under_different_hash_seeds(mdb_path):
    """Python randomises str hashes per run; a deterministic solver must not care."""
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from io_sudoku.core.pipeline import solve\n"
        "print(solve(%r).kpis['output_sha256'])\n" % (str(ROOT), str(mdb_path))
    )
    hashes = set()
    for seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
        assert out.returncode == 0, out.stderr
        hashes.add(out.stdout.strip())
    assert len(hashes) == 1 and len(next(iter(hashes))) == 64
