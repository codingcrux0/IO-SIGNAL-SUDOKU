"""The independent referee: checks finished allocation rows against the rulebook.

This module deliberately knows NOTHING about how the solver placed things.  It does not
import the grid, the placer or the spare engine; it receives only the output ROWS (the
same 76-column rows that go into Excel) plus the configuration, and re-derives every
rule from them.  That is why it can also audit a human-made allocation (the demo does).

Rules (V10W and V16 are warnings, everything else is an error):
  V01 every expected tag appears exactly once     V09 status discipline (Field/Spare/...)
  V02 no slot is used twice                       V10 wired spares >= 10% per IO type/controller
  V03 CHARM_No formula, ranges, name prefixes     V10W more wired spares than the quota
  V04 cable pairs unique and in channel order     V11 exactly 384 slots per cabinet
  V05 a cable is one aligned contiguous run       V12 wired-spare tag equals its address
  V06 A and B never share a CIOC                  V13 cabinet / CIOC / controller consistency
  V07 alarm baseplate = alarms only                V14 future space: enough Spare Slots
  V08 IO type / CHARM / terminal block agree      V15 SE4302T02 <=> SE4502
                                                  V16 empty baseplates at the end of CIOC 4
Never raises: a row it cannot read becomes a V00 violation.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from io_sudoku.core.catalog import charm_matches_io, hardware
from io_sudoku.core.config import Config
from io_sudoku.core.constants import (
    BPS_PER_CIOC, CIOCS_PER_CAB, IO_TYPES, PROFILES, SLOTS_PER_BP, SLOTS_PER_CAB, STATUS_ALARM, STATUS_FIELD,
    STATUS_SLOT, STATUS_WIRED,
)
from io_sudoku.core.models import Violation
from io_sudoku.core.naming import dsp_tag, parse_bp
from io_sudoku.core.textnorm import match_key, to_int

_DSP_RE = re.compile(r"^\d{4}DSP\d{5}\d{1,2}\d{1,2}$")
_STATUSES = (STATUS_FIELD, STATUS_ALARM, STATUS_WIRED, STATUS_SLOT)
_TAIL3 = re.compile(r"(\d{3})$")


def _s(row: dict[str, Any], column: str) -> str:
    value = row.get(column)
    return "-" if value is None or str(value).strip() == "" else str(value).strip()


class _R:
    """One output row, parsed once."""

    __slots__ = ("row", "cab", "cioc_name", "bp_name", "bp", "ch", "charm_no", "status", "tag", "io", "charm", "tb",
                 "cable", "pair", "seg", "controller", "system", "cioc_seq", "cioc_idx", "pos", "ref")

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.cab = _s(row, "Electronic/ Marshalling Cabinet")
        self.cioc_name = _s(row, "CIOC/CSLS Name")
        self.bp_name = _s(row, "Baseplate")
        self.bp = parse_bp(self.bp_name)
        self.ch = to_int(row.get("Channel_No"))
        self.charm_no = to_int(row.get("CHARM_No"))
        self.status = _s(row, "Tag Status")
        self.tag = _s(row, "Tag Name")
        self.io = _s(row, "IO Type")
        self.charm = _s(row, "CHARM Type")
        self.tb = _s(row, "CHARM TB Part No")
        self.cable = _s(row, "Field Cable No")
        self.pair = to_int(row.get("Field Cable Pair")) if _s(row, "Field Cable Pair") != "-" else None
        self.seg = _s(row, "Segregation")
        self.controller = _s(row, "Controller")
        self.system = _s(row, "System Cabinet")
        match = _TAIL3.search(self.cioc_name)
        self.cioc_seq = int(match.group(1)) if match else None
        self.cioc_idx = ((self.cioc_seq - 1) % CIOCS_PER_CAB + 1) if self.cioc_seq else None
        self.pos = ((self.bp - 1) * SLOTS_PER_BP + (self.ch - 1)) if self.bp and self.ch else None
        self.ref = f"{self.cab} {self.bp_name} ch {self.ch}"


def verify(rows: list[dict[str, Any]], cfg: Config, expected_keys: set[str] | None = None) -> list[Violation]:
    """All rule violations found in `rows`. Never raises."""
    out: list[Violation] = []
    parsed: list[_R] = []
    for number, row in enumerate(rows, start=1):
        try:
            parsed.append(_R(row))
        except Exception:
            out.append(Violation("V00", "error", f"row {number}", "This row could not be read."))
    try:
        _check(parsed, cfg, expected_keys, out)
    except Exception as exc:                     # a bug in the checker must not take the app down
        out.append(Violation("V00", "error", "verifier", f"The verifier stopped early: {type(exc).__name__}: {exc}"))
    return out


def _family(code: str, cfg: Config) -> str | None:
    upper = code.strip().upper()
    if upper in {c.upper() for c in cfg.rules.a_codes}:
        return "A"
    if upper in {c.upper() for c in cfg.rules.b_codes}:
        return "B"
    return None


def _check(rows: list[_R], cfg: Config, expected_keys: set[str] | None, out: list[Violation]) -> None:
    add = lambda rule, severity, ref, msg: out.append(Violation(rule, severity, ref, msg))   # noqa: E731
    rules = cfg.rules

    # V01 conservation ---------------------------------------------------------------
    if expected_keys is not None:
        seen = Counter(match_key(r.tag) for r in rows if r.status in (STATUS_FIELD, STATUS_ALARM))
        for key in sorted(expected_keys):
            if seen.get(key, 0) != 1:
                add("V01", "error", key, f"Tag '{key}' appears {seen.get(key, 0)} times (expected exactly once).")

    # V02 slot uniqueness ------------------------------------------------------------
    slots = Counter((r.cab, r.cioc_name, r.bp_name, r.ch) for r in rows)
    for (cab, cioc, bp, ch), n in sorted(slots.items(), key=str):
        if n > 1:
            add("V02", "error", f"{cab} {bp} ch {ch}", f"Slot used {n} times.")

    # V03 numbering --------------------------------------------------------------------
    for r in rows:
        if r.bp is None or r.ch is None or not 1 <= r.ch <= SLOTS_PER_BP:
            add("V03", "error", r.ref, "Baseplate or channel number is outside 1-8 / 1-12.")
        elif r.charm_no != (r.bp - 1) * SLOTS_PER_BP + r.ch:
            add("V03", "error", r.ref, f"CHARM_No {r.charm_no} should be {(r.bp - 1) * SLOTS_PER_BP + r.ch}.")
        elif r.cioc_seq is None or r.bp_name[:3] != f"{r.cioc_seq:03d}":
            add("V03", "error", r.ref, "The baseplate prefix does not match the CIOC number.")

    # V04 / V05 cables --------------------------------------------------------------------
    by_cable: dict[str, list[_R]] = defaultdict(list)
    for r in rows:
        if r.cable != "-" and r.status != STATUS_ALARM:
            by_cable[match_key(r.cable) or r.cable].append(r)
    for key in sorted(by_cable):
        members = by_cable[key]
        cable = members[0].cable
        pairs = Counter(m.pair for m in members if m.pair is not None)
        for pair, n in sorted(pairs.items()):
            if n > 1:
                add("V04", "error", cable, f"Pair {pair} of cable {cable} is used {n} times.")
        located = [m for m in members if m.pos is not None and m.pair is not None and m.cioc_idx is not None]
        if len({m.pos - m.pair for m in located}) > 1:
            add("V04", "error", cable, f"Pairs of cable {cable} are not in channel order.")
        homes = {(m.cab, m.cioc_name) for m in members}
        if len(homes) > 1:
            add("V05", "error", cable, f"Cable {cable} is spread over {len(homes)} CIOCs.")
            continue
        positions = sorted(m.pos for m in members if m.pos is not None)
        if positions:
            if positions != list(range(positions[0], positions[0] + len(positions))):
                add("V05", "error", cable, f"Cable {cable} does not occupy consecutive channels.")
            step = 6 if len(positions) <= 6 else SLOTS_PER_BP
            if positions[0] % step != 0:
                add("V05", "error", cable, f"Cable {cable} does not start on a {step}-channel boundary.")

    # V06 segregation ------------------------------------------------------------------------
    families: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        if r.status == STATUS_FIELD:
            fam = _family(r.seg, cfg)
            if fam:
                families[(r.cab, r.cioc_name)].add(fam)
    for (cab, cioc), fams in sorted(families.items()):
        if len(fams) > 1:
            add("V06", "error", f"{cab} {cioc}", "Segregation A and B share this CIOC.")

    # V07 alarm baseplate (a project choice: rules.alarm_cioc / alarm_bp) -----------------------------------
    for r in rows:
        on_alarm_bp = r.cioc_idx == rules.alarm_cioc and r.bp == rules.alarm_bp
        if on_alarm_bp and r.status not in (STATUS_ALARM, STATUS_SLOT):
            add("V07", "error", r.ref, f"A {r.status} row sits on the cabinet-alarm baseplate.")
        if r.status == STATUS_ALARM and not on_alarm_bp:
            add("V07", "error", r.ref, f"A cabinet alarm is not on CIOC {rules.alarm_cioc}, baseplate {rules.alarm_bp} "
                                       "(the project's cabinet-alarm baseplate).")

    # V08 / V15 hardware ----------------------------------------------------------------------
    allowed_pairs = {(hardware(p).charm_type, hardware(p).tb_part) for p in PROFILES}
    for r in rows:
        if r.status in (STATUS_FIELD, STATUS_WIRED, STATUS_ALARM):
            if not charm_matches_io(r.io, r.charm, r.status):
                add("V08", "error", r.ref, f"IO type {r.io} cannot use CHARM {r.charm}.")
            elif (r.charm, r.tb) not in allowed_pairs:
                add("V08", "error", r.ref, f"CHARM {r.charm} does not go with terminal block {r.tb}.")
            if (r.charm == "SE4302T02") != (r.tb == "SE4502"):
                add("V15", "error", r.ref, "SE4302T02 must be fitted on SE4502 (and only that CHARM).")

    # V09 status discipline -------------------------------------------------------------------------
    for r in rows:
        if r.status not in _STATUSES:
            add("V09", "error", r.ref, f"Unknown Tag Status '{r.status}'.")
        elif r.status == STATUS_SLOT:
            if r.charm != "SE6103" or r.tag != "-":
                add("V09", "error", r.ref, "A Spare Slot must be an SE6103 cover with no tag.")
        elif r.status == STATUS_WIRED:
            if not _DSP_RE.match(r.tag) or r.io not in IO_TYPES or r.charm == "SE6103" or r.cable == "-" or r.pair is None:
                add("V09", "error", r.ref, "A Wired Spare needs a DSP tag, an IO type, a functional CHARM and a wired pair.")
        elif r.status == STATUS_FIELD:
            if r.charm == "SE6103" or r.tb == "-" or r.cable == "-" or r.pair is None or r.tag == "-":
                add("V09", "error", r.ref, "A Field signal needs a tag, cable, pair, functional CHARM and terminal block.")

    # V10 spares per IO type per controller --------------------------------------------------------------
    field = Counter((r.controller, r.io) for r in rows if r.status == STATUS_FIELD)
    wired = Counter((r.controller, r.io) for r in rows if r.status == STATUS_WIRED)
    for controller, io in sorted(set(field) | set(wired)):
        need = -(-field[(controller, io)] * rules.spare_pct // 100)
        have = wired[(controller, io)]
        if have < need:
            add("V10", "error", f"{controller}/{io}", f"{have} wired spares but {need} are required "
                f"({rules.spare_pct}% of {field[(controller, io)]} field signals).")
        elif have > need:
            add("V10W", "warning", f"{controller}/{io}", f"{have} wired spares, more than the {need} required.")

    # V11 / V13 / V14 / V16 per cabinet -------------------------------------------------------------------
    per_cab: dict[str, list[_R]] = defaultdict(list)
    for r in rows:
        per_cab[r.cab].append(r)
    for cab_name in sorted(per_cab):
        members = per_cab[cab_name]
        if len(members) != SLOTS_PER_CAB:
            add("V11", "error", cab_name, f"{len(members)} slots listed; a cabinet has exactly {SLOTS_PER_CAB}.")
        controllers, systems = {m.controller for m in members}, {m.system for m in members}
        if len(controllers) > 1 or len(systems) > 1:
            add("V13", "error", cab_name, "A cabinet lists more than one controller or system cabinet.")
        cfg_cab = cfg.cabinet_by_marshalling(cab_name)
        if cfg_cab is not None:
            if controllers != {cfg_cab.controller} or systems != {cfg_cab.system}:
                add("V13", "error", cab_name, "Controller or system cabinet differs from the configured topology.")
            if any(m.cioc_seq is None or not (cfg_cab.cabinet_seq - 1) * CIOCS_PER_CAB < m.cioc_seq <= cfg_cab.cabinet_seq * CIOCS_PER_CAB
                   for m in members):
                add("V13", "error", cab_name, "A CIOC does not belong to this cabinet.")
        slots_free = sum(1 for m in members if m.status == STATUS_SLOT)
        if slots_free < rules.future_slots_required():
            add("V14", "error", cab_name, f"Only {slots_free} Spare Slots left; {rules.future_slots_required()} "
                f"({rules.future_pct}% future space) are required.")
        tail = [m for m in members if m.cioc_idx == CIOCS_PER_CAB and m.bp and m.bp > BPS_PER_CIOC - rules.empty_bp_min]
        if rules.empty_bp_min and any(m.status != STATUS_SLOT or m.cable != "-" for m in tail):
            add("V16", "warning", cab_name, f"The last {rules.empty_bp_min} baseplates of CIOC 4 are not completely empty.")

    # V12 wired-spare tags equal their address -----------------------------------------------------------------
    for r in rows:
        if r.status != STATUS_WIRED or r.bp is None or r.ch is None or r.cioc_seq is None:
            continue
        ctrl = to_int(r.controller[-2:]) if r.controller != "-" else None
        if ctrl is None:
            continue
        suffix = f"{ctrl:02d}{r.cioc_seq:03d}{r.bp}{r.ch}"
        cab = cfg.cabinet_by_marshalling(r.cab)
        full_ok = True
        if cab is not None and r.cioc_idx:
            full_ok = r.tag == dsp_tag(cab, r.cioc_idx, r.bp, r.ch)
        if not r.tag.endswith("DSP" + suffix) or not full_ok:
            add("V12", "error", r.ref, f"Wired-spare tag {r.tag} does not match its address (expected ...DSP{suffix}).")
