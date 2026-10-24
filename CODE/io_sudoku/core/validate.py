"""Check every signal and set aside (quarantine) the ones that cannot be allocated.

Nothing is ever dropped silently: each quarantined signal gets a TQ that tells an
engineer exactly what to fix.  The checks run in a fixed order and a signal that fails
one check is not checked again.

Order:  blank tag -> duplicate tag -> IS signal -> IRC/MCC -> IO type -> technical room
        -> segregation code -> cable -> pair -> cable size -> pair range -> duplicate pair
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from io_sudoku.core.config import Config
from io_sudoku.core.constants import COUNTERPART_PAIRS, IO_TYPES, MAX_CABLE_PAIRS, STANDARD_CABLE_SIZES
from io_sudoku.core.ingest import IngestResult
from io_sudoku.core.models import Quarantined, Signal
from io_sudoku.core.textnorm import match_key, normalise_io_type, text_key
from io_sudoku.core.tq import TQLog

_SIZE_RE = re.compile(r"^\s*(\d+)\s*[PT]", re.IGNORECASE)
_NON_IS = {"non-is", "non is", "nonis"}


@dataclass
class Validated:
    accepted: list[Signal] = field(default_factory=list)       # clean field signals
    alarms: list[Signal] = field(default_factory=list)         # cabinet diagnostic alarms
    quarantined: list[Quarantined] = field(default_factory=list)
    size_by_cable: dict[str, int] = field(default_factory=dict)  # cable match key -> pair count


def parse_cable_size(text: str | None) -> int | None:
    """Pair count from a cable description: '24PX1MM2/...' -> 24, '1TX1.3MM2/...' -> 1."""
    if not text:
        return None
    from io_sudoku.core.textnorm import clean

    cleaned = clean(text)
    if cleaned is None:
        return None
    match = _SIZE_RE.match(cleaned)
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def _out_of_scope_pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    words = [re.escape(str(k).casefold().strip()) for k in keywords if str(k).strip()]
    return re.compile(r"\b(" + "|".join(words) + r")\b") if words else None


def _single_signal_check(sig: Signal, cfg: Config, dup_keys: set[str],
                         oos: re.Pattern[str] | None, families: set[str]) -> str | None:
    """The first per-signal rule this signal breaks (a TQ id), or None."""
    if not sig.tag or not sig.key:
        return "BLANK-TAG"
    if sig.key in dup_keys:
        return "DUPLICATE-TAG"
    execution = text_key(sig.execution)
    if execution and execution not in _NON_IS:
        return "IS-SIGNAL-UNSUPPORTED"
    if oos is not None:
        haystack = " ".join(t for t in (sig.instrument_type, sig.equipment, sig.service) if t).casefold()
        if oos.search(haystack):
            return "OUT-OF-SCOPE-SIGNAL"
    if sig.io_type is None:
        return "MISSING-IO-TYPE"
    if sig.io_type not in IO_TYPES:
        return "UNKNOWN-IO-TYPE"
    if not cfg.cabinets_in_room(sig.tech_room):
        return "NO-CABINET-FOR-ROOM"
    if sig.segregation and sig.segregation.strip().upper() not in families:
        return "UNSUPPORTED-SEGREGATION"
    if not sig.cable_no:
        return "MISSING-CABLE"
    if sig.pair_no is None:
        return "MISSING-PAIR"
    return None


def _infer_size(max_pair: int) -> int | None:
    for size in STANDARD_CABLE_SIZES:
        if size >= max_pair:
            return size
    return None


def validate(ing: IngestResult, cfg: Config, log: TQLog) -> Validated:
    """Split the ingested signals into accepted / quarantined and log a TQ for each problem."""
    out = Validated()
    rules = cfg.rules
    families = {c.upper() for c in rules.a_codes + rules.b_codes + rules.neutral_codes}
    oos = _out_of_scope_pattern(rules.out_of_scope_keywords)
    quarantined: list[Quarantined] = []

    def reject(sig: Signal, tq_id: str, ref: str | None = None) -> None:
        quarantined.append(Quarantined(sig, tq_id))
        log.add(tq_id, sig.tag if ref is None else ref)

    # --- duplicate tags (across field signals AND alarms) ---------------------------------
    counts = Counter(s.key for s in ing.signals + ing.alarms if s.key)
    dup_keys = {k for k, n in counts.items() if n > 1}

    # --- alarms: only the tag is checked here (cabinet mapping happens in place.py) ------
    for alarm in ing.alarms:
        if not alarm.tag or not alarm.key:
            reject(alarm, "BLANK-TAG")
        elif alarm.key in dup_keys:
            reject(alarm, "DUPLICATE-TAG")
        else:
            out.alarms.append(alarm)

    # --- per-signal checks ------------------------------------------------------------------
    survivors: list[Signal] = []
    for sig in ing.signals:
        problem = _single_signal_check(sig, cfg, dup_keys, oos, families)
        if problem:
            reject(sig, problem)
        else:
            survivors.append(sig)

    # --- per-cable checks (size, pair range, duplicate pairs) ---------------------------------
    by_cable: dict[str, list[Signal]] = defaultdict(list)
    for sig in survivors:
        by_cable[match_key(sig.cable_no) or ""].append(sig)
    removed: set[int] = set()   # id() of signals quarantined in this stage

    for cable_key in sorted(by_cable):
        members = by_cable[cable_key]
        cable_text = members[0].cable_no or cable_key
        sizes = {parse_cable_size(m.cable_size) for m in members} - {None}
        if len(sizes) > 1:
            log.add("CABLE-SIZE-CONFLICT", cable_text)
            for m in members:
                quarantined.append(Quarantined(m, "CABLE-SIZE-CONFLICT"))
                removed.add(id(m))
            continue
        if sizes:
            size = next(iter(sizes))
        else:
            valid_pairs = [m.pair_no for m in members if m.pair_no is not None and m.pair_no >= 1]
            size = _infer_size(max(valid_pairs)) if valid_pairs else None
            if size is None:
                log.add("BAD-CABLE-SIZE", cable_text)
                for m in members:
                    quarantined.append(Quarantined(m, "BAD-CABLE-SIZE"))
                    removed.add(id(m))
                continue
            log.add("CABLE-SIZE-INFERRED", cable_text,
                    f"Cable {cable_text} has no readable size, so {size} pairs were assumed from its highest "
                    f"pair number. Is that right?")
        if size > MAX_CABLE_PAIRS:
            # too big for one CIOC: cables.build_blocks reports CABLE-TOO-LARGE with the block
            out.size_by_cable[cable_key] = size
            continue
        out.size_by_cable[cable_key] = size

        remaining: list[Signal] = []
        for m in members:
            if m.pair_no is None or m.pair_no < 1 or m.pair_no > size:
                quarantined.append(Quarantined(m, "PAIR-BEYOND-CABLE"))
                log.add("PAIR-BEYOND-CABLE", m.tag,
                        f"Tag {m.tag} uses pair {m.pair_no}, but cable {cable_text} only has {size} pairs. "
                        f"Is the pair or the cable size wrong?")
                removed.add(id(m))
            else:
                remaining.append(m)
        pair_counts = Counter(m.pair_no for m in remaining)
        for m in remaining:
            if pair_counts[m.pair_no] > 1:
                quarantined.append(Quarantined(m, "DUPLICATE-PAIR"))
                log.add("DUPLICATE-PAIR", m.tag,
                        f"Tag {m.tag} shares pair {m.pair_no} of cable {cable_text} with another signal. "
                        f"Which pair is correct?")
                removed.add(id(m))

    out.accepted = [s for s in survivors if id(s) not in removed]

    # --- second IO type (informational) ---------------------------------------------------------
    with_second = [s for s in ing.signals + ing.alarms if s.io_type2]
    if with_second:
        log.add("IO-TYPE2-NOTED", f"{len(with_second)} rows")
    for sig in out.accepted:
        if sig.io_type2:
            pair = (sig.io_type, normalise_io_type(sig.io_type2))
            if pair not in COUNTERPART_PAIRS and pair[::-1] not in COUNTERPART_PAIRS:
                log.add("IO-TYPE-CONFLICT", sig.tag)

    out.quarantined = sorted(quarantined, key=lambda q: (q.signal.sheet, q.signal.row_ref, q.signal.tag))
    return out
