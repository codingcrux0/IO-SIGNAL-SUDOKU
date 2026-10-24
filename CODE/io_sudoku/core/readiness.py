"""The issue-readiness gate: how far can a reviewer trust this result?

  ISSUE-READY  no error, nothing set aside, no rule violation - safe to hand to a reviewer
  DRAFT        no error, but there are open items (warnings to sign off, special TQs)
  BLOCKED      nothing could be allocated (unreadable input or zero rows), OR something must be fixed
               first: an error TQ, a broken rule, or a signal that was set aside.  Strict on purpose -
               a result with an error is never offered as a draft.

Warning sign-off: when `signoffs` is given (the website always gives it), every warning - a warning
TQ or a warning from the verifier - must be approved by an engineer before the result is ISSUE-READY.
A warning marked as a problem keeps it in DRAFT.  Sign-offs are keyed by warning_key(), so a sign-off
survives a re-allocation as long as the same warning comes back.  Without `signoffs` (command line,
which has no review step) warnings are only listed, as before.

Drafts are delivered with '_DRAFT' in the file name so nobody mistakes them for a final issue.
The function only reads attributes of the result object (duck typing), so it needs no import
of the pipeline and cannot create an import cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BLOCKING_TQS = ("UNREADABLE-FILE", "UNSUPPORTED-FORMAT", "FILE-TOO-LARGE", "TOO-MANY-ROWS")
DRAFT_TQS = ("INTERNAL", "SPARE-SHORTFALL", "CAPACITY-OVERFLOW", "REV-A-UNPARSEABLE", "FUTURE-SPACE-MISS", "ROW-REALIGNED")


APPROVED, PROBLEM = "approved", "problem"


@dataclass(frozen=True)
class Readiness:
    status: str                 # 'ISSUE-READY' | 'DRAFT' | 'BLOCKED'
    reasons: tuple[str, ...]


def suffix(status: str) -> str:
    """File-name suffix: '' for a final issue, '_DRAFT' otherwise."""
    return "" if status == "ISSUE-READY" else "_DRAFT"


def warning_key(item: Any) -> str:
    """Stable id of one warning (a TQ or a verifier finding): 'TOPOLOGY-INFERRED|PIB-40'."""
    kind = getattr(item, "tq_id", None) or getattr(item, "rule", "")
    return f"{kind}|{getattr(item, 'ref', '')}"


def warnings_of(result: Any) -> list[Any]:
    """Every warning of a result, TQs first, then verifier findings."""
    tqs = [t for t in (getattr(result, "tqs", []) or []) if t.severity == "warning"]
    found = [v for v in (getattr(result, "violations", []) or []) if v.severity == "warning"]
    return tqs + found


def signoff_counts(result: Any, signoffs: dict[str, str]) -> dict[str, int]:
    """{'approved': n, 'problem': n, 'waiting': n, 'total': n} over the distinct warnings of a result."""
    keys = {warning_key(w) for w in warnings_of(result)}
    counts = {APPROVED: 0, PROBLEM: 0, "waiting": 0, "total": len(keys)}
    for key in keys:
        decision = signoffs.get(key)
        counts[decision if decision in (APPROVED, PROBLEM) else "waiting"] += 1
    return counts


def assess(result: Any, signoffs: dict[str, str] | None = None) -> Readiness:
    """Classify a SolveResult (or anything with rows/tqs/violations/quarantined).
    `signoffs` maps warning_key -> 'approved' | 'problem'; see the module docstring."""
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
    blocked = bool(reasons)                       # every error must be fixed: no draft is offered with one
    if blocked:
        reasons.append("Fix every error, then re-allocate.")
    for special in sorted({i for i in ids if i in DRAFT_TQS}):
        if not any(special in r for r in reasons):
            reasons.append(f"{special} was raised")
    signed = signoff_counts(result, signoffs) if signoffs is not None else None
    if signed:
        if signed[PROBLEM]:
            reasons.append(f"{signed[PROBLEM]} warnings were marked as a problem")
        if signed["waiting"]:
            reasons.append(f"{signed['waiting']} warnings are waiting for sign-off")
    if reasons:
        return Readiness("BLOCKED" if blocked else "DRAFT", tuple(reasons))
    if signed and signed["total"]:
        return Readiness("ISSUE-READY", (f"{signed['total']} warnings were signed off",))

    notes = []
    warnings = sum(1 for t in tqs if t.severity == "warning") + sum(1 for v in violations if v.severity == "warning")
    if warnings:
        notes.append(f"{warnings} warnings to review")
    return Readiness("ISSUE-READY", tuple(notes))
