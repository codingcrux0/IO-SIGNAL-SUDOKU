"""Pure helpers behind the Streamlit views (no widgets here, so they are testable without a browser).

Contents: the cached solve call, the cabinet-grid HTML, TQ filtering/paging, KPI cards, column
header listing and the download catalogue.  Anything that draws a widget lives in `views/`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from html import escape
from typing import Any

import streamlit as st

from io_sudoku.core import readiness as readiness_mod
from io_sudoku.core.allocio import build_allocation, load_template
from io_sudoku.core.bom import parts_report_bytes
from io_sudoku.core.config import Config, load_config
from io_sudoku.core.constants import (BPS_PER_CIOC, CIOCS_PER_CAB, SLOTS_PER_BP, STATUS_ALARM, STATUS_FIELD, STATUS_SLOT,
                                      STATUS_WIRED)
from io_sudoku.core.diagnostics import make_support_bundle
from io_sudoku.core.elevation import elevation_html
from io_sudoku.core.manifest import build_manifest
from io_sudoku.core.naming import parse_bp
from io_sudoku.core.overrides import Override, overrides_from_json
from io_sudoku.core.pipeline import SolveResult, solve
from io_sudoku.core.redline import redline_bytes
from io_sudoku.core.report import impact_report_bytes, tq_register_bytes, violations_bytes
from io_sudoku.core.rulepack import RulePack, apply_pack, default_pack, pack_from_dict, pack_hash, pack_to_dict
from io_sudoku.core.summary_html import build_summary_html
from io_sudoku.core.textnorm import to_int
from io_sudoku.core.trace import trace_bytes
from io_sudoku.core.tq import TQ
from io_sudoku.core.workspace import export_workspace

PAGE_SIZE = 100
TQ_FILTERS = ("all", "error", "warning", "info")
IO_SHORT = {"AIR": "AI", "AOR": "AO", "DIR": "DI", "DOR": "DO"}


# ------------------------------------------------------------------------------ solving
def pack_json(pack: RulePack) -> str:
    return json.dumps(pack_to_dict(pack), sort_keys=True)


def config_for_pack(pack: RulePack) -> Config:
    """The project config with the rule pack applied (an invalid pack changes nothing)."""
    return apply_pack(pack, load_config())


def pins_from_json(text: str) -> dict[str, tuple[str, int]]:
    """{cable: [cabinet, cioc]} JSON -> {cable: (cabinet, cioc)}; anything malformed is dropped."""
    out: dict[str, tuple[str, int]] = {}
    try:
        for cable, value in json.loads(text or "{}").items():
            if isinstance(value, (list, tuple)) and len(value) == 2 and to_int(value[1]) is not None:
                out[str(cable)] = (str(value[0]), int(to_int(value[1])))
    except (ValueError, AttributeError):
        pass
    return out


def solve_inputs(mdb_bytes: bytes, pack_text: str, overrides_text: str, pins_text: str, column_text: str,
                 rev_label: str) -> SolveResult:
    """The one place the UI turns its (all-text) inputs into a solve. Never raises (solve never does)."""
    try:
        pack = pack_from_dict(json.loads(pack_text)) if pack_text else default_pack()
    except ValueError:
        pack = default_pack()
    try:
        columns = {str(k): str(v) for k, v in json.loads(column_text or "{}").items()}
    except (ValueError, AttributeError):
        columns = {}
    return solve(mdb_bytes, config_for_pack(pack), rev_label or "00", overrides=overrides_from_json(overrides_text),
                 pins=pins_from_json(pins_text), column_overrides=columns)


@st.cache_data(max_entries=8, show_spinner=False)
def cached_solve(mdb_bytes: bytes, pack_text: str, overrides_text: str, pins_text: str, column_text: str,
                 rev_label: str) -> SolveResult:
    return solve_inputs(mdb_bytes, pack_text, overrides_text, pins_text, column_text, rev_label)


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


# --------------------------------------------------------------------------- revision history
@st.cache_data(max_entries=32, show_spinner=False)
def compare_snapshots(id_a: int, sha_a: str, id_b: int, sha_b: str, _a, _b):
    """Changes between two saved revisions (cached: the same pair is never compared twice)."""
    from io_sudoku.ui.history import compare_snapshots as run
    return run(_a, _b)


# --------------------------------------------------------------------------- editing the input
@st.cache_data(max_entries=4, show_spinner=False)
def editable_sheets(mdb_bytes: bytes) -> list:
    """The uploaded file as editable tables (cached per file version, so searching is instant)."""
    from io_sudoku.ui.editing import read_editable
    return read_editable(mdb_bytes)


@st.cache_data(max_entries=4, show_spinner=False)
def edit_index(mdb_bytes: bytes, column_text: str, pack_text: str):
    """Where each tag, cable and room is in the file (used by the Edit buttons of the TQ Board)."""
    from io_sudoku.core.rulepack import pack_from_dict
    from io_sudoku.ui.editing import build_index
    try:
        aliases = config_for_pack(pack_from_dict(json.loads(pack_text))).rules.io_aliases
    except Exception:  # noqa: BLE001
        aliases = None
    return build_index(mdb_bytes, json.loads(column_text or "{}"), aliases)


# --------------------------------------------------------------------------- column headers
def list_headers(mdb_bytes: bytes) -> list[str]:
    """Header texts of the sheet the solver would read first (for the column-mapping dropdowns)."""
    try:
        from io_sudoku.core import ingest
        from io_sudoku.core.columnmap import load_aliases
        tables = ingest._xlsx_tables(mdb_bytes) if mdb_bytes[:2] == b"PK" else ingest._csv_tables(mdb_bytes)
        aliases = load_aliases()
        best: list[str] = []
        for _name, rows in tables:
            header_index, _mapping = ingest._pick_header(rows, aliases, None)
            if header_index < len(rows):
                headers = [str(h).strip() for h in rows[header_index] if h is not None and str(h).strip()]
                if len(headers) > len(best):
                    best = headers
        return list(dict.fromkeys(best))
    except Exception:  # noqa: BLE001 - the mapping table is a convenience; the solver has its own reader
        return []


@st.cache_data(max_entries=8, show_spinner=False)
def is_allocation_file(mdb_bytes: bytes) -> bool:
    """True if the uploaded 'MDB' is really a finished IO Allocation (76-column template)."""
    try:
        from io_sudoku.core import allocinput, ingest
        tables = ingest._xlsx_tables(mdb_bytes) if mdb_bytes[:2] == b"PK" else ingest._csv_tables(mdb_bytes)
        for _name, rows in tables:
            first = next((r for r in rows[:10] if any(c is not None and str(c).strip() for c in r)), None)
            if first is not None and allocinput.detect(first) is not None:
                return True
    except Exception:  # noqa: BLE001 - only a hint for the Upload view
        pass
    return False


def blocking_questions(result: SolveResult, limit: int = 5) -> list[str]:
    """The first few distinct error questions, in plain words (shown under a BLOCKED or DRAFT badge)."""
    seen: list[str] = []
    for t in result.tqs:
        if t.severity == "error" and t.message not in seen:
            seen.append(t.message)
        if len(seen) >= limit:
            break
    return seen


# -------------------------------------------------------------------------------- the grid
def _cell_parts(row: dict[str, Any]) -> tuple[int, int, int] | None:
    digits = "".join(ch for ch in str(row.get("CIOC/CSLS Name") or "")[-3:] if ch.isdigit())
    bp, ch = parse_bp(str(row.get("Baseplate") or "")), to_int(row.get("Channel_No"))
    if not digits or bp is None or ch is None:
        return None
    return (int(digits) - 1) % CIOCS_PER_CAB + 1, bp, ch


def _slot_text(row: dict[str, Any]) -> tuple[str, str, str]:
    """(css class, visible cue, plain-language description) for one slot."""
    status = str(row.get("Tag Status") or STATUS_SLOT)
    io = str(row.get("IO Type") or "")
    if status == STATUS_FIELD:
        return f"s-field io-{io}", IO_SHORT.get(io, "F"), "Field"
    if status == STATUS_WIRED:
        return f"s-wired io-{io}", IO_SHORT.get(io, "W").lower(), "Wired Spare"
    if status == STATUS_ALARM:
        return "s-alarm", "!", "Cabinet Alarm"
    return "s-spare", "", "Spare Slot"


def cabinet_grid_html(rows: list[dict[str, Any]], cabinet: str) -> str:
    """The 4 x 8 x 12 slot grid of one cabinet as display-only HTML (every dynamic value escaped)."""
    slots: dict[tuple[int, int, int], dict[str, Any]] = {}
    for row in rows:
        if str(row.get("Electronic/ Marshalling Cabinet")) == cabinet:
            parts = _cell_parts(row)
            if parts:
                slots[parts] = row
    out = [f'<div class="iosg-grid" role="group" aria-label="Cabinet {escape(cabinet)} slot map">']
    for cioc in range(1, CIOCS_PER_CAB + 1):
        out.append(f'<section class="iosg-cioc" aria-label="CIOC {cioc}"><h4>CIOC {cioc}</h4>')
        for bp in range(1, BPS_PER_CIOC + 1):
            out.append(f'<div class="iosg-bp"><span class="iosg-bpn">{bp}</span>')
            for ch in range(1, SLOTS_PER_BP + 1):
                row = slots.get((cioc, bp, ch))
                if row is None:
                    out.append('<i class="iosg-slot s-none" role="img" aria-label="No data"></i>')
                    continue
                css, cue, kind = _slot_text(row)
                tag = str(row.get("Tag Name") or "-")
                io = str(row.get("IO Type") or "-")
                detail = f"{tag}, {kind}, {io}"
                cable = str(row.get("Field Cable No") or "-")
                pair = str(row.get("Field Cable Pair") or "-")
                pair = pair if pair.lower().startswith("pair") else f"pair {pair}"      # the template says 'Pair 6'
                if cable != "-":
                    detail += f", cable {cable} {pair}"
                label = f"Cabinet {cabinet}, CIOC {cioc}, baseplate {bp}, channel {ch}: {detail}"
                tip = "\n".join([tag, f"{kind} \u00b7 {IO_SHORT.get(io, io)} \u00b7 {row.get('CHARM Type') or '-'}",
                                  f"Cable {cable} \u00b7 {pair}" if cable != "-" else "No field cable",
                                  f"CIOC {cioc} \u00b7 BP {bp} \u00b7 CH {ch} \u00b7 CHARM {row.get('CHARM_No') or '-'}"])
                out.append(f'<i class="iosg-slot {css}" role="img" aria-label="{escape(label, quote=True)}" '
                           f'data-tip="{escape(tip, quote=True)}">{escape(cue)}</i>')
            out.append("</div>")
        out.append("</section>")
    out.append("</div>")
    return "".join(out)


# The cabinet drawings are SVG, which st.html removes (it allows HTML only), so each drawing is shown as a
# small page in an iframe.  The SVG comes from elevation.cabinet_svg, which escapes every value; the
# script only turns each cell's <title> into an instant hover card.
_DRAWING_PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0d1117;color:#e6edf3;color-scheme:dark;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
svg{display:block;max-width:100%;height:auto}
g.cell:hover rect{stroke:#fff;stroke-width:2.5}
#tip{position:fixed;display:none;pointer-events:none;white-space:pre;background:#0b0f14;color:#e6edf3;
border:1px solid #58a6ff;border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.45;z-index:9;
box-shadow:0 6px 18px rgba(0,0,0,.55)}
#tip b{font-weight:700}
</style></head><body>@SVG@<div id="tip" role="tooltip"></div><script>
(function () {
  var tip = document.getElementById("tip");
  document.querySelectorAll("g.cell").forEach(function (g) {
    var t = g.querySelector("title");
    if (!t) return;
    var p = t.textContent.split(" \u00b7 ");
    g.setAttribute("aria-label", t.textContent);
    g.dataset.tag = p[0] || "-";
    g.dataset.rest = [(p[1] || "-") + " \u00b7 " + (p[2] || "-"), "CHARM " + (p[3] || "-"),
                      p[4] === "no cable" ? "No field cable" : "Cable " + (p[4] || "-")].join("\n");
    t.remove();
  });
  function place(e) {
    var x = e.clientX + 14, y = e.clientY + 14, w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > innerWidth - 4) x = e.clientX - w - 14;
    if (y + h > innerHeight - 4) y = e.clientY - h - 14;
    tip.style.left = Math.max(4, x) + "px";
    tip.style.top = Math.max(4, y) + "px";
  }
  document.addEventListener("mouseover", function (e) {
    var g = e.target.closest && e.target.closest("g.cell");
    if (!g) { tip.style.display = "none"; return; }
    tip.textContent = "";
    var b = document.createElement("b");
    b.textContent = g.dataset.tag;
    tip.appendChild(b);
    tip.appendChild(document.createTextNode("\n" + g.dataset.rest));
    tip.style.display = "block";
    place(e);
  });
  document.addEventListener("mousemove", function (e) { if (tip.style.display === "block") place(e); });
  document.addEventListener("mouseleave", function () { tip.style.display = "none"; });
})();
</script></body></html>"""


def drawing_page(svg: str) -> tuple[str, int]:
    """(self-contained page, height in px) for one cabinet drawing, with instant hover cards."""
    import re
    match = re.search(r'<svg[^>]*\sheight="(\d+)"', svg)
    return _DRAWING_PAGE.replace("@SVG@", svg), (int(match.group(1)) if match else 300) + 6


@st.cache_data(max_entries=64, show_spinner=False)
def grid_html(result_key: str, cabinet: str, _rows: list[dict[str, Any]]) -> str:
    """Cached per (solve, cabinet); `_rows` is excluded from the cache key (the key identifies it)."""
    return cabinet_grid_html(_rows, cabinet)


def cabinet_names(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(r.get("Electronic/ Marshalling Cabinet")) for r in rows} - {"-", "None"})


# ----------------------------------------------------------------------------- TQ helpers
def filter_tqs(tqs: list[TQ], severity: str = "all", text: str = "") -> list[TQ]:
    needle = (text or "").strip().lower()
    return [t for t in tqs if (severity == "all" or t.severity == severity)
            and (not needle or needle in f"{t.tq_id} {t.ref} {t.message} {t.owner}".lower())]


def page_slice(items: list[Any], page: int, size: int = PAGE_SIZE) -> tuple[list[Any], int, int]:
    """(items on the page, clamped page number, page count)."""
    pages = max(1, -(-len(items) // size))
    page = min(max(0, int(page or 0)), pages - 1)
    return items[page * size:(page + 1) * size], page, pages


SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}
SEVERITY_LABEL = {"error": "● Error", "warning": "▲ Warning", "info": "ℹ Info"}     # shape + word, not colour alone
# (row background, row text, Severity cell text) - tinted to stay readable on the dark theme
SEVERITY_COLOURS = {"error": ("#3d1518", "#ffd8d5", "#ff7b72"), "warning": ("#3a2d0c", "#f6e3b0", "#e3b341"),
                    "info": ("#0f2740", "#d2e6ff", "#79c0ff")}


def by_severity(tqs: list[TQ]) -> list[TQ]:
    """Errors first, then warnings, then info; the original order is kept inside each group."""
    return sorted(tqs, key=lambda t: SEVERITY_RANK.get(t.severity, 3))


SIGNOFF_TEXT = {readiness_mod.APPROVED: "\u2713 Approved", readiness_mod.PROBLEM: "\u2717 Problem"}


def signoff_text(item: Any, signoffs: dict[str, str]) -> str:
    """'✓ Approved' / '✗ Problem' / 'Waiting' for a warning; '' for anything else."""
    if getattr(item, "severity", "") != "warning":
        return ""
    return SIGNOFF_TEXT.get(signoffs.get(readiness_mod.warning_key(item), ""), "Waiting")


def tq_rows(tqs: list[TQ], signoffs: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Table rows for TQs; with `signoffs`, a Sign-Off column shows each warning's state."""
    rows = []
    for t in tqs:
        row = {"ID": t.tq_id, "Severity": SEVERITY_LABEL.get(t.severity, t.severity)}
        if signoffs is not None:
            row["Sign-Off"] = signoff_text(t, signoffs)
        row.update({"Owner": t.owner, "Reference": t.ref, "Question": t.message, "Suggested Fix": t.resolution})
        rows.append(row)
    return rows


def warning_rows(result: SolveResult) -> list[tuple[str, str, str, str]]:
    """(warning key, id, reference, text) for every distinct warning to sign off, TQs then verifier findings."""
    seen: dict[str, tuple[str, str, str, str]] = {}
    for w in readiness_mod.warnings_of(result):
        key = readiness_mod.warning_key(w)
        if key not in seen:
            kind = getattr(w, "tq_id", None) or f"Check {getattr(w, 'rule', '')}"
            seen[key] = (key, kind, str(w.ref), str(w.message))
    return list(seen.values())


# ---------------------------------------------------------------------------------- KPIs
def kpi_cards(result: SolveResult) -> list[tuple[str, str]]:
    k = result.kpis or {}
    return [("Field Signals", f"{k.get('field', 0):,}"), ("Wired Spares", f"{k.get('wired_spare', 0):,}"),
            ("Cabinets Used", f"{k.get('cabinets_used', 0):,}"), ("Cabinet Alarms", f"{k.get('cabinet_alarm', 0):,}"),
            ("TQs Raised", f"{k.get('tq_error', 0) + k.get('tq_warning', 0) + k.get('tq_info', 0):,}"),
            ("Spare Compliance", f"{k.get('spare_compliance_pct', 100)}%")]


SPARES_ANCHOR = "wired-spares"
# Where each summary box on the Solve view leads: ('view', name) opens a view, ('anchor', id) scrolls the page.
KPI_LINKS: dict[str, tuple[str, str]] = {
    "Field Signals": ("view", "Cabinet Layout"), "Wired Spares": ("anchor", SPARES_ANCHOR),
    "Cabinets Used": ("view", "Cabinet Layout"), "Cabinet Alarms": ("view", "Cabinet Layout"),
    "TQs Raised": ("view", "TQ Board"), "Spare Compliance": ("anchor", SPARES_ANCHOR)}
# The tab of Cabinet Layout each box opens (the map for signals and alarms, the drawings for cabinets).
KPI_TABS: dict[str, str] = {"Field Signals": "Slot Map", "Cabinet Alarms": "Slot Map", "Cabinets Used": "Front & Rear Drawings"}


def readiness_text(result: SolveResult) -> tuple[str, list[str]]:
    r = result.readiness or readiness_mod.assess(result)
    return r.status, list(r.reasons)


# -------------------------------------------------------------------------------- downloads
@dataclass(frozen=True)
class DownloadSpec:
    key: str
    label: str
    needs: str = ""          # '' | 'impact' (only offered when a revision comparison exists)

    @property
    def title(self) -> str:
        """'Download TQ Register (.xlsx)' -> 'TQ Register' (used by the file viewer)."""
        return self.label.removeprefix("Download ").split(" (")[0]


DOWNLOADS: tuple[DownloadSpec, ...] = (
    DownloadSpec("allocation", "Download Allocation"),
    DownloadSpec("tq", "Download TQ Register (.xlsx)"),
    DownloadSpec("violations", "Download Verification List (.xlsx)"),
    DownloadSpec("impact", "Download Impact Report (.xlsx)", "impact"),
    DownloadSpec("redline", "Download Redline (.xlsx)", "impact"),
    DownloadSpec("parts", "Download Parts List (.xlsx)"),
    DownloadSpec("trace", "Download Decision Trace (.xlsx)"),
    DownloadSpec("summary", "Download Summary Page (.html)"),
    DownloadSpec("drawings", "Download Printable Drawings (.html)"),
    DownloadSpec("manifest", "Download Run Manifest (.json)"),
    DownloadSpec("workspace", "Download Workspace (.zip)"),
    DownloadSpec("support", "Download Support Bundle (.zip)"),
)


def available_downloads(has_impact: bool) -> list[DownloadSpec]:
    return [d for d in DOWNLOADS if not d.needs or (d.needs == "impact" and has_impact)]


def build_download(key: str, ctx: dict[str, Any]) -> tuple[bytes, str, str]:
    """(bytes, file name, mime) for one download.  `ctx` holds result, mdb_bytes, pack, overrides, pins,
    rev_label, template_bytes, impact, rev_a_rows.  File names carry the readiness suffix."""
    result: SolveResult = ctx["result"]
    status, _ = readiness_text(result)
    suffix = readiness_mod.suffix(status)
    rev = ctx.get("rev_label") or "00"
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    template = load_template(ctx["template_bytes"]) if ctx.get("template_bytes") else None
    cfg = result.cfg_used or load_config()
    if key == "allocation":
        data, report = build_allocation(result.rows, template)
        return data, f"IO_Allocation_Rev{rev}{suffix}{report.filename_ext}", report.content_type
    if key == "tq":
        return (tq_register_bytes(result.tqs, result.quarantined, ctx.get("tq_diff"), result.assumptions),
                f"TQ_Register_Rev{rev}.xlsx", xlsx)
    if key == "violations":
        return violations_bytes(result.violations), f"Verification_Rev{rev}.xlsx", xlsx
    if key == "impact" and ctx.get("impact") is not None:
        return impact_report_bytes(ctx["impact"], ctx.get("rev_a_rows"), result.rows), f"Impact_Report_Rev{rev}.xlsx", xlsx
    if key == "redline" and ctx.get("impact") is not None:
        data, report = redline_bytes(result.rows, ctx["impact"], template)
        return data, f"Redline_Rev{rev}{report.filename_ext}", report.content_type
    if key == "parts":
        return parts_report_bytes(result.rows, cfg), f"Parts_List_Rev{rev}.xlsx", xlsx
    if key == "trace":
        return trace_bytes(result), f"Decision_Trace_Rev{rev}.xlsx", xlsx
    manifest = build_manifest(ctx["mdb_bytes"], ctx["pack"], result)
    if key == "summary":
        html = build_summary_html(result, manifest, result.readiness or readiness_mod.assess(result), result.assumptions)
        return html.encode("utf-8"), f"Summary_Rev{rev}{suffix}.html", "text/html"
    if key == "drawings":
        return elevation_html(result.rows).encode("utf-8"), f"Cabinet_Drawings_Rev{rev}{suffix}.html", "text/html"
    if key == "manifest":
        return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"), f"Run_Manifest_Rev{rev}.json", "application/json"
    if key == "workspace":
        return (export_workspace(result, ctx["pack"], ctx["overrides"], ctx["pins"], manifest["input_sha256"], rev),
                f"Workspace_Rev{rev}.zip", "application/zip")
    if key == "support":
        info = {"name": ctx["pack"].name, "version": ctx["pack"].version, "hash": pack_hash(ctx["pack"])}
        return make_support_bundle(result, manifest["input_sha256"], info), f"Support_Bundle_Rev{rev}.zip", "application/zip"
    return b"", f"unknown_{key}.txt", "text/plain"


@st.cache_data(max_entries=32, show_spinner=False)
def cached_download(result_key: str, key: str, _ctx: dict[str, Any]) -> tuple[bytes, str, str]:
    return build_download(key, _ctx)


def bundle_all_name(ctx: dict[str, Any]) -> str:
    status, _ = readiness_text(ctx["result"])
    return f"IO_Sudoku_Files_Rev{ctx.get('rev_label') or '00'}{readiness_mod.suffix(status)}.zip"


def bundle_all(result_key: str, ctx: dict[str, Any]) -> bytes:
    """Every available file of one result in a single ZIP (built on click, from the cached files)."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for spec in available_downloads(ctx.get("impact") is not None):
            try:
                data, name, _mime = cached_download(result_key, spec.key, ctx)
            except Exception:  # noqa: BLE001 - one broken report must not block the others
                continue
            if data:
                zf.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data)
    return buf.getvalue()


def overrides_summary(overrides: list[Override]) -> list[dict[str, Any]]:
    return [{"Tag": o.tag_key, "Field": o.field, "Value": o.value, "By": o.by, "Note": o.note} for o in overrides]


def clip(text: Any, limit: int = 60) -> str:
    s = str(text)
    return s if len(s) <= limit else s[: limit - 1] + "…"

