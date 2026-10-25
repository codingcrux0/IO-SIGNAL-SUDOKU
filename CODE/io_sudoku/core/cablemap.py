"""Cable view of the cabinets: which field cable lands on which CIOC, baseplate and channels.

The drawings show every signal.  This view shows the CABLES first: each field cable is one bar over the
baseplate channels its pairs land on (a 24-pair cable is two bars, one per baseplate, 'pairs 1-12 of 24' and
'pairs 13-24 of 24').  A thin strip under the bar shows what its pairs carry (colour = IO type).  Clicking a
cable in the page opens it: the bar splits into its pairs and a list of its signals appears below.  Clicking
a pair or a signal opens it on Rule Check, the same as a drawing cell.

Pure: rows in, data or a self-contained HTML page out.  Every value is escaped; deterministic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from typing import Any

from io_sudoku.core.constants import BPS_PER_CIOC, CIOCS_PER_CAB, SLOTS_PER_BP, STATUS_ALARM, STATUS_FIELD, STATUS_SLOT, STATUS_WIRED
from io_sudoku.core.elevation import IO_COLOURS, _cioc_index, _s
from io_sudoku.core.naming import parse_bp
from io_sudoku.core.textnorm import to_int
from io_sudoku.core.validate import parse_cable_size

CABINET = "Electronic/ Marshalling Cabinet"
SIDES = (("F", "Front (CIOC 1–2)", (1, 2)), ("R", "Rear (CIOC 3–4)", (3, 4)))


@dataclass(frozen=True)
class Slot:
    """One channel of a baseplate."""
    ch: int
    charm: str
    tag: str
    status: str
    io: str
    pair: int | None
    cable: str               # '-' = no field cable
    slot_id: str             # 'cabinet~cioc~bp~ch', the id Rule Check opens


@dataclass
class Run:
    """The channels one cable takes on one baseplate (consecutive channels)."""
    cable: str
    size: str
    total_pairs: int | None
    slots: list[Slot] = field(default_factory=list)

    @property
    def first(self) -> int:
        return self.slots[0].ch

    @property
    def last(self) -> int:
        return self.slots[-1].ch


def _esc(value: Any) -> str:
    return escape(str(value), quote=True)


def _pair_no(text: str) -> int | None:
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def _slots(rows: list[dict[str, Any]], cabinet: str) -> dict[int, dict[int, dict[int, tuple[Slot, dict]]]]:
    """cioc index -> baseplate -> channel -> (slot, row) for one cabinet."""
    out: dict[int, dict[int, dict[int, tuple[Slot, dict]]]] = {}
    for r in rows:
        if _s(r, CABINET) != cabinet:
            continue
        idx, bp, ch = _cioc_index(r), parse_bp(_s(r, "Baseplate")), to_int(r.get("Channel_No"))
        if idx is None or bp is None or ch is None or not 1 <= ch <= SLOTS_PER_BP:
            continue
        slot = Slot(ch, _s(r, "CHARM_No"), _s(r, "Tag Name"), _s(r, "Tag Status") if r.get("Tag Status") else STATUS_SLOT,
                    _s(r, "IO Type"), _pair_no(_s(r, "Field Cable Pair")), _s(r, "Field Cable No"),
                    f"{cabinet}~{idx}~{bp}~{ch}")
        out.setdefault(idx, {}).setdefault(bp, {})[ch] = (slot, r)
    return out


def runs_of(channels: dict[int, tuple[Slot, dict]]) -> list[Run | Slot]:
    """One baseplate, left to right: a Run for each cable's channels, a Slot for a channel without a cable."""
    out: list[Run | Slot] = []
    for ch in sorted(channels):
        slot, row = channels[ch]
        if slot.cable == "-":
            out.append(slot)
            continue
        last = out[-1] if out else None
        if isinstance(last, Run) and last.cable == slot.cable and last.last == ch - 1:
            last.slots.append(slot)
            continue
        size = _s(row, "Field Cable Size")
        out.append(Run(slot.cable, size, parse_cable_size(size if size != "-" else None), [slot]))
    return out


def cable_table(rows: list[dict[str, Any]], cabinets: list[str]) -> list[dict[str, Any]]:
    """Where each cable goes: one row per cable and cabinet, in cabinet / CIOC / baseplate / channel order."""
    out: list[dict[str, Any]] = []
    for cabinet in cabinets:
        found: dict[str, dict[str, Any]] = {}
        for idx, bps in sorted(_slots(rows, cabinet).items()):
            for bp, channels in sorted(bps.items()):
                for item in runs_of(channels):
                    if not isinstance(item, Run):
                        continue
                    name = next((r[1] for r in channels.values()), {})
                    row = found.setdefault(item.cable, {
                        "Cable": item.cable, "Size": item.size, "Pairs": item.total_pairs, "Cabinet": cabinet,
                        "CIOC": _s(name, "CIOC/CSLS Name"), "Side": "Front" if idx in (1, 2) else "Rear",
                        "_bps": [], "_charms": [], "Signals": 0, "Wired Spares": 0, "_io": set()})
                    row["_bps"].append(bp)
                    for slot in item.slots:
                        row["_charms"].append(slot.charm)
                        row["Signals"] += slot.status in (STATUS_FIELD, STATUS_ALARM)
                        row["Wired Spares"] += slot.status == STATUS_WIRED
                        if slot.status != STATUS_SLOT and slot.io in IO_COLOURS:
                            row["_io"].add(slot.io)
        for row in found.values():
            bps, charms = row.pop("_bps"), [c for c in row.pop("_charms") if c != "-"]
            row["Baseplates"] = f"BP {bps[0]}" if len(set(bps)) == 1 else f"BP {bps[0]}–{bps[-1]}"
            row["CHARMs"] = (charms[0] if len(charms) == 1 else f"{charms[0]}–{charms[-1]}") if charms else "-"
            row["IO Types"] = ", ".join(sorted(row.pop("_io"))) or "-"
            out.append(row)
    return out


# ----------------------------------------------------------------------------- the page
def _tip(slot: Slot) -> str:
    where = f"CHARM {slot.charm}" + (f" · pair {slot.pair}" if slot.pair else "")
    return "\n".join([slot.tag, f"{slot.status} · {slot.io}", where])


def _cell(slot: Slot, label: str) -> str:
    """One channel as a small clickable square (a pair of an open cable, or a channel without a cable)."""
    css = {STATUS_FIELD: "field", STATUS_WIRED: "wired", STATUS_ALARM: "alarm"}.get(slot.status, "spare")
    colour = IO_COLOURS.get(slot.io, "#8b949e")
    mark = '<em>!</em>' if slot.status == STATUS_ALARM else ""
    return (f'<i class="cell {css}" style="--io:{colour}" data-slot="{_esc(slot.slot_id)}" data-tip="{_esc(_tip(slot))}" '
            f'role="button" tabindex="0" aria-label="{_esc(_tip(slot))}">{mark}{_esc(label)}</i>')


_STRIP = {STATUS_FIELD: "f", STATUS_WIRED: "w", STATUS_ALARM: "a"}     # the strip under a cable: one mark per pair


def _bar(run: Run, key: str, part: str) -> str:
    n = len(run.slots)
    pairs = [sl.pair for sl in run.slots if sl.pair]
    of = f" of {run.total_pairs}" if run.total_pairs else ""
    span = (f"pair {pairs[0]}" if len(pairs) == 1 else f"pairs {pairs[0]}–{pairs[-1]}") + of if pairs else f"{n} channels"
    used = sum(sl.status in (STATUS_FIELD, STATUS_ALARM) for sl in run.slots)
    strip = "".join(f'<b class="{_STRIP.get(sl.status, "s")}" style="--io:{IO_COLOURS.get(sl.io, "#8b949e")}"></b>'
                    for sl in run.slots)
    cells = "".join(_cell(sl, str(sl.pair or sl.ch)) for sl in run.slots)
    tags = " ".join(sl.tag.lower() for sl in run.slots if sl.tag != "-")
    tip = f"{run.cable}{part}\n{span} · {used} signal{'s' * (used != 1)}\n{run.size}"
    return (f'<div class="bar" style="grid-column:{run.first + 1} / span {n}" data-cable="{key}" '
            f'data-name="{_esc(run.cable.lower())}" data-tags="{_esc(tags)}" data-tip="{_esc(tip)}" '
            f'role="button" tabindex="0" aria-expanded="false" aria-label="{_esc(f"Cable {run.cable}, {span}. Click to open it.")}">'
            f'<span class="head"><span class="nm">{_esc(run.cable)}</span><span class="pr">{_esc(span)}</span></span>'
            f'<span class="strip" style="grid-template-columns:repeat({n},1fr)">{strip}</span>'
            f'<span class="cells" style="grid-template-columns:repeat({n},1fr)">{cells}</span></div>')


def _loose(slots: list[Slot]) -> list[str]:
    """Channels without a cable: alarms as cells, runs of empty spare slots as one faint 'N spare' bar."""
    out: list[str] = []
    k = 0
    while k < len(slots):
        slot = slots[k]
        if slot.status != STATUS_SLOT:
            out.append(f'<span style="grid-column:{slot.ch + 1}">{_cell(slot, slot.charm)}</span>')
            k += 1
            continue
        j = k
        while j + 1 < len(slots) and slots[j + 1].status == STATUS_SLOT and slots[j + 1].ch == slots[j].ch + 1:
            j += 1
        n = j - k + 1
        out.append(f'<span class="free" style="grid-column:{slot.ch + 1} / span {n}" title="{n} spare channel'
                   f'{"s" * (n != 1)}, no cable">{n if n > 1 else ""}{" spare" if n > 2 else ""}</span>')
        k = j + 1
    return out


def _detail(cable: str, key: str, slots: list[tuple[int, Slot]], size: str) -> str:
    """The list of a cable's signals under its last baseplate, shown when the cable is opened."""
    rows = "".join(
        f'<tr data-slot="{_esc(sl.slot_id)}" tabindex="0"><td>{_esc(sl.pair or "-")}</td><td class="tg">{_esc(sl.tag)}</td>'
        f'<td><i class="dot" style="--io:{IO_COLOURS.get(sl.io, "#8b949e")}"></i>{_esc(sl.io)}</td><td>{_esc(sl.status)}</td>'
        f'<td>BP {bp} · ch {sl.ch} · CHARM {_esc(sl.charm)}</td></tr>'
        for bp, sl in slots)
    return (f'<div class="detail" data-cable="{key}" hidden><div class="dh"><b>{_esc(cable)}</b> <span>{_esc(size)}</span>'
            f'<a class="x" data-close="{key}" role="button" tabindex="0">Close ✕</a></div>'
            f'<table><thead><tr><th>Pair</th><th>Tag</th><th>IO</th><th>Status</th><th>Lands on</th></tr></thead>'
            f'<tbody>{rows}</tbody></table><p class="hint">Click a signal to check its rules.</p></div>')


def _cioc(idx: int, bps: dict[int, dict[int, tuple[Slot, dict]]], keys: dict[str, str], prefix: str) -> str:
    name = next((_s(r, "CIOC/CSLS Name") for chans in bps.values() for _, r in chans.values()), f"CIOC {idx}")
    side = "front" if idx in (1, 2) else "rear"
    laid = {bp: runs_of(chans) for bp, chans in bps.items()}
    cables = {it.cable for items in laid.values() for it in items if isinstance(it, Run)}
    busy = cables or any(isinstance(it, Slot) and it.status != STATUS_SLOT for items in laid.values() for it in items)
    head = (f'<h4>{_esc(name)} <span>CIOC {idx} · {side} · {len(cables)} cable{"s" * (len(cables) != 1)}</span></h4>')
    if not busy:
        return f'<div class="cioc empty">{head}<p class="none">No cables yet: all {BPS_PER_CIOC * SLOTS_PER_BP} channels are spare.</p></div>'
    last_bp: dict[str, int] = {}
    members: dict[str, list[tuple[int, Slot]]] = {}
    size_of: dict[str, str] = {}
    for bp in sorted(laid):
        for it in laid[bp]:
            if isinstance(it, Run):
                last_bp[it.cable] = bp
                members.setdefault(it.cable, []).extend((bp, sl) for sl in it.slots)
                size_of.setdefault(it.cable, it.size)
    out = [f'<div class="cioc">{head}']
    for bp in range(1, BPS_PER_CIOC + 1):
        items = laid.get(bp, [])
        seen: dict[str, int] = {}
        parts: list[str] = []
        loose: list[Slot] = []
        for it in items:
            if isinstance(it, Run):
                parts.extend(_loose(loose))
                loose = []
                key = keys.setdefault(it.cable, f"{prefix}c{len(keys)}")
                pieces = sum(1 for b in laid.values() for x in b if isinstance(x, Run) and x.cable == it.cable)
                seen[it.cable] = seen.get(it.cable, 0) + 1
                parts.append(_bar(it, key, f" ({seen[it.cable]}/{pieces})" if pieces > 1 else ""))
            else:
                loose.append(it)
        parts.extend(_loose(loose))
        if not items:
            parts.append(f'<span class="free" style="grid-column:2 / span {SLOTS_PER_BP}">{SLOTS_PER_BP} spare</span>')
        out.append(f'<div class="bp"><span class="lbl">BP {bp}</span>{"".join(parts)}</div>')
        for cable, at in last_bp.items():
            if at == bp:
                out.append(_detail(cable, keys[cable], members[cable], size_of[cable]))
    out.append("</div>")
    return "".join(out)


def cabinet_section(rows: list[dict[str, Any]], cabinet: str, number: int = 0) -> str:
    """One cabinet: front (CIOC 1-2) and rear (CIOC 3-4), every cable as a bar on its baseplates."""
    data = _slots(rows, cabinet)
    keys: dict[str, str] = {}
    prefix = f"k{number}"
    sides = []
    for _, title, wanted in SIDES:
        cards = "".join(_cioc(idx, data.get(idx, {}), keys, prefix) for idx in wanted if idx <= CIOCS_PER_CAB)
        sides.append(f'<div class="side"><h3>{_esc(title)}</h3><div class="pair">{cards}</div></div>')
    count = len(keys)
    return (f'<section class="cab" data-cab="{_esc(cabinet)}"><h2>{_esc(cabinet)} <span>{count} cable'
            f'{"s" * (count != 1)}</span></h2>{"".join(sides)}</section>')


_PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0d1117;color:#e6edf3;color-scheme:dark;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:13px}
body{overflow:auto;padding:0 4px 30px}
.tools{position:sticky;top:0;z-index:5;display:flex;gap:8px;align-items:center;padding:8px 0;background:#0d1117}
.tools input{flex:0 1 320px;background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 9px;font:inherit}
.tools input:focus{outline:none;border-color:#58a6ff}
.tools button{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:5px 10px;font:inherit;cursor:pointer}
.tools button:hover{border-color:#58a6ff;color:#fff}
.tools .msg{color:#8b949e}
section.cab{margin:0 0 26px}
h2{position:sticky;top:44px;z-index:4;margin:0 0 6px;padding:6px 2px;font-size:15px;background:#0d1117;border-bottom:1px solid #30363d}
h2 span,h4 span{font-weight:400;color:#8b949e;font-size:12px;margin-left:6px}
h3{margin:12px 0 6px;font-size:13px;color:#c9d1d9;font-weight:600}
.pair{display:flex;flex-wrap:wrap;gap:22px;align-items:flex-start}
.cioc{width:510px}
.cioc.empty{opacity:.8}
h4{margin:0 0 6px;font-size:12.5px;font-weight:600}
.none{margin:0;color:#8b949e;font-size:12px;border:1px dashed #30363d;border-radius:6px;padding:8px 10px}
.bp{display:grid;grid-template-columns:40px repeat(12,1fr);gap:3px;margin:0 0 4px;align-items:stretch;min-height:30px}
.lbl{grid-column:1;color:#9aa4b2;font-size:11px;align-self:center;text-align:right;padding-right:6px}
.free{border:1px dashed #2a313b;border-radius:5px;color:#4b5563;font-size:10px;display:flex;align-items:center;
justify-content:center;min-height:28px}
.bar{position:relative;display:flex;flex-direction:column;justify-content:space-between;min-width:0;cursor:pointer;
background:linear-gradient(#2a313c,#20262f);border:1px solid #3d4653;border-radius:14px 6px 6px 14px;padding:3px 7px 0 12px;
min-height:28px;box-sizing:border-box;transition:border-color .12s}
.bar::before{content:"";position:absolute;left:3px;top:50%;width:5px;height:5px;margin-top:-5px;border-radius:50%;
background:#8b949e;box-shadow:0 0 0 2px #161b22}
.bar:hover,.bar.hl,.bar:focus-visible{border-color:#58a6ff;outline:none}
.bar.open{border-color:#58a6ff;background:#161b22;border-radius:8px;padding:3px 4px 4px}
.bar.open::before{display:none}
.bar.found{box-shadow:0 0 0 2px #f2cc60}
.head{display:flex;gap:6px;align-items:baseline;min-width:0;white-space:nowrap;overflow:hidden}
.nm{font-weight:700;font-size:11.5px;overflow:hidden;text-overflow:ellipsis}
.pr{color:#8b949e;font-size:10.5px;overflow:hidden;text-overflow:ellipsis}
.strip{display:grid;gap:1px;height:4px;margin:2px 0 3px}
.strip b{border-radius:1px;background:#3b4452}
.strip b.f{background:var(--io)}
.strip b.a{background:#ff4d4f}
.strip b.w{background:repeating-linear-gradient(45deg,var(--io) 0 2px,transparent 2px 4px)}
.cells{display:none;gap:3px;margin-top:4px}
.bar.open .strip{display:none}
.bar.open .cells{display:grid}
.cell{display:flex;align-items:center;justify-content:center;flex-direction:column;font-style:normal;font-size:10px;
height:22px;border-radius:4px;cursor:pointer;box-sizing:border-box;border:1px solid #6b7280;color:#6b7280;line-height:1}
.cell.field{background:var(--io);border-color:#0b1220;color:#0b1220;font-weight:600}
.cell.wired{background:repeating-linear-gradient(45deg,var(--io) 0 3px,#161b22 3px 6px);border-color:var(--io);color:#fff;
font-weight:700;text-shadow:0 0 3px #000}
.cell.alarm{background:#2b1d1d;border:2px solid #ff4d4f;color:#ffb3b3}
.cell em{font-style:normal;color:#ff4d4f;font-weight:800;font-size:9px}
.cell:hover,.cell:focus-visible{outline:2px solid #fff;outline-offset:0}
.detail{margin:2px 0 10px 43px;border:1px solid #58a6ff;border-radius:8px;background:#0b1018;padding:6px 8px}
.dh{display:flex;gap:8px;align-items:baseline;margin-bottom:4px}
.dh span{color:#8b949e;font-size:11px}
.x{margin-left:auto;color:#58a6ff;cursor:pointer;font-size:11.5px}
table{border-collapse:collapse;width:100%;font-size:11.5px}
th{text-align:left;color:#8b949e;font-weight:500;padding:2px 6px;border-bottom:1px solid #30363d}
td{padding:3px 5px;border-bottom:1px solid #1c222b;white-space:nowrap}
td.tg{font-weight:600}
tbody tr{cursor:pointer}
tbody tr:hover,tbody tr:focus-visible{background:#1f2937;outline:none}
.dot{display:inline-block;width:8px;height:8px;border-radius:2px;background:var(--io);margin-right:5px}
.hint{margin:4px 0 0;color:#58a6ff;font-size:11px}
#tip{position:fixed;display:none;pointer-events:none;white-space:pre;background:#0b0f14;color:#e6edf3;
border:1px solid #58a6ff;border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.45;z-index:9;
box-shadow:0 6px 18px rgba(0,0,0,.55)}
#tip b{font-weight:700}
#tip i{color:#58a6ff;font-style:normal}
</style></head><body><div class="tools"><input id="find" placeholder="Find a cable or tag, then press Enter…" autocomplete="off"
aria-label="Find a cable or tag"><button id="all">Open All Cables</button><button id="none">Close All</button>
<span class="msg" id="msg"></span></div>@BODY@<div id="tip" role="tooltip"></div><script>
(function () {
  var tip = document.getElementById("tip"), msg = document.getElementById("msg");
  function group(bar) {
    var sec = bar.closest("section");
    return sec.querySelectorAll('[data-cable="' + bar.dataset.cable + '"]');
  }
  function setOpen(bar, open) {
    group(bar).forEach(function (el) {
      if (el.classList.contains("detail")) el.hidden = !open;
      else { el.classList.toggle("open", open); el.setAttribute("aria-expanded", open ? "true" : "false"); }
    });
  }
  function rules(slot) {
    try { if (window.parent.__iosgCell) window.parent.__iosgCell(slot); } catch (err) {}
  }
  function act(e) {
    var t = e.target;
    var x = t.closest && t.closest("[data-close]");
    if (x) {
      var b = x.closest("section").querySelector('.bar[data-cable="' + x.dataset.close + '"]');
      if (b) setOpen(b, false);
      return;
    }
    var c = t.closest && t.closest(".cell, tbody tr");
    if (c && c.dataset.slot) { rules(c.dataset.slot); return; }
    var bar = t.closest && t.closest(".bar");
    if (bar) setOpen(bar, !bar.classList.contains("open"));
  }
  document.addEventListener("click", act);
  document.addEventListener("keydown", function (e) {
    if ((e.key === "Enter" || e.key === " ") && e.target !== document.getElementById("find")) { e.preventDefault(); act(e); }
  });
  document.getElementById("all").onclick = function () { document.querySelectorAll(".bar").forEach(function (b) { setOpen(b, true); }); };
  document.getElementById("none").onclick = function () { document.querySelectorAll(".bar").forEach(function (b) { setOpen(b, false); }); };
  document.getElementById("find").addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    var q = this.value.trim().toLowerCase().replace(/\s+/g, " ");
    document.querySelectorAll(".bar.found").forEach(function (b) { b.classList.remove("found"); });
    if (!q) { msg.textContent = ""; return; }
    var hits = [].filter.call(document.querySelectorAll(".bar"), function (b) {
      return b.dataset.name.indexOf(q) >= 0 || b.dataset.tags.replace(/\s+/g, " ").indexOf(q) >= 0;
    });
    if (!hits.length) { msg.textContent = "No cable or tag matches “" + this.value.trim() + "”."; return; }
    hits.forEach(function (b) { b.classList.add("found"); setOpen(b, true); });
    msg.textContent = hits.length + " cable piece" + (hits.length === 1 ? "" : "s") + " found and opened.";
    hits[0].scrollIntoView({block: "center"});
  });
  document.addEventListener("mouseover", function (e) {
    var t = e.target.closest && e.target.closest(".cell, .bar");
    document.querySelectorAll(".bar.hl").forEach(function (b) { b.classList.remove("hl"); });
    if (!t) { tip.style.display = "none"; return; }
    if (t.classList.contains("bar")) group(t).forEach(function (el) { if (el.classList.contains("bar")) el.classList.add("hl"); });
    var lines = (t.dataset.tip || "").split("\n");
    tip.textContent = "";
    var b = document.createElement("b"); b.textContent = lines[0]; tip.appendChild(b);
    tip.appendChild(document.createTextNode("\n" + lines.slice(1).join("\n") + "\n"));
    var hint = document.createElement("i");
    hint.textContent = t.classList.contains("bar") ? (t.classList.contains("open") ? "Click the cable name to close it" : "Click to see its signals")
                                                     : "Click to check its rules";
    tip.appendChild(hint);
    tip.style.display = "block";
    place(e);
  });
  function place(e) {
    var x = e.clientX + 14, y = e.clientY + 14, w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > innerWidth - 4) x = e.clientX - w - 14;
    if (y + h > innerHeight - 4) y = e.clientY - h - 14;
    tip.style.left = Math.max(4, x) + "px"; tip.style.top = Math.max(4, y) + "px";
  }
  document.addEventListener("mousemove", function (e) { if (tip.style.display === "block") place(e); });
  document.addEventListener("mouseleave", function () { tip.style.display = "none"; });
})();
</script></body></html>"""


def page_height(rows: list[dict[str, Any]], cabinet: str) -> int:
    """About how tall one cabinet's page is with every cable closed (px), so its frame has no empty space."""
    data = _slots(rows, cabinet)

    def card(idx: int) -> int:
        busy = any(sl.cable != "-" or sl.status != STATUS_SLOT
                   for chans in data.get(idx, {}).values() for sl, _ in chans.values())
        return 24 + (BPS_PER_CIOC * 34 if busy else 40)
    return 50 + 38 + sum(34 + max(card(i) for i in wanted) for _, _, wanted in SIDES) + 40


def cable_page(rows: list[dict[str, Any]], cabinets: list[str]) -> str:
    """The cables of every given cabinet in one page that scrolls inside its own box."""
    body = "".join(cabinet_section(rows, cab, n) for n, cab in enumerate(cabinets)) or "<p>No cabinets to show.</p>"
    return _PAGE.replace("@BODY@", body)
