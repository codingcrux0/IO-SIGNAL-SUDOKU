"""Work out cabinets for technical rooms that are not in the configured topology.

If a new MDB uses a room we have never seen (say PIB-31), refusing every signal would
make the tool useless.  Instead we infer the cabinets from the data and flag each guess
with a TOPOLOGY-INFERRED TQ so a senior engineer can confirm it.

How a room's cabinets are inferred (deterministic):
  1. From the cabinet-alarm rows of the room: equipment names such as
     'P30-DCM-32001-04' (marshalling) and 'P30-DCS-32001-02' (system) give the project
     prefix, area code and sequence numbers.  Marshalling and system names are paired
     by ascending sequence number; a missing system name is synthesised.
  2. Otherwise from the room itself:  'PIB-31' -> loc 'P31', and the dominant risk area
     'RA 330-01' -> area code '33001'.
  3. If neither works, nothing is added and the signals are quarantined later with
     NO-CABINET-FOR-ROOM (the safe last resort).
"""
from __future__ import annotations

import re
from collections import Counter

from io_sudoku.core.config import CabinetCfg, Config
from io_sudoku.core.ingest import IngestResult
from io_sudoku.core.models import Signal
from io_sudoku.core.naming import area4
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.tq import TQLog

NAME_RE = re.compile(r"^(?P<loc>[A-Z0-9]+)-DC(?P<kind>[MS])-(?P<area5>\d{5})-(?P<seq>\d{2})$")


def _dominant_unit(signals: list[Signal]) -> int:
    """Most common WBS/unit in the room (ties -> smallest); 0 if none."""
    counts = Counter(s.unit for s in signals if s.unit is not None)
    if not counts:
        return 0
    best = max(counts.values())
    return min(u for u, n in counts.items() if n == best)


def _controller(loc: str, area5: str, ctrl_seq: int) -> str:
    return f"{loc}DPK{area4(area5)}{ctrl_seq:02d}"


def _from_alarm_names(room: str, room_signals: list[Signal], alarms: list[Signal]) -> list[CabinetCfg]:
    marshalling: list[tuple[int, str, str, str]] = []   # (seq, name, loc, area5)
    system: list[tuple[int, str]] = []
    for alarm in alarms:
        name = (alarm.equipment or "").strip().upper()
        match = NAME_RE.match(name)
        if not match:
            continue
        seq = int(match.group("seq"))
        if match.group("kind") == "M":
            entry = (seq, name, match.group("loc"), match.group("area5"))
            if entry not in marshalling:
                marshalling.append(entry)
        else:
            entry2 = (seq, name)
            if entry2 not in system:
                system.append(entry2)
    marshalling.sort()
    system.sort()
    unit = _dominant_unit(room_signals)
    cabinets: list[CabinetCfg] = []
    for i, (cabinet_seq, m_name, loc, area5) in enumerate(marshalling):
        if i < len(system):
            ctrl_seq, s_name = system[i]
        else:
            ctrl_seq = i + 1
            s_name = f"{loc}-DCS-{area5}-{ctrl_seq:02d}"
        cabinets.append(CabinetCfg(
            marshalling=m_name, system=s_name, controller=_controller(loc, area5, ctrl_seq),
            tech_room=room, loc=loc, area5=area5, unit=unit,
            cabinet_seq=cabinet_seq, ctrl_seq=ctrl_seq, inferred=True))
    return cabinets


def _from_room_name(room: str, room_signals: list[Signal]) -> list[CabinetCfg]:
    letters = re.search(r"[A-Za-z]", room)
    digits = "".join(re.findall(r"\d+", room))
    if not letters or not digits:
        return []
    loc = letters.group(0).upper() + digits
    areas = Counter(re.sub(r"\D", "", s.risk_area or "") for s in room_signals)
    valid = {a: n for a, n in areas.items() if len(a) == 5}
    if not valid:
        return []
    top = max(valid.values())
    area5 = min(a for a, n in valid.items() if n == top)
    return [CabinetCfg(
        marshalling=f"{loc}-DCM-{area5}-01", system=f"{loc}-DCS-{area5}-01",
        controller=_controller(loc, area5, 1), tech_room=room, loc=loc, area5=area5,
        unit=_dominant_unit(room_signals), cabinet_seq=1, ctrl_seq=1, inferred=True)]


def infer_cabinets(ing: IngestResult, cfg: Config, log: TQLog) -> int:
    """Add inferred cabinets to `cfg` for every technical room it lacks. Returns how many."""
    everyone = ing.signals + ing.alarms
    rooms: dict[str, str] = {}                      # match key -> first spelling seen
    for sig in everyone:
        key = match_key(sig.tech_room)
        if key and key not in rooms:
            rooms[key] = sig.tech_room or key
    added = 0
    known = {match_key(c.marshalling) for c in cfg.cabinets}
    for key in sorted(rooms):
        room = rooms[key]
        if cfg.cabinets_in_room(room):
            continue
        room_signals = [s for s in everyone if match_key(s.tech_room) == key]
        room_alarms = [s for s in ing.alarms if match_key(s.tech_room) == key]
        cabinets = _from_alarm_names(room, room_signals, room_alarms) or _from_room_name(room, room_signals)
        fresh = [c for c in cabinets if match_key(c.marshalling) not in known]
        for cab in fresh:
            cfg.cabinets.append(cab)
            known.add(match_key(cab.marshalling))
            added += 1
        if fresh:
            names = "; ".join(f"{c.marshalling} / {c.system} / {c.controller}" for c in fresh)
            log.add("TOPOLOGY-INFERRED", room,
                    f"Cabinets for technical room {room} were inferred from names: {names}. Are they correct?")
    return added
