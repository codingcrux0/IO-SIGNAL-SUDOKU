"""Revision engine: what changed between Rev A and Rev B, and a re-solve that moves nothing.

MODE 1 - compare(rows_a, rows_b)            (CLAUDE_RULES section 4)
    Tags are matched by Tag Name (case/space-insensitive) and sorted into FOUR categories:
      Added    the tag exists only in Rev B
      Deleted  the tag exists only in Rev A
      Moved    same tag, different cabinet / CIOC / baseplate / channel
      Renamed  different tag name but the SAME location (or Rev B's 'Old Tag' names the Rev A tag)
    A tag that is renamed AND relocated is reported once, as Moved ("also renamed").

MODE 2 - solve_incremental(mdb_b, rows_a)   (the differentiator)
    Re-solves Rev B but PINS every cable that still exists to the exact slot it had in Rev A,
    so unchanged tags do not move at all.  Deleted tags leave a reserved pair behind (their
    slot becomes a Spare Slot, or a Wired Spare if that IO type is short of spares), new tags
    use free pairs or a freshly placed cable, and wired spares are kept.  If Rev A cannot be
    mapped to the cabinets, we fall back to comparison only (REV-A-UNPARSEABLE).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.cables import CableBlock, block_length
from io_sudoku.core.config import CabinetCfg, Config, copy_config, load_config
from io_sudoku.core.constants import (
    REVISION_CATEGORIES, STATUS_ALARM, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED,
)
from io_sudoku.core.grid import CabinetGrid
from io_sudoku.core.naming import area4, parse_bp, parse_cioc_index
from io_sudoku.core.pipeline import SolveResult, Placer, output_hash, solve, solve_core
from io_sudoku.core.place import PlanResult, family_fits, plan_and_place
from io_sudoku.core.readiness import assess
from io_sudoku.core.textnorm import match_key, to_int
from io_sudoku.core.topology_infer import NAME_RE
from io_sudoku.core.tq import TQLog
from io_sudoku.core.validate import Validated

_FAMILY_RANK = {"A": 0, "B": 1, None: 2}
_TAG_ROWS = (STATUS_FIELD, STATUS_ALARM)


# ------------------------------------------------------------------------------ data types
@dataclass
class Change:
    category: str                    # Added | Deleted | Moved | Renamed (also 'Hardware' / 'Conversion' in side lists)
    tag: str
    old_tag: str | None = None
    a_loc: tuple | None = None       # (cabinet, CIOC name, baseplate, channel) in Rev A
    b_loc: tuple | None = None       # the same in Rev B
    note: str = ""


@dataclass
class ImpactReport:
    changes: list[Change] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {c: 0 for c in REVISION_CATEGORIES})
    conversions: list[Change] = field(default_factory=list)       # deleted tags whose slot is now a spare
    affected_cabinets: list[str] = field(default_factory=list)
    affected_cables: list[str] = field(default_factory=list)
    hardware_changes: list[Change] = field(default_factory=list)  # same tag, different CHARM
    unchanged: int = 0
    warnings: list[str] = field(default_factory=list)
    mode: str = "pinned"             # 'pinned' | 'compare-only'


def _s(row: dict[str, Any], column: str) -> str:
    value = row.get(column)
    return "-" if value is None or str(value).strip() == "" else str(value).strip()


def location(row: dict[str, Any]) -> tuple[str, str, str, int]:
    """Where a row sits: (cabinet, CIOC name, baseplate, channel)."""
    return (_s(row, "Electronic/ Marshalling Cabinet"), _s(row, "CIOC/CSLS Name"), _s(row, "Baseplate"),
            to_int(row.get("Channel_No")) or 0)


# ----------------------------------------------------------------------------------- compare
def _tag_rows(rows: list[dict[str, Any]], warnings: list[str], label: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("Tag Status") not in _TAG_ROWS:
            continue
        key = match_key(row.get("Tag Name"))
        if not key:
            continue
        if key in out:
            warnings.append(f"Revision {label}: tag {row.get('Tag Name')} appears more than once; the first was kept.")
            continue
        out[key] = row
    return out


def compare(rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]]) -> ImpactReport:
    """Added / Deleted / Moved / Renamed between two allocations. Never raises on odd rows."""
    report = ImpactReport()
    a = _tag_rows(rows_a or [], report.warnings, "A")
    b = _tag_rows(rows_b or [], report.warnings, "B")
    changes: list[Change] = []

    for key in sorted(set(a) & set(b)):
        la, lb = location(a[key]), location(b[key])
        if la == lb:
            report.unchanged += 1
        else:
            changes.append(Change("Moved", _s(b[key], "Tag Name"), None, la, lb))
        if _s(a[key], "CHARM Type") != _s(b[key], "CHARM Type"):
            report.hardware_changes.append(Change(
                "Hardware", _s(b[key], "Tag Name"), None, la, lb,
                f"{_s(a[key], 'CHARM Type')} -> {_s(b[key], 'CHARM Type')}"))

    a_only = sorted(set(a) - set(b))
    b_only = sorted(set(b) - set(a))
    taken_a: set[str] = set()
    taken_b: set[str] = set()

    for key in b_only:                                    # renamed through the explicit 'Old Tag' column
        old = match_key(b[key].get("Old Tag"))
        if old and old in a and old in set(a_only) and old not in taken_a:
            la, lb = location(a[old]), location(b[key])
            taken_a.add(old)
            taken_b.add(key)
            if la == lb:
                changes.append(Change("Renamed", _s(b[key], "Tag Name"), _s(a[old], "Tag Name"), la, lb))
            else:
                changes.append(Change("Moved", _s(b[key], "Tag Name"), _s(a[old], "Tag Name"), la, lb, "also renamed"))

    free_a = {location(a[k]): k for k in a_only if k not in taken_a}
    for key in b_only:                                    # renamed without an Old Tag: same slot, different tag
        if key in taken_b:
            continue
        lb = location(b[key])
        if lb in free_a:
            old = free_a.pop(lb)
            taken_a.add(old)
            taken_b.add(key)
            changes.append(Change("Renamed", _s(b[key], "Tag Name"), _s(a[old], "Tag Name"), location(a[old]), lb))

    b_by_loc = {location(r): r for r in rows_b or []}
    for key in a_only:
        if key in taken_a:
            continue
        la = location(a[key])
        changes.append(Change("Deleted", _s(a[key], "Tag Name"), None, la, None))
        now = b_by_loc.get(la)
        if now is not None and now.get("Tag Status") in (STATUS_SLOT, STATUS_WIRED):
            report.conversions.append(Change("Conversion", _s(a[key], "Tag Name"), None, la, la, f"now a {now.get('Tag Status')}"))
    for key in b_only:
        if key not in taken_b:
            changes.append(Change("Added", _s(b[key], "Tag Name"), None, None, location(b[key])))

    order = {c: i for i, c in enumerate(REVISION_CATEGORIES)}
    report.changes = sorted(changes, key=lambda c: (order[c.category], match_key(c.tag) or ""))
    report.counts = {c: sum(1 for ch in report.changes if ch.category == c) for c in REVISION_CATEGORIES}

    cabinets: set[str] = set()
    cables: set[str] = set()
    for change in report.changes:
        for loc in (change.a_loc, change.b_loc):
            if loc:
                cabinets.add(loc[0])
        for key_row in (a.get(match_key(change.old_tag or change.tag) or ""), b.get(match_key(change.tag) or "")):
            if key_row is not None and _s(key_row, "Field Cable No") != "-":
                cables.add(_s(key_row, "Field Cable No"))
    report.affected_cabinets = sorted(cabinets)
    report.affected_cables = sorted(cables)
    return report


# ------------------------------------------------------------------- reading Rev A's layout
@dataclass
class CableLayout:
    key: str
    cable_no: str
    cabinet: str
    cioc: int
    start: int            # first position (0-95) of the cable's run inside its CIOC
    rows: int             # pairs listed for the cable
    size_text: str | None = None


@dataclass
class WiredPos:
    cabinet: str
    cioc: int
    bp: int
    ch: int
    dsp: str
    io: str
    profile: str
    cable_key: str
    pair: int


@dataclass
class Layout:
    cabinets: list[CabinetCfg] = field(default_factory=list)      # cabinets Rev A uses that the config lacks
    cables: dict[str, CableLayout] = field(default_factory=dict)
    wired: list[WiredPos] = field(default_factory=list)
    unmapped_ratio: float = 0.0


def _most_common(values: list[Any], default: Any = None) -> Any:
    counts = Counter(v for v in values if v not in (None, "", "-"))
    if not counts:
        return default
    best = max(counts.values())
    return sorted((v for v, n in counts.items() if n == best), key=str)[0]


def cabinets_from_rows(rows: list[dict[str, Any]]) -> list[CabinetCfg]:
    """Self-describing cabinet definitions read from an allocation's own columns."""
    by_cab: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name = _s(row, "Electronic/ Marshalling Cabinet")
        if name != "-":
            by_cab.setdefault(name, []).append(row)
    cabinets: list[CabinetCfg] = []
    for name, members in by_cab.items():
        seqs = [int(m.group(1)) for m in (re.search(r"(\d{3})$", _s(r, "CIOC/CSLS Name")) for r in members) if m]
        cabinet_seq = ((min(seqs) - 1) // 4 + 1) if seqs else 1
        controller = _most_common([_s(r, "Controller") for r in members], "-")
        tail = re.search(r"(\d{2})$", controller)
        ctrl_seq = int(tail.group(1)) if tail else 1
        match = NAME_RE.match(name.upper())
        cioc_example = _most_common([_s(r, "CIOC/CSLS Name") for r in members], "")
        parsed = re.match(r"^(.*?)DCIOC(\d{4})\d{3}$", cioc_example)
        if match:
            loc, area5 = match.group("loc"), match.group("area5")
        else:
            loc = parsed.group(1) if parsed else name.split("-")[0]
            a4 = parsed.group(2) if parsed else "0000"
            area5 = f"{a4[:2]}0{a4[2:]}"
        if parsed and area4(area5) != parsed.group(2):          # keep CIOC names reproducible
            a4 = parsed.group(2)
            area5 = f"{a4[:2]}0{a4[2:]}"
        unit = _most_common([to_int(r.get("Unit")) for r in members], 0)
        cabinets.append(CabinetCfg(
            marshalling=name, system=_most_common([_s(r, "System Cabinet") for r in members], "-"),
            controller=controller, tech_room=_most_common([_s(r, "Technical Room") for r in members], "-"),
            loc=loc, area5=area5, unit=int(unit or 0), cabinet_seq=cabinet_seq, ctrl_seq=ctrl_seq))
    return cabinets


def _profile_from_hardware(io: str, charm: str, tb1: Any) -> str:
    if io == "AIR":
        return "AIR_4W" if _s({"x": tb1}, "x") == "-" else "AIR_2W"
    if io == "DOR":
        return "DOR_T02" if charm == "SE4302T02" else "DOR_T01"
    return {"AOR": "AOR", "DIR": "DIR"}.get(io, "AIR_2W")


def layout_from_rows(rows: list[dict[str, Any]], cfg: Config, log: TQLog) -> Layout:
    """Where every cable and wired spare of Rev A sits, plus the share of rows we could not map."""
    layout = Layout()
    known = {match_key(c.marshalling) for c in cfg.cabinets}
    layout.cabinets = [c for c in cabinets_from_rows(rows) if match_key(c.marshalling) not in known]
    all_cabs = {match_key(c.marshalling): c for c in cfg.cabinets + layout.cabinets}
    unmapped = 0
    per_cable: dict[tuple[str, str], list[tuple[int, int, int, int]]] = defaultdict(list)   # -> (cioc, pos, pair, row index)
    cable_text: dict[tuple[str, str], tuple[str, str | None]] = {}
    for index, row in enumerate(rows):
        cab = all_cabs.get(match_key(_s(row, "Electronic/ Marshalling Cabinet")) or "")
        cioc = parse_cioc_index(cab, _s(row, "CIOC/CSLS Name")) if cab else None
        bp, ch = parse_bp(_s(row, "Baseplate")), to_int(row.get("Channel_No"))
        if cab is None or cioc is None or bp is None or ch is None or not 1 <= ch <= 12:
            unmapped += 1
            continue
        pos = (bp - 1) * 12 + ch - 1
        status = row.get("Tag Status")
        if status == STATUS_WIRED:
            io = _s(row, "IO Type")
            pair = to_int(row.get("Field Cable Pair"))
            cable_key = match_key(row.get("Field Cable No")) or ""
            layout.wired.append(WiredPos(cab.marshalling, cioc, bp, ch, _s(row, "Tag Name"), io,
                                         _profile_from_hardware(io, _s(row, "CHARM Type"), row.get("CHARM TB1")),
                                         cable_key, pair or 0))
        cable_no = _s(row, "Field Cable No")
        if cable_no != "-" and status != STATUS_ALARM:
            pair = to_int(row.get("Field Cable Pair"))
            if pair is None:
                unmapped += 1
                continue
            key = (cab.marshalling, match_key(cable_no) or "")
            per_cable[key].append((cioc, pos, pair, index))
            cable_text.setdefault(key, (cable_no, None if _s(row, "Field Cable Size") == "-" else _s(row, "Field Cable Size")))
    by_cable_key: dict[str, list[tuple[str, list[tuple[int, int, int, int]]]]] = defaultdict(list)
    for (cab_name, ckey), members in per_cable.items():
        by_cable_key[ckey].append((cab_name, members))
    for ckey, parts in by_cable_key.items():
        starts = {(cab_name, c, p - (pair - 1)) for cab_name, members in parts for c, p, pair, _ in members}
        if len(parts) != 1 or len(starts) != 1:                   # cable spread out or out of order: cannot be pinned
            unmapped += sum(len(m) for _, m in parts)
            continue
        cab_name, members = parts[0]
        _, cioc_idx, start = next(iter(starts))
        text, size_text = cable_text[(cab_name, ckey)]
        layout.cables[ckey] = CableLayout(ckey, text, cab_name, cioc_idx, start, len(members), size_text)
    layout.unmapped_ratio = unmapped / len(rows) if rows else 1.0
    return layout


# ----------------------------------------------------------------------------------- stamping
def stamp_changes(rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]], report: ImpactReport,
                  rev_label: str) -> list[dict[str, Any]]:
    """Copy of Rev B with Change Type / Remarks / Old Tag / Revision No filled for changed rows only."""
    a_by_loc = {location(r): r for r in rows_a}
    changed = {c.b_loc: c for c in report.changes if c.b_loc and c.category in ("Added", "Moved", "Renamed")}
    deleted = {c.a_loc: c for c in report.changes if c.category == "Deleted" and c.a_loc}
    labels = {"Added": "Tag Added", "Moved": "Tag Moved", "Renamed": "Tag Renamed", "Deleted": "Tag Deleted"}
    out: list[dict[str, Any]] = []
    for row in rows_b:
        row = dict(row)
        loc = location(row)
        change = changed.get(loc) or deleted.get(loc)
        if change is not None:
            label = labels[change.category]
            if change.category == "Moved" and "renamed" in change.note:
                label = "Tag Moved (also renamed)"
            row["Change Type"] = change.category
            row["Revision No"] = rev_label
            existing = _s(row, "Remarks")
            row["Remarks"] = label if existing == "-" else (existing if label.lower() in existing.lower() else f"{label}; {existing}")
            if change.old_tag and _s(row, "Old Tag") == "-":
                row["Old Tag"] = change.old_tag
        else:
            before = a_by_loc.get(loc)
            same = before is not None and _s(before, "Tag Name") == _s(row, "Tag Name") and before.get("Tag Status") == row.get("Tag Status")
            row["Revision No"] = before.get("Revision No") if same else rev_label
        out.append(row)
    return out


# ------------------------------------------------------------------- the incremental placer
def _incremental_placer(layout: Layout, rows_a: list[dict[str, Any]], pins: dict[str, tuple[str, int]] | None) -> Placer:
    def place(blocks: list[CableBlock], val: Validated, cfg: Config, log: TQLog) -> PlanResult:
        grids: dict[str, CabinetGrid] = {}
        traces: dict[str, list[str]] = {}
        hints: dict[int, str] = {}
        new_blocks: list[CableBlock] = []

        def grid_of(cab: CabinetCfg) -> CabinetGrid:
            if cab.marshalling not in grids:
                grids[cab.marshalling] = CabinetGrid(cab, cfg.rules)
            return grids[cab.marshalling]

        def note(block: CableBlock, line: str) -> None:
            traces.setdefault(block.key, []).append(line)

        for block in blocks:
            shared = f" (shared logic {', '.join(block.logic_nos)})" if block.logic_nos else ""
            note(block, f"Cable {block.cable_no} ({block.declared_pairs} pairs) is in logic group {block.group_id}{shared}")

        ordered = sorted(blocks, key=lambda b: (_FAMILY_RANK.get(b.family, 2), b.key))
        stable = [b for b in ordered if b.key in layout.cables and b.length <= block_length(layout.cables[b.key].rows)]
        stable_keys = {b.key for b in stable}
        grown = [b for b in ordered if b.key in layout.cables and b.key not in stable_keys]
        for block in ordered:
            if block.key not in layout.cables:
                new_blocks.append(block)

        for block in stable + grown:                              # stable cables first, then cables that grew
            lay = layout.cables[block.key]
            cab = cfg.cabinet_by_marshalling(lay.cabinet)
            if cab is None:
                new_blocks.append(block)
                continue
            grid = grid_of(cab)
            step = 6 if block.length == 6 else 12
            fits = (lay.start % step == 0 and lay.start + block.length <= 96 and not (lay.cioc == 1 and lay.start < 12)
                    and not any(grid.occ[lay.cioc][lay.start:lay.start + block.length])
                    and family_fits(grid.cioc_family(lay.cioc), block.family))
            if fits:
                grid.place_block(block, lay.cioc, lay.start, origin="pinned")
                hints.setdefault(block.group_id, cab.marshalling)
                bp, ch = grid.pos_to_bp_ch(lay.start)
                note(block, f"Kept at its Rev A position: {cab.marshalling} CIOC {lay.cioc}, baseplate {bp}, channel {ch}")
            else:
                note(block, "Could not stay at its Rev A position, so it was placed again")
                new_blocks.append(block)

        for w in layout.wired:                                   # keep Rev A's wired spares where they were
            cab = cfg.cabinet_by_marshalling(w.cabinet)
            grid = grids.get(cab.marshalling) if cab else None
            cell = grid.cells.get((w.cioc, w.bp, w.ch)) if grid else None
            if cell is None or cell.cable_key != w.cable_key or cell.pair_no != w.pair:
                continue
            if cell.status == STATUS_SLOT:
                cell.status, cell.io_type, cell.profile, cell.dsp = STATUS_WIRED, w.io, w.profile, w.dsp
            elif cell.status == STATUS_FIELD:
                cell.remark = "Wired spare consumed"

        b_keys = {s.key for s in val.accepted + val.alarms}
        b_old = {match_key(s.old_tag) for s in val.accepted if s.old_tag}
        cab_by_name = {match_key(c.marshalling): c for c in cfg.cabinets}
        for row in rows_a:                                       # deleted tags leave a reserved pair behind
            key = match_key(row.get("Tag Name"))
            if row.get("Tag Status") != STATUS_FIELD or not key or key in b_keys or key in b_old:
                continue
            cab = cab_by_name.get(match_key(_s(row, "Electronic/ Marshalling Cabinet")) or "")
            grid = grids.get(cab.marshalling) if cab else None
            cioc = parse_cioc_index(cab, _s(row, "CIOC/CSLS Name")) if cab else None
            bp, ch = parse_bp(_s(row, "Baseplate")), to_int(row.get("Channel_No"))
            cell = grid.cells.get((cioc, bp, ch)) if grid and cioc and bp and ch else None
            if cell is not None and cell.status == STATUS_SLOT:
                cell.remark = "Tag Deleted"
                cell.former_io = _s(row, "IO Type") if _s(row, "IO Type") != "-" else None

        return plan_and_place(new_blocks, val.alarms, cfg, log, prebuilt=grids, pins=pins,
                              group_cabinet_hint=hints, traces=traces)
    return place


# ------------------------------------------------------------------------------- public API
def _finish(result: SolveResult, rows_a: list[dict[str, Any]], report: ImpactReport, rev_label: str) -> SolveResult:
    result.rows = stamp_changes(rows_a, result.rows, report, rev_label)
    result.kpis["output_sha256"] = output_hash(result.rows)
    result.readiness = assess(result)
    return result


def solve_incremental(mdb_b_source: Any, rows_a: list[dict[str, Any]], cfg: Config | None = None,
                      rev_label: str = "B", **solve_kwargs: Any) -> tuple[SolveResult, ImpactReport]:
    """Solve Rev B while keeping every surviving cable exactly where Rev A had it.

    Falls back to a plain comparison (mode 'compare-only') if Rev A cannot be mapped.
    Never raises.
    """
    rows_a = list(rows_a or [])
    cfg_in = copy_config(cfg) if cfg is not None else load_config()
    layout: Layout | None = None
    try:
        layout = layout_from_rows(rows_a, cfg_in, TQLog())
    except Exception:  # noqa: BLE001
        layout = None

    if layout is None or not rows_a or layout.unmapped_ratio >= 0.01:
        result = solve_core(mdb_b_source, cfg_in, rev_label, **solve_kwargs)
        report = compare(rows_a, result.rows)
        report.mode = "compare-only"
        extra = TQLog().add("REV-A-UNPARSEABLE", "")
        result.tqs = result.tqs + [extra]
        return _finish(result, rows_a, report, rev_label), report

    cfg_in.cabinets.extend(layout.cabinets)
    placer = _incremental_placer(layout, rows_a, solve_kwargs.get("pins"))
    result = solve_core(mdb_b_source, cfg_in, rev_label, placer=placer, **solve_kwargs)
    report = compare(rows_a, result.rows)
    report.mode = "pinned"
    return _finish(result, rows_a, report, rev_label), report


def solve_revision(mdb_a_source: Any, mdb_b_source: Any, cfg: Config | None = None, rev_label: str = "B",
                   **solve_kwargs: Any) -> tuple[SolveResult, SolveResult, ImpactReport]:
    """Solve Rev A fresh, then Rev B with Rev A's positions pinned. Returns (A, B, impact)."""
    result_a = solve(mdb_a_source, cfg, "00", **solve_kwargs)
    result_b, report = solve_incremental(mdb_b_source, result_a.rows, cfg, rev_label, **solve_kwargs)
    return result_a, result_b, report
