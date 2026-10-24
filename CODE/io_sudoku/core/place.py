"""The Sudoku solver: put every cable block (and alarm) into a cabinet slot.

Everything here is deterministic: no randomness, every sort has a full tie-break key.

Pass 0  ALARMS      cabinet alarms go on CIOC 1 / baseplate 1 of their cabinet.
Pass 1  CABINETS    each logic group (cables that share a Logic Number) is assigned, as a
                    whole, to ONE cabinet of its technical room: the one with the most
                    remaining capacity (worst-fit decreasing keeps cabinets balanced).
Pass 2  SLOTS       inside each cabinet cables are placed in the order
                        pinned -> A-family -> B-family -> neutral, largest first,
                    each into the lowest aligned free run of the best CIOC.
                    A and B cables NEVER share a CIOC (hard rule, derived not stored).
LADDER  anything that did not fit is retried in a fixed order, always logging a TQ:
        R1 another existing cabinet of the room
        R2 a brand-new cabinet                           (CABINET-AUTO-ADDED)
        R3 split the logic group across cabinets         (AFFINITY-SPLIT)
        R4 use the empty end-of-cabinet reserve          (FUTURE-SPACE-MISS, an error)
        R5 give up on that cable                         (CAPACITY-OVERFLOW)
Hard rules (cable contiguity/alignment, alarm baseplate, A/B separation, 384 slots) are
NEVER relaxed - only our own soft preferences are.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from io_sudoku.core.cables import CableBlock
from io_sudoku.core.config import CabinetCfg, Config
from io_sudoku.core.constants import ALARM_SLOTS, CIOCS_PER_CAB
from io_sudoku.core.grid import CabinetGrid
from io_sudoku.core.models import Signal
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQLog

KIND_ORDER = {"T": 0, "AC": 1, "DC": 2}
_PREFERRED = {"A": ((1, False), (2, False), (3, True), (4, True)),
              "B": ((3, False), (4, False), (1, True), (2, True))}
_PREF_TEXT = {"A": "1-2", "B": "3-4"}
_FAMILY_RANK = {"A": 0, "B": 1, None: 2}


@dataclass
class PlanResult:
    grids: dict[str, CabinetGrid] = field(default_factory=dict)   # marshalling cabinet -> grid
    unplaced: list[CableBlock] = field(default_factory=list)
    alarms_unplaced: list[Signal] = field(default_factory=list)
    traces: dict[str, list[str]] = field(default_factory=dict)    # why-here sentences (cable key / tag key)


# ------------------------------------------------------------------------------ helpers
def _note(traces: dict[str, list[str]], key: str, line: str) -> None:
    traces.setdefault(key, []).append(line)


def _grid(grids: dict[str, CabinetGrid], cfg: Config, cab: CabinetCfg) -> CabinetGrid:
    if cab.marshalling not in grids:
        grids[cab.marshalling] = CabinetGrid(cab, cfg.rules)
    return grids[cab.marshalling]


def alarm_kind(tag: str | None) -> str | None:
    """'T' (temperature), 'AC' or 'DC' from the tag suffix ('...-01001-AC'), else None."""
    suffix = str(tag or "").strip().rsplit("-", 1)[-1].strip().upper()
    return suffix if suffix in KIND_ORDER else None


def place_alarms(alarms: list[Signal], cfg: Config, grids: dict[str, CabinetGrid], log: TQLog,
                 traces: dict[str, list[str]] | None = None) -> list[Signal]:
    """Put cabinet alarms on CIOC 1 / baseplate 1. Returns the alarms that could not be placed."""
    traces = traces if traces is not None else {}
    unplaced: list[Signal] = []
    per_cab: dict[str, list[tuple[tuple, Signal, str]]] = defaultdict(list)
    for alarm in sorted(alarms, key=lambda a: (a.row_ref, a.tag)):
        cab = cfg.cabinet_for_equipment(alarm.equipment)
        if cab is None:
            log.add("NO-CABINET-FOR-ALARM", alarm.tag)
            unplaced.append(alarm)
            continue
        kind = alarm_kind(alarm.tag)
        if kind is None:
            log.add("ALARM-UNKNOWN-KIND", alarm.tag)
            unplaced.append(alarm)
            continue
        own = 0 if match_key(alarm.equipment) == match_key(cab.marshalling) else 1
        per_cab[cab.marshalling].append(((own, KIND_ORDER[kind], alarm.key), alarm, kind))
    for cab in cfg.cabinets:
        entries = sorted(per_cab.get(cab.marshalling, []), key=lambda e: e[0])
        if not entries:
            continue
        grid = _grid(grids, cfg, cab)
        for index, (_key, alarm, kind) in enumerate(entries):
            if index >= ALARM_SLOTS:
                if not log.has_once("ALARM-OVERFLOW", cab.marshalling):
                    log.add("ALARM-OVERFLOW", cab.marshalling)
                unplaced.append(alarm)
                continue
            grid.place_alarm(alarm, index + 1, kind)
            _note(traces, alarm.key, f"Cabinet alarm {kind}: fixed to CIOC 1, baseplate 1, channel {index + 1} of {cab.marshalling}")
    return unplaced


def cioc_order(block: CableBlock, grid: CabinetGrid) -> list[tuple[int, bool]]:
    """CIOCs to try for a block, best first, as (cioc, relaxed-preference) pairs.

    A-family tries CIOC 1,2 then 3,4; B-family tries 3,4 then 1,2 - but a CIOC that already
    holds the OTHER family is never offered (the hard A/B rule).  Neutral cables prefer a
    CIOC that already holds their logic group, then the lowest CIOC.
    """
    if block.family in _PREFERRED:
        return [(c, relaxed) for c, relaxed in _PREFERRED[block.family]
                if grid.cioc_family(c) in (None, block.family)]
    cioces = list(range(1, CIOCS_PER_CAB + 1))
    same_group = [c for c in cioces if block.group_id in grid.cioc_groups(c)]
    return [(c, False) for c in same_group + [c for c in cioces if c not in same_group]]


def try_place(block: CableBlock, grid: CabinetGrid, log: TQLog | None, traces: dict[str, list[str]],
              allow_reserved: bool = False, origin: str | None = None) -> bool:
    """Place the block in the first CIOC that has a fitting aligned run. False if none does."""
    for cioc, relaxed in cioc_order(block, grid):
        start = grid.find_run(block, cioc, allow_reserved)
        if start is None:
            continue
        together = block.group_id in grid.cioc_groups(cioc)
        grid.place_block(block, cioc, start, origin)
        bp, ch = grid.pos_to_bp_ch(start)
        if block.family:
            _note(traces, block.key, f"{block.family}-family cable -> CIOC {cioc} (preferred CIOCs {_PREF_TEXT[block.family]})")
        else:
            _note(traces, block.key, f"Neutral cable -> CIOC {cioc} ("
                  + (f"keeps group {block.group_id} together)" if together else "first CIOC with room)"))
        _note(traces, block.key, f"Placed at baseplate {bp}, channel {ch} (aligned start {start})")
        if relaxed and log is not None and not log.has_once("SEGREGATION-PREFERENCE-RELAXED", block.cable_no):
            log.add("SEGREGATION-PREFERENCE-RELAXED", block.cable_no)
        return True
    return False


def family_fits(cioc_family: str | None, block_family: str | None) -> bool:
    """May a cable of `block_family` go into a CIOC currently holding `cioc_family`?

    Neutral cables (no family) fit anywhere; an A or B cable fits only an empty CIOC or one
    that already holds its own family."""
    return block_family is None or cioc_family in (None, block_family)


def _sorted_blocks(blocks: list[CableBlock], pinned: set[str]) -> list[CableBlock]:
    return sorted(blocks, key=lambda b: (0 if b.key in pinned else 1, _FAMILY_RANK.get(b.family, 2),
                                         b.group_id, -b.length, b.key))


def _try_unit(unit: list[CableBlock], grid: CabinetGrid, log: TQLog | None, traces: dict[str, list[str]],
              allow_reserved: bool = False) -> bool:
    return all(try_place(b, grid, log, traces, allow_reserved) for b in _sorted_blocks(unit, set()))


def _merge_traces(into: dict[str, list[str]], scratch: dict[str, list[str]]) -> None:
    for key, lines in scratch.items():
        into.setdefault(key, []).extend(lines)


# --------------------------------------------------------------------------- the planner
def plan_and_place(blocks: list[CableBlock], alarms: list[Signal], cfg: Config, log: TQLog,
                   prebuilt: dict[str, CabinetGrid] | None = None,
                   pins: dict[str, tuple[str, int]] | None = None,
                   group_cabinet_hint: dict[int, str] | None = None,
                   check_alarms: bool = True, traces: dict[str, list[str]] | None = None) -> PlanResult:
    """Place alarms and cable blocks. Never raises for data problems (they become TQs).

    `prebuilt` grids already hold cables (revisions keep their old positions); `traces`
    may be pre-filled with sentences for those cables."""
    rules = cfg.rules
    grids: dict[str, CabinetGrid] = dict(prebuilt) if prebuilt else {}
    traces = traces if traces is not None else {}
    pin_map = {(match_key(k) or str(k)): v for k, v in (pins or {}).items()}
    hints = dict(group_cabinet_hint or {})
    result = PlanResult(grids=grids, traces=traces)

    # ---- Pass 0: alarms -----------------------------------------------------------------
    result.alarms_unplaced = place_alarms(alarms, cfg, grids, log, traces)

    # ---- bookkeeping --------------------------------------------------------------------
    for block in blocks:
        shared = f" (shared logic {', '.join(block.logic_nos)})" if block.logic_nos else ""
        _note(traces, block.key, f"Cable {block.cable_no} ({block.declared_pairs} pairs) is in logic group {block.group_id}{shared}")

    groups: dict[int, list[CableBlock]] = defaultdict(list)
    gid_of: dict[str, int] = {}                       # cable key -> effective group id
    for index, block in enumerate(blocks):
        gid_of[block.key] = block.group_id if block.group_id >= 0 else 10_000_000 + index   # ungrouped: alone
        groups[gid_of[block.key]].append(block)

    pending: dict[str, int] = defaultdict(int)          # channels assigned in pass 1, not yet placed
    assigned: dict[str, CabinetCfg] = {}                # cable key -> cabinet
    split_groups: set[int] = set()
    effective_pins: dict[str, tuple[str, int]] = {}

    def remaining(cab: CabinetCfg) -> int:
        grid = grids.get(cab.marshalling)
        return rules.usable_channels() - (grid.used_channels() if grid else 0) - pending[cab.marshalling]

    def make_new_cabinet(room: str) -> CabinetCfg | None:
        if not rules.auto_expand:
            return None
        cab = cfg.new_cabinet_for_room(room)
        if cab is not None:
            _grid(grids, cfg, cab)
            log.add("CABINET-AUTO-ADDED", cab.marshalling)
        return cab

    def choose(length: int, room: str) -> tuple[CabinetCfg | None, str]:
        """Best cabinet for `length` channels in `room`: most remaining space that fits."""
        position = {c.marshalling: i for i, c in enumerate(cfg.cabinets)}
        cands = sorted(cfg.cabinets_in_room(room), key=lambda c: (-remaining(c), position[c.marshalling]))
        fit = next((c for c in cands if remaining(c) >= length), None)
        if fit is not None:
            other = next((remaining(c) for c in cands if c is not fit), None)
            return fit, f"most remaining capacity ({remaining(fit)} channels vs {other if other is not None else 'no other cabinet'})"
        new = make_new_cabinet(room)
        if new is not None:
            return new, "existing cabinets are full, so a new cabinet was added"
        if cands:
            return cands[0], "no cabinet has enough room; the one with the most space was tried"
        return None, ""

    # ---- Pass 1: groups -> cabinets -----------------------------------------------------
    by_room: dict[str, list[int]] = defaultdict(list)
    for gid, members in groups.items():
        by_room[match_key(members[0].tech_room) or ""].append(gid)
    for room_key in sorted(by_room):
        gids = sorted(by_room[room_key], key=lambda g: (-sum(b.length for b in groups[g]), g))
        for gid in gids:
            members = sorted(groups[gid], key=lambda b: b.key)
            room = members[0].tech_room or room_key
            total = sum(b.length for b in members)
            if not cfg.cabinets_in_room(room):
                log.add("NO-CABINET-FOR-ROOM", room)
                result.unplaced.extend(members)
                continue
            target: CabinetCfg | None = None
            why = ""
            pinned = [b for b in members if b.key in pin_map]
            if pinned:
                first = min(pinned, key=lambda b: b.key)
                candidate = cfg.cabinet_by_marshalling(pin_map[first.key][0])
                if candidate is not None and match_key(candidate.tech_room) == room_key:
                    target, why = candidate, "kept with a cable pinned by the engineer"
                for b in pinned:
                    ok = target is not None and match_key(pin_map[b.key][0]) == match_key(target.marshalling)
                    if ok:
                        effective_pins[b.key] = pin_map[b.key]
                    else:
                        log.add("PIN-UNSATISFIABLE", b.cable_no)
            if target is None and gid in hints:
                candidate = cfg.cabinet_by_marshalling(hints[gid])
                if candidate is not None and match_key(candidate.tech_room) == room_key:
                    target, why = candidate, "kept with its earlier cabinet"
            if target is None and total > rules.usable_channels():
                split_groups.add(gid)
                log.add("AFFINITY-SPLIT", min(members, key=lambda b: b.key).cable_no)
                for block in sorted(members, key=lambda b: (-b.length, b.key)):
                    cab, reason = choose(block.length, room)
                    if cab is None:
                        result.unplaced.append(block)
                        continue
                    assigned[block.key] = cab
                    pending[cab.marshalling] += block.length
                    _note(traces, block.key, f"Group {gid} is larger than one cabinet, so this cable was assigned alone -> {cab.marshalling}: {reason}")
                continue
            if target is None:
                target, why = choose(total, room)
            if target is None:
                result.unplaced.extend(members)
                continue
            for block in members:
                assigned[block.key] = target
                _note(traces, block.key, f"Group {gid} -> {target.marshalling}: {why}")
            pending[target.marshalling] += total

    # ---- Pass 2: place inside each cabinet ------------------------------------------------
    retry: list[tuple[list[CableBlock], str]] = []        # (units to retry, cabinet that failed them)
    for cab in list(cfg.cabinets):
        mine = [b for b in blocks if b.key in assigned and assigned[b.key].marshalling == cab.marshalling]
        if not mine:
            continue
        mine_keys = {b.key for b in mine}
        grid = _grid(grids, cfg, cab)
        failed_groups: set[int] = set()
        placed_by_group: dict[int, list[str]] = defaultdict(list)
        for block in _sorted_blocks(mine, set(effective_pins)):
            gid = gid_of[block.key]
            if gid in failed_groups:
                continue
            ok = False
            pin = effective_pins.get(block.key)
            if pin is not None:
                cioc = pin[1]
                if 1 <= cioc <= CIOCS_PER_CAB and family_fits(grid.cioc_family(cioc), block.family):
                    start = grid.find_run(block, cioc)
                    if start is not None:
                        grid.place_block(block, cioc, start)
                        bp, ch = grid.pos_to_bp_ch(start)
                        _note(traces, block.key, f"Pinned by engineer to {cab.marshalling} CIOC {cioc}")
                        _note(traces, block.key, f"Placed at baseplate {bp}, channel {ch} (aligned start {start})")
                        ok = True
                if not ok:
                    log.add("PIN-UNSATISFIABLE", block.cable_no)
            if not ok:
                ok = try_place(block, grid, log, traces)
            if ok:
                placed_by_group[gid].append(block.key)
            elif gid in split_groups:
                retry.append(([block], cab.marshalling))     # a split group's cables move one by one
            else:
                failed_groups.add(gid)                       # the whole group moves together
                for key in placed_by_group.pop(gid, []):
                    grid.remove_block(key)
                retry.append(([b for b in groups[gid] if b.key in mine_keys], cab.marshalling))
        pending[cab.marshalling] = 0

    # ---- Retry ladder ----------------------------------------------------------------------
    retry.sort(key=lambda item: (-sum(b.length for b in item[0]), min(gid_of[b.key] for b in item[0]),
                                 min(b.key for b in item[0])))
    split_logged: set[int] = set()
    for unit, failed_in in retry:
        _run_ladder(unit, failed_in, cfg, log, grids, traces, result, make_new_cabinet, split_logged)

    # ---- alarms missing in the MDB -----------------------------------------------------------
    if check_alarms:
        present = {match_key(a.equipment) for a in alarms}
        for cab in cfg.cabinets:
            grid = grids.get(cab.marshalling)
            if grid is None or not grid.has_content() or cab.inferred:
                continue
            for name in (cab.marshalling, cab.system):
                if match_key(name) not in present:
                    log.add("ALARMS-MISSING-FOR-CABINET", name)

    # ---- finish ----------------------------------------------------------------------------------
    result.grids = {c.marshalling: grids[c.marshalling] for c in cfg.cabinets
                    if c.marshalling in grids and grids[c.marshalling].has_content()}
    for grid in result.grids.values():
        grid.assign_profiles(log)
        for block, _cioc, _start in grid.placements.values():
            lines = traces.get(block.key, [])
            for sig in block.signals.values():
                traces[sig.key] = lines
    return result


def _run_ladder(unit: list[CableBlock], failed_in: str, cfg: Config, log: TQLog, grids: dict[str, CabinetGrid],
                traces: dict[str, list[str]], result: PlanResult, make_new_cabinet, split_logged: set[int]) -> None:
    """Retry one failed unit (a whole group, or one block of a split group) rung by rung."""
    room = unit[0].tech_room or ""
    room_cabs = lambda: cfg.cabinets_in_room(room)                      # noqa: E731 (list grows when cabinets are added)
    already = {failed_in} | {name for name, g in grids.items() if any(b.key in g.placements for b in unit)}
    ids = ", ".join(sorted(b.cable_no for b in unit))

    def commit(trial: CabinetGrid, scratch_log: TQLog, scratch_traces: dict[str, list[str]], cab: CabinetCfg, note: str) -> None:
        grids[cab.marshalling] = trial
        log.extend(scratch_log.items())
        _merge_traces(traces, scratch_traces)
        for b in unit:
            _note(traces, b.key, note)

    # R1: another existing cabinet of the room (whole unit, atomically on a copy)
    position = {c.marshalling: i for i, c in enumerate(cfg.cabinets)}
    others = sorted((c for c in room_cabs() if c.marshalling not in already),
                    key=lambda c: (-(_grid(grids, cfg, c).free_non_reserved()), position[c.marshalling]))
    for cab in others:
        trial, s_log, s_tr = _grid(grids, cfg, cab).clone(), TQLog(), {}
        if _try_unit(unit, trial, s_log, s_tr):
            commit(trial, s_log, s_tr, cab, f"Ladder step R1: did not fit its first cabinet, moved to {cab.marshalling}")
            return

    # R2: a brand-new cabinet
    new = make_new_cabinet(room)
    if new is not None:
        trial, s_log, s_tr = _grid(grids, cfg, new).clone(), TQLog(), {}
        if _try_unit(unit, trial, s_log, s_tr):
            commit(trial, s_log, s_tr, new, f"Ladder step R2: placed in the new cabinet {new.marshalling}")
            return
        cfg.cabinets.pop()                                            # unused: take it back
        grids.pop(new.marshalling, None)
        _drop_cabinet_tq(log, new.marshalling)

    # R3: split the group across cabinets (only meaningful for more than one cable)
    leftover = list(unit)
    if len(unit) > 1:
        leftover = []
        for block in _sorted_blocks(unit, set()):
            done = False
            for cab in list(room_cabs()):
                if try_place(block, _grid(grids, cfg, cab), log, traces):
                    _note(traces, block.key, f"Ladder step R3: the logic group was split; this cable went to {cab.marshalling}")
                    done = True
                    break
            if not done:
                extra = make_new_cabinet(room)
                if extra is not None:
                    if try_place(block, _grid(grids, cfg, extra), log, traces):
                        _note(traces, block.key, f"Ladder step R3: the logic group was split; this cable went to the new cabinet {extra.marshalling}")
                        done = True
                    else:
                        cfg.cabinets.pop()
                        grids.pop(extra.marshalling, None)
                        _drop_cabinet_tq(log, extra.marshalling)
            if not done:
                leftover.append(block)
        homes = {name for name, g in grids.items() if any(b.key in g.placements for b in unit)}
        gid = unit[0].group_id
        if len(homes) > 1 and gid not in split_logged:
            split_logged.add(gid)
            log.add("AFFINITY-SPLIT", min(unit, key=lambda b: b.key).cable_no)

    # R4: use the empty end-of-cabinet reserve (breaks the 'empty baseplates at the end' goal)
    still: list[CableBlock] = []
    for block in leftover:
        done = False
        for cab in list(room_cabs()):
            if try_place(block, _grid(grids, cfg, cab), log, traces, allow_reserved=True):
                if not log.has_once("FUTURE-SPACE-MISS", cab.marshalling):
                    log.add("FUTURE-SPACE-MISS", cab.marshalling)
                _note(traces, block.key, f"Ladder step R4: only the end reserve of {cab.marshalling} had room")
                done = True
                break
        if not done:
            still.append(block)

    # R5: give up on these cables
    for block in still:
        log.add("CAPACITY-OVERFLOW", block.cable_no)
        result.unplaced.append(block)
        _note(traces, block.key, f"Ladder step R5: no cabinet could hold cable {block.cable_no}; it is listed as unplaced ({ids})")


def _drop_cabinet_tq(log: TQLog, marshalling: str) -> None:
    """Remove the CABINET-AUTO-ADDED TQ of a cabinet that was taken back again."""
    items = [t for t in log.items() if not (t.tq_id == "CABINET-AUTO-ADDED" and t.ref == marshalling)]
    log._items = items          # noqa: SLF001 - deliberate: TQLog has no remove(), and this is its sole caller
