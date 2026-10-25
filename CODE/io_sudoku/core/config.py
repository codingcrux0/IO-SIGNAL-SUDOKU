"""Project configuration: which cabinets exist, and the tunable (non-locked) rules.

The cabinet topology (which marshalling cabinet belongs to which controller, in which
technical room) is NOT stored in the MDB, so it lives here as editable data.  The
default is the topology of the official sample project (data/topology.json).

load_config() never raises: a missing or corrupt file falls back to the bundled one,
and if even that fails, to a hard-coded copy of the sample topology.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from io_sudoku.core.constants import (ALARM_BP, ALARM_CIOC, ALARM_SLOTS, BPS_PER_CIOC, CIOCS_PER_CAB, MAX_CABINETS,
                                      SLOTS_PER_BP, SLOTS_PER_CAB)
from io_sudoku.core.naming import area4
from io_sudoku.core.textnorm import match_key

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_TOPOLOGY_PATH = DATA_DIR / "topology.json"

# Hard-coded last resort (identical to data/topology.json).
_BUILTIN_CABINETS: list[dict[str, Any]] = [
    {"marshalling": "P30-DCM-32001-01", "system": "P30-DCS-32001-01", "controller": "P30DPK320101",
     "tech_room": "PIB-30", "loc": "P30", "area5": "32001", "unit": 320, "cabinet_seq": 1, "ctrl_seq": 1},
    {"marshalling": "P30-DCM-32001-04", "system": "P30-DCS-32001-02", "controller": "P30DPK320102",
     "tech_room": "PIB-30", "loc": "P30", "area5": "32001", "unit": 320, "cabinet_seq": 4, "ctrl_seq": 2},
    {"marshalling": "P24-DCM-50002-01", "system": "P24-DCS-50002-01", "controller": "P24DPK500201",
     "tech_room": "PIB-24", "loc": "P24", "area5": "50002", "unit": 500, "cabinet_seq": 1, "ctrl_seq": 1},
]


@dataclass(frozen=True)
class CabinetCfg:
    """One marshalling cabinet (384 slots) and the system cabinet/controller that owns it."""

    marshalling: str      # e.g. 'P30-DCM-32001-04'
    system: str           # e.g. 'P30-DCS-32001-02'
    controller: str       # e.g. 'P30DPK320102'
    tech_room: str        # e.g. 'PIB-30'
    loc: str              # e.g. 'P30'
    area5: str            # e.g. '32001'
    unit: int             # e.g. 320
    cabinet_seq: int      # e.g. 4  (decides the CIOC numbers 013..016)
    ctrl_seq: int         # e.g. 2
    inferred: bool = False  # True when we invented it (needs human confirmation)


@dataclass
class RulesCfg:
    """Tunable project parameters (project choices).  The LOCKED rules (384 slots, CHARM formula, A/B separation,
    SE6103 spare slots, hardware table) are not here."""

    spare_pct: int = 10
    future_pct: int = 10
    end_reserve_bps: int = 4          # last baseplates of CIOC 4 kept empty (CLAUDE_RULES 3D.3)
    empty_bp_min: int = 3
    alarm_cioc: int = ALARM_CIOC      # the cabinet-alarm baseplate: a project choice (CIOC 1-4 ...
    alarm_bp: int = ALARM_BP          # ... baseplate 1-8), the same in every marshalling cabinet
    auto_expand: bool = True          # add another cabinet when a room is full
    batch: str = "B1"
    a_codes: tuple[str, ...] = ("A", "A-CONTROL")
    b_codes: tuple[str, ...] = ("B", "B-ALARM")
    neutral_codes: tuple[str, ...] = ("C", "D", "E")
    io_aliases: dict[str, str] = field(default_factory=dict)
    high_current_keywords: tuple[str, ...] = ("solenoid", "sov", "horn", "beacon", "sounder", "siren")
    high_current_codes: tuple[str, ...] = ("XYV", "ZYV", "SOV")
    instrument_profiles: dict[str, str] = field(default_factory=dict)
    out_of_scope_keywords: tuple[str, ...] = ("irc", "mcc")
    project_rules: tuple[dict[str, Any], ...] = ()   # project columns and constraints (checked after the solve)

    def usable_channels(self) -> int:
        """Channels per cabinet available to field cables: 384 - alarm baseplate - the space kept free, which is the
        empty end baseplates or the future space, whichever is larger (both must be kept: with the defaults the 4 end
        baseplates = 48 channels already hold the 10% future space of 39, so this is 324)."""
        kept_free = max(self.end_reserve_bps * SLOTS_PER_BP, self.future_slots_required())
        return SLOTS_PER_CAB - ALARM_SLOTS - kept_free

    def alarm_problem(self) -> str:
        """'' when the cabinet-alarm baseplate is a usable position, else why not (it must not be one of the empty
        baseplates kept at the end of CIOC 4)."""
        if not (1 <= self.alarm_cioc <= CIOCS_PER_CAB and 1 <= self.alarm_bp <= BPS_PER_CIOC):
            return f"The cabinet-alarm baseplate must be CIOC 1-{CIOCS_PER_CAB}, baseplate 1-{BPS_PER_CIOC}."
        empty_end = max(self.end_reserve_bps, self.empty_bp_min)
        if self.alarm_cioc == CIOCS_PER_CAB and self.alarm_bp > BPS_PER_CIOC - empty_end:
            return (f"CIOC {CIOCS_PER_CAB}, baseplate {self.alarm_bp} is one of the last {empty_end} baseplates kept "
                    "empty, so it cannot hold the cabinet alarms.")
        return ""

    def future_slots_required(self) -> int:
        """Spare Slots every cabinet must keep: ceil(future_pct% of 384) = 39 for 10%."""
        return -(-self.future_pct * SLOTS_PER_CAB // 100)


@dataclass
class Config:
    cabinets: list[CabinetCfg]
    rules: RulesCfg = field(default_factory=RulesCfg)

    def cabinets_in_room(self, room: str | None) -> list[CabinetCfg]:
        """Cabinets of one technical room, in configuration order."""
        key = match_key(room)
        if key is None:
            return []
        return [c for c in self.cabinets if match_key(c.tech_room) == key]

    def cabinet_by_marshalling(self, name: str | None) -> CabinetCfg | None:
        key = match_key(name)
        if key is None:
            return None
        for cab in self.cabinets:
            if match_key(cab.marshalling) == key:
                return cab
        return None

    def cabinet_for_equipment(self, name: str | None) -> CabinetCfg | None:
        """Find the cabinet an alarm belongs to: matches the marshalling OR system cabinet name."""
        key = match_key(name)
        if key is None:
            return None
        for cab in self.cabinets:
            if key in (match_key(cab.marshalling), match_key(cab.system)):
                return cab
        return None

    def known_rooms(self) -> list[str]:
        rooms: list[str] = []
        for cab in self.cabinets:
            if cab.tech_room not in rooms:
                rooms.append(cab.tech_room)
        return rooms

    def new_cabinet_for_room(self, room: str | None) -> CabinetCfg | None:
        """Create the NEXT cabinet of a room (seq + 1) and append it.  (Mutates self.)

        Returns None if the room is unknown or the safety cap is reached.
        """
        existing = self.cabinets_in_room(room)
        if not existing or len(self.cabinets) >= MAX_CABINETS:
            return None
        template = max(existing, key=lambda c: (c.cabinet_seq, c.ctrl_seq))
        cabinet_seq = max(c.cabinet_seq for c in existing) + 1
        ctrl_seq = max(c.ctrl_seq for c in existing) + 1
        taken = {match_key(c.marshalling) for c in self.cabinets}
        marshalling = f"{template.loc}-DCM-{template.area5}-{cabinet_seq:02d}"
        for _ in range(MAX_CABINETS + 1):  # bounded: skip any already-used name
            marshalling = f"{template.loc}-DCM-{template.area5}-{cabinet_seq:02d}"
            if match_key(marshalling) not in taken:
                break
            cabinet_seq += 1
        else:
            return None
        new = CabinetCfg(
            marshalling=marshalling,
            system=f"{template.loc}-DCS-{template.area5}-{ctrl_seq:02d}",
            controller=f"{template.loc}DPK{area4(template.area5)}{ctrl_seq:02d}",
            tech_room=template.tech_room, loc=template.loc, area5=template.area5,
            unit=template.unit, cabinet_seq=cabinet_seq, ctrl_seq=ctrl_seq, inferred=True,
        )
        self.cabinets.append(new)
        return new


# ----------------------------------------------------------------------------- loading
_TUPLE_FIELDS = ("a_codes", "b_codes", "neutral_codes", "high_current_keywords",
                 "high_current_codes", "out_of_scope_keywords")
_DICT_FIELDS = ("io_aliases", "instrument_profiles")
_INT_FIELDS = ("spare_pct", "future_pct", "end_reserve_bps", "empty_bp_min", "alarm_cioc", "alarm_bp")


def _cabinet_from_dict(d: dict[str, Any]) -> CabinetCfg:
    return CabinetCfg(
        marshalling=str(d["marshalling"]).strip(), system=str(d["system"]).strip(),
        controller=str(d["controller"]).strip(), tech_room=str(d["tech_room"]).strip(),
        loc=str(d["loc"]).strip(), area5=str(d["area5"]).strip(), unit=int(d["unit"]),
        cabinet_seq=int(d["cabinet_seq"]), ctrl_seq=int(d["ctrl_seq"]),
        inferred=bool(d.get("inferred", False)),
    )


def _rules_from_dict(d: dict[str, Any]) -> RulesCfg:
    rules = RulesCfg()
    known = {f.name for f in fields(RulesCfg)}
    for name, value in d.items():
        if name not in known:
            continue
        if name in _INT_FIELDS:
            setattr(rules, name, int(value))
        elif name in _TUPLE_FIELDS:
            setattr(rules, name, tuple(str(v) for v in value))
        elif name in _DICT_FIELDS:
            setattr(rules, name, {str(k): str(v) for k, v in dict(value).items()})
        elif name == "auto_expand":
            rules.auto_expand = bool(value)
        elif name == "batch":
            rules.batch = str(value)
    if rules.alarm_problem():                       # an unusable alarm baseplate falls back to the project default
        rules.alarm_cioc, rules.alarm_bp = ALARM_CIOC, ALARM_BP
    return rules


def _parse(data: Any) -> Config | None:
    """Turn a dict into a Config, or None if it is not usable."""
    try:
        cabinets = [_cabinet_from_dict(c) for c in data["cabinets"]]
        if not cabinets:
            return None
        rules = _rules_from_dict(data.get("rules", {})) if isinstance(data.get("rules"), dict) else RulesCfg()
        return Config(cabinets=cabinets, rules=rules)
    except Exception:
        return None


def _builtin_config() -> Config:
    return Config(cabinets=[_cabinet_from_dict(c) for c in _BUILTIN_CABINETS], rules=RulesCfg())


def load_config(path: str | Path | None = None) -> Config:
    """Load the topology from `path` (or the bundled default). Never raises."""
    candidates = ([Path(path)] if path else []) + [DEFAULT_TOPOLOGY_PATH]
    for candidate in candidates:
        try:
            cfg = _parse(json.loads(candidate.read_text(encoding="utf-8")))
            if cfg is not None:
                return cfg
        except Exception:
            continue
    return _builtin_config()


def config_to_dict(cfg: Config) -> dict[str, Any]:
    """JSON-friendly form of a Config (used by workspace snapshots and support bundles)."""
    rules: dict[str, Any] = {}
    for f in fields(RulesCfg):
        value = getattr(cfg.rules, f.name)
        rules[f.name] = list(value) if isinstance(value, tuple) else value
    cabinets = [{f.name: getattr(c, f.name) for f in fields(CabinetCfg)} for c in cfg.cabinets]
    return {"cabinets": cabinets, "rules": rules}


def config_from_dict(d: Any) -> Config:
    """Inverse of config_to_dict. Invalid input -> the bundled default config."""
    return _parse(d) or load_config()


def copy_config(cfg: Config) -> Config:
    """Deep copy, so a run can add auto-expanded cabinets without touching the caller's config."""
    return copy.deepcopy(cfg)
