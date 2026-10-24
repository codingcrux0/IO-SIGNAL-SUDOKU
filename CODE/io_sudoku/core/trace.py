"""'Why is this tag here?' - the decision trace.

While the solver works it writes one plain-English sentence per decision (which logic group a
cable is in, which cabinet it went to and why, which CIOC, where exactly, which spares were
converted).  This module only READS those sentences: it never influences placement, and it
adds no column to the 76-column allocation.
"""
from __future__ import annotations

from typing import Any

from io_sudoku.core.report import _emit, _safe, _workbook_bytes
from io_sudoku.core.textnorm import match_key


def explain(result: Any, query: str) -> list[str]:
    """The decision sentences for a tag, cable number, alarm or wired-spare tag ([] if unknown)."""
    traces = getattr(result, "traces", {}) or {}
    key = match_key(query)
    return list(traces.get(key, [])) if key else []


def trace_bytes(result: Any) -> bytes:
    """Decision_Trace.xlsx: one row per (key, step)."""
    def build() -> bytes:
        traces = getattr(result, "traces", {}) or {}
        rows = [[key, step, line] for key in sorted(traces) for step, line in enumerate(traces[key], start=1)]
        return _workbook_bytes([("Decision Trace", ["Key", "Step", "Reason"], rows)])
    return _safe(build)


def write_trace(result: Any, target: Any) -> None:
    _emit(target, trace_bytes(result))
