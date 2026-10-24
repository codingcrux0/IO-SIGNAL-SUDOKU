"""Rule packs: the ONLY editable layer of the project rules.

A rule pack is a small, versioned bundle of tunable settings (spare percentage, aliases,
extra keywords ...).  The default pack `VIT-2026` holds the values from CLAUDE_RULES and is
read-only: changing anything creates a NEW pack version that points back to its parent.

What a pack can NEVER change (the locked core, see LOCKED_RULES): the 384-slot capacity,
the CHARM_No formula, the cabinet-alarm baseplate, the A/B separation, SE6103 spare slots,
the base hardware table, the naming formulas and determinism.  They are simply not
fields of a pack, so no pack - and no AI suggestion - can express a change to them.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

from io_sudoku.core.config import CabinetCfg, Config, copy_config
from io_sudoku.core.constants import IO_TYPES, PROFILES
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.topology_infer import NAME_RE

LOCKED_RULES: tuple[str, ...] = (
    "384 slots per cabinet (4 CIOCs x 8 baseplates x 12 channels)",
    "CHARM_No = (Baseplate - 1) x 12 + Channel",
    "CIOC 1 / baseplate 1 is reserved for Cabinet Alarms",
    "Segregation A and B never share a CIOC",
    "Spare Slot = SE6103, no functional CHARM",
    "Base hardware mapping (AIR, AOR, DIR, DOR CHARMs and terminal blocks)",
    "Naming formulas",
    "Deterministic allocation (no AI)",
)
PARAM_RANGES = {"spare_pct": (0, 30), "future_pct": (0, 30), "end_reserve_bps": (0, 8), "empty_bp_min": (0, 8)}
OVERRIDE_KEYS = ("io_aliases", "high_current_keywords", "high_current_codes", "instrument_profiles",
                 "segregation_families", "extra_cabinets", "project_rules")
_CABINET_FIELDS = ("marshalling", "system", "controller", "tech_room", "loc", "area5", "unit", "cabinet_seq", "ctrl_seq")
_FAMILIES = ("A", "B", "neutral")


@dataclass(frozen=True)
class RulePack:
    name: str
    version: int
    parent: str | None
    params: dict[str, int] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    read_only: bool = False


def default_pack() -> RulePack:
    """The project's own rules (CLAUDE_RULES): 10% spares, 10% future space, 4 empty end baseplates."""
    return RulePack("VIT-2026", 1, None,
                    {"spare_pct": 10, "future_pct": 10, "end_reserve_bps": 4, "empty_bp_min": 3}, {}, True)


def derive(pack: RulePack, name: str | None = None) -> RulePack:
    """An editable copy: version + 1 and a link back to the pack it came from."""
    return RulePack(name or pack.name, pack.version + 1, f"{pack.name} v{pack.version}",
                    dict(pack.params), copy.deepcopy(pack.overrides), False)


def validate_pack(pack: RulePack) -> list[str]:
    """Everything wrong with a pack (empty list = valid)."""
    problems: list[str] = []
    if not str(pack.name).strip():
        problems.append("The pack needs a name.")
    if not isinstance(pack.version, int) or pack.version < 1:
        problems.append("The version must be 1 or higher.")
    for key, value in pack.params.items():
        if key not in PARAM_RANGES:
            problems.append(f"'{key}' is not a setting that can be changed.")
        elif not isinstance(value, int) or isinstance(value, bool) or not PARAM_RANGES[key][0] <= value <= PARAM_RANGES[key][1]:
            low, high = PARAM_RANGES[key]
            problems.append(f"{key} must be a whole number from {low} to {high}.")
    for key, value in pack.overrides.items():
        if key not in OVERRIDE_KEYS:
            problems.append(f"'{key}' is not something a rule pack can override.")
            continue
        try:
            problems.extend(_validate_override(key, value))
        except Exception:
            problems.append(f"{key} has an unreadable value.")
    return problems


def _validate_override(key: str, value: Any) -> list[str]:
    out: list[str] = []
    if key == "io_aliases":
        for alias, io in dict(value).items():
            if not str(alias).strip() or len(str(alias).strip()) > 20:
                out.append("IO aliases must be 1 to 20 characters.")
            if str(io).upper() not in IO_TYPES:
                out.append(f"IO alias '{alias}' must map to AIR, AOR, DIR or DOR.")
    elif key == "high_current_keywords":
        for word in list(value):
            if not str(word).strip() or len(str(word).strip()) > 40:
                out.append("Keywords must be 1 to 40 characters.")
    elif key == "high_current_codes":
        for code in list(value):
            text = str(code).strip()
            if not text or len(text) > 10 or not text.isalnum():
                out.append("Instrument codes must be 1 to 10 letters or digits.")
    elif key == "instrument_profiles":
        for name, profile in dict(value).items():
            if not str(name).strip() or len(str(name)) > 60:
                out.append("Instrument names must be 1 to 60 characters.")
            if profile not in PROFILES or profile == "AIR_RTD":
                out.append(f"'{profile}' is not an allowed hardware profile for '{name}'.")
    elif key == "segregation_families":
        for code, family in dict(value).items():
            if not str(code).strip() or len(str(code)) > 20:
                out.append("Segregation codes must be 1 to 20 characters.")
            if family not in _FAMILIES:
                out.append(f"Segregation code '{code}' must map to A, B or neutral.")
    elif key == "project_rules":
        from io_sudoku.core.projectrules import validate_rule
        for rule in list(value):
            out.extend(validate_rule(rule))
    elif key == "extra_cabinets":
        for cab in list(value):
            if not isinstance(cab, dict) or any(f not in cab for f in _CABINET_FIELDS):
                out.append("Each extra cabinet needs all of: " + ", ".join(_CABINET_FIELDS) + ".")
                continue
            if not NAME_RE.match(str(cab["marshalling"]).upper()) or not NAME_RE.match(str(cab["system"]).upper()):
                out.append("Cabinet names must look like P30-DCM-32001-04 and P30-DCS-32001-02.")
            for number in ("unit", "cabinet_seq", "ctrl_seq"):
                if not isinstance(cab[number], int) or isinstance(cab[number], bool):
                    out.append(f"Extra cabinet field '{number}' must be a whole number.")
    return out


def apply_pack(pack: RulePack, cfg: Config) -> Config:
    """A NEW config with the pack applied. An invalid pack changes nothing. Never mutates `cfg`."""
    result = copy_config(cfg)
    if validate_pack(pack):
        return result
    rules = result.rules
    changes: dict[str, Any] = {k: int(v) for k, v in pack.params.items() if k in PARAM_RANGES}
    ov = pack.overrides
    if "io_aliases" in ov:
        changes["io_aliases"] = {**rules.io_aliases, **{str(k).strip().upper(): str(v).upper() for k, v in ov["io_aliases"].items()}}
    if "high_current_keywords" in ov:
        changes["high_current_keywords"] = tuple(dict.fromkeys(rules.high_current_keywords + tuple(str(w).strip().lower() for w in ov["high_current_keywords"])))
    if "high_current_codes" in ov:
        changes["high_current_codes"] = tuple(dict.fromkeys(rules.high_current_codes + tuple(str(c).strip().upper() for c in ov["high_current_codes"])))
    if "instrument_profiles" in ov:
        changes["instrument_profiles"] = {**rules.instrument_profiles, **{str(k).strip(): v for k, v in ov["instrument_profiles"].items()}}
    if "segregation_families" in ov:
        a, b, n = list(rules.a_codes), list(rules.b_codes), list(rules.neutral_codes)
        for code, family in ov["segregation_families"].items():
            up = str(code).strip().upper()
            for bucket in (a, b, n):
                bucket[:] = [c for c in bucket if c.upper() != up]
            {"A": a, "B": b, "neutral": n}[family].append(up)
        changes.update(a_codes=tuple(a), b_codes=tuple(b), neutral_codes=tuple(n))
    if "project_rules" in ov:
        changes["project_rules"] = tuple(copy.deepcopy(list(ov["project_rules"])))
    result.rules = replace(rules, **changes)
    if "extra_cabinets" in ov:
        have = {match_key(c.marshalling) for c in result.cabinets}
        for cab in ov["extra_cabinets"]:
            if match_key(cab["marshalling"]) not in have:
                result.cabinets.append(CabinetCfg(**{**{f: cab[f] for f in _CABINET_FIELDS}, "inferred": False}))
                have.add(match_key(cab["marshalling"]))
    return result


def pack_to_dict(pack: RulePack) -> dict[str, Any]:
    return {"name": pack.name, "version": pack.version, "parent": pack.parent, "params": dict(pack.params),
            "overrides": copy.deepcopy(pack.overrides), "read_only": pack.read_only}


def pack_from_dict(data: Any) -> RulePack:
    """Tolerant inverse of pack_to_dict: anything unusable gives the default pack."""
    try:
        if not isinstance(data, dict) or "name" not in data or "version" not in data:
            return default_pack()
        pack = RulePack(str(data["name"]), int(data["version"]), data.get("parent"),
                        {str(k): v for k, v in dict(data.get("params", {})).items()},
                        dict(data.get("overrides", {})), bool(data.get("read_only", False)))
        return pack if not validate_pack(pack) else default_pack()
    except Exception:
        return default_pack()


def pack_hash(pack: RulePack) -> str:
    """SHA-256 of the pack's content (stable whatever the key order)."""
    return hashlib.sha256(json.dumps(pack_to_dict(pack), sort_keys=True, default=str).encode("utf-8")).hexdigest()
