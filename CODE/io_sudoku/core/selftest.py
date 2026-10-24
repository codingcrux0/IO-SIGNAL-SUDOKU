"""Start-up self-test: proves the tool works in THIS environment before anyone relies on it.

Runs the bundled sample through the whole solver and checks: the row count, no rule
violations, an ISSUE-READY verdict, that the Excel writer round-trips, that two runs give the
same fingerprint, and that the fingerprint equals the recorded golden value.  Takes about a
second.  If a library on the host is the wrong version, this is where it shows up.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from io_sudoku.samples import golden_hash, sample_mdb_bytes


@dataclass
class SelfTestReport:
    ok: bool = False
    checks: list[tuple[str, bool, str]] = field(default_factory=list)   # (name, passed, detail)
    ms: float = 0.0


def run_selftest() -> SelfTestReport:
    """Run all checks. Never raises: an exception becomes a failed check."""
    started = time.perf_counter()
    report = SelfTestReport()

    def check(name: str, fn) -> None:
        try:
            outcome = fn()
            passed, detail = outcome if isinstance(outcome, tuple) else (bool(outcome), "")
        except Exception as exc:  # noqa: BLE001
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        report.checks.append((name, bool(passed), str(detail)))

    holder: dict = {}

    def solve_sample():
        from io_sudoku.core.pipeline import solve
        holder["result"] = solve(sample_mdb_bytes())
        n = len(holder["result"].rows)
        return n == 1152, f"{n} rows (expected 1152)"

    check("Solve the bundled sample", solve_sample)
    result = holder.get("result")
    check("No rule violations", lambda: (result is not None and result.violations == [],
                                         f"{len(result.violations) if result else '?'} violations"))
    check("Result is ISSUE-READY", lambda: (result is not None and result.readiness is not None
                                            and result.readiness.status == "ISSUE-READY",
                                            result.readiness.status if result and result.readiness else "no result"))

    def writer():
        from io_sudoku.core.allocio import build_allocation, read_allocation
        data, rep = build_allocation(result.rows)
        return rep.verified and read_allocation(data) == result.rows, f"{rep.path_kind}, verified={rep.verified}"
    check("Excel writer round-trips", writer)

    def determinism():
        from io_sudoku.core.pipeline import output_hash, solve
        again = solve(sample_mdb_bytes())
        return output_hash(again.rows) == output_hash(result.rows), "two runs compared"
    check("Two runs give the same fingerprint", determinism)

    def golden():
        from io_sudoku.core.pipeline import output_hash
        expected = golden_hash()
        if expected is None:
            return False, "golden_output.sha256 is missing"
        got = output_hash(result.rows)
        return got == expected, "matches the recorded value" if got == expected else f"{got[:12]}... differs from {expected[:12]}..."
    check("Fingerprint equals the golden value", golden)

    report.ok = all(passed for _, passed, _ in report.checks)
    report.ms = round((time.perf_counter() - started) * 1000, 1)
    return report
