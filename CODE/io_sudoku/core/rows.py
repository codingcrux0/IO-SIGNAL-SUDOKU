"""Turn the solved cabinet grids into rows of the 76-column IO Allocation template.

Every used cabinet emits ALL 384 slots (one row each), ordered by cabinet, CIOC,
baseplate, channel; "Sr. No." counts 1..N over the whole file.  The four Tag Status
values are filled exactly as the official sample does:

  Field          real signal: data from the MDB, hardware from the catalogue profile
  Cabinet Alarm  diagnostic alarm on the cabinet-alarm baseplate (CIOC 1 / baseplate 1 by default)
  Wired Spare    DSP tag, SPARE <type> text, hardware of its cable, Location/Unit
                 inherited from the cable's signals
  Spare Slot     SE6103 protection cover; keeps the cable/pair when one is reserved

Columns we have no data for stay '-'.  Numbers are written as integers.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from io_sudoku.core.allocio import CANONICAL_COLUMNS
from io_sudoku.core.catalog import Hardware, alarm_hardware, hardware, profile_for, spare_slot_hardware
from io_sudoku.core.config import CabinetCfg, Config
from io_sudoku.core.constants import (
    BPS_PER_CIOC, CIOCS_PER_CAB, SLOTS_PER_BP, SPARE_DESC, STATUS_ALARM, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED,
)
from io_sudoku.core.grid import CabinetGrid, Cell
from io_sudoku.core.models import Signal
from io_sudoku.core.naming import baseplate_name, charm_no, cioc_name, dst_name, side, viz_name
from io_sudoku.core.tq import TQLog

_SECTION_RE = re.compile(r"-\s*(\d{5})")


def derive_section(tag: str | None, unit: int | None) -> str:
    """'Section / Sub Unit' from the tag number: 20202 -> 200, 42049 -> 420, 8xxxx -> 800.

    It is informational (no hard rule) and follows the pattern seen in the sample:
    first digit 8 -> '800', otherwise the first two digits plus '0'.  Logistics units
    (WBS 440 and 500) are 'LOGISTIC'.  Unknown -> '-'.
    """
    if unit in (440, 500):
        return "LOGISTIC"
    match = _SECTION_RE.search(tag or "")
    if not match:
        return "-"
    digits = match.group(1)
    return "800" if digits[0] == "8" else digits[:2] + "0"


def _dominant(items: list[tuple[int, Any]]) -> Any:
    """Most common non-empty value; ties go to the value on the lowest pair number."""
    values = [(pair, v) for pair, v in items if v not in (None, "")]
    if not values:
        return None
    counts = Counter(v for _, v in values)
    best = max(counts.values())
    return min((pair, v) for pair, v in values if counts[v] == best)[1]


def _text(value: Any) -> Any:
    return "-" if value in (None, "") else value


def _tb(value: int | None) -> Any:
    return "-" if value is None else int(value)


def _fill_hardware(row: dict[str, Any], hw: Hardware) -> None:
    row["CHARM Type"] = hw.charm_type
    row["Charm Description"] = hw.charm_desc
    row["CHARM TB Part No"] = hw.tb_part
    row["CHARM TB Description"] = hw.tb_desc
    row["CHARM TB1"], row["CHARM TB2"], row["CHARM TB3"] = _tb(hw.tb1), _tb(hw.tb2), _tb(hw.tb3)
    row["HW Loop Typical"] = hw.hw_loop


class _CabinetFacts:
    """Facts about one cabinet that rows without their own data borrow from."""

    def __init__(self, grid: CabinetGrid) -> None:
        cab = grid.cab
        fields = [(k, c) for k, c in sorted(grid.cells.items()) if c.status == STATUS_FIELD and c.signal]
        signals = [c.signal for _, c in fields if c.signal]
        self.operating_area = self._most_common([s.operating_area for s in signals])
        self.risk_area = self._most_common([s.risk_area for s in signals])
        self.unit = self._most_common([s.unit for s in signals]) or cab.unit
        self.by_cable: dict[str, list[tuple[int, Cell]]] = defaultdict(list)
        for _key, cell in sorted(grid.cells.items()):
            if cell.cable_key and cell.status in (STATUS_FIELD, STATUS_WIRED):
                self.by_cable[cell.cable_key].append((cell.pair_no or 0, cell))

    @staticmethod
    def _most_common(values: list[Any]) -> Any:
        counts = Counter(v for v in values if v not in (None, ""))
        if not counts:
            return None
        best = max(counts.values())
        return sorted((v for v, n in counts.items() if n == best), key=str)[0]

    def cable_value(self, cable_key: str | None, getter) -> Any:
        members = self.by_cable.get(cable_key or "", [])
        return _dominant([(pair, getter(c)) for pair, c in members if c.status == STATUS_FIELD and c.signal])

    def cable_has_t02(self, cable_key: str | None) -> bool:
        return any(c.profile == "DOR_T02" for _, c in self.by_cable.get(cable_key or "", []))


def build_rows(grids: dict[str, CabinetGrid], cfg: Config, log: TQLog, rev_label: str = "00") -> list[dict[str, Any]]:
    """All rows of the allocation (384 per used cabinet), in template column order."""
    rows: list[dict[str, Any]] = []
    section_missing = False
    high_current_logged: set[str] = set()
    sr_no = 0
    for cab in cfg.cabinets:
        grid = grids.get(cab.marshalling)
        if grid is None or not grid.has_content():
            continue
        facts = _CabinetFacts(grid)
        for cioc in range(1, CIOCS_PER_CAB + 1):
            for bp in range(1, BPS_PER_CIOC + 1):
                for ch in range(1, SLOTS_PER_BP + 1):
                    sr_no += 1
                    cell = grid.cells.get((cioc, bp, ch))
                    row = _row(cab, grid, facts, cell, cioc, bp, ch, sr_no, rev_label, cfg)
                    if cell is not None and cell.status == STATUS_FIELD and row["Section / Sub Unit"] == "-":
                        section_missing = True
                    if (cell is not None and cell.status == STATUS_FIELD and cell.profile == "DOR_T02"
                            and cell.cable_key and cell.cable_key not in high_current_logged):
                        high_current_logged.add(cell.cable_key)
                        log.add("HIGH-CURRENT-VERIFY", cell.cable_no or cell.cable_key)
                    rows.append(row)
    if section_missing and not log.has("SECTION-UNDERIVABLE"):
        log.add("SECTION-UNDERIVABLE", "")
    return rows


def _row(cab: CabinetCfg, grid: CabinetGrid, facts: _CabinetFacts, cell: Cell | None, cioc: int, bp: int, ch: int,
         sr_no: int, rev_label: str, cfg: Config) -> dict[str, Any]:
    row: dict[str, Any] = {c: "-" for c in CANONICAL_COLUMNS}
    sig: Signal | None = cell.signal if cell else None
    row["Sr. No."] = sr_no
    row["Revision No"] = str(rev_label)
    row["Technical Room"] = (sig.tech_room if sig and sig.tech_room else cab.tech_room)
    row["Operating Area"] = _text(sig.operating_area if sig and sig.operating_area else facts.operating_area)
    row["Risk Area"] = _text(sig.risk_area if sig and sig.risk_area else facts.risk_area)
    row["System Cabinet"] = cab.system
    row["Controller"] = cab.controller
    row["Electronic/ Marshalling Cabinet"] = cab.marshalling
    row["CIOC/CSLS Name"] = cioc_name(cab, cioc)
    row["Baseplate"] = baseplate_name(cab, cioc, bp)
    row["Channel_No"] = ch
    row["CHARM_No"] = charm_no(bp, ch)
    row["Cabinet Side (F/R)"] = side(cioc)
    row["Cabinet Name for Visualization"] = viz_name(cab, cioc)
    row["BATCH"] = cfg.rules.batch
    row["Tag Status"] = cell.status if cell else STATUS_SLOT
    if cell is not None and cell.cable_no:
        row["Field Cable No"] = cell.cable_no
        row["Field Cable Size"] = _text(cell.size_text)
        row["Field Cable Pair"] = _text(cell.pair_text)
    if cell is not None and cell.remark:
        row["Remarks"] = cell.remark

    status = cell.status if cell else STATUS_SLOT
    if status == STATUS_FIELD and cell is not None and sig is not None:
        _field(row, cell, sig, grid, cfg)
    elif status == STATUS_ALARM and cell is not None and sig is not None:
        _alarm(row, cell, sig)
    elif status == STATUS_WIRED and cell is not None:
        _wired(row, cell, facts, cab)
    else:
        _slot(row, cell, facts, cab)
    return row


def _field(row: dict[str, Any], cell: Cell, sig: Signal, grid: CabinetGrid, cfg: Config) -> None:
    profile = cell.profile or profile_for(sig, cfg.rules)
    row["Tag Name"] = sig.tag
    row["DSTName"] = dst_name(sig.tag)
    row["Service Description"] = _text(sig.service)
    row["Unit"] = sig.unit if sig.unit is not None else "-"
    row["Segregation"] = _text(sig.segregation)
    row["Location"] = _text(sig.location)
    row["IO Type"] = _text(sig.io_type)
    row["Signal Type"] = _text(sig.signal_type)
    row["Signal Level"] = _text(sig.signal_level)
    row["NON-IS / IS"] = _text(sig.execution)
    row["Equipment Name"] = _text(sig.equipment)
    row["External Power"] = _text(sig.ext_power)
    row["System 2"] = _text(sig.system2)
    row["Old Tag"] = _text(sig.old_tag)
    row["Instrument type"] = _text(sig.instrument_type)
    row["Loop Name"] = _text(sig.loop_name)
    row["Section / Sub Unit"] = derive_section(sig.tag, sig.unit)
    _fill_hardware(row, hardware(profile))


def _alarm(row: dict[str, Any], cell: Cell, sig: Signal) -> None:
    kind = cell.alarm_kind or "AC"
    on_cable = bool(cell.cable_no)
    hw = alarm_hardware(kind, on_cable)
    row["Tag Name"] = sig.tag
    row["DSTName"] = dst_name(sig.tag)
    row["Service Description"] = _text(sig.service)
    row["Unit"] = sig.unit if sig.unit is not None else "-"
    row["Segregation"] = _text(sig.segregation)
    row["Location"] = _text(sig.location)
    row["IO Type"] = "AIR" if kind == "T" else "DIR"      # fixed by the alarm kind, whatever the MDB cell says
    row["Signal Type"] = hw.signal_type
    row["Signal Level"] = hw.signal_level
    row["NON-IS / IS"] = _text(sig.execution)
    row["Equipment Name"] = _text(sig.equipment)
    row["External Power"] = _text(sig.ext_power)
    if not row["Remarks"] or row["Remarks"] == "-":
        row["Remarks"] = "-" if on_cable else "Internal Cabinet Alarm."
    _fill_hardware(row, hw)


def _wired(row: dict[str, Any], cell: Cell, facts: _CabinetFacts, cab: CabinetCfg) -> None:
    io = cell.io_type or "AIR"
    hw = hardware(cell.profile or "AIR_2W")
    unit = facts.cable_value(cell.cable_key, lambda c: c.signal.unit if c.signal else None)
    location = facts.cable_value(cell.cable_key, lambda c: c.signal.location if c.signal else None)
    execution = facts.cable_value(cell.cable_key, lambda c: c.signal.execution if c.signal else None)
    row["Tag Name"] = cell.dsp or "-"
    row["DSTName"] = dst_name(cell.dsp)
    row["Service Description"] = SPARE_DESC.get(io, "SPARE")
    row["Unit"] = unit if unit is not None else facts.unit
    row["Location"] = _text(location)
    row["IO Type"] = io
    row["Signal Type"] = hw.signal_type
    row["Signal Level"] = hw.signal_level
    row["NON-IS / IS"] = _text(execution)
    _fill_hardware(row, hw)


def _slot(row: dict[str, Any], cell: Cell | None, facts: _CabinetFacts, cab: CabinetCfg) -> None:
    cable_key = cell.cable_key if cell else None
    unit = facts.cable_value(cable_key, lambda c: c.signal.unit if c.signal else None) if cable_key else None
    row["Unit"] = unit if unit is not None else facts.unit
    row["DSTName"] = "_"
    tb = "SE4502" if cable_key and facts.cable_has_t02(cable_key) else "SE4501"
    _fill_hardware(row, spare_slot_hardware(tb))
