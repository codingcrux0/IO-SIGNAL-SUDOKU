"""The cabinet grid: 4 CIOCs x 8 baseplates x 12 channels = 384 slots.

Slots of one CIOC are numbered by a linear POSITION 0..95:
    position = (baseplate - 1) * 12 + (channel - 1)
so CHARM_No within the CIOC is simply position + 1 (the CLAUDE_RULES formula).

Fixed rules enforced HERE (they cannot be configured away):
  * CIOC 1, baseplate 1 (positions 0-11) is reserved for Cabinet Alarms - no field cable
    may use it.
  * A cable run is contiguous and aligned: 6-pair cables start on channel 1 or 7 of a
    baseplate, everything else on channel 1 of a baseplate.
  * The last `end_reserve_bps` baseplates of CIOC 4 are kept EMPTY (CLAUDE_RULES asks for
    3-4 empty baseplates at the end of the cabinet) unless a caller explicitly allows it.

The segregation family of a CIOC is DERIVED from the cables placed in it (never stored),
so it can never go stale after a block is removed.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from io_sudoku.core.catalog import profile_for
from io_sudoku.core.cables import CableBlock
from io_sudoku.core.config import CabinetCfg, RulesCfg
from io_sudoku.core.constants import (
    ALARM_CIOC, ALARM_SLOTS, BPS_PER_CIOC, CIOCS_PER_CAB, SLOTS_PER_BP, SLOTS_PER_CIOC,
    STATUS_ALARM, STATUS_FIELD, STATUS_SLOT,
)
from io_sudoku.core.models import Signal
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQLog


@dataclass
class Cell:
    """What sits in one slot. Slots with no Cell are plain empty Spare Slots."""

    status: str                              # Field | Cabinet Alarm | Wired Spare | Spare Slot
    signal: Signal | None = None
    cable_no: str | None = None
    cable_key: str | None = None
    pair_no: int | None = None
    pair_text: str | None = None
    size_text: str | None = None
    io_type: str | None = None
    profile: str | None = None               # hardware profile (see catalog)
    dsp: str | None = None                   # wired-spare tag
    remark: str | None = None
    former_io: str | None = None             # IO type of a tag that used to be here (revisions)
    origin: str | None = None                # 'pinned' | 'new' | None
    alarm_kind: str | None = None            # T | AC | DC


def _pair_label(block: CableBlock, pair: int) -> str:
    """'Pair 3', or 'Triad 1' for triad cables (size text starting '1T')."""
    triad = (block.size_text or "").strip().upper().startswith("1T")
    return f"{'Triad' if triad else 'Pair'} {pair}"


class CabinetGrid:
    """One marshalling cabinet. Cells are keyed by (cioc 1-4, baseplate 1-8, channel 1-12)."""

    def __init__(self, cab: CabinetCfg, rules: RulesCfg) -> None:
        self.cab = cab
        self.rules = rules
        self.cells: dict[tuple[int, int, int], Cell] = {}
        self.placements: dict[str, tuple[CableBlock, int, int]] = {}   # cable key -> (block, cioc, start)
        self.occ: dict[int, bytearray] = {c: bytearray(SLOTS_PER_CIOC) for c in range(1, CIOCS_PER_CAB + 1)}

    # --- geometry -------------------------------------------------------------------
    @staticmethod
    def pos_to_bp_ch(pos: int) -> tuple[int, int]:
        return pos // SLOTS_PER_BP + 1, pos % SLOTS_PER_BP + 1

    def end_reserve_start(self) -> int:
        """First position of CIOC 4 that belongs to the empty end reserve."""
        return (BPS_PER_CIOC - self.rules.end_reserve_bps) * SLOTS_PER_BP

    def is_alarm_pos(self, cioc: int, pos: int) -> bool:
        return cioc == ALARM_CIOC and pos < ALARM_SLOTS

    def is_end_reserved(self, cioc: int, pos: int) -> bool:
        return (self.rules.end_reserve_bps > 0 and cioc == CIOCS_PER_CAB and pos >= self.end_reserve_start())

    # --- derived facts ----------------------------------------------------------------
    def cioc_family(self, cioc: int) -> str | None:
        """'A' / 'B' if an A/B cable sits in this CIOC, else None."""
        found = {blk.family for blk, c, _ in self.placements.values() if c == cioc and blk.family}
        if len(found) == 1:
            return next(iter(found))
        return None if not found else "A"   # both present would be a bug; the verifier reports it

    def cioc_groups(self, cioc: int) -> set[int]:
        return {blk.group_id for blk, c, _ in self.placements.values() if c == cioc}

    # --- searching and placing ----------------------------------------------------------
    def find_run(self, block: CableBlock, cioc: int, allow_reserved: bool = False) -> int | None:
        """Lowest aligned start position where `block` fits entirely, or None."""
        length = block.length
        step = 6 if length == 6 else SLOTS_PER_BP
        low = ALARM_SLOTS if cioc == ALARM_CIOC else 0
        high = SLOTS_PER_CIOC
        if cioc == CIOCS_PER_CAB and not allow_reserved and self.rules.end_reserve_bps > 0:
            high = self.end_reserve_start()
        first = -(-low // step) * step
        occupancy = self.occ[cioc]
        for start in range(first, high - length + 1, step):
            if not any(occupancy[start:start + length]):
                return start
        return None

    def place_block(self, block: CableBlock, cioc: int, start: int, origin: str | None = None) -> None:
        """Put a whole cable block at `start` of `cioc`. Raises ValueError if it does not fit."""
        end = start + block.length
        if not (1 <= cioc <= CIOCS_PER_CAB) or start < 0 or end > SLOTS_PER_CIOC:
            raise ValueError("block outside the CIOC")
        if cioc == ALARM_CIOC and start < ALARM_SLOTS:
            raise ValueError("baseplate 1 of CIOC 1 is reserved for cabinet alarms")
        if any(self.occ[cioc][start:end]):
            raise ValueError("slots already in use")
        if block.key in self.placements:
            raise ValueError("cable already placed")
        self.occ[cioc][start:end] = b"\x01" * block.length
        for pair in range(1, block.declared_pairs + 1):
            bp, ch = self.pos_to_bp_ch(start + pair - 1)
            sig = block.signals.get(pair)
            if sig is not None:
                cell = Cell(STATUS_FIELD, sig, block.cable_no, block.key, pair,
                            sig.pair_text or _pair_label(block, pair), block.size_text, sig.io_type, origin=origin)
            else:   # a wired pair with no signal yet: reserved (may become a Wired Spare later)
                cell = Cell(STATUS_SLOT, None, block.cable_no, block.key, pair,
                            _pair_label(block, pair), block.size_text, origin=origin)
            self.cells[(cioc, bp, ch)] = cell
        self.placements[block.key] = (block, cioc, start)

    def remove_block(self, cable_key: str) -> None:
        """Take a placed cable out again (used when a whole group is retried elsewhere)."""
        if cable_key not in self.placements:
            return
        block, cioc, start = self.placements.pop(cable_key)
        self.occ[cioc][start:start + block.length] = bytes(block.length)
        for pos in range(start, start + block.length):
            bp, ch = self.pos_to_bp_ch(pos)
            self.cells.pop((cioc, bp, ch), None)

    def place_alarm(self, sig: Signal, ch: int, kind: str) -> None:
        """Put a cabinet alarm on channel `ch` of CIOC 1, baseplate 1."""
        if not 1 <= ch <= ALARM_SLOTS:
            raise ValueError("alarm channel out of range")
        cable_key = match_key(sig.cable_no)
        self.cells[(ALARM_CIOC, 1, ch)] = Cell(
            STATUS_ALARM, sig, sig.cable_no, cable_key, sig.pair_no, sig.pair_text, sig.cable_size,
            sig.io_type, alarm_kind=kind)
        self.occ[ALARM_CIOC][ch - 1] = 1

    # --- counting -----------------------------------------------------------------------
    def used_channels(self) -> int:
        """Channels taken by field cables (the alarm baseplate does not count)."""
        total = sum(sum(o) for o in self.occ.values())
        return total - sum(self.occ[ALARM_CIOC][:ALARM_SLOTS])

    def free_non_reserved(self) -> int:
        """Free channels outside the alarm baseplate and the end reserve."""
        free = 0
        for cioc, occupancy in self.occ.items():
            for pos in range(SLOTS_PER_CIOC):
                if (not occupancy[pos] and not self.is_alarm_pos(cioc, pos)
                        and not self.is_end_reserved(cioc, pos)):
                    free += 1
        return free

    def has_content(self) -> bool:
        return bool(self.cells) or bool(self.placements)

    def clone(self) -> "CabinetGrid":
        """Independent copy (cells are copied, blocks and signals are shared read-only)."""
        other = CabinetGrid(self.cab, self.rules)
        other.cells = {k: replace(v) for k, v in self.cells.items()}
        other.placements = dict(self.placements)
        other.occ = {c: bytearray(o) for c, o in self.occ.items()}
        return other

    def assign_profiles(self, log: TQLog | None = None) -> None:
        """Work out the hardware profile of every Field cell that has none yet."""
        for key in sorted(self.cells):
            cell = self.cells[key]
            if cell.status == STATUS_FIELD and cell.signal is not None and cell.profile is None:
                cell.profile = profile_for(cell.signal, self.rules, log)
