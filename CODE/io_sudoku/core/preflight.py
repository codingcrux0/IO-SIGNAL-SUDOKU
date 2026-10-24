"""Pre-flight check: how good is this MDB BEFORE we allocate anything?

Reads and validates the file (no placement) and reports a 0-100 score, how complete each
important column is, what the tool repaired silently (spacing, AI->AIR ...) and what needs a
human.  Score = 100 x (1 - (set-aside signals + 0.25 x signals with warnings) / rows), clamped
to 0-100; an unreadable or empty file scores 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.config import Config, copy_config, load_config
from io_sudoku.core.ingest import read_mdb
from io_sudoku.core.tq import TQ, TQLog
from io_sudoku.core.topology_infer import infer_cabinets
from io_sudoku.core.validate import validate


@dataclass
class ColumnStat:
    field: str
    header: str | None
    method: str
    filled: int
    total: int
    pct: float


@dataclass
class PreflightReport:
    score: int = 0
    columns: list[ColumnStat] = field(default_factory=list)
    issues: list[TQ] = field(default_factory=list)
    auto_fixed: dict[str, int] = field(default_factory=dict)
    needs_human: int = 0
    total_rows: int = 0


def preflight(source: Any, cfg: Config | None = None, column_overrides: dict[str, str] | None = None) -> PreflightReport:
    """Score and describe an MDB without allocating it. Never raises."""
    report = PreflightReport()
    log = TQLog()
    try:
        cfg_used = copy_config(cfg) if cfg is not None else load_config()
        ing = read_mdb(source, log, column_overrides, cfg_used.rules.io_aliases)
        infer_cabinets(ing, cfg_used, log)
        val = validate(ing, cfg_used, log)
        everyone = ing.signals + ing.alarms + ing.deleted
        for fld, match in ing.mapping.items():
            if match.index is None or not everyone or not hasattr(everyone[0], fld):
                continue
            filled = sum(1 for s in everyone if getattr(s, fld, None) not in (None, ""))
            report.columns.append(ColumnStat(fld, match.header, match.method, filled, len(everyone),
                                             round(100.0 * filled / len(everyone), 1)))
        report.auto_fixed = {k: ing.stats.get(k, 0) for k in ("whitespace_fixed", "io_alias_fixed", "deleted_excluded", "io_type2_rows")}
        report.needs_human = len(val.quarantined)
        report.total_rows = ing.rows_read
        warning_refs = {t.ref for t in log if t.severity == "warning"}
        if ing.rows_read == 0:
            report.score = 0
        else:
            raw = 100 * (1 - (report.needs_human + 0.25 * len(warning_refs)) / max(report.total_rows, 1))
            report.score = max(0, min(100, round(raw)))
    except Exception:  # noqa: BLE001
        log.add("INTERNAL", "preflight")
        report.score = 0
    report.issues = log.items()
    return report
