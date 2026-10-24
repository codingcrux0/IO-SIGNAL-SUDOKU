from __future__ import annotations

import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

from io_sudoku.core.allocio import build_allocation
from io_sudoku.core.pipeline import solve
from tests.synth import make_mdb

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def big():
    data = make_mdb(10_000, seed=1)
    started = time.perf_counter()
    result = solve(data)
    return data, result, time.perf_counter() - started


def test_ten_thousand_signals_are_allocated_quickly_and_correctly(big):
    _, r, seconds = big
    print(f"\n10,000 signals solved in {seconds:.1f} s; stages(ms): {r.stages_ms}")
    assert seconds <= 15, r.stages_ms                    # target is a few seconds; 15 s is the CI-safe ceiling
    assert len(r.rows) % 384 == 0 and r.kpis["cabinets_used"] >= 30
    field = Counter(x["Tag Status"] for x in r.rows)["Field"]
    assert field + len(r.quarantined) == 10_000
    assert [v for v in r.violations if v.severity == "error"] == []
    assert not any(t.tq_id == "INTERNAL" for t in r.tqs)
    assert sum(1 for t in r.tqs if t.tq_id == "CABINET-AUTO-ADDED") >= 30
    assert r.kpis["spare_compliance_pct"] == 100.0


def test_every_cabinet_keeps_the_rules_at_scale(big):
    _, r, _ = big
    assert r.violations == [] or all(v.severity == "warning" for v in r.violations)
    k = r.kpis
    assert all(pct >= 10.0 for pct in k["future_space_pct_per_cabinet"].values())


def test_writing_a_huge_allocation_is_fast_and_verified(big):
    _, r, _ = big
    started = time.perf_counter()
    data, report = build_allocation(r.rows)
    seconds = time.perf_counter() - started
    print(f"\nwrote {len(r.rows)} rows in {seconds:.1f} s via {report.path_kind}")
    assert report.verified and report.path_kind == "write_only" and seconds <= 60 and len(data) > 100_000


def test_memory_stays_reasonable_at_ten_thousand_signals(tmp_path):
    path = tmp_path / "big.xlsx"
    path.write_bytes(make_mdb(10_000, seed=2))
    script = ("import resource, sys; sys.path.insert(0, %r)\n"
              "from io_sudoku.core.pipeline import solve\n"
              "r = solve(%r)\n"
              "peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
              "print(peak, len(r.rows))\n" % (str(ROOT), str(path)))
    out = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert out.returncode == 0, out.stderr
    peak, rows = out.stdout.split()
    peak_mb = int(peak) / (1024 * 1024 if sys.platform == "darwin" else 1024)
    print(f"\npeak memory for 10,000 signals: {peak_mb:.0f} MB, {rows} rows")
    assert peak_mb < 1200


def test_small_synthetic_runs_are_deterministic():
    data = make_mdb(1_000, seed=5)
    assert solve(data).rows == solve(data).rows
    assert solve(make_mdb(1_000, seed=5)).kpis["output_sha256"] == solve(make_mdb(1_000, seed=5)).kpis["output_sha256"]
