"""Small shared data types: one MDB row (Signal), a quarantined row, a rule violation.

A Signal is a plain, already-cleaned copy of one row of the customer MDB.  Treat it
as read-only: to change one, use dataclasses.replace(signal, field=new_value).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Signal:
    """One signal (one MDB row) after cleaning.  None means 'not provided'."""

    row_ref: int                       # 1-based Excel row number it came from
    sheet: str                         # worksheet name (or 'csv')
    tag: str                           # display text of the tag (ends stripped, inner spaces kept)
    key: str                           # match_key(tag): used to compare tags

    io_type: str | None = None         # AIR / AOR / DIR / DOR after normalising AI/DI/DO/AO
    io_type2: str | None = None        # counterpart type of a third-party interface (noted, not allocated)
    signal_type: str | None = None
    signal_level: str | None = None
    execution: str | None = None       # 'NON-IS' (IS signals are out of scope)
    ext_power: str | None = None
    segregation: str | None = None     # A, B, A-CONTROL, B-ALARM, C, D, E ...
    logic_no: str | None = None        # controller logic number: cables sharing one stay together
    tech_room: str | None = None
    operating_area: str | None = None
    risk_area: str | None = None
    unit: int | None = None
    location: str | None = None
    equipment: str | None = None
    cable_no: str | None = None
    cable_size: str | None = None      # original text, e.g. '24PX1MM2/FR/IND&OS/ARM/NIS'
    pair_no: int | None = None
    pair_text: str | None = None       # original text, e.g. 'Pair 3' or 'Triad 1'
    service: str | None = None
    instrument_type: str | None = None  # description, e.g. 'Solenoid Valve'
    instrument_code: str | None = None  # short code, e.g. 'XYV'
    loop_name: str | None = None
    old_tag: str | None = None
    system2: str | None = None
    status: str | None = None          # MDB status: New / Modified / DELETED
    is_alarm: bool = False             # Cabinet Diagnostic Alarm row


@dataclass
class Quarantined:
    """A signal that could not be allocated, with the TQ id that explains why."""

    signal: Signal
    tq_id: str


@dataclass
class Violation:
    """One broken rule found by the independent verifier."""

    rule: str        # e.g. 'V06'
    severity: str    # 'error' | 'warning'
    ref: str         # where (tag, cabinet, cable ...)
    message: str
