"""The official sample files, bundled so the tool and its demo run completely offline.

  sample_mdb_bytes()         the Customer IO MDB (190 data rows)
  sample_allocation_bytes()  the hand-made allocation (1152 rows) - used for the Human vs Tool audit
  load_sample_result()       the solved sample (computed once, then remembered)
  golden_hash()              the SHA-256 the solved sample must always produce (the self-test checks it)
  case_names() / case_bytes() the MDB test cases in test_cases/ (clean, messy and broken files for trying the tool)
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data" / "sample"
GOLDEN_PATH = DATA_DIR / "golden_output.sha256"
CASES_DIR = Path(__file__).resolve().parents[1] / "test_cases"
_CASE_TYPES = (".xlsx", ".csv")


def case_names() -> list[str]:
    """File names of the bundled test cases, in order (empty if the folder is missing)."""
    try:
        return sorted(p.name for p in CASES_DIR.iterdir() if p.is_file() and p.suffix.lower() in _CASE_TYPES)
    except OSError:
        return []


def case_bytes(name: str) -> bytes | None:
    """One test case by name; only names from case_names() are read, so no other path can be opened."""
    if name not in case_names():
        return None
    try:
        return (CASES_DIR / name).read_bytes()
    except OSError:
        return None


def sample_mdb_bytes() -> bytes:
    return (DATA_DIR / "sample_mdb.xlsx").read_bytes()


def sample_allocation_bytes() -> bytes:
    return (DATA_DIR / "sample_allocation.xlsx").read_bytes()


@lru_cache(maxsize=1)
def load_sample_result():
    """Solve the bundled sample MDB (cached: it is deterministic, so the answer never changes)."""
    from io_sudoku.core.pipeline import solve

    return solve(sample_mdb_bytes())


def golden_hash() -> str | None:
    """The recorded fingerprint of the solved sample, or None if the file is missing."""
    try:
        text = GOLDEN_PATH.read_text(encoding="utf-8").strip()
        return text or None
    except Exception:
        return None
