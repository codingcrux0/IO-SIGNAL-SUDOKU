"""Parts list, cable right-sizing advice and headroom forecast - all computed from the output rows.

* bom():               how many CHARMs, terminal blocks, baseplates, CIOCs and cabinets to buy
* cable_utilisation(): how full each cable is, with an ADVISORY when a smaller standard cable
                       would have been enough (engineering review required - never automatic)
* headroom():          how many more 24-, 12- or 6-pair cables each cabinet can still take
Nothing here changes the allocation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from io_sudoku.core.config import Config
from io_sudoku.core.constants import BPS_PER_CIOC, CIOCS_PER_CAB, SLOTS_PER_BP, STATUS_ALARM, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED
from io_sudoku.core.naming import parse_bp
from io_sudoku.core.report import _emit, _safe, _workbook_bytes
from io_sudoku.core.textnorm import match_key, to_int


def _s(row: dict[str, Any], column: str) -> str:
    value = row.get(column)
    return "-" if value is None or str(value).strip() == "" else str(value).strip()


def _cioc_index(row: dict[str, Any]) -> int | None:
    digits = "".join(ch for ch in _s(row, "CIOC/CSLS Name")[-3:] if ch.isdigit())
    return ((int(digits) - 1) % CIOCS_PER_CAB + 1) if digits else None


def bom(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parts per cabinet plus a TOTAL block: {'Cabinet', 'Part No', 'Description', 'Qty'}."""
    out: list[dict[str, Any]] = []
    total: Counter[tuple[str, str]] = Counter()
    by_cab: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cab[_s(r, "Electronic/ Marshalling Cabinet")].append(r)
    for cab in by_cab:
        members = by_cab[cab]
        counts: Counter[tuple[str, str]] = Counter()
        for r in members:
            counts[(_s(r, "CHARM Type"), _s(r, "Charm Description"))] += 1
            counts[(_s(r, "CHARM TB Part No"), _s(r, "CHARM TB Description"))] += 1
        used_bps = {(_s(r, "CIOC/CSLS Name"), _s(r, "Baseplate")) for r in members if r.get("Tag Status") != STATUS_SLOT}
        counts[("BASEPLATE", "CHARM baseplate (12 channels)")] = len(used_bps)
        counts[("CIOC/CSLS", "CIOC / CSLS I/O controller")] = len({c for c, _ in used_bps})
        counts[("CABINET", "Marshalling cabinet")] = 1
        for (part, desc), qty in sorted(counts.items()):
            out.append({"Cabinet": cab, "Part No": part, "Description": desc, "Qty": qty})
            total[(part, desc)] += qty
    for (part, desc), qty in sorted(total.items()):
        out.append({"Cabinet": "TOTAL", "Part No": part, "Description": desc, "Qty": qty})
    return out


def cable_utilisation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per cable: size, Field / Wired Spare / reserved pairs, utilisation and advice."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        cable = _s(r, "Field Cable No")
        if cable != "-" and r.get("Tag Status") != STATUS_ALARM:
            groups[(_s(r, "Electronic/ Marshalling Cabinet"), match_key(cable) or cable)].append(r)
    out: list[dict[str, Any]] = []
    for (cab, _key), members in sorted(groups.items()):
        size = len(members)
        field = sum(1 for m in members if m.get("Tag Status") == STATUS_FIELD)
        wired = sum(1 for m in members if m.get("Tag Status") == STATUS_WIRED)
        reserved = sum(1 for m in members if m.get("Tag Status") == STATUS_SLOT)
        used_pairs = [to_int(m.get("Field Cable Pair")) or 0 for m in members if m.get("Tag Status") in (STATUS_FIELD, STATUS_WIRED)]
        highest = max(used_pairs) if used_pairs else 0
        advice = "OK"
        for smaller in (6, 12, 24):
            if highest <= smaller < size:
                advice = (f"Could be {smaller}P (highest used pair {highest}) - engineering review required; "
                          "pair numbers are positional")
                break
        out.append({"Cabinet": cab, "Cable": _s(members[0], "Field Cable No"), "Size": size, "Field": field,
                    "Wired Spare": wired, "Reserved Pairs": reserved,
                    "Utilisation %": round(100.0 * (field + wired) / size, 1) if size else 0.0,
                    "Highest Used Pair": highest, "Advisory": advice})
    return out


def headroom(rows: list[dict[str, Any]], cfg: Config) -> list[dict[str, Any]]:
    """How many more cables each cabinet can take, counting only truly free, non-reserved channels."""
    reserve_from = BPS_PER_CIOC - cfg.rules.end_reserve_bps          # baseplates above this (CIOC 4) are the end reserve
    by_cab: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cab[_s(r, "Electronic/ Marshalling Cabinet")].append(r)
    out: list[dict[str, Any]] = []
    for cab in sorted(by_cab):
        free: dict[tuple[int, int], set[int]] = defaultdict(set)      # (cioc, bp) -> free channels
        reserved_pairs = 0
        seen: set[tuple[int, int]] = set()
        for r in by_cab[cab]:
            cioc, bp, ch = _cioc_index(r), parse_bp(_s(r, "Baseplate")), to_int(r.get("Channel_No"))
            if cioc is None or bp is None or ch is None:
                continue
            seen.add((cioc, bp))
            if r.get("Tag Status") == STATUS_SLOT and _s(r, "Field Cable No") != "-":
                reserved_pairs += 1
            alarm_bp = cioc == cfg.rules.alarm_cioc and bp == cfg.rules.alarm_bp
            end_reserve = cioc == CIOCS_PER_CAB and cfg.rules.end_reserve_bps > 0 and bp > reserve_from
            if r.get("Tag Status") == STATUS_SLOT and _s(r, "Field Cable No") == "-" and not alarm_bp and not end_reserve:
                free[(cioc, bp)].add(ch)
        free_bps = {k for k, chans in free.items() if len(chans) == SLOTS_PER_BP}
        pairs24 = 0
        for cioc in range(1, CIOCS_PER_CAB + 1):
            run = 0
            for bp in range(1, BPS_PER_CIOC + 1):
                if (cioc, bp) in free_bps:
                    run += 1
                else:
                    pairs24 += run // 2
                    run = 0
            pairs24 += run // 2
        halves = sum((all(c in chans for c in range(1, 7))) + (all(c in chans for c in range(7, 13))) for chans in free.values())
        out.append({"Cabinet": cab, "Free baseplates": len(free_bps), "Free 24-pair slots": pairs24,
                    "Free 12-pair slots": len(free_bps), "Free 6-pair slots": halves, "Unused wired pairs": reserved_pairs,
                    "Statement": f"Can still take {pairs24} x 24-pair, or {len(free_bps)} x 12-pair, or {halves} x 6-pair "
                                 f"cables before a new cabinet."})
    return out


def parts_report_bytes(rows: list[dict[str, Any]], cfg: Config) -> bytes:
    def build() -> bytes:
        b, c, h = bom(rows), cable_utilisation(rows), headroom(rows, cfg)
        return _workbook_bytes([
            ("BOM", ["Cabinet", "Part No", "Description", "Qty"], [[x["Cabinet"], x["Part No"], x["Description"], x["Qty"]] for x in b]),
            ("Cable Utilisation", ["Cabinet", "Cable", "Size", "Field", "Wired Spare", "Reserved Pairs", "Utilisation %", "Highest Used Pair", "Advisory"],
             [[x[k] for k in ("Cabinet", "Cable", "Size", "Field", "Wired Spare", "Reserved Pairs", "Utilisation %", "Highest Used Pair", "Advisory")] for x in c]),
            ("Headroom", ["Cabinet", "Free baseplates", "Free 24-pair slots", "Free 12-pair slots", "Free 6-pair slots", "Unused wired pairs", "Statement"],
             [[x[k] for k in ("Cabinet", "Free baseplates", "Free 24-pair slots", "Free 12-pair slots", "Free 6-pair slots", "Unused wired pairs", "Statement")] for x in h])])
    return _safe(build)


def write_parts_report(rows: list[dict[str, Any]], cfg: Config, target: Any) -> None:
    _emit(target, parts_report_bytes(rows, cfg))
