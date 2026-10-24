"""Allocation Health Check: audit ANY allocation, including one a human made.

audit_allocation() reads an allocation workbook, runs the independent verifier on it, and
reports a 0-100 health score, the broken rules, the wired-spare table per controller and IO
type, and the future-space picture.  scorecard() puts a human allocation next to the tool's
own result for the same project (the "Human vs IO Sudoku" comparison).  Nothing is changed.

Score = 100 - 15 x (distinct error rules) - 3 x (distinct warning rules)
            - min(25, error violations // 4), kept between 0 and 100.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html import escape
from typing import Any

from io_sudoku.core.allocio import TemplateSpec, looks_like_allocation, read_allocation
from io_sudoku.core.config import Config, copy_config, load_config
from io_sudoku.core.constants import BPS_PER_CIOC, CIOCS_PER_CAB, IO_TYPES, SLOTS_PER_CAB, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED
from io_sudoku.core.models import Violation
from io_sudoku.core.report import _emit, _safe, _workbook_bytes
from io_sudoku.core.revision import cabinets_from_rows
from io_sudoku.core.textnorm import match_key
from io_sudoku.core.verify import verify


@dataclass
class HealthReport:
    rows: int = 0
    cabinets: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    by_rule: dict[str, int] = field(default_factory=dict)
    score: int = 0
    spare_table: list[dict[str, Any]] = field(default_factory=list)
    future_space: list[dict[str, Any]] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _s(row: dict[str, Any], column: str) -> str:
    value = row.get(column)
    return "-" if value is None or str(value).strip() == "" else str(value).strip()


def _spare_table(rows: list[dict[str, Any]], cfg: Config) -> list[dict[str, Any]]:
    field_n, wired_n = Counter(), Counter()
    for r in rows:
        key = (_s(r, "Controller"), _s(r, "IO Type"))
        if r.get("Tag Status") == STATUS_FIELD:
            field_n[key] += 1
        elif r.get("Tag Status") == STATUS_WIRED:
            wired_n[key] += 1
    table = []
    for controller, io in sorted(set(field_n) | set(wired_n), key=lambda k: (k[0], IO_TYPES.index(k[1]) if k[1] in IO_TYPES else 9)):
        need = -(-field_n[(controller, io)] * cfg.rules.spare_pct // 100)
        have = wired_n[(controller, io)]
        table.append({"Controller": controller, "IO Type": io, "Field": field_n[(controller, io)], "Required": need,
                      "Wired": have, "Status": "OK" if have == need else ("SHORT" if have < need else "EXCESS")})
    return table


def future_space(rows: list[dict[str, Any]], cfg: Config) -> list[dict[str, Any]]:
    """Per cabinet: Spare Slots, the requirement, and how many of the end baseplates are completely empty."""
    by_cab: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cab[_s(r, "Electronic/ Marshalling Cabinet")].append(r)
    out = []
    for cab in sorted(by_cab):
        members = by_cab[cab]
        slots = sum(1 for m in members if m.get("Tag Status") == STATUS_SLOT)
        by_bp: dict[tuple[str, str], bool] = {}
        for m in members:
            digits = "".join(ch for ch in _s(m, "CIOC/CSLS Name")[-3:] if ch.isdigit())
            if not digits or (int(digits) - 1) % CIOCS_PER_CAB + 1 != CIOCS_PER_CAB:
                continue
            tail = _s(m, "Baseplate").rsplit("-", 1)[-1]
            if not tail.isdigit() or int(tail) <= BPS_PER_CIOC - cfg.rules.end_reserve_bps:
                continue
            key = (_s(m, "CIOC/CSLS Name"), _s(m, "Baseplate"))
            by_bp[key] = by_bp.get(key, True) and m.get("Tag Status") == STATUS_SLOT and _s(m, "Field Cable No") == "-"
        out.append({"Cabinet": cab, "Spare Slots": slots, "Required": cfg.rules.future_slots_required(),
                    "Future space %": round(100.0 * slots / SLOTS_PER_CAB, 1), "Empty end baseplates": sum(1 for v in by_bp.values() if v)})
    return out


def audit_allocation(source: Any, cfg: Config | None = None, template: TemplateSpec | None = None) -> HealthReport:
    """Verify an allocation workbook. Never raises; an unreadable file gives rows=0 and score 0."""
    report = HealthReport()
    try:
        rows = read_allocation(source, template)
        if not looks_like_allocation(rows):
            report.notes.append("The file could not be read as an IO Allocation. Check it is the 76-column workbook.")
            return report
        merged = copy_config(cfg) if cfg is not None else load_config()
        known = {match_key(c.marshalling) for c in merged.cabinets}
        merged.cabinets.extend(c for c in cabinets_from_rows(rows) if match_key(c.marshalling) not in known)
        report.rows = len(rows)
        report.cabinets = sorted({_s(r, "Electronic/ Marshalling Cabinet") for r in rows})
        report.violations = verify(rows, merged, None)
        report.by_rule = dict(sorted(Counter(v.rule for v in report.violations).items()))
        errors = [v for v in report.violations if v.severity == "error"]
        error_rules = {v.rule for v in errors}
        warning_rules = {v.rule for v in report.violations if v.severity == "warning"}
        report.score = max(0, min(100, 100 - 15 * len(error_rules) - 3 * len(warning_rules) - min(25, len(errors) // 4)))
        report.spare_table = _spare_table(rows, merged)
        report.future_space = future_space(rows, merged)
        report.status_counts = dict(Counter(_s(r, "Tag Status") for r in rows))
    except Exception:  # noqa: BLE001
        report.notes.append("The audit stopped unexpectedly. Please download the support bundle and report it.")
    return report


def scorecard(human: HealthReport, machine: Any, machine_seconds: float) -> list[dict[str, Any]]:
    """Human allocation vs the tool's own result, as 8 comparable metrics."""
    m_rows = getattr(machine, "rows", []) or []
    m_cfg = getattr(machine, "cfg_used", None) or load_config()
    m_violations = list(getattr(machine, "violations", []) or [])
    m_spares = _spare_table(m_rows, m_cfg)
    m_future = future_space(m_rows, m_cfg)
    kpis = getattr(machine, "kpis", {}) or {}
    rules = lambda vs: ", ".join(sorted({v.rule for v in vs if v.severity == "error"})) or "none"   # noqa: E731
    ok_pct = lambda table: round(100.0 * sum(1 for x in table if x["Status"] == "OK") / len(table), 1) if table else 100.0   # noqa: E731
    low = lambda fs, key: min((x[key] for x in fs), default=0)   # noqa: E731
    return [
        {"Metric": "Rules broken", "Human allocation": rules(human.violations), "IO Sudoku": rules(m_violations)},
        {"Metric": "Total violations", "Human allocation": len(human.violations), "IO Sudoku": len(m_violations)},
        {"Metric": "Wired-spare compliance (%)", "Human allocation": ok_pct(human.spare_table), "IO Sudoku": ok_pct(m_spares)},
        {"Metric": "Cabinets used", "Human allocation": len(human.cabinets), "IO Sudoku": kpis.get("cabinets_used", len(m_future))},
        {"Metric": "Lowest future space (%)", "Human allocation": low(human.future_space, "Future space %"), "IO Sudoku": low(m_future, "Future space %")},
        {"Metric": "Fewest empty end baseplates", "Human allocation": low(human.future_space, "Empty end baseplates"), "IO Sudoku": low(m_future, "Empty end baseplates")},
        {"Metric": "TQs raised", "Human allocation": "-", "IO Sudoku": len(getattr(machine, "tqs", []) or [])},
        {"Metric": "Time taken", "Human allocation": "hours (manual)", "IO Sudoku": f"{machine_seconds:.1f} s"},
    ]


def health_report_bytes(report: HealthReport, card: list[dict[str, Any]] | None = None) -> bytes:
    def build() -> bytes:
        sheets = [
            ("Summary", ["Item", "Value"], [["Health score (0-100)", report.score], ["Rows", report.rows],
                                            ["Cabinets", ", ".join(report.cabinets) or "-"],
                                            ["Rules broken", ", ".join(f"{k} x{v}" for k, v in report.by_rule.items()) or "none"],
                                            *[["Note", n] for n in report.notes]]),
            ("Violations", ["Rule", "Severity", "Reference", "Message"], [[v.rule, v.severity, v.ref, v.message] for v in report.violations]),
            ("Spares", ["Controller", "IO Type", "Field", "Required", "Wired", "Status"],
             [[x[k] for k in ("Controller", "IO Type", "Field", "Required", "Wired", "Status")] for x in report.spare_table]),
            ("Future Space", ["Cabinet", "Spare Slots", "Required", "Future space %", "Empty end baseplates"],
             [[x[k] for k in ("Cabinet", "Spare Slots", "Required", "Future space %", "Empty end baseplates")] for x in report.future_space]),
        ]
        if card:
            sheets.append(("Scorecard", ["Metric", "Human allocation", "IO Sudoku"], [[c["Metric"], c["Human allocation"], c["IO Sudoku"]] for c in card]))
        return _workbook_bytes(sheets)
    return _safe(build)


def write_health_report(report: HealthReport, target: Any, card: list[dict[str, Any]] | None = None) -> None:
    _emit(target, health_report_bytes(report, card))


def health_html(report: HealthReport, card: list[dict[str, Any]] | None = None) -> str:
    """Self-contained, escaped, script-free page with the score, broken rules and scorecard."""
    def table(headers: list[str], rows: list[list[Any]]) -> str:
        head = "".join(f"<th>{escape(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>" for r in rows) or \
               f'<tr><td colspan="{len(headers)}">Nothing to show.</td></tr>'
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    colour = "#1a7f37" if report.score >= 90 else ("#b35900" if report.score >= 60 else "#cf222e")
    parts = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Allocation Health Check</title>',
             "<style>body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:60rem}table{border-collapse:collapse;width:100%}"
             "th,td{text-align:left;padding:.3rem .6rem;border-bottom:1px solid #ddd}th{background:#f6f8fa}"
             ".score{font-size:3rem;font-weight:700}</style></head><body>",
             "<h1>Allocation Health Check</h1>",
             f'<p class="score" style="color:{colour}">{report.score}<span style="font-size:1rem"> / 100</span></p>',
             f"<p>{report.rows} rows in {escape(', '.join(report.cabinets) or 'no cabinets')}.</p>"]
    parts += [f"<p>{escape(n)}</p>" for n in report.notes]
    parts.append("<h2>Rules broken</h2>")
    parts.append(table(["Rule", "Count"], [[k, v] for k, v in report.by_rule.items()]))
    parts.append("<h2>Wired spares</h2>")
    parts.append(table(["Controller", "IO type", "Field", "Required", "Wired", "Status"],
                       [[x["Controller"], x["IO Type"], x["Field"], x["Required"], x["Wired"], x["Status"]] for x in report.spare_table]))
    if card:
        parts.append("<h2>Human vs IO Sudoku</h2>")
        parts.append(table(["Metric", "Human allocation", "IO Sudoku"], [[c["Metric"], c["Human allocation"], c["IO Sudoku"]] for c in card]))
    parts.append("</body></html>")
    return "\n".join(parts)
