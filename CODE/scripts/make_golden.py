"""Record the fingerprint (SHA-256) of the solved sample as the 'golden' value.

Run this ONLY when you have deliberately changed the solver's behaviour and checked the
new output is correct:      python scripts/make_golden.py
The self-test and the test-suite compare every future run against this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from io_sudoku.core.pipeline import output_hash, solve          # noqa: E402
from io_sudoku.samples import GOLDEN_PATH, sample_mdb_bytes    # noqa: E402


def main() -> int:
    result = solve(sample_mdb_bytes())
    if result.readiness is None or result.readiness.status != "ISSUE-READY" or result.violations:
        print("Refusing to record a golden value: the sample result is not clean.")
        return 1
    GOLDEN_PATH.write_text(output_hash(result.rows) + "\n", encoding="utf-8")
    print(f"Golden hash written to {GOLDEN_PATH}: {output_hash(result.rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
