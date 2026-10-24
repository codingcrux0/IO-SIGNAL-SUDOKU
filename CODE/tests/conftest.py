"""Shared pytest fixtures.

Only fixtures that need nothing but the sample files live here. Fixtures that
need project code (a config object, a Signal factory, a CableBlock factory) are
added by the same step that creates that code, so this file never imports
something that does not exist yet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make "import io_sudoku" work no matter where pytest is started from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def mdb_path() -> Path:
    """Official sample Customer IO MDB (190 data rows, sheet MDB-1)."""
    return FIXTURES / "mdb.xlsx"


@pytest.fixture(scope="session")
def alloc_path() -> Path:
    """Official hand-made sample allocation (1152 rows = 3 cabinets x 384)."""
    return FIXTURES / "allocation.xlsx"


@pytest.fixture(scope="session")
def mdb_bytes(mdb_path: Path) -> bytes:
    """The MDB as raw bytes - exactly what a Streamlit upload gives us."""
    return mdb_path.read_bytes()


@pytest.fixture()
def tmp_out(tmp_path: Path) -> Path:
    """A fresh empty folder for files a test writes."""
    out = tmp_path / "out"
    out.mkdir()
    return out


@pytest.fixture()
def cfg():
    """A FRESH default configuration (the planner may append auto-added cabinets)."""
    from io_sudoku.core.config import load_config
    return load_config()


@pytest.fixture(autouse=True)
def _no_real_ai(monkeypatch):
    """Tests never call a real AI service, even on a machine whose .streamlit/secrets.toml holds a key."""
    monkeypatch.setenv("IO_SUDOKU_AI_OFF", "1")
