"""Small factories used by many tests (hand-built signals, cable blocks)."""
from __future__ import annotations

from typing import Any

from io_sudoku.core.models import Signal
from io_sudoku.core.textnorm import match_key


def make_signal(**overrides: Any) -> Signal:
    """A valid, boring signal: AIR, 2-wire, room PIB-30, cable C-1 (12 pairs), pair 1."""
    data: dict[str, Any] = dict(
        row_ref=2, sheet="MDB-1", tag="T-1", key="t-1",
        io_type="AIR", io_type2=None, signal_type="4-20 ma HART", signal_level="2-Wire",
        execution="NON-IS", ext_power=None, segregation=None, logic_no=None,
        tech_room="PIB-30", operating_area="OA-11", risk_area="RA 320-01", unit=320,
        location="L", equipment=None, cable_no="C-1",
        cable_size="12PX1MM2/FR/IND&OS/ARM/NIS", pair_no=1, pair_text="Pair 1",
        service="TEST SERVICE", instrument_type="Pressure Transmitter", instrument_code="PT",
        loop_name="T-1", old_tag=None, system2=None, status="New", is_alarm=False,
    )
    data.update(overrides)
    if "key" not in overrides:  # keep key consistent with the tag unless the test sets it
        data["key"] = match_key(data["tag"]) or ""
    if "pair_text" not in overrides and data.get("pair_no") is not None:
        data["pair_text"] = f"Pair {data['pair_no']}"
    return Signal(**data)


def make_block(cable: str, pairs, family: str | None = None, group: int = 0, room: str = "PIB-30",
               size: int | None = None, io: str = "AIR", logic: str | None = None,
               instrument: str | None = "Pressure Transmitter", code: str | None = "PT"):
    """A CableBlock for placement tests.

    `pairs` is a list of used pair numbers, or an int n meaning pairs 1..n.  The declared
    cable size is `size`, or the smallest standard size that holds the highest pair.
    """
    from io_sudoku.core.cables import CableBlock, block_length
    from io_sudoku.core.constants import STANDARD_CABLE_SIZES
    from io_sudoku.core.textnorm import match_key

    used = list(range(1, pairs + 1)) if isinstance(pairs, int) else list(pairs)
    highest = max(used) if used else 1
    declared = size or next((s for s in STANDARD_CABLE_SIZES if s >= highest), highest)
    seg = family
    signals = {}
    for p in used:
        signals[p] = make_signal(
            tag=f"{cable}-{p}", cable_no=cable, pair_no=p, io_type=io, segregation=seg, tech_room=room,
            logic_no=logic, instrument_type=instrument, instrument_code=code, row_ref=p + 1,
            cable_size=f"{declared:02d}PX1MM2/FR/IND&OS/ARM/NIS")
    return CableBlock(cable_no=cable, key=match_key(cable) or cable, declared_pairs=declared,
                      length=block_length(declared), signals=signals, family=family, tech_room=room,
                      logic_nos=(logic,) if logic else (), group_id=group,
                      size_text=f"{declared:02d}PX1MM2/FR/IND&OS/ARM/NIS")


def fixture_grids(mdb_path):
    """Run the solver stages up to and including the spare engine on the sample MDB."""
    from io_sudoku.core.cables import build_blocks, link_groups
    from io_sudoku.core.config import load_config
    from io_sudoku.core.ingest import read_mdb
    from io_sudoku.core.place import plan_and_place
    from io_sudoku.core.spares import apply_spares
    from io_sudoku.core.tq import TQLog
    from io_sudoku.core.validate import validate

    cfg, log = load_config(), TQLog()
    ing = read_mdb(mdb_path, log)
    v = validate(ing, cfg, log)
    blocks, _ = build_blocks(v.accepted, v.size_by_cable, cfg, log)
    link_groups(blocks)
    res = plan_and_place(blocks, v.alarms, cfg, log)
    lines = apply_spares(res.grids, cfg, log, res.traces)
    return cfg, log, res, lines
