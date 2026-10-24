"""One-page summary of a run as a single self-contained HTML file.

Inline styles only: no scripts, no external links, no fonts to download - it opens offline
and prints cleanly.  Every piece of dynamic text is HTML-escaped, so a tag called
'<script>...' shows up as harmless text.  The output has no timestamps: the same run always
gives the same page.
"""
from __future__ import annotations

from collections import Counter
from html import escape
from typing import Any

_STYLE = """
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:2rem auto;max-width:60rem;color:#1b1f24;line-height:1.45}
h1{margin:0 0 .25rem}h2{margin:2rem 0 .5rem;border-bottom:1px solid #d0d7de;padding-bottom:.25rem}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:.3rem .6rem;border-bottom:1px solid #eaeef2}
th{background:#f6f8fa}.badge{display:inline-block;padding:.3rem .8rem;border-radius:.4rem;font-weight:700;color:#fff}
.ISSUE-READY{background:#1a7f37}.DRAFT{background:#b35900}.BLOCKED{background:#cf222e}
.ok{color:#1a7f37;font-weight:600}.bad{color:#cf222e;font-weight:600}.muted{color:#57606a}
@media print{body{margin:1rem}}
"""


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="muted">Nothing to show.</td></tr>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def build_summary_html(result: Any, manifest: dict[str, Any], readiness: Any, assumptions: list[Any]) -> str:
    """The summary page for a SolveResult."""
    kpis = getattr(result, "kpis", {}) or {}
    status = getattr(readiness, "status", "BLOCKED")
    reasons = list(getattr(readiness, "reasons", ()) or ())
    tqs = list(getattr(result, "tqs", []) or [])
    violations = list(getattr(result, "violations", []) or [])
    parts: list[str] = [
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>IO Allocation Summary</title><style>{_STYLE}</style></head><body>",
        "<h1>IO Allocation Summary</h1>",
        f'<p><span class="badge {escape(status)}">{escape(status)}</span></p>',
    ]
    if reasons:
        parts.append("<ul>" + "".join(f"<li>{escape(r)}</li>" for r in reasons) + "</ul>")

    parts.append("<h2>Key numbers</h2>")
    parts.append(_table(["Item", "Value"], [
        ["Field signals", kpis.get("field", 0)], ["Wired spares", kpis.get("wired_spare", 0)],
        ["Spare slots", kpis.get("spare_slot", 0)], ["Cabinet alarms", kpis.get("cabinet_alarm", 0)],
        ["Signals set aside", kpis.get("quarantined", 0)], ["Cabinets used", kpis.get("cabinets_used", 0)],
        ["Rows in the allocation", kpis.get("rows", 0)],
        ["TQs (errors / warnings / info)", f"{kpis.get('tq_error', 0)} / {kpis.get('tq_warning', 0)} / {kpis.get('tq_info', 0)}"],
        ["Wired-spare compliance", f"{kpis.get('spare_compliance_pct', 100)}%"]]))

    parts.append("<h2>Wired spares per controller and IO type</h2>")
    lines = list(getattr(result, "spare_lines", []) or [])
    parts.append(_table(["Controller", "IO type", "Field", "Required (10%)", "Wired", "Status"],
                        [[l.controller, l.io_type, l.field, l.quota, l.wired,
                          "OK" if l.shortfall == 0 else f"Short by {l.shortfall}"] for l in lines]))

    parts.append("<h2>Cabinets</h2>")
    fill = kpis.get("fill_pct_per_cabinet", {}) or {}
    future = kpis.get("future_space_pct_per_cabinet", {}) or {}
    empty = kpis.get("empty_baseplates_per_cabinet", {}) or {}
    parts.append(_table(["Cabinet", "Slots in use (%)", "Future space (%)", "Empty baseplates"],
                        [[c, fill.get(c, 0), future.get(c, 0), empty.get(c, 0)] for c in sorted(fill)]))

    parts.append("<h2>Technical queries</h2>")
    by_severity = Counter(t.severity for t in tqs)
    by_owner = Counter(t.owner for t in tqs)
    parts.append(_table(["Severity", "Count"], [[s, by_severity.get(s, 0)] for s in ("error", "warning", "info")]))
    parts.append(_table(["Owner", "Count"], [[o, n] for o, n in sorted(by_owner.items())]))

    parts.append("<h2>Verification</h2>")
    if violations:
        parts.append(_table(["Rule", "Severity", "Count"],
                            [[rule, sev, n] for (rule, sev), n in sorted(Counter((v.rule, v.severity) for v in violations).items())]))
    else:
        parts.append('<p class="ok">All rules passed: no violations were found.</p>')

    parts.append("<h2>Assumptions to confirm</h2>")
    parts.append(_table(["ID", "Assumption", "Confirm with"], [[a.id, a.text, a.confirm_by] for a in assumptions]))

    parts.append("<h2>Reproducibility</h2>")
    parts.append(_table(["Item", "Value"], [[k, manifest.get(k, "-")] for k in
                                            ("tool_version", "input_sha256", "pack_name", "pack_version", "pack_hash", "output_sha256")]))
    parts.append("</body></html>")
    return "\n".join(parts)
