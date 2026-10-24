"""The "5% client revision" simulator - the problem from the brief, as a number.

make_revision() writes an edited copy of an MDB (a given percentage of the field signals is
deleted, renamed, added or moved to another pair).  simulate_churn() then compares two ways of
handling that revision:

  naive        re-run the allocation from scratch on Rev B (what you get if you start over)
  incremental  our pinned re-solve: every unchanged tag keeps its Rev A slot

and counts how many tags moved in each case, with a rework-hours ESTIMATE from minutes per
change that the user can edit (the defaults are illustrative assumptions, not measurements).

The edits use a seeded pseudo-random generator, so the same seed always gives the same
revision.  This is the only module that uses randomness; the allocation never does.
"""
from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.columnmap import load_aliases
from io_sudoku.core.config import Config
from io_sudoku.core.ingest import _csv_tables, _get_bytes, _pick_header, _xlsx_tables
from io_sudoku.core.pipeline import solve
from io_sudoku.core.revision import ImpactReport, compare, solve_incremental
from io_sudoku.core.textnorm import clean, is_blank, match_key, to_int
from io_sudoku.core.validate import parse_cable_size

_WEIGHTS = (("deleted", 30), ("renamed", 20), ("added", 30), ("pair_change", 20))


@dataclass(frozen=True)
class ReworkMinutes:
    """Engineer minutes per change - ILLUSTRATIVE defaults, meant to be edited by the user."""

    per_moved_tag: float = 15.0
    per_renamed_tag: float = 3.0
    per_added_tag: float = 10.0
    per_deleted_tag: float = 5.0


@dataclass
class ChurnResult:
    edits: dict[str, int] = field(default_factory=lambda: {k: 0 for k, _ in _WEIGHTS})
    naive: ImpactReport = field(default_factory=ImpactReport)
    incremental: ImpactReport = field(default_factory=ImpactReport)
    naive_moved_pct: float = 0.0
    incremental_moved_pct: float = 0.0
    hours_naive: float = 0.0
    hours_incremental: float = 0.0
    hours_saved: float = 0.0


def _quotas(n: int) -> dict[str, int]:
    """Split n edits 30/20/30/20 by the largest-remainder method (deterministic)."""
    base = {k: n * w // 100 for k, w in _WEIGHTS}
    leftover = n - sum(base.values())
    by_fraction = sorted(_WEIGHTS, key=lambda kw: (-(n * kw[1] % 100), [k for k, _ in _WEIGHTS].index(kw[0])))
    for k, _ in by_fraction[:leftover]:
        base[k] += 1
    return base


def make_revision_with_edits(mdb_source: Any, pct: float = 5.0, seed: int = 1) -> tuple[bytes, dict[str, int]]:
    """(xlsx bytes of the edited MDB, how many edits of each kind were really applied)."""
    edits = {k: 0 for k, _ in _WEIGHTS}
    try:
        data = _get_bytes(mdb_source)
        tables = _xlsx_tables(data) if data[:2] == b"PK" else _csv_tables(data)
        sheet, rows = tables[0]
        header_index, mapping = _pick_header(rows, load_aliases(), None)
        idx = {name: m.index for name, m in mapping.items() if m.index is not None}
        for needed in ("tag", "cable_no", "pair_no"):
            if needed not in idx:
                raise ValueError(f"column {needed} not found")
        grid = [list(r) for r in rows]
        width = max(len(r) for r in grid)
        for r in grid:
            r.extend([None] * (width - len(r)))

        def cell(r: list[Any], name: str) -> Any:
            return r[idx[name]] if name in idx else None

        candidates: list[int] = []
        used: dict[str, set[int]] = {}
        sizes: dict[str, int] = {}
        for i in range(header_index + 1, len(grid)):
            r = grid[i]
            if all(is_blank(c) for c in r):
                continue
            status = (clean(cell(r, "status")) or "").casefold()
            kind = (clean(cell(r, "instrument_type")) or "").casefold()
            cable = match_key(cell(r, "cable_no"))
            pair = to_int(cell(r, "pair_no"))
            if status == "deleted" or "cabinet diagnostic alarm" in kind:
                continue
            if cable and cable != "internal wiring" and pair is not None:
                used.setdefault(cable, set()).add(pair)
                sizes.setdefault(cable, parse_cable_size(clean(cell(r, "cable_size"))) or max(used[cable]))
                if match_key(cell(r, "tag")):
                    candidates.append(i)
        candidates.sort(key=lambda i: match_key(cell(grid[i], "tag")) or "")
        n = min(len(candidates), round(pct / 100.0 * len(candidates)))
        rng = random.Random(seed)
        order = candidates[:]
        rng.shuffle(order)
        order = order[:n]
        quotas = _quotas(n)
        plan: dict[str, list[int]] = {}
        cursor = 0
        for kind_name, _ in _WEIGHTS:
            plan[kind_name] = order[cursor:cursor + quotas[kind_name]]
            cursor += quotas[kind_name]

        def free_pair(cable: str, avoid: int | None = None) -> int | None:
            return next((p for p in range(1, sizes.get(cable, 0) + 1) if p not in used[cable] and p != avoid), None)

        def set_pair(r: list[Any], number: int) -> None:
            r[idx["pair_no"]] = f"Pair {number}"

        drop: set[int] = set()
        appended: list[list[Any]] = []
        for i in plan["deleted"]:
            drop.add(i)
            edits["deleted"] += 1
        for i in plan["renamed"]:
            r = grid[i]
            old = clean(cell(r, "tag")) or ""
            r[idx["tag"]] = f"{old}-R"
            if "old_tag" in idx:
                r[idx["old_tag"]] = old
            if "tag_compact" in idx and clean(cell(r, "tag_compact")):
                r[idx["tag_compact"]] = f"{clean(cell(r, 'tag_compact'))}R"
            edits["renamed"] += 1
        for k, i in enumerate(plan["added"]):
            r = grid[i]
            cable = match_key(cell(r, "cable_no")) or ""
            copy = list(r)
            tag = clean(cell(r, "tag")) or ""
            copy[idx["tag"]] = f"{tag}-N"
            if "tag_compact" in idx and clean(cell(r, "tag_compact")):
                copy[idx["tag_compact"]] = f"{clean(cell(r, 'tag_compact'))}N"
            if "old_tag" in idx:
                copy[idx["old_tag"]] = "-"
            number = free_pair(cable) if k % 2 == 0 else None
            if number is not None:                                   # onto a free pair of the same cable
                used[cable].add(number)
                set_pair(copy, number)
            else:                                                    # onto a brand-new cable (a realistic revision)
                new_cable = f"{clean(cell(r, 'cable_no'))}-X"
                if match_key(new_cable) in used:
                    continue
                used[match_key(new_cable) or ""] = {1}
                sizes[match_key(new_cable) or ""] = sizes.get(cable, 12)
                copy[idx["cable_no"]] = new_cable
                set_pair(copy, 1)
            appended.append(copy)
            edits["added"] += 1
        for i in plan["pair_change"]:
            r = grid[i]
            cable = match_key(cell(r, "cable_no")) or ""
            current = to_int(cell(r, "pair_no"))
            number = free_pair(cable, avoid=current)
            if number is None:
                continue
            used[cable].discard(current) if current is not None else None
            used[cable].add(number)
            set_pair(r, number)
            edits["pair_change"] += 1

        out_rows = [r for i, r in enumerate(grid) if i not in drop] + appended
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = sheet[:31] or "MDB"
        for r in out_rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), edits
    except Exception:  # noqa: BLE001 - unreadable input: no revision, no edits
        return b"", {k: 0 for k, _ in _WEIGHTS}


def make_revision(mdb_source: Any, pct: float = 5.0, seed: int = 1) -> bytes:
    """An edited copy of the MDB as xlsx bytes (empty bytes if the MDB cannot be read)."""
    return make_revision_with_edits(mdb_source, pct, seed)[0]


def rework_hours(report: ImpactReport, m: ReworkMinutes) -> float:
    """Estimated hours of rework for the changes in `report` at `m` minutes per change."""
    c = report.counts
    minutes = (c.get("Moved", 0) * m.per_moved_tag + c.get("Renamed", 0) * m.per_renamed_tag
               + c.get("Added", 0) * m.per_added_tag + c.get("Deleted", 0) * m.per_deleted_tag)
    return round(minutes / 60.0, 2)


_hours = rework_hours


def simulate_churn(mdb_source: Any, pct: float = 5.0, seed: int = 1, minutes: ReworkMinutes = ReworkMinutes(),
                   cfg: Config | None = None) -> ChurnResult:
    """Naive re-allocation versus the pinned re-solve for a pct% revision. Never raises."""
    result = ChurnResult()
    try:
        base = solve(mdb_source, cfg)
        revised, edits = make_revision_with_edits(mdb_source, pct, seed)
        result.edits = edits
        if not revised or not base.rows:
            return result
        result.naive = compare(base.rows, solve(revised, cfg).rows)
        _, result.incremental = solve_incremental(revised, base.rows, cfg)
        tags = sum(1 for r in base.rows if r.get("Tag Status") in ("Field", "Cabinet Alarm")) or 1
        result.naive_moved_pct = round(100.0 * result.naive.counts.get("Moved", 0) / tags, 1)
        result.incremental_moved_pct = round(100.0 * result.incremental.counts.get("Moved", 0) / tags, 1)
        result.hours_naive = _hours(result.naive, minutes)
        result.hours_incremental = _hours(result.incremental, minutes)
        result.hours_saved = round(result.hours_naive - result.hours_incremental, 2)
    except Exception:  # noqa: BLE001
        pass
    return result
