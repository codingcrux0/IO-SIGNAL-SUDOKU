"""Build a synthetic MDB of any size for scale tests (deterministic for a given seed)."""
from __future__ import annotations

import random

from tests.mutate import to_xlsx_bytes

HEADERS = ["OA No.", "Technical Room (Signal Location 2)", "Design Area", "Tag Number", "TagNumber", "Old Tag Number",
           "Instrument Type", "Instrument Type Description", "Loop Name", "Tag Service 1 and 2", "Equipment Name", "WBS",
           "Status", "Location", "I/O Type Name", "I/O Type Name 2", "Signal Type", "Execution", "Signal Level",
           "Multi-cable / Cable", "Multipair Cable No.", "Pair Number", "IO Grouping", "Logic Number"]


def make_mdb(n_signals: int, seed: int = 1, room: str = "PIB-30", fill: float = 0.8) -> bytes:
    """About `n_signals` field signals on 24/12/6-pair cables, 10% A, 10% B, shared logic numbers."""
    rng = random.Random(seed)
    rows: list[list] = []
    counter = 0
    cable_no = 0
    logic_no = 0
    while counter < n_signals:
        cable_no += 1
        size = rng.choices([24, 12, 6], weights=[60, 30, 10])[0]
        used = max(1, min(size, int(size * fill)))
        family = rng.choices(["A", "B", None], weights=[10, 10, 80])[0]
        if rng.random() < 0.5:
            logic_no += 1
        logic = f"LC-{logic_no:05d}"
        io = rng.choices(["AIR", "AOR", "DIR", "DOR"], weights=[45, 15, 25, 15])[0]
        for pair in range(1, used + 1):
            counter += 1
            sov = io == "DOR" and rng.random() < 0.6
            tag = f"320-XX  -{counter:05d}"
            rows.append([
                "OA-11", room, "RA 320-01", tag, f"320XX{counter:05d}", "-", "XYV" if sov else "PT",
                "Solenoid Valve" if sov else ("Alarm" if io == "DOR" else "Pressure Transmitter"), f"320-X -{counter:05d}",
                f"SERVICE {counter}", "-", 320, "New", "L", io, "-",
                "4-20 ma HART" if io in ("AIR", "AOR") else "-", "NON-IS",
                "2-Wire" if io in ("AIR", "AOR") else ("Voltfree-contact" if io == "DIR" else "Volt-contact"),
                f"{size:02d}PX1MM2/FR/IND&OS/ARM/NIS", f"320-CE-{cable_no:04d}", f"Pair {pair}", family or "-", logic])
            if counter >= n_signals:
                break
    for tag, kind in (("320-EJA  -01001-T", "Cabinet Diagnostic Alarm"), ("320-EJA  -01001-AC", "Cabinet Diagnostic Alarm"),
                      ("320-EJA  -01001-DC", "Cabinet Diagnostic Alarm")):
        rows.append(["OA-11", room, "RA 320-01", tag, tag.replace("-", "").replace(" ", ""), "-", "EJA", kind, "-", "alarm",
                     "P30-DCM-32001-01", 320, "New", room, "AIR" if tag.endswith("T") else "DIR", "-", "-", "NON-IS", "-",
                     "-", "Internal Wiring", "-", "-", "-"])
    return to_xlsx_bytes(HEADERS, rows)
