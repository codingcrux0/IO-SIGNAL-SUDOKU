"""Dark "control room" theme: CSS only, no fonts or scripts from the network.

Follows the Web Interface Guidelines: color-scheme dark, visible :focus-visible rings, animation
limited to opacity/transform and switched off for prefers-reduced-motion and Lite mode, tabular
numbers, ellipsis truncation, content-visibility on the big grid."""
from __future__ import annotations

import streamlit as st

CSS = """
:root{color-scheme:dark;--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#9da7b3;--accent:#58a6ff;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--AIR:#4C9AFF;--AOR:#36B37E;--DIR:#FFAB00;--DOR:#FF5630}
html{scroll-behavior:smooth}
.stApp{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
h1,h2,h3{text-wrap:balance;letter-spacing:-.01em}
:focus-visible{outline:2px solid var(--accent)!important;outline-offset:2px}
.stButton>button,.stDownloadButton>button{touch-action:manipulation;border:1px solid var(--line)}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:var(--accent);background-color:#1f2630}
.stButton>button:active,.stDownloadButton>button:active{background-color:#262e3a}
[data-testid="stMetricValue"],.iosg-kpi b,table,.stDataFrame{font-variant-numeric:tabular-nums}
.iosg-hero{padding:1.2rem 1.4rem;border:1px solid var(--line);border-radius:12px;
background:linear-gradient(135deg,#0f1b2d 0%,#161b22 55%,#101a14 100%);margin-bottom:1rem}
.iosg-hero h1{margin:.1rem 0 .3rem}.iosg-hero p{color:var(--muted);margin:0;max-width:62ch}
.iosg-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin:.6rem 0 1rem}
.iosg-kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem;min-width:0}
.iosg-kpi span{display:block;color:var(--muted);font-size:.8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.iosg-kpi b{font-size:1.6rem}
.iosg-kpi small{display:block;color:var(--accent);font-size:.72rem;margin-top:.1rem;opacity:.85}
a.iosg-kpi{display:block;text-decoration:none;color:inherit}
a.iosg-kpi-go:hover,[class*="st-key-kpicard_"]:hover .iosg-kpi-go{border-color:var(--accent);background:#1c2330}
[class*="st-key-kpicard_"]{position:relative}
[class*="st-key-kpigo_"]{position:absolute!important;inset:0;z-index:2;width:100%!important;height:100%!important}
[class*="st-key-kpigo_"] .stButton,[class*="st-key-kpigo_"] button{width:100%!important;height:100%!important}
[class*="st-key-kpigo_"] button{background:transparent!important;border:0!important;color:transparent!important;
cursor:pointer;border-radius:10px}
.iosg-badge{display:inline-block;padding:.2rem .7rem;border-radius:999px;font-weight:700;font-size:.85rem;border:1px solid}
.iosg-badge.ready{color:var(--ok);border-color:var(--ok)}.iosg-badge.draft{color:var(--warn);border-color:var(--warn)}
.iosg-badge.blocked{color:var(--bad);border-color:var(--bad)}
.iosg-note{border-left:3px solid var(--accent);padding:.4rem .8rem;background:var(--panel);border-radius:0 8px 8px 0;
overflow-wrap:anywhere}
.iosg-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:.8rem;min-width:0}
.iosg-cioc{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.5rem .6rem;min-width:0;
content-visibility:auto;contain-intrinsic-size:auto 330px}
.iosg-cioc h4{margin:0 0 .35rem;font-size:.85rem;color:var(--muted)}
.iosg-bp{display:flex;align-items:center;gap:2px;margin-bottom:2px;min-width:0}
.iosg-bpn{width:1.1rem;font-size:.68rem;color:var(--muted);text-align:right;margin-right:3px;flex:none}
.iosg-slot{display:flex;align-items:center;justify-content:center;flex:1 1 0;min-width:0;height:22px;border-radius:3px;
font-size:.6rem;font-style:normal;font-weight:700;color:#0d1117;border:1px solid transparent;overflow:hidden}
.s-none{background:#1b222c}
.s-spare{background:transparent;border-color:#3b4452}
.s-field{background:var(--c,#888)}
.s-wired{background:repeating-linear-gradient(45deg,var(--c,#888) 0 3px,transparent 3px 6px);color:var(--text);
border-color:var(--c,#888)}
.s-alarm{background:#2b1315;border-color:var(--bad);color:var(--bad)}
.io-AIR{--c:var(--AIR)}.io-AOR{--c:var(--AOR)}.io-DIR{--c:var(--DIR)}.io-DOR{--c:var(--DOR)}
.iosg-legend{display:flex;flex-wrap:wrap;gap:.9rem;margin:.4rem 0 .8rem;font-size:.82rem;color:var(--muted)}
.iosg-legend span{display:inline-flex;align-items:center;gap:.35rem}
.iosg-legend i{display:inline-block;width:18px;height:14px;border-radius:3px}
.iosg-trunc{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.iosg-sev{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.7rem;margin:.4rem 0 1rem}
.iosg-sev div{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--c);border-radius:10px;
padding:.6rem .9rem;min-width:0}
.iosg-sev span{display:block;color:var(--muted);font-size:.85rem}
.iosg-sev b{font-size:1.7rem;color:var(--c)}
.sev-error{--c:var(--bad)}.sev-warning{--c:var(--warn)}.sev-info{--c:var(--accent)}
[data-testid="stSidebar"]{border-right:1px solid var(--line)}
iframe[data-testid=stIFrame]{background:#fff;border-radius:8px;color-scheme:light}
.iosg-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.iosg-skip{position:absolute;left:-999px;top:0;background:var(--accent);color:#0d1117;padding:.4rem .8rem;border-radius:0 0 8px 0;z-index:9999}
.iosg-skip:focus{left:0}
.iosg-grid,.iosg-cioc{scroll-margin-top:4rem}
@media (prefers-reduced-motion:no-preference){.iosg-hero,.iosg-kpi{animation:iosg-in .35s ease-out both}}
@keyframes iosg-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
"""

LITE_CSS = "*{animation:none!important;transition:none!important}.iosg-hero{background:var(--panel)}"


def inject(lite: bool = False) -> None:
    """Add the theme.  Lite mode removes all motion and the gradient (for weak machines)."""
    st.markdown(f"<style>{CSS}{LITE_CSS if lite else ''}</style>", unsafe_allow_html=True)


def badge(status: str) -> str:
    cls = {"ISSUE-READY": "ready", "DRAFT": "draft"}.get(status, "blocked")
    return f'<span class="iosg-badge {cls}" role="status">{status}</span>'


def kpi_html(cards: list[tuple[str, str]]) -> str:
    from html import escape
    return '<div class="iosg-kpis">' + "".join(
        f'<div class="iosg-kpi"><span title="{escape(k)}">{escape(k)}</span><b>{escape(v)}</b></div>' for k, v in cards) + "</div>"


def kpi_card_html(label: str, value: str, hint: str, href: str | None = None) -> str:
    """One summary box.  With `href` it is a link (same-page jump); otherwise a button is laid over it."""
    from html import escape
    body = (f'<span title="{escape(label)}">{escape(label)}</span><b>{escape(value)}</b>'
            f'<small aria-hidden="true">{escape(hint)} \u2192</small>')
    if href:
        return f'<a class="iosg-kpi iosg-kpi-go" href="{escape(href)}">{body}</a>'
    return f'<div class="iosg-kpi iosg-kpi-go">{body}</div>'


def severity_cards_html(counts: dict[str, int]) -> str:
    """Three coloured counters: red errors, amber warnings, blue info (same colours as the TQ table rows)."""
    cards = (("error", "Errors", "must be answered"), ("warning", "Warnings", "please confirm"),
             ("info", "Info", "no action needed"))
    return '<div class="iosg-sev" role="group" aria-label="Questions by severity">' + "".join(
        f'<div class="sev-{sev}"><span>{label} · {hint}</span><b>{counts.get(sev, 0):,}</b></div>'
        for sev, label, hint in cards) + "</div>"


LEGEND_HTML = (
    '<div class="iosg-legend" aria-label="Legend">'
    '<span><i style="background:#4C9AFF"></i>AI = analog in (solid)</span>'
    '<span><i style="background:#36B37E"></i>AO = analog out</span>'
    '<span><i style="background:#FFAB00"></i>DI = digital in</span>'
    '<span><i style="background:#FF5630"></i>DO = digital out</span>'
    '<span><i style="background:repeating-linear-gradient(45deg,#888 0 3px,transparent 3px 6px);border:1px solid #888"></i>'
    'Hatched, lower-case = wired spare</span>'
    '<span><i style="border:1px solid #3b4452"></i>Empty outline = spare slot</span>'
    '<span><i style="border:1px solid #f85149;color:#f85149;font-size:.7rem;text-align:center;line-height:12px">!</i>'
    'Cabinet alarm</span></div>')
