from __future__ import annotations

import hashlib
import json
from pathlib import Path

import openpyxl
import pytest

from io_sudoku.cli import main
from io_sudoku.core.allocio import read_allocation
from io_sudoku.core.manifest import build_manifest
from io_sudoku.core.pipeline import solve
from io_sudoku.core.rulepack import default_pack, derive, pack_to_dict, RulePack
from io_sudoku.core.workspace import export_workspace
from tests.mutate import col, mutated, row_of


@pytest.fixture(scope="module")
def solved_dir(tmp_path_factory, mdb_path):
    out = tmp_path_factory.mktemp("solve")
    assert main(["solve", str(mdb_path), "--out", str(out)]) == 0
    return out


def test_manifest_fields_and_hashes(mdb_bytes):
    result = solve(mdb_bytes)
    m = build_manifest(mdb_bytes, default_pack(), result)
    assert m["input_sha256"] == hashlib.sha256(mdb_bytes).hexdigest() and m["rows"] == 1152 and m["readiness"] == "ISSUE-READY"
    assert m["pack_name"] == "VIT-2026" and len(m["pack_hash"]) == 64 and m["tool_version"] == "1.0.0"
    again = build_manifest(mdb_bytes, default_pack(), solve(mdb_bytes))
    assert m["output_sha256"] == again["output_sha256"]
    other = build_manifest(mdb_bytes, derive(default_pack()), result)
    assert other["pack_hash"] != m["pack_hash"] and m["created_utc"].endswith("+00:00")


def test_solve_writes_every_output(solved_dir, mdb_bytes):
    names = {p.name for p in solved_dir.iterdir()}
    assert names == {"IO_Allocation_00.xlsx", "TQ_Register.xlsx", "Parts_and_Cables.xlsx", "Decision_Trace.xlsx",
                     "Summary.html", "Cabinet_Drawings.html", "Run_Manifest.json"}
    rows = read_allocation(solved_dir / "IO_Allocation_00.xlsx")
    assert len(rows) == 1152
    ws = openpyxl.load_workbook(solved_dir / "IO_Allocation_00.xlsx").worksheets[0]
    assert ws.max_column == 76 and ws.title == "IO Assignment"
    manifest = json.loads((solved_dir / "Run_Manifest.json").read_text())
    assert manifest["output_sha256"] == solve(mdb_bytes).kpis["output_sha256"]


def test_running_twice_gives_the_same_fingerprint(solved_dir, mdb_path, tmp_path):
    assert main(["solve", str(mdb_path), "--out", str(tmp_path)]) == 0
    a = json.loads((solved_dir / "Run_Manifest.json").read_text())
    b = json.loads((tmp_path / "Run_Manifest.json").read_text())
    assert a["output_sha256"] == b["output_sha256"] and a["input_sha256"] == b["input_sha256"]


def test_a_rule_pack_changes_the_hash_and_the_output(mdb_path, tmp_path, solved_dir):
    pack = RulePack("custom", 2, "VIT-2026 v1", {"spare_pct": 15}, {}, False)
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack_to_dict(pack)))
    out = tmp_path / "out"
    assert main(["solve", str(mdb_path), "--out", str(out), "--pack", str(path)]) == 0
    a = json.loads((solved_dir / "Run_Manifest.json").read_text())
    b = json.loads((out / "Run_Manifest.json").read_text())
    assert a["pack_hash"] != b["pack_hash"] and a["output_sha256"] != b["output_sha256"]


def test_bad_inputs_give_exit_code_one_and_a_one_line_message(tmp_path, capsys):
    assert main(["solve", str(tmp_path / "missing.xlsx"), "--out", str(tmp_path / "o")]) == 1
    out = capsys.readouterr().out
    assert "Cannot read the file" in out and "Traceback" not in out and len(out.strip().splitlines()) == 1
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"garbage")
    assert main(["solve", str(junk), "--out", str(tmp_path / "o2")]) == 1
    out = capsys.readouterr().out
    assert "Traceback" not in out and (tmp_path / "o2" / "TQ_Register.xlsx").exists()   # the TQ register explains why


def test_argument_errors_are_exit_code_two(capsys):
    assert main([]) == 2 and main(["solve"]) == 2 and main(["nonsense"]) == 2 and main(["solve", "x"]) == 2


def test_revise_with_an_allocation_and_with_a_workspace(solved_dir, mdb_path, tmp_path):
    def change(h, rows):
        rows.pop(row_of(h, rows, "320-LT   -80002"))
    b = tmp_path / "rev_b.xlsx"
    b.write_bytes(mutated(mdb_path, change))
    out = tmp_path / "rev"
    assert main(["revise", str(solved_dir / "IO_Allocation_00.xlsx"), str(b), "--out", str(out)]) == 0
    assert {"Revision_Impact.xlsx", "IO_Allocation_B_REDLINE.xlsx", "IO_Allocation_B.xlsx"} <= {p.name for p in out.iterdir()}
    ws = openpyxl.load_workbook(out / "Revision_Impact.xlsx")["Summary"]
    summary = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(2, ws.max_row + 1)}
    assert summary["Deleted"] == 1 and summary["Moved"] == 0 and summary["Comparison mode"] == "pinned"

    workspace = tmp_path / "ws.zip"
    workspace.write_bytes(export_workspace(solve(mdb_path), default_pack(), [], {}, "s", "00"))
    out2 = tmp_path / "rev2"
    assert main(["revise", str(workspace), str(b), "--out", str(out2), "--rev", "C"]) == 0
    assert (out2 / "IO_Allocation_C.xlsx").exists()


def test_revise_rejects_a_file_that_is_not_an_allocation(mdb_path, tmp_path, capsys):
    assert main(["revise", str(mdb_path), str(mdb_path), "--out", str(tmp_path / "o")]) == 1
    assert "not an IO Allocation" in capsys.readouterr().out


def test_audit_the_human_sample(alloc_path, tmp_path, capsys):
    assert main(["audit", str(alloc_path), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "V10" in out and {p.name for p in tmp_path.iterdir()} == {"Health_Check.xlsx", "Health_Check.html"}
    assert main(["audit", str(tmp_path / "Health_Check.html"), "--out", str(tmp_path / "x")]) == 1


def test_selftest_command(capsys):
    assert main(["selftest"]) == 0 and "Self-test passed" in capsys.readouterr().out


def test_module_entry_point_runs(tmp_path):
    import subprocess, sys
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-m", "io_sudoku", "selftest"], capture_output=True, text=True, cwd=root, timeout=120)
    assert out.returncode == 0 and "Self-test passed" in out.stdout
