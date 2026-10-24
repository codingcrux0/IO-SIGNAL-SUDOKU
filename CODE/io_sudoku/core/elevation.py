"""Cabinet elevation drawings: a front and a rear view of each marshalling cabinet as SVG.

The front shows CIOC 1-2 and the rear CIOC 3-4 (the template's own 'Cabinet Side (F/R)').
Each CIOC is a column of 8 baseplates (baseplate 1 at the top) of 12 channel cells, so every
side has 192 cells.  Status is never shown by colour alone:
    Field          solid fill in the colour of the IO type
    Wired Spare    diagonal hatching in the IO colour
    Spare Slot     empty outline
    Cabinet Alarm  red border and the letter A
Every cell has a tooltip (tag, status, IO type, CHARM, cable/pair).  Output is deterministic,
all text is escaped, and there are no scripts or external references (print-friendly).
"""
from __future__ import annotations

import re
from html import escape
from typing import Any

from io_sudoku.core.constants import BPS_PER_CIOC, CIOCS_PER_CAB, SLOTS_PER_BP, STATUS_ALARM, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED
from io_sudoku.core.naming import parse_bp
from io_sudoku.core.textnorm import to_int

STATUS_STYLE = {"Field": "solid", "Wired Spare": "hatched", "Spare Slot": "outline", "Cabinet Alarm": "alarm"}
IO_COLOURS = {"AIR": "#4C9AFF", "AOR": "#36B37E", "DIR": "#FFAB00", "DOR": "#FF5630"}
_CELL, _ROW, _LEFT, _TOP, _GAP = 22, 24, 52, 70, 34
_FAMILY = {"A": "A", "A-CONTROL": "A", "B": "B", "B-ALARM": "B"}


def _s(row: dict[str, Any], column: str) -> str:
    value = row.get(column)
    return "-" if value is None or str(value).strip() == "" else str(value).strip()


def _cioc_index(row: dict[str, Any]) -> int | None:
    digits = "".join(ch for ch in _s(row, "CIOC/CSLS Name")[-3:] if ch.isdigit())
    return ((int(digits) - 1) % CIOCS_PER_CAB + 1) if digits else None


def _esc(value: Any) -> str:
    return escape(str(value), quote=True)


def cabinet_svg(rows: list[dict[str, Any]], cabinet: str, side: str) -> str:
    """One side ('F' = CIOC 1-2, 'R' = CIOC 3-4) of one cabinet as an inline SVG string."""
    side = "R" if str(side).upper() == "R" else "F"
    uid = re.sub(r"[^A-Za-z0-9]+", "-", f"{cabinet}-{side}").strip("-") or f"cab-{side}"
    wanted = (1, 2) if side == "F" else (3, 4)
    label = f"{cabinet} - {'front' if side == 'F' else 'rear'}"
    mine = [r for r in rows if _s(r, "Electronic/ Marshalling Cabinet") == cabinet and _cioc_index(r) in wanted]
    if not mine:
        return (f'<svg viewBox="0 0 420 70" role="img" aria-labelledby="t-{_esc(uid)}"><title id="t-{_esc(uid)}">{_esc(label)}</title>'
                f'<text x="12" y="40" font-size="14" fill="#9aa4b2">No data for this cabinet.</text></svg>')
    cells: dict[tuple[int, int, int], dict[str, Any]] = {}
    names: dict[int, str] = {}
    families: dict[int, set[str]] = {i: set() for i in wanted}
    for r in mine:
        idx, bp, ch = _cioc_index(r), parse_bp(_s(r, "Baseplate")), to_int(r.get("Channel_No"))
        if idx is None or bp is None or ch is None:
            continue
        cells[(idx, bp, ch)] = r
        names.setdefault(idx, _s(r, "CIOC/CSLS Name"))
        if r.get("Tag Status") == STATUS_FIELD and _s(r, "Segregation").upper() in _FAMILY:
            families[idx].add(_FAMILY[_s(r, "Segregation").upper()])
    block = SLOTS_PER_BP * _CELL
    width = _LEFT + 2 * block + _GAP + 16
    height = _TOP + BPS_PER_CIOC * _ROW + 12
    out = [f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
           f'aria-labelledby="t-{_esc(uid)} d-{_esc(uid)}" font-family="system-ui, sans-serif">',
           f'<title id="t-{_esc(uid)}">{_esc(label)}</title>',
           f'<desc id="d-{_esc(uid)}">Elevation of {_esc(label)}: two CIOCs of eight baseplates with twelve channels each.</desc>',
           "<defs>"]
    for io, colour in IO_COLOURS.items():
        out.append(f'<pattern id="h-{_esc(uid)}-{io}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
                   f'<rect width="6" height="6" fill="#161b22"/><line x1="0" y1="0" x2="0" y2="6" stroke="{colour}" stroke-width="3"/></pattern>')
    out.append("</defs>")
    out.append(f'<text x="{_LEFT}" y="20" font-size="14" font-weight="700" fill="#e6edf3">{_esc(label)}</text>')
    for k, idx in enumerate(wanted):
        x0 = _LEFT + k * (block + _GAP)
        fams = families[idx]
        badge = next(iter(fams)) if len(fams) == 1 else ("A+B" if fams else "-")
        out.append(f'<text x="{x0}" y="{_TOP - 22}" font-size="11" fill="#c9d1d9">{_esc(names.get(idx, f"CIOC {idx}"))} (family {_esc(badge)})</text>')
        for bp in range(1, BPS_PER_CIOC + 1):
            y = _TOP + (bp - 1) * _ROW
            if k == 0:
                out.append(f'<text x="{_LEFT - 8}" y="{y + 15}" font-size="10" text-anchor="end" fill="#9aa4b2">BP {bp}</text>')
            for ch in range(1, SLOTS_PER_BP + 1):
                x = x0 + (ch - 1) * _CELL
                row = cells.get((idx, bp, ch))
                status = _s(row, "Tag Status") if row else STATUS_SLOT
                io = _s(row, "IO Type") if row else "-"
                colour = IO_COLOURS.get(io, "#8b949e")
                if status == STATUS_FIELD:
                    shape = f'fill="{colour}" stroke="#0b1220" stroke-width="1"'
                    ink = "#0b1220"
                elif status == STATUS_WIRED:
                    shape = f'fill="url(#h-{_esc(uid)}-{io})" stroke="{colour}" stroke-width="1.5"' if io in IO_COLOURS else 'fill="none" stroke="#8b949e"'
                    ink = "#ffffff"
                elif status == STATUS_ALARM:
                    shape = 'fill="#2b1d1d" stroke="#ff4d4f" stroke-width="2"'
                    ink = "#ffb3b3"
                else:
                    shape = 'fill="none" stroke="#6b7280" stroke-width="1"'
                    ink = "#6b7280"
                tag = _s(row, "Tag Name") if row else "-"
                cable = f"{_s(row, 'Field Cable No')}/{_s(row, 'Field Cable Pair')}" if row and _s(row, "Field Cable No") != "-" else "no cable"
                tip = f"{tag} · {status} · {io} · {_s(row, 'CHARM Type') if row else '-'} · {cable}"
                charm = _s(row, "CHARM_No") if row else str((bp - 1) * SLOTS_PER_BP + ch)
                glyph = f'<text x="{x + _CELL / 2}" y="{y + 9}" font-size="8" font-weight="700" text-anchor="middle" fill="#ff4d4f">A</text>' if status == STATUS_ALARM else ""
                # on the hatching, white numbers with a dark outline stay readable (paint-order draws the outline first)
                halo = ' font-weight="700" stroke="#0d1117" stroke-width="2.4" paint-order="stroke"' if status == STATUS_WIRED else ""
                out.append(f'<g class="cell" data-status="{_esc(status)}" data-slot="{_esc(f"{cabinet}~{idx}~{bp}~{ch}")}">'
                           f'<title>{_esc(tip)}</title>'
                           f'<rect x="{x}" y="{y}" width="{_CELL - 2}" height="{_CELL - 2}" rx="3" {shape}/>'
                           f'<text x="{x + _CELL / 2 - 1}" y="{y + 15}" font-size="8" text-anchor="middle" fill="{ink}"{halo}>{_esc(charm)}</text>{glyph}</g>')
    out.append("</svg>")
    return "".join(out)


def _legend() -> str:
    def swatch(inner: str, text: str) -> str:
        return f'<span class="key"><svg width="22" height="22" role="img" aria-label="{_esc(text)}">{inner}</svg>{_esc(text)}</span>'
    return "".join([
        swatch(f'<rect x="1" y="1" width="20" height="20" rx="3" fill="{IO_COLOURS["AIR"]}"/>', "Field signal (colour = IO type)"),
        swatch('<defs><pattern id="lg" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#161b22"/>'
               f'<line x1="0" y1="0" x2="0" y2="6" stroke="{IO_COLOURS["AIR"]}" stroke-width="3"/></pattern></defs>'
               f'<rect x="1" y="1" width="20" height="20" rx="3" fill="url(#lg)" stroke="{IO_COLOURS["AIR"]}"/>', "Wired spare (hatched)"),
        swatch('<rect x="1" y="1" width="20" height="20" rx="3" fill="none" stroke="#6b7280"/>', "Spare slot (empty outline)"),
        swatch('<rect x="1" y="1" width="20" height="20" rx="3" fill="#2b1d1d" stroke="#ff4d4f" stroke-width="2"/>'
               '<text x="11" y="15" font-size="11" text-anchor="middle" fill="#ff4d4f">A</text>', "Cabinet alarm"),
        "".join(f'<span class="key"><i style="background:{c}"></i>{io}</span>' for io, c in IO_COLOURS.items())])


def elevation_html(rows: list[dict[str, Any]], cabinets: list[str] | None = None) -> str:
    """A printable page with the front and rear elevation of every (or the chosen) cabinet."""
    names = cabinets if cabinets is not None else sorted({_s(r, "Electronic/ Marshalling Cabinet") for r in rows} - {"-"})
    parts = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Cabinet Elevation Drawings</title><style>',
             "body{background:#0d1117;color:#e6edf3;font-family:system-ui,sans-serif;margin:1.5rem}h1,h2{font-weight:700}",
             ".legend{display:flex;flex-wrap:wrap;gap:1rem;margin:1rem 0}.key{display:inline-flex;align-items:center;gap:.4rem;font-size:.85rem}",
             ".key i{display:inline-block;width:14px;height:14px;border-radius:3px}.pair{display:flex;flex-wrap:wrap;gap:1.5rem}",
             "section{margin-bottom:2rem;break-inside:avoid}@media print{body{background:#fff;color:#000}}</style></head><body>",
             "<h1>Cabinet Elevation Drawings</h1>", f'<div class="legend">{_legend()}</div>']
    if not names:
        parts.append("<p>No cabinets to draw.</p>")
    for cabinet in names:
        parts.append(f'<section><h2>{_esc(cabinet)}</h2><div class="pair">{cabinet_svg(rows, cabinet, "F")}{cabinet_svg(rows, cabinet, "R")}</div></section>')
    parts.append("</body></html>")
    return "\n".join(parts)
