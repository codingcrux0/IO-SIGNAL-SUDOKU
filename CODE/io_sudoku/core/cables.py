"""Cable blocks and logic groups - the units the allocator actually places.

KEY IDEA: a multipair cable is placed as ONE block.  Pair N of the cable lands on
channel N of the block's run of baseplates, so a cable can be checked directly against
its channels (CLAUDE_RULES 3D.4: cables are contiguous on identical baseplates).  A block
is never split across CIOCs.

Block length (in channels):
    cables of 6 pairs or fewer  -> 6   (half a baseplate; two such cables may share one)
    larger cables               -> rounded UP to a multiple of 12 (whole baseplates)

Logic groups: cables whose signals share a Logic Number belong to the same controller
logic, so they must live in the same cabinet.  We join them with a union-find; in the
official sample this reproduces the engineers' controller split exactly.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from io_sudoku.core.config import Config, RulesCfg
from io_sudoku.core.constants import MAX_CABLE_PAIRS, SLOTS_PER_BP, STANDARD_CABLE_SIZES
from io_sudoku.core.models import Quarantined, Signal
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQLog
from io_sudoku.core.validate import parse_cable_size


@dataclass
class CableBlock:
    cable_no: str                       # display text of the cable number
    key: str                            # match_key(cable_no)
    declared_pairs: int                 # pairs in the cable (from its size text)
    length: int                         # channels the block occupies (6, 12, 24 ...)
    signals: dict[int, Signal] = field(default_factory=dict)   # pair number -> signal
    family: str | None = None           # 'A', 'B' or None (neutral)
    tech_room: str | None = None
    logic_nos: tuple[str, ...] = ()
    group_id: int = -1                  # logic group (-2 = group spans technical rooms)
    size_text: str | None = None        # original size text, e.g. '24PX1MM2/...'


def block_length(declared_pairs: int) -> int:
    """6 channels for small cables, otherwise whole baseplates (multiples of 12)."""
    if declared_pairs <= 6:
        return 6
    return -(-declared_pairs // SLOTS_PER_BP) * SLOTS_PER_BP


def family_of(code: str | None, rules: RulesCfg) -> str | None:
    """Segregation family of one signal: A / A-CONTROL -> 'A', B / B-ALARM -> 'B', else None."""
    if not code:
        return None
    upper = code.strip().upper()
    if upper in {c.upper() for c in rules.a_codes}:
        return "A"
    if upper in {c.upper() for c in rules.b_codes}:
        return "B"
    return None


def build_blocks(accepted: list[Signal], size_by_cable: dict[str, int], cfg: Config,
                 log: TQLog) -> tuple[list[CableBlock], list[Quarantined]]:
    """Group validated signals into cable blocks (sorted by cable key) + quarantined cables."""
    by_cable: dict[str, list[Signal]] = defaultdict(list)
    for sig in accepted:
        by_cable[match_key(sig.cable_no) or ""].append(sig)

    blocks: list[CableBlock] = []
    quarantined: list[Quarantined] = []

    def reject(members: list[Signal], tq_id: str, cable: str) -> None:
        log.add(tq_id, cable)
        quarantined.extend(Quarantined(m, tq_id) for m in members)

    for key in sorted(by_cable):
        members = sorted(by_cable[key], key=lambda s: (s.row_ref, s.tag))
        cable_no = members[0].cable_no or key
        size_text = next((m.cable_size for m in members if m.cable_size), None)
        declared = size_by_cable.get(key) or parse_cable_size(size_text)
        if declared is None:
            highest = max((m.pair_no or 0) for m in members)
            declared = next((s for s in STANDARD_CABLE_SIZES if s >= highest), highest)
        if declared > MAX_CABLE_PAIRS:
            reject(members, "CABLE-TOO-LARGE", cable_no)
            continue
        families = {family_of(m.segregation, cfg.rules) for m in members} - {None}
        if families == {"A", "B"}:
            reject(members, "MIXED-SEGREGATION", cable_no)
            continue
        if len({match_key(m.tech_room) for m in members}) > 1:
            reject(members, "GROUP-SPANS-ROOMS", cable_no)
            continue
        if declared > 6 and declared not in STANDARD_CABLE_SIZES:
            log.add("CABLE-SIZE-ROUNDED", cable_no)
        logic: dict[str, str] = {}
        for m in members:
            lk = match_key(m.logic_no)
            if lk and lk not in logic:
                logic[lk] = m.logic_no or lk
        blocks.append(CableBlock(
            cable_no=cable_no, key=key, declared_pairs=declared, length=block_length(declared),
            signals={m.pair_no: m for m in members if m.pair_no is not None},
            family=next(iter(families)) if families else None,
            tech_room=members[0].tech_room, logic_nos=tuple(sorted(logic.values())),
            size_text=size_text))
    return blocks, quarantined


def link_groups(blocks: list[CableBlock], log: TQLog | None = None) -> None:
    """Join blocks that share a Logic Number into groups and number the groups (in place).

    group_id = rank of the group's smallest cable key (0, 1, 2 ...), so ids are stable.
    A group whose cables sit in different technical rooms gets group_id = -2 (the caller
    quarantines those cables) and, if a log is given, a GROUP-SPANS-ROOMS TQ.
    """
    parent = list(range(len(blocks)))

    def find(i: int) -> int:
        while parent[i] != i:                 # path halving; ends because parents form a forest
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_with_logic: dict[str, int] = {}
    for i, block in enumerate(blocks):
        for logic in {match_key(n) for n in block.logic_nos}:
            if logic is None:
                continue
            if logic in first_with_logic:
                a, b = find(first_with_logic[logic]), find(i)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                first_with_logic[logic] = i

    components: dict[int, list[int]] = defaultdict(list)
    for i in range(len(blocks)):
        components[find(i)].append(i)
    for rank, root in enumerate(sorted(components, key=lambda r: min(components[r]))):
        members = components[root]
        rooms = {match_key(blocks[i].tech_room) for i in members}
        for i in members:
            blocks[i].group_id = rank if len(rooms) == 1 else -2
        if len(rooms) > 1 and log is not None:
            log.add("GROUP-SPANS-ROOMS", blocks[min(members)].cable_no)
