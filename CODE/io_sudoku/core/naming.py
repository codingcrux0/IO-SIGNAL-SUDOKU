"""Naming and numbering formulas (all verified against the official sample).

Examples in the comments come straight from Sample_IO_Allocation_VIT_v2:
  cabinet seq 4 owns CIOCs 013..016        -> P30DCIOC3201013
  baseplate 6 of CIOC 013                  -> 013-CBP-6
  wired-spare tag at CIOC 013, BP 6, ch 9  -> 3201DSP0201369
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from io_sudoku.core.constants import BPS_PER_CIOC, CIOCS_PER_CAB, SLOTS_PER_BP

if TYPE_CHECKING:  # only for type hints; avoids a circular import with config.py
    from io_sudoku.core.config import CabinetCfg


def charm_no(bp: int, ch: int) -> int:
    """CHARM_No = (Baseplate - 1) * 12 + Channel   (baseplate 6, channel 9 -> 69)."""
    return (bp - 1) * SLOTS_PER_BP + ch


def area4(area5: str) -> str:
    """Compress a 5-digit area code: first two + last two digits (32001 -> 3201)."""
    digits = re.sub(r"\D", "", str(area5))
    if len(digits) < 4:
        return digits
    return digits[:2] + digits[-2:]


def cioc_seq(cab: "CabinetCfg", cioc: int) -> int:
    """Running CIOC number of the project: cabinet 04, CIOC 1 -> 13."""
    return (cab.cabinet_seq - 1) * CIOCS_PER_CAB + cioc


def cioc_name(cab: "CabinetCfg", cioc: int) -> str:
    """e.g. P30DCIOC3201013"""
    return f"{cab.loc}DCIOC{area4(cab.area5)}{cioc_seq(cab, cioc):03d}"


def baseplate_name(cab: "CabinetCfg", cioc: int, bp: int) -> str:
    """e.g. 013-CBP-6"""
    return f"{cioc_seq(cab, cioc):03d}-CBP-{bp}"


def dsp_tag(cab: "CabinetCfg", cioc: int, bp: int, ch: int) -> str:
    """Wired-spare tag: area4 + 'DSP' + controller(2) + CIOC(3) + baseplate + channel."""
    return f"{area4(cab.area5)}DSP{cab.ctrl_seq:02d}{cioc_seq(cab, cioc):03d}{bp}{ch}"


def dst_name(tag: str | None) -> str:
    """DSTName = tag with everything except letters/digits removed, plus '_'."""
    if not tag:
        return "_"
    return re.sub(r"[^A-Za-z0-9]", "", str(tag)) + "_"


def side(cioc: int) -> str:
    """Cabinet side: CIOC 1-2 are the front (F), CIOC 3-4 the rear (R)."""
    return "F" if cioc in (1, 2) else "R"


def viz_name(cab: "CabinetCfg", cioc: int) -> str:
    """Cabinet name for visualisation, e.g. P30-DCM-32001-04(F)."""
    return f"{cab.marshalling}({side(cioc)})"


_CIOC_TAIL = re.compile(r"(\d{3})$")
_BP_TAIL = re.compile(r"-CBP-(\d+)$", re.IGNORECASE)


def parse_cioc_index(cab: "CabinetCfg", name: str | None) -> int | None:
    """Inverse of cioc_name: 'P30DCIOC3201013' in cabinet 4 -> CIOC index 1 (or None)."""
    if not name:
        return None
    match = _CIOC_TAIL.search(str(name).strip())
    if not match:
        return None
    index = int(match.group(1)) - (cab.cabinet_seq - 1) * CIOCS_PER_CAB
    return index if 1 <= index <= CIOCS_PER_CAB else None


def parse_bp(name: str | None) -> int | None:
    """Inverse of baseplate_name: '013-CBP-6' -> 6 (None if not 1..8)."""
    if not name:
        return None
    match = _BP_TAIL.search(str(name).strip())
    if not match:
        return None
    bp = int(match.group(1))
    return bp if 1 <= bp <= BPS_PER_CIOC else None
