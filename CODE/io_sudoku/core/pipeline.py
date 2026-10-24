"""The whole solver as one safe function: MDB in -> allocation rows + TQs out.

    ingest -> topology -> overrides -> validate -> blocks -> place -> spares -> rows -> verify

Every stage runs inside _guard(): if a stage raises an unexpected error, the error becomes
an INTERNAL TQ (with the traceback kept privately for the support bundle), the stage's
safe fallback value is used, and the later stages still run.  solve() therefore never raises.

The solver itself is 100% deterministic: no randomness, no clock, no AI.  Running it twice
on the same input gives rows with the same SHA-256 (see output_hash).
"""
from __future__ import annotations

import hashlib
import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from io_sudoku.core.allocio import CANONICAL_COLUMNS
from io_sudoku.core.assumptions import Assumption, applicable_assumptions
from io_sudoku.core.cables import CableBlock, build_blocks, link_groups
from io_sudoku.core.columnmap import ColumnMatch
from io_sudoku.core.config import Config, copy_config, load_config
from io_sudoku.core.constants import (
    BPS_PER_CIOC, CIOCS_PER_CAB, IO_TYPES, SLOTS_PER_BP, SLOTS_PER_CAB, STATUS_ALARM, STATUS_FIELD, STATUS_SLOT,
    STATUS_WIRED,
)
from io_sudoku.core.ingest import IngestResult, empty_result, read_mdb
from io_sudoku.core.models import Quarantined, Signal, Violation
from io_sudoku.core.overrides import Override, apply_overrides, overrides_to_json
from io_sudoku.core.place import PlanResult, alarm_kind, plan_and_place
from io_sudoku.core.readiness import Readiness, assess
from io_sudoku.core.rows import build_rows
from io_sudoku.core.spares import SpareLine, apply_spares
from io_sudoku.core.topology_infer import infer_cabinets
from io_sudoku.core.tq import TQ, TQLog
from io_sudoku.core.validate import Validated, validate
from io_sudoku.core.verify import verify

T = TypeVar("T")


@dataclass
class SolveResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    tqs: list[TQ] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)
    kpis: dict[str, Any] = field(default_factory=dict)
    spare_lines: list[SpareLine] = field(default_factory=list)
    stages_ms: dict[str, float] = field(default_factory=dict)
    traces: dict[str, list[str]] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    readiness: Readiness | None = None
    assumptions: list[Assumption] = field(default_factory=list)
    mapping: dict[str, ColumnMatch] = field(default_factory=dict)
    cfg_used: Config | None = None


def output_hash(rows: list[dict[str, Any]]) -> str:
    """SHA-256 fingerprint of the rows - the single definition used everywhere."""
    text = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _guard(name: str, fn: Callable[[], T], fallback: T, log: TQLog, diag: dict[str, Any]) -> T:
    """Run one stage; on an unexpected error record an INTERNAL TQ and return the fallback."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - this IS the last-resort safety net
        log.add("INTERNAL", name, f"The tool hit an unexpected problem in the '{name}' step "
                f"({type(exc).__name__}: {exc}). Please download the support bundle and report it.")
        diag.setdefault("tracebacks", {})[name] = traceback.format_exc()
        return fallback


def compute_kpis(rows: list[dict[str, Any]], spare_lines: list[SpareLine], quarantined: list[Quarantined],
                 tqs: list[TQ]) -> dict[str, Any]:
    """Headline numbers. Every ratio is guarded so empty input gives zeros, never an error."""
    status = {k: 0 for k in (STATUS_FIELD, STATUS_WIRED, STATUS_SLOT, STATUS_ALARM)}
    for r in rows:
        status[r.get("Tag Status")] = status.get(r.get("Tag Status"), 0) + 1
    per_cab: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        per_cab.setdefault(str(r.get("Electronic/ Marshalling Cabinet")), []).append(r)
    fill, future, empty_bps = {}, {}, {}
    for cab, items in per_cab.items():
        used = sum(1 for r in items if r.get("Tag Status") != STATUS_SLOT)
        free = sum(1 for r in items if r.get("Tag Status") == STATUS_SLOT)
        fill[cab] = round(100.0 * used / SLOTS_PER_CAB, 1)
        future[cab] = round(100.0 * free / SLOTS_PER_CAB, 1)
        by_bp: dict[tuple[str, str], bool] = {}
        for r in items:
            key = (str(r.get("CIOC/CSLS Name")), str(r.get("Baseplate")))
            empty = r.get("Tag Status") == STATUS_SLOT and r.get("Field Cable No") in ("-", None)
            by_bp[key] = by_bp.get(key, True) and empty
        empty_bps[cab] = sum(1 for v in by_bp.values() if v)
    compliant = sum(1 for line in spare_lines if line.wired >= line.quota)
    severity = {"error": 0, "warning": 0, "info": 0}
    for t in tqs:
        severity[t.severity] = severity.get(t.severity, 0) + 1
    placed = status[STATUS_FIELD] + status[STATUS_ALARM]
    return {
        "signals_in": placed + len(quarantined), "field": status[STATUS_FIELD], "wired_spare": status[STATUS_WIRED],
        "spare_slot": status[STATUS_SLOT], "cabinet_alarm": status[STATUS_ALARM], "quarantined": len(quarantined),
        "tq_error": severity["error"], "tq_warning": severity["warning"], "tq_info": severity["info"],
        "cabinets_used": len(per_cab), "rows": len(rows),
        "fill_pct_per_cabinet": fill, "empty_baseplates_per_cabinet": empty_bps, "future_space_pct_per_cabinet": future,
        "spare_compliance_pct": round(100.0 * compliant / len(spare_lines), 1) if spare_lines else 100.0,
        "output_sha256": output_hash(rows),
    }


def _alarm_problem(alarm: Signal, cfg: Config) -> str:
    """Which TQ explains why this alarm could not be placed."""
    if cfg.cabinet_for_equipment(alarm.equipment) is None:
        return "NO-CABINET-FOR-ALARM"
    if alarm_kind(alarm.tag) is None:
        return "ALARM-UNKNOWN-KIND"
    return "ALARM-OVERFLOW"


def solve(mdb_source: Any, cfg: Config | None = None, rev_label: str = "00", *,
          overrides: list[Override] | None = None, pins: dict[str, tuple[str, int]] | None = None,
          column_overrides: dict[str, str] | None = None) -> SolveResult:
    """Allocate every signal of an MDB. Never raises: problems become TQs and a readiness status."""
    return solve_core(mdb_source, cfg, rev_label, overrides=overrides, pins=pins, column_overrides=column_overrides)


# A placer decides WHERE the cable blocks go: (blocks, validated, config, log) -> PlanResult.
Placer = Callable[[list[CableBlock], Validated, Config, TQLog], PlanResult]


def solve_core(mdb_source: Any, cfg: Config | None = None, rev_label: str = "00", *,
               overrides: list[Override] | None = None, pins: dict[str, tuple[str, int]] | None = None,
               column_overrides: dict[str, str] | None = None, placer: Placer | None = None) -> SolveResult:
    """solve() with a pluggable placement step (the revision engine plugs in its own).

    Every other stage - reading, validation, spares, rows, verification, readiness - is
    identical, so a revision gets exactly the same safety net as a first run."""
    log, diag = TQLog(), {"tracebacks": {}}
    timings: dict[str, float] = {}
    cfg_used = copy_config(cfg) if cfg is not None else load_config()     # never mutate the caller's config

    def stage(name: str, fn: Callable[[], T], fallback: T) -> T:
        started = time.perf_counter()
        value = _guard(name, fn, fallback, log, diag)
        timings[name] = round((time.perf_counter() - started) * 1000, 2)
        return value

    ing: IngestResult = stage("ingest", lambda: read_mdb(mdb_source, log, column_overrides, cfg_used.rules.io_aliases),
                              empty_result())
    stage("topology", lambda: infer_cabinets(ing, cfg_used, log), 0)

    def apply_answers() -> None:
        if overrides:
            merged = apply_overrides(ing.signals + ing.alarms, overrides, cfg_used, log)
            ing.signals = [s for s in merged if not s.is_alarm]
            ing.alarms = [s for s in merged if s.is_alarm]
    stage("overrides", apply_answers, None)

    val: Validated = stage("validate", lambda: validate(ing, cfg_used, log), Validated())

    def make_blocks() -> tuple[list[CableBlock], list[Quarantined]]:
        blocks, bad = build_blocks(val.accepted, val.size_by_cable, cfg_used, log)
        link_groups(blocks, log)
        usable = []
        for block in blocks:
            if block.group_id == -2:
                bad.extend(Quarantined(s, "GROUP-SPANS-ROOMS") for s in block.signals.values())
            else:
                usable.append(block)
        return usable, bad
    blocks, block_bad = stage("blocks", make_blocks, ([], []))

    def default_placer(blocks_: list[CableBlock], val_: Validated, cfg_: Config, log_: TQLog) -> PlanResult:
        return plan_and_place(blocks_, val_.alarms, cfg_, log_, pins=pins)

    chosen = placer or default_placer
    plan: PlanResult = stage("place", lambda: chosen(blocks, val, cfg_used, log), PlanResult())
    lines = stage("spares", lambda: apply_spares(plan.grids, cfg_used, log, plan.traces), [])
    rows = stage("rows", lambda: build_rows(plan.grids, cfg_used, log, rev_label), [])

    later: list[Quarantined] = list(block_bad)
    for block in plan.unplaced:
        later.extend(Quarantined(s, "CAPACITY-OVERFLOW") for s in block.signals.values())
    later.extend(Quarantined(a, _alarm_problem(a, cfg_used)) for a in plan.alarms_unplaced)
    quarantined = sorted(val.quarantined + later, key=lambda q: (q.signal.sheet, q.signal.row_ref, q.signal.tag))

    gone = {q.signal.key for q in later}
    expected = {s.key for s in val.accepted + val.alarms if s.key} - gone
    violations = stage("verify", lambda: verify(rows, cfg_used, expected), [])

    result = SolveResult(
        rows=rows, tqs=log.items(), violations=violations, quarantined=quarantined, spare_lines=lines,
        stages_ms={**timings}, traces=plan.traces, diagnostics=diag, mapping=ing.mapping, cfg_used=cfg_used)
    result.kpis = stage("kpis", lambda: compute_kpis(rows, lines, quarantined, result.tqs), compute_kpis([], [], [], []))
    result.kpis["overrides_sha256"] = _sha(overrides_to_json(overrides or []))
    result.kpis["pins_sha256"] = _sha(json.dumps(pins or {}, sort_keys=True, default=str))
    result.tqs = log.items()                                  # include any TQs raised while finishing
    result.readiness = stage("readiness", lambda: assess(result), Readiness("DRAFT", ("Readiness could not be assessed.",)))
    result.assumptions = stage("assumptions", lambda: applicable_assumptions(result), [])
    result.tqs = log.items()
    result.stages_ms = dict(timings)
    result.stages_ms["total"] = round(sum(timings.values()), 2)
    return result
