"""Wired spares: exactly 10% per IO type per controller (CLAUDE_RULES 3D.3).

For every controller (= every cabinet) and every IO type:
    quota = ceil(10% x number of FIELD signals of that IO type)      (integer maths)
A wired spare is an installed, wired spare channel, so it must use a cable pair that is
ALREADY wired: we convert unused pairs of the controller's own cables.  We never invent
pairs - if there are not enough free pairs we raise SPARE-SHORTFALL and ask for more.

Which free pair is converted (best first):
  1. a pair freed by a deleted tag of the same IO type (revisions),
  2. a pair in a cable that already carries that IO type (same hardware family),
  3. then by cable name and pair number (stable, deterministic).
The new spare takes the hardware profile its cable already uses (a solenoid cable gets
high-current DOR spares), so the CHARM and terminal block always match the cable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from io_sudoku.core.catalog import default_profile_for_io
from io_sudoku.core.config import Config
from io_sudoku.core.constants import IO_TYPES, PROFILES, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED
from io_sudoku.core.grid import Cell, CabinetGrid
from io_sudoku.core.naming import dsp_tag
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQLog


def quota(field_count: int, pct: int = 10) -> int:
    """ceil(pct% of field_count) using only integers (42 -> 5, 5 -> 1, 0 -> 0)."""
    return -(-max(0, field_count) * pct // 100)


@dataclass
class SpareLine:
    controller: str
    io_type: str
    field: int       # Field signals of this IO type on the controller
    quota: int       # wired spares required
    wired: int       # wired spares now present
    shortfall: int   # how many are missing (0 = compliant)
    excess: int      # how many more than the quota (possible when spares are kept from a revision)


def _dominant_profile(profiles: Counter[str]) -> str | None:
    """Most common profile; ties go to the earlier entry of PROFILES."""
    if not profiles:
        return None
    best = max(profiles.values())
    return next(p for p in PROFILES if profiles.get(p) == best)


def apply_spares(grids: dict[str, CabinetGrid], cfg: Config, log: TQLog,
                 traces: dict[str, list[str]] | None = None) -> list[SpareLine]:
    """Convert unused wired pairs into Wired Spares until every quota is met. Mutates the grids."""
    lines: list[SpareLine] = []
    for grid in grids.values():
        lines.extend(_spares_for_cabinet(grid, cfg, log, traces))
    return sorted(lines, key=lambda line: (line.controller, IO_TYPES.index(line.io_type)))


def _spares_for_cabinet(grid: CabinetGrid, cfg: Config, log: TQLog,
                        traces: dict[str, list[str]] | None) -> list[SpareLine]:
    cab, pct = grid.cab, cfg.rules.spare_pct
    field = Counter()
    wired = Counter()
    cable_ios: dict[str, set[str]] = defaultdict(set)
    cable_profiles: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    cable_profile_set: dict[str, set[str]] = defaultdict(set)
    for cell in grid.cells.values():
        if cell.status == STATUS_FIELD and cell.signal is not None and cell.signal.io_type:
            io = cell.signal.io_type
            field[io] += 1
            if cell.cable_key:
                cable_ios[cell.cable_key].add(io)
                if cell.profile:
                    cable_profiles[(cell.cable_key, io)][cell.profile] += 1
                    cable_profile_set[cell.cable_key].add(cell.profile)
        elif cell.status == STATUS_WIRED and cell.io_type:
            wired[cell.io_type] += 1
            if cell.cable_key and cell.profile:
                cable_profile_set[cell.cable_key].add(cell.profile)

    start_wired = dict(wired)
    deficit = {io: max(0, quota(field[io], pct) - wired[io]) for io in IO_TYPES}

    # Free wired pairs outside the alarm baseplate and the empty end reserve.
    candidates: list[tuple[tuple[int, int, int], Cell]] = []
    for key in sorted(grid.cells):
        cell = grid.cells[key]
        cioc, bp, ch = key
        pos = (bp - 1) * 12 + ch - 1
        if (cell.status == STATUS_SLOT and cell.pair_no is not None and cell.cable_key
                and not grid.is_alarm_pos(cioc, pos) and not grid.is_end_reserved(cioc, pos)):
            candidates.append((key, cell))

    def rank(io: str, item: tuple[tuple[int, int, int], Cell]) -> tuple:
        key, cell = item
        return (0 if cell.former_io == io else 1,
                0 if io in cable_ios.get(cell.cable_key or "", set()) else 1,
                cell.cable_key or "", cell.pair_no or 0, key)

    while any(d > 0 for d in deficit.values()):
        io = max(IO_TYPES, key=lambda i: (deficit[i], -IO_TYPES.index(i)))
        if not candidates:
            break
        key, cell = min(candidates, key=lambda item: rank(io, item))
        candidates.remove((key, cell))
        profile = (_dominant_profile(cable_profiles.get((cell.cable_key or "", io), Counter()))
                   or ("DOR_T02" if io == "DOR" and "DOR_T02" in cable_profile_set.get(cell.cable_key or "", set())
                       else default_profile_for_io(io)))
        cell.status, cell.io_type, cell.profile = STATUS_WIRED, io, profile
        cell.dsp = dsp_tag(cab, key[0], key[1], key[2])
        wired[io] += 1
        deficit[io] -= 1
        if traces is not None:
            why = ("a pair freed by a deleted " + io + " tag" if cell.former_io == io
                   else f"the cable already carries {io}" if io in cable_ios.get(cell.cable_key or "", set())
                   else "the first free pair")
            traces.setdefault(match_key(cell.dsp) or cell.dsp, []).append(
                f"Wired spare {io}: quota {quota(field[io], pct)}, had {start_wired.get(io, 0)}, "
                f"converted {cell.cable_no} pair {cell.pair_no} ({why})")

    result: list[SpareLine] = []
    for io in IO_TYPES:
        need = quota(field[io], pct)
        short = max(0, need - wired[io])
        if short:
            log.add("SPARE-SHORTFALL", f"{cab.controller}/{io}",
                    f"{cab.controller} needs {need} wired {io} spares but only {wired[io]} could be wired "
                    f"from unused pairs. Can spare pairs or a spare cable be added?")
        result.append(SpareLine(cab.controller, io, field[io], need, wired[io], short, max(0, wired[io] - need)))
    return result
