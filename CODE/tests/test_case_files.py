"""The files in test_cases/ must still give the result their README promises."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from io_sudoku.core.pipeline import solve
from io_sudoku.samples import CASES_DIR, case_bytes, case_names

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_test_cases.py"
_spec = importlib.util.spec_from_file_location("make_test_cases", _SCRIPT)
make_test_cases = importlib.util.module_from_spec(_spec)
sys.modules["make_test_cases"] = make_test_cases          # dataclasses look the module up while it loads
_spec.loader.exec_module(make_test_cases)
CASES = make_test_cases.CASES


def test_every_case_file_exists_and_is_listed():
    assert case_names() == sorted(c.file for c in CASES)
    assert (CASES_DIR / "README.md").is_file()


@pytest.mark.parametrize("case", CASES, ids=[c.file for c in CASES])
def test_case_gives_its_promised_result(case):
    result = solve(case_bytes(case.file))
    assert result.readiness.status == case.expect
    assert not result.violations


def test_case_bytes_refuses_other_paths():
    assert case_bytes("../app.py") is None
    assert case_bytes("README.md") is None
