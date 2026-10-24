"""TQ lifecycle: which TQs are still open, which are new, which got resolved between revisions.

A TQ is identified by (id, reference) - for example ('MISSING-PAIR', '320-ft -20645-a') -
so the same question raised again in the next revision is recognised as the same TQ.
TQs can also be grouped by the owner who should answer them (Instrument, Electrical,
Process, Engineering, System) and turned into plain text ready to paste into an e-mail.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQ

OWNER_ORDER = ("Instrument", "Electrical", "Process", "Engineering", "System")


def tq_key(tq: TQ) -> tuple[str, str]:
    """Identity of a TQ across revisions: its id plus its reference (compared by match key)."""
    return tq.tq_id, match_key(tq.ref) or ""


@dataclass
class TQDiff:
    still_open: list[TQ] = field(default_factory=list)   # raised in both revisions
    new: list[TQ] = field(default_factory=list)          # only in the current revision
    resolved: list[TQ] = field(default_factory=list)     # only in the previous revision


def diff_tqs(previous: list[TQ], current: list[TQ]) -> TQDiff:
    before = {tq_key(t) for t in previous}
    now = {tq_key(t) for t in current}
    diff = TQDiff()
    for t in current:
        (diff.still_open if tq_key(t) in before else diff.new).append(t)
    seen: set[tuple[str, str]] = set()
    for t in previous:
        key = tq_key(t)
        if key not in now and key not in seen:
            seen.add(key)
            diff.resolved.append(t)
    return diff


def group_by_owner(tqs: list[TQ]) -> dict[str, list[TQ]]:
    """TQs per owner (known owners first, in a fixed order); order inside a group is kept."""
    groups: dict[str, list[TQ]] = {}
    for t in tqs:
        groups.setdefault(t.owner, []).append(t)
    known = [o for o in OWNER_ORDER if o in groups]
    other = sorted(o for o in groups if o not in OWNER_ORDER)
    return {o: groups[o] for o in known + other}


def tqs_as_email_text(tqs: list[TQ], owner: str, project: str = "IO Allocation") -> str:
    """A numbered list of the owner's questions, each with its suggested fix."""
    mine = [t for t in tqs if t.owner == owner]
    lines = [f"Technical queries for {owner} - {project}", ""]
    if not mine:
        lines.append("There are no open queries for you.")
        return "\n".join(lines)
    lines.append(f"{len(mine)} open {'query' if len(mine) == 1 else 'queries'}:")
    lines.append("")
    for n, t in enumerate(mine, start=1):
        lines.append(f"{n}. [{t.severity.upper()}] {t.message}")
        lines.append(f"   Suggested fix: {t.resolution}")
    return "\n".join(lines)
