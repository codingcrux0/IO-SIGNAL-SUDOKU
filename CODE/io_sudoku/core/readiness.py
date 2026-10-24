"""The issue-readiness gate: how far can a reviewer trust this result?

  ISSUE-READY  no error, nothing set aside, no rule violation - safe to hand to a reviewer
  DRAFT        usable, but there are open items (TQs, quarantined signals, violations)
  BLOCKED      nothing could be allocated (unreadable input or zero rows)

Drafts are delivered with '_DRAFT' in the file name so nobody mistakes them for a final issue.
The function only reads attributes of the result object (duck typing), so it needs no import
of the pipeline and cannot create an import cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BLOCKING_TQS = ("UNREADABLE-FILE", "UNSUPPORTED-FORMAT", "FILE-TOO-LARGE", "TOO-MANY-ROWS")
DRAFT_TQS = ("INTERNAL", "SPARE-SHORTFALL", "CAPACITY-OVERFLOW", "REV-A-UNPARSEABLE", "FUTURE-SPACE-MISS")


@dataclass(frozen=True)
class Readiness:
    status: str                 # 'ISSUE-READY' | 'DRAFT' | 'BLOCKED'
    reasons: tuple[str, ...]


def suffix(status: str) -> str:
    """File-name suffix: '' for a final issue, '_DRAFT' otherwise."""
    return "" if status == "ISSUE-READY" else "_DRAFT"


def assess(result: Any) -> Readiness:
    """Classify a SolveResult (or anything with rows/tqs/violations/quarantined)."""
    rows = getattr(result, "rows", []) or []
    tqs = list(getattr(result, "tqs", []) or [])
    violations = list(getattr(result, "violations", []) or [])
    quarantined = list(getattr(result, "quarantined", []) or [])
    ids = [t.tq_id for t in tqs]

    blockers = sorted({i for i in ids if i in BLOCKING_TQS})
    if blockers or not rows:
        reasons = [f"Blocking problem: {i}" for i in blockers] or ["No signals could be allocated."]
        return Readiness("BLOCKED", tuple(reasons))

    reasons: list[str] = []
    errors = [t for t in tqs if t.severity == "error"]
    if errors:
        kinds = ", ".join(sorted({t.tq_id for t in errors}))
        reasons.append(f"{len(errors)} error TQs ({kinds})")
    error_violations = [v for v in violations if v.severity == "error"]
    if error_violations:
        kinds = ", ".join(sorted({v.rule for v in error_violations}))
        reasons.append(f"{len(error_violations)} rule violations ({kinds})")
    if quarantined:
        reasons.append(f"{len(quarantined)} signals were set aside")
    for special in sorted({i for i in ids if i in DRAFT_TQS}):
        if not any(special in r for r in reasons):
            reasons.append(f"{special} was raised")
    if reasons:
        return Readiness("DRAFT", tuple(reasons))

    notes = []
    warnings = sum(1 for t in tqs if t.severity == "warning") + sum(1 for v in violations if v.severity == "warning")
    if warnings:
        notes.append(f"{warnings} warnings to review")
    return Readiness("ISSUE-READY", tuple(notes))
