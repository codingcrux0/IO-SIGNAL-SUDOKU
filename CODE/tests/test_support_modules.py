from __future__ import annotations

import io
import json
import zipfile

import pytest

from io_sudoku import samples
from io_sudoku.cli import main as cli_main
from io_sudoku.core import pipeline
from io_sudoku.core.allocio import read_allocation
from io_sudoku.core.assumptions import ASSUMPTIONS
from io_sudoku.core.diagnostics import make_support_bundle
from io_sudoku.core.overrides import Override
from io_sudoku.core.pipeline import output_hash, solve
from io_sudoku.core.rulepack import default_pack, derive
from io_sudoku.core.selftest import run_selftest
from io_sudoku.core.summary_html import build_summary_html
from io_sudoku.core.workspace import export_workspace, import_workspace
from tests.helpers import make_signal


@pytest.fixture(scope="module")
def result():
    return samples.load_sample_result()


# -------------------------------------------------------------------------- samples
def test_bundled_samples_equal_the_fixtures(mdb_bytes, alloc_path):
    assert samples.sample_mdb_bytes() == mdb_bytes
    assert samples.sample_allocation_bytes() == alloc_path.read_bytes()


def test_sample_result_and_golden_hash(result):
    assert len(result.rows) == 1152 and result.readiness.status == "ISSUE-READY"
    assert samples.golden_hash() == output_hash(result.rows) and len(samples.golden_hash()) == 64
    assert samples.load_sample_result() is result              # cached


# ------------------------------------------------------------------------ selftest
def test_selftest_passes_on_a_clean_checkout():
    report = run_selftest()
    assert report.ok, report.checks
    assert [name for name, _, _ in report.checks][-1] == "Fingerprint equals the golden value"
    assert report.ms < 20_000


def test_selftest_names_the_failing_check_when_the_golden_value_is_wrong(monkeypatch):
    monkeypatch.setattr("io_sudoku.core.selftest.golden_hash", lambda: "0" * 64)
    report = run_selftest()
    failed = [name for name, passed, _ in report.checks if not passed]
    assert not report.ok and failed == ["Fingerprint equals the golden value"]


def test_selftest_survives_a_broken_solver(monkeypatch):
    monkeypatch.setattr(pipeline, "read_mdb", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    report = run_selftest()
    assert not report.ok and report.checks             # reported, not raised


def test_cli_selftest_exit_codes(capsys):
    assert cli_main(["selftest"]) == 0
    assert "Self-test passed" in capsys.readouterr().out
    assert cli_main([]) == 2
    assert cli_main(["bogus"]) == 2
    assert cli_main(["--nonsense"]) == 2


# ---------------------------------------------------------------------- diagnostics
def test_support_bundle_contents_and_privacy(result, mdb_bytes, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(pipeline, "build_rows", boom)
    broken = solve(mdb_bytes)
    data = make_support_bundle(broken, "abc123", {"name": "VIT-2026"})
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        assert names == {"manifest.json", "tqs.json", "stages.json", "tracebacks.txt", "config.json", "pack.json", "readiness.json"}
        assert "boom" in z.read("tracebacks.txt").decode() and "=== rows ===" in z.read("tracebacks.txt").decode()
        assert json.loads(z.read("manifest.json"))["input_sha256"] == "abc123"
        assert json.loads(z.read("readiness.json"))["status"] in ("DRAFT", "BLOCKED")
        assert len(json.loads(z.read("config.json"))["cabinets"]) == 3
    with_input = make_support_bundle(broken, "abc123", None, include_input=mdb_bytes)
    assert "input.xlsx" in zipfile.ZipFile(io.BytesIO(with_input)).namelist()


def test_support_bundle_of_a_clean_run(result):
    data = make_support_bundle(result, "h")
    assert b"No unexpected errors" in zipfile.ZipFile(io.BytesIO(data)).read("tracebacks.txt")


# ------------------------------------------------------------------------ workspace
def test_workspace_round_trip(result):
    pack = derive(default_pack(), "mine")
    overrides = [Override("320-ft -1", "io_type", "AIR", "eng1", "checked")]
    pins = {"320-ce-0001": ("P30-DCM-32001-04", 4)}
    blob = export_workspace(result, pack, overrides, pins, "sha", "B")
    again, _ = import_workspace(export_workspace(result, pack, overrides, pins, "sha", "B"))
    assert again.rows == result.rows and again.manifest == import_workspace(blob)[0].manifest   # same content every time
    state, reason = import_workspace(blob)
    assert reason == "" and state is not None
    assert state.rows == result.rows and state.pack == pack and state.overrides == overrides and state.pins == pins
    assert state.rev_label == "B" and state.manifest["output_sha256"] == output_hash(result.rows)


@pytest.mark.parametrize("junk", [b"", b"not a zip", b"PK\x03\x04broken"])
def test_damaged_workspaces_give_a_reason_not_an_exception(junk):
    state, reason = import_workspace(junk)
    assert state is None and reason


def test_workspace_with_missing_members_or_bad_json(result):
    good = export_workspace(result, default_pack(), [], {}, "s", "00")
    src = zipfile.ZipFile(io.BytesIO(good))
    for drop in ("allocation.xlsx", "pack.json", "manifest.json"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n in src.namelist():
                if n != drop:
                    z.writestr(n, src.read(n))
        state, reason = import_workspace(buf.getvalue())
        assert state is None and drop in reason
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in src.namelist():
            z.writestr(n, b"{not json" if n == "manifest.json" else src.read(n))
    assert import_workspace(buf.getvalue())[0] is None


def test_workspace_rows_work_as_rev_a(result, mdb_path):
    from io_sudoku.core.revision import solve_incremental
    state, _ = import_workspace(export_workspace(result, default_pack(), [], {}, "s", "00"))
    res, rep = solve_incremental(mdb_path, state.rows)
    assert rep.changes == [] and rep.mode == "pinned"


# ---------------------------------------------------------------------- summary html
def test_summary_html_content(result):
    html = build_summary_html(result, {"output_sha256": "f" * 64, "tool_version": "1.0.0"}, result.readiness, result.assumptions)
    assert 'class="badge ISSUE-READY"' in html and "ISSUE-READY" in html
    for a in result.assumptions:
        assert a.id in html
    assert "P30DPK320102" in html and "All rules passed" in html and "f" * 64 in html
    for forbidden in ("http://", "https://", "<script", "<link", "javascript:"):
        assert forbidden not in html
    assert html == build_summary_html(result, {"output_sha256": "f" * 64, "tool_version": "1.0.0"}, result.readiness, result.assumptions)


def test_summary_html_escapes_everything(result):
    nasty = pipeline.TQLog()
    nasty.add("MISSING-PAIR", "<script>alert(1)</script>", "<img src=x onerror=alert(2)>")
    fake = type("R", (), {"kpis": {}, "tqs": nasty.items(), "violations": [], "spare_lines": [], "rows": []})()
    readiness = type("Rd", (), {"status": "DRAFT", "reasons": ("<b>bold</b>",)})()
    assumption = type("A", (), {"id": "A99", "text": "<script>x</script>", "confirm_by": "me"})()
    html = build_summary_html(fake, {}, readiness, [assumption])
    assert "<script" not in html and "<img" not in html and "<b>" not in html and "&lt;script&gt;" in html


def test_summary_html_survives_an_empty_blocked_result():
    empty = solve(b"garbage")
    html = build_summary_html(empty, {}, empty.readiness, empty.assumptions)
    assert "BLOCKED" in html and "Nothing to show." in html


def test_assumption_register_is_complete():
    assert [a.id for a in ASSUMPTIONS] == [f"A{n:02d}" for n in range(1, 13)]
    assert all(a.text and a.source and a.confirm_by for a in ASSUMPTIONS)
