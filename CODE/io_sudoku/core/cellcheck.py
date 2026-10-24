"""Rule Check: every rule and constraint that applies to ONE cell (slot) of the allocation, checked live.

For a slot it lists, in plain words, each locked rule, each project rule of the active pack, the engineer's
answers and pins, the open questions and the decisions the solver wrote down - with ✓ (met), ✗ (broken),
▲ (needs a look) or • (information).  It also gives the signal path: field device → cable → cabinet → CIOC →
baseplate → CHARM → controller.

Read-only, like trace.py: it re-checks the finished rows (the same 76-column rows that go into Excel) and
never influences placement.  The rule numbers match verify.py (V03, V06 ...) so the two always agree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from io_sudoku.core.catalog import charm_matches_io, hardware
from io_sudoku.core.constants import (BPS_PER_CIOC, CIOCS_PER_CAB, PROFILES, SLOTS_PER_BP, SLOTS_PER_CAB, STATUS_ALARM,
                                      STATUS_FIELD, STATUS_SLOT, STATUS_WIRED)
from io_sudoku.core.naming import parse_bp
from io_sudoku.core.projectrules import judge, matches
from io_sudoku.core.textnorm import match_key, to_int

SEP = "~"                                   # slot id: 'P30-DCM-32001-01~1~2~3' (cabinet, CIOC 1-4, baseplate, channel)
_TAIL3 = re.compile(r"(\d{3})$")
PASS, FAIL, WARN, INFO = "pass", "fail", "warn", "info"
ICONS = {PASS: "✓", FAIL: "✗", WARN: "▲", INFO: "•"}


def _s(row: dict[str, Any] | None, column: str) -> str:
    value = (row or {}).get(column)
    return "-" if value is None or str(value).strip() == "" else str(value).strip()


def _cioc_seq(row: dict[str, Any]) -> int | None:
    match = _TAIL3.search(_s(row, "CIOC/CSLS Name"))
    return int(match.group(1)) if match else None


def position(row: dict[str, Any]) -> tuple[str, int, int, int] | None:
    """(cabinet, CIOC 1-4, baseplate, channel) of a row, or None when it cannot be read."""
    seq, bp, ch = _cioc_seq(row), parse_bp(_s(row, "Baseplate")), to_int(row.get("Channel_No"))
    if seq is None or bp is None or ch is None:
        return None
    return _s(row, "Electronic/ Marshalling Cabinet"), (seq - 1) % CIOCS_PER_CAB + 1, bp, ch


def slot_id(row: dict[str, Any]) -> str | None:
    pos = position(row)
    return SEP.join(str(x) for x in pos) if pos else None


def slot_label(row: dict[str, Any]) -> str:
    pos = position(row)
    where = f"{pos[0]} · CIOC {pos[1]} · BP {pos[2]} · CH {pos[3]}" if pos else "unknown slot"
    tag = _s(row, "Tag Name")
    return f"{tag if tag != '-' else _s(row, 'Tag Status')} · {where}"


def index_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{slot id: row} for a whole allocation."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = slot_id(r)
        if key and key not in out:
            out[key] = r
    return out


@dataclass(frozen=True)
class Check:
    status: str          # pass | fail | warn | info
    rule: str            # 'V03', 'Project rule', 'Answer' ...
    title: str
    detail: str

    @property
    def line(self) -> str:
        return f"{ICONS.get(self.status, '-')} [{self.rule}] {self.title}: {self.detail}"


def _family(code: str, cfg: Any) -> str | None:
    upper = code.strip().upper()
    if cfg is None:
        return None
    if upper in {c.upper() for c in cfg.rules.a_codes}:
        return "A"
    if upper in {c.upper() for c in cfg.rules.b_codes}:
        return "B"
    return None


def check_cell(result: Any, row: dict[str, Any], *, overrides: list[Any] | None = None,
               pins: dict[str, tuple[str, int]] | None = None) -> list[Check]:
    """Every rule that applies to this row, checked against the whole allocation of `result`."""
    rows: list[dict[str, Any]] = list(getattr(result, "rows", []) or [])
    cfg = getattr(result, "cfg_used", None)
    rules = cfg.rules if cfg is not None else None
    out: list[Check] = []
    add = lambda *a: out.append(Check(*a))   # noqa: E731
    pos = position(row)
    status, tag, io, charm = _s(row, "Tag Status"), _s(row, "Tag Name"), _s(row, "IO Type"), _s(row, "CHARM Type")
    cab = _s(row, "Electronic/ Marshalling Cabinet")
    cioc_name, bp_name, cable = _s(row, "CIOC/CSLS Name"), _s(row, "Baseplate"), _s(row, "Field Cable No")
    if pos is None:
        add(FAIL, "V03", "Position", "the CIOC, baseplate or channel of this row cannot be read")
        return out
    _, cioc, bp, ch = pos

    # ---- locked rules ------------------------------------------------------------------------------------
    inside = 1 <= cioc <= CIOCS_PER_CAB and 1 <= bp <= BPS_PER_CIOC and 1 <= ch <= SLOTS_PER_BP
    add(PASS if inside else FAIL, "Locked", "384 slots per cabinet",
        f"slot {(cioc - 1) * BPS_PER_CIOC * SLOTS_PER_BP + (bp - 1) * SLOTS_PER_BP + ch} of {SLOTS_PER_CAB} "
        f"(CIOC {cioc} of {CIOCS_PER_CAB}, baseplate {bp} of {BPS_PER_CIOC}, channel {ch} of {SLOTS_PER_BP})")
    want = (bp - 1) * SLOTS_PER_BP + ch
    have = to_int(row.get("CHARM_No"))
    add(PASS if have == want else FAIL, "V03", "CHARM_No = (Baseplate - 1) x 12 + Channel",
        f"({bp} - 1) x 12 + {ch} = {want}; the row says {have if have is not None else '-'}")
    seq = _cioc_seq(row)
    add(PASS if seq is not None and bp_name[:3] == f"{seq:03d}" else FAIL, "V03", "Baseplate name matches its CIOC",
        f"baseplate {bp_name} on {cioc_name}")
    on_alarm_bp = cioc == 1 and bp == 1
    if status == STATUS_ALARM:
        add(PASS if on_alarm_bp else FAIL, "V07", "Cabinet alarms sit on CIOC 1, baseplate 1",
            "this alarm is " + ("there" if on_alarm_bp else f"on CIOC {cioc}, baseplate {bp}"))
    elif on_alarm_bp:
        add(PASS if status == STATUS_SLOT else FAIL, "V07", "CIOC 1, baseplate 1 is kept for cabinet alarms",
            f"this slot is a {status}")
    else:
        add(PASS, "V07", "CIOC 1, baseplate 1 is kept for cabinet alarms", "this slot is not on that baseplate")
    if status in (STATUS_FIELD, STATUS_WIRED, STATUS_ALARM):
        families = {_family(_s(r, "Segregation"), cfg) for r in rows if r.get("Tag Status") == STATUS_FIELD
                    and _s(r, "Electronic/ Marshalling Cabinet") == cab and _s(r, "CIOC/CSLS Name") == cioc_name} - {None}
        mine = _family(_s(row, "Segregation"), cfg) if status == STATUS_FIELD else None
        what = f"segregation {_s(row, 'Segregation')} (family {mine or 'neutral'})" if status == STATUS_FIELD else status
        add(PASS if len(families) <= 1 else FAIL, "V06", "Segregation A and B never share a CIOC",
            f"{what}; families on {cioc_name}: {', '.join(sorted(families)) or 'none'}")
        allowed = {(hardware(p).charm_type, hardware(p).tb_part) for p in PROFILES}
        tb = _s(row, "CHARM TB Part No")
        ok_io = charm_matches_io(io, charm, status)
        add(PASS if ok_io else FAIL, "V08", "IO type, CHARM and terminal block agree",
            f"{io} uses CHARM {charm} on terminal block {tb}" + ("" if ok_io else " (not allowed)"))
        if ok_io and status != STATUS_ALARM and (charm, tb) not in allowed:
            add(FAIL, "V08", "CHARM and terminal block are a known pair", f"{charm} does not go with {tb}")
        if charm == "SE4302T02" or tb == "SE4502":
            add(PASS if (charm == "SE4302T02") == (tb == "SE4502") else FAIL, "V15", "High-current CHARM SE4302T02 sits on SE4502",
                f"CHARM {charm} on {tb}")
    if status == STATUS_SLOT:
        add(PASS if charm == "SE6103" and tag == "-" else FAIL, "V09", "A Spare Slot is an SE6103 cover with no tag",
            f"CHARM {charm}, tag {tag}")
    elif status == STATUS_FIELD:
        ok = charm != "SE6103" and _s(row, "CHARM TB Part No") != "-" and cable != "-" and _s(row, "Field Cable Pair") != "-"
        add(PASS if ok else FAIL, "V09", "A Field signal has a tag, cable, pair, CHARM and terminal block",
            f"cable {cable}, {_s(row, 'Field Cable Pair')}, CHARM {charm}")
    elif status == STATUS_WIRED:
        add(INFO, "V12", "A wired spare is named after its address", f"tag {tag}")

    # ---- the cable this signal is on -----------------------------------------------------------------------
    if cable != "-" and status != STATUS_ALARM:
        mates = [r for r in rows if (match_key(_s(r, "Field Cable No")) or "") == (match_key(cable) or "")
                 and r.get("Tag Status") != STATUS_ALARM]
        homes = {(_s(r, "Electronic/ Marshalling Cabinet"), _s(r, "CIOC/CSLS Name")) for r in mates}
        add(PASS if len(homes) == 1 else FAIL, "V05", "A cable stays on one CIOC",
            f"cable {cable} has {len(mates)} rows on {len(homes)} CIOC" + ("" if len(homes) == 1 else "s"))
        spots = sorted(p for p in ((lambda q: (q[2] - 1) * SLOTS_PER_BP + (q[3] - 1) if q else None)(position(r)) for r in mates)
                       if p is not None)
        if spots and len(homes) == 1:
            run = spots == list(range(spots[0], spots[0] + len(spots)))
            step = 6 if len(spots) <= 6 else SLOTS_PER_BP
            add(PASS if run and spots[0] % step == 0 else FAIL, "V05", "A cable is one run that starts on a boundary",
                f"{len(spots)} consecutive channels from a {step}-channel boundary" if run and spots[0] % step == 0
                else "the channels are not one aligned run")
        if pins and cable in pins:
            pin_cab, pin_cioc = pins[cable]
            add(PASS if (pin_cab, pin_cioc) == (cab, cioc) else WARN, "Pin", "Pinned by an engineer",
                f"cable {cable} was pinned to {pin_cab}, CIOC {pin_cioc}; it is in {cab}, CIOC {cioc}")

    # ---- project rules of the active pack -------------------------------------------------------------------
    if rules is not None:
        controller = _s(row, "Controller")
        if status in (STATUS_FIELD, STATUS_WIRED) and io != "-":
            field_n = sum(1 for r in rows if r.get("Tag Status") == STATUS_FIELD and _s(r, "Controller") == controller and _s(r, "IO Type") == io)
            wired_n = sum(1 for r in rows if r.get("Tag Status") == STATUS_WIRED and _s(r, "Controller") == controller and _s(r, "IO Type") == io)
            need = -(-field_n * rules.spare_pct // 100)
            add(PASS if wired_n >= need else FAIL, "V10", f"{rules.spare_pct}% wired spares per IO type and controller",
                f"{controller} / {io}: {field_n} field signals need {need}; {wired_n} wired spares")
        free = sum(1 for r in rows if _s(r, "Electronic/ Marshalling Cabinet") == cab and r.get("Tag Status") == STATUS_SLOT)
        need_free = rules.future_slots_required()
        add(PASS if free >= need_free else FAIL, "V14", f"{rules.future_pct}% future space per cabinet",
            f"{cab} keeps {free} Spare Slots; {need_free} are required")
        if cioc == CIOCS_PER_CAB and bp > BPS_PER_CIOC - rules.empty_bp_min and rules.empty_bp_min:
            empty = status == STATUS_SLOT and cable == "-"
            add(PASS if empty else WARN, "V16", f"The last {rules.empty_bp_min} baseplates of CIOC 4 stay empty",
                "this slot is " + ("empty" if empty else f"used ({status})"))
        if status == STATUS_FIELD:
            seg = _s(row, "Segregation").upper()
            instrument = _s(row, "Instrument type")
            if charm == "SE4302T02":
                words = [w for w in rules.high_current_keywords if w in f"{instrument} {_s(row, 'Service Description')}".casefold()]
                add(INFO, "Project rule", "High-current output", f"CHARM SE4302T02 (keywords: {', '.join(words) or 'instrument code'})")
            if instrument in rules.instrument_profiles:
                add(INFO, "Project rule", "Instrument hardware", f"'{instrument}' uses profile {rules.instrument_profiles[instrument]}")
            if seg in {c.upper() for c in rules.neutral_codes}:
                add(INFO, "Project rule", "Segregation code", f"{seg} counts as neutral (may share a CIOC with A or B)")
        for rule in rules.project_rules:
            if matches(rule, row):
                o = judge(rule, row)
                add(INFO if o.ok is None else (PASS if o.ok else FAIL), "Project rule", str(rule.get("statement") or rule.get("kind")),
                    o.detail)
        if cfg is not None and cfg.cabinet_by_marshalling(cab) is not None and cfg.cabinet_by_marshalling(cab).inferred:
            add(WARN, "Topology", "Cabinet name inferred", f"{cab} was inferred from names; confirm it")

    # ---- answers, questions, broken rules, decisions -----------------------------------------------------------
    key = match_key(tag) or ""
    for o in overrides or []:
        if key and (match_key(o.tag_key) or "") == key:
            add(INFO, "Answer", "An engineer's answer was applied", f"{o.field} = {o.value} (by {o.by or 'unnamed'})")
    refs = {x for x in (key, match_key(cable) or "", match_key(cab) or "") if x}
    for t in getattr(result, "tqs", []) or []:
        if (match_key(t.ref) or "") in refs and t.severity in ("error", "warning"):
            add(FAIL if t.severity == "error" else WARN, t.tq_id, "Open question", t.message)
    here = f"{cab} {bp_name} ch {ch}"
    for v in getattr(result, "violations", []) or []:
        if v.ref in (here, cable, cab, f"{cab} {cioc_name}", f"{controller_of(row)}/{io}") or (key and match_key(v.ref) == key):
            add(FAIL if v.severity == "error" else WARN, v.rule, "Checker finding", v.message)
    traces = getattr(result, "traces", {}) or {}
    lines = [line for name in dict.fromkeys(x for x in (key, match_key(cable) or "") if x) for line in traces.get(name, [])]
    for line in dict.fromkeys(lines):                       # the tag and its cable share most decisions
        add(INFO, "Decision", "Why it is here", line)
    return out


def controller_of(row: dict[str, Any]) -> str:
    return _s(row, "Controller")


def summary(checks: list[Check]) -> dict[str, int]:
    out = {PASS: 0, FAIL: 0, WARN: 0, INFO: 0}
    for c in checks:
        out[c.status] = out.get(c.status, 0) + 1
    return out


def signal_path(row: dict[str, Any]) -> list[tuple[str, str]]:
    """(step, text) from the field device to the controller."""
    pair, size = _s(row, "Field Cable Pair"), _s(row, "Field Cable Size")
    tb = " / ".join(x for x in (_s(row, "CHARM TB1"), _s(row, "CHARM TB2"), _s(row, "CHARM TB3")) if x != "-")
    side = {"F": "front", "R": "rear"}.get(_s(row, "Cabinet Side (F/R)"), _s(row, "Cabinet Side (F/R)"))
    return [
        ("Field device", f"{_s(row, 'Tag Name')} · {_s(row, 'Instrument type')} · {_s(row, 'Service Description')}"),
        ("Field cable", f"{_s(row, 'Field Cable No')} · {pair} · {size}"),
        ("Marshalling cabinet", f"{_s(row, 'Electronic/ Marshalling Cabinet')} ({side})"),
        ("CIOC", _s(row, "CIOC/CSLS Name")),
        ("Baseplate / channel", f"{_s(row, 'Baseplate')} · channel {_s(row, 'Channel_No')} · CHARM_No {_s(row, 'CHARM_No')}"),
        ("CHARM", f"{_s(row, 'CHARM Type')} on terminal block {_s(row, 'CHARM TB Part No')}" + (f" (TB {tb})" if tb else "")),
        ("Controller", f"{_s(row, 'Controller')} in system cabinet {_s(row, 'System Cabinet')}"),
        ("DeltaV name", _s(row, "DSTName")),
    ]
