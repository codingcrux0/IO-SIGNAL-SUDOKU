"""Revision history: every allocation of the session is kept as a named snapshot that can be compared.

Pure logic (no widgets).  A snapshot stores the allocation rows COMPRESSED (zlib JSON, about 30-60 KB
for a 1,152-row allocation), plus a small summary, so dozens of revisions fit in memory.  The rows are
unpacked only when a comparison needs them.

Comparisons use the same revision engine as the Revision view (core.revision.compare): Added /
Deleted / Moved / Renamed by tag, so the numbers always agree with the impact report.
"""
from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.revision import ImpactReport, compare

MAX_SNAPSHOTS = 30
KPI_KEYS = ("field", "wired_spare", "cabinets_used", "cabinet_alarm", "spare_slot", "quarantined", "rows")


@dataclass
class Snapshot:
    id: int
    name: str
    source: str               # 'Allocation run' or 'Revision compare (Rev B)'
    file_name: str
    input_sha: str
    output_sha: str
    solve_key: str
    status: str
    reasons: tuple[str, ...]
    kpis: dict[str, Any]
    tq_counts: dict[str, int]
    created: str              # display only, never hashed
    rows_z: bytes = field(repr=False, default=b"")

    @property
    def label(self) -> str:
        return f"{self.name} · {self.file_name} · {self.status} · {self.created}"

    def rows(self) -> list[dict[str, Any]]:
        try:
            return json.loads(zlib.decompress(self.rows_z).decode("utf-8"))
        except Exception:  # noqa: BLE001 - a damaged snapshot compares as empty, it never crashes
            return []


def pack_rows(rows: list[dict[str, Any]]) -> bytes:
    return zlib.compress(json.dumps(rows, default=str, separators=(",", ":")).encode("utf-8"), 6)


def next_name(history: list[Snapshot]) -> str:
    """'Original' for the first snapshot, then 'Revision 1', 'Revision 2' ... (never reused)."""
    if not history:
        return "Original"
    used = {s.name for s in history}
    n = sum(1 for s in history if s.name != "Original") + 1
    while f"Revision {n}" in used:
        n += 1
    return f"Revision {n}"


def make_snapshot(history: list[Snapshot], result: Any, *, source: str, file_name: str, input_sha: str,
                  solve_key: str, created: str, name: str | None = None) -> Snapshot:
    readiness = getattr(result, "readiness", None)
    tqs = list(getattr(result, "tqs", []) or [])
    kpis = dict(getattr(result, "kpis", {}) or {})
    return Snapshot(
        id=max((s.id for s in history), default=0) + 1, name=name or next_name(history), source=source,
        file_name=file_name or "-", input_sha=input_sha or "", output_sha=str(kpis.get("output_sha256", "")),
        solve_key=solve_key or "", status=getattr(readiness, "status", "?"),
        reasons=tuple(getattr(readiness, "reasons", ()) or ()),
        kpis={k: kpis.get(k, 0) for k in KPI_KEYS},
        tq_counts={sev: sum(1 for t in tqs if t.severity == sev) for sev in ("error", "warning", "info")},
        created=created, rows_z=pack_rows(list(getattr(result, "rows", []) or [])))


def add(history: list[Snapshot], snap: Snapshot) -> list[Snapshot]:
    """History with `snap` added.  The same run twice in a row is stored once; the oldest revisions after
    the first are dropped beyond MAX_SNAPSHOTS (the first one, usually 'Original', is always kept)."""
    if history and history[-1].solve_key == snap.solve_key and history[-1].output_sha == snap.output_sha:
        return history
    out = history + [snap]
    while len(out) > MAX_SNAPSHOTS:
        out = out[:1] + out[2:]
    return out


def pairs(chosen: list[Snapshot], mode: str) -> list[tuple[Snapshot, Snapshot]]:
    """'previous': each with the one before it.  'first': each with the first one chosen."""
    if len(chosen) < 2:
        return []
    if mode == "first":
        return [(chosen[0], b) for b in chosen[1:]]
    return list(zip(chosen, chosen[1:]))


def compare_snapshots(a: Snapshot, b: Snapshot) -> ImpactReport:
    return compare(a.rows(), b.rows())


def summary_row(a: Snapshot, b: Snapshot, report: ImpactReport) -> dict[str, Any]:
    c = report.counts
    return {"From": a.name, "To": b.name, "Added": c.get("Added", 0), "Deleted": c.get("Deleted", 0),
            "Moved": c.get("Moved", 0), "Renamed": c.get("Renamed", 0), "Unchanged": report.unchanged,
            "Field Signals": f"{a.kpis.get('field', 0)} → {b.kpis.get('field', 0)}",
            "Status": f"{a.status} → {b.status}"}
