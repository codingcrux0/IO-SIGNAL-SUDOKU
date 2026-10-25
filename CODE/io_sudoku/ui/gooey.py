"""Smooth navigation: gooey tab bars, the page bar at the top, and the bouncing dot in the sidebar.

Rebuilt from two React designs (a "gooey nav" and a "bounce sidebar") without React: the app's OWN widgets are
restyled, so every tab, key, link and search jump keeps working exactly as before.

  gooey tabs      every st.tabs bar and every one-choice button row (segmented control) is drawn as one joined bar.
                  The chosen tab splits away from its neighbours with a short stretchy "neck" and turns blue.  Pure CSS:
                  a registered number (--gn-o, 0 closed .. 1 open) eases on a damped spring curve, and the gap, the
                  corners and the neck all follow it, so the browser animates it on its own - no server round trip.
  page bar        the pages of the sidebar as one gooey bar at the top of every page (the same choice as the sidebar).
  bounce sidebar  the sidebar list is thinner; one small dot jumps along a little arc to the page you pick.  A few
                  lines of JavaScript move it (transform only, one frame at a time), installed once in the app page.

Lite Mode and "reduce motion" turn every movement off: things simply switch.
"""
from __future__ import annotations

import math

import streamlit as st

ACCENT = "#1f6feb"           # the chosen tab (white text on it is easy to read); the Helpdesk uses the same blue
BAR = "#212830"              # the bar behind the other tabs
MUTED = "#8b949e"            # the other tabs' words
DOT = "#58a6ff"              # the sidebar dot (the theme accent)
SIDEBAR_WIDTH = 244          # px (Streamlit's own is 300)
NECK_BREAK = 0.22            # the neck has thinned to nothing once the gap is this much open (from the design)
TOP_KEY = "gooeynav_top"     # the page bar's own widget key; it always shows the page of the sidebar
# button rows that stay as they are: the sign-off of each warning row is too narrow (its Show filter is gooey)
NO_GOOEY = ('[class*="st-key-signoff_"]:not(.st-key-signoff_show)',)

SIZES = {   # height, side padding, font size, corner radius, the gap a chosen tab opens (px; from the design)
    "sm": (32, 14, 13, 10, 16),
    "md": (36, 18, 14, 12, 20),
}


def spring_easing(stiffness: float = 200, damping: float = 28, mass: float = 1, points: int = 28) -> tuple[str, int]:
    """The design's spring (stiffness 200, damping 28) as a CSS linear() curve, and how long it takes (ms).

    It is damped so it settles without bouncing past the end."""
    w0 = math.sqrt(stiffness / mass)
    zeta = damping / (2 * math.sqrt(stiffness * mass))
    wd = w0 * math.sqrt(max(1e-9, 1 - zeta * zeta))

    def at(t: float) -> float:
        return 1 - math.exp(-zeta * w0 * t) * (math.cos(wd * t) + zeta * w0 / wd * math.sin(wd * t))
    end = 0.05
    while abs(1 - at(end)) > 0.002 and end < 3:
        end += 0.01
    values = [0.0] + [round(min(1.0, at(end * i / points)), 4) for i in range(1, points)] + [1.0]
    return "linear(" + ",".join(f"{v:g}" for v in values) + ")", round(end * 1000)


SPRING, SPRING_MS = spring_easing()


def gooey_css(bar: str, item: str, active: str, size: str = "md") -> str:
    """CSS that turns a row of sibling items (`bar` > `item`, the chosen one matching `active`) into a gooey bar."""
    height, pad, font, radius, gap = SIZES[size]
    i, on = f"{bar}>{item}", f"{bar}>{item}{active}"
    corners = (f"border-top-left-radius:{{l}}px;border-bottom-left-radius:{{l}}px;"
               f"border-top-right-radius:{{r}}px;border-bottom-right-radius:{{r}}px")
    move = (f"--gn-o {SPRING_MS}ms ease-out,border-radius {SPRING_MS}ms ease-out,margin {SPRING_MS}ms ease-out")
    spring = (f"--gn-o {SPRING_MS}ms {SPRING},border-radius {SPRING_MS}ms {SPRING},margin {SPRING_MS}ms {SPRING}")
    return (
        f"{bar}{{display:flex;flex-wrap:nowrap;align-items:center;gap:0!important;height:auto!important;"
        f"padding:2px 2px 6px!important;overflow-x:auto;scrollbar-width:none}}"
        f"{bar}::-webkit-scrollbar{{display:none}}"
        f"{bar}::after{{display:none!important}}"
        f"{i}{{--gn-o:0;--gn-l:var(--gn-bar);--gn-r:var(--gn-bar);position:relative;flex:none;box-sizing:border-box;"
        f"display:flex;align-items:center;height:{height}px!important;min-height:{height}px!important;"
        f"padding:0 {pad}px!important;margin:0 0 0 calc(var(--gn-o)*{gap + 1}px - 1px)!important;"
        f"border:0!important;box-shadow:none!important;background:var(--gn-bar)!important;color:var(--gn-muted)!important;"
        + corners.format(l=0, r=0) + ";"
        f"transition:{move},background-color 0s,color 0s;transition:{spring},background-color 0s,color 0s}}"
        f"{i}:first-child{{margin-left:0!important;border-top-left-radius:{radius}px;border-bottom-left-radius:{radius}px}}"
        f"{i}:last-child{{border-top-right-radius:{radius}px;border-bottom-right-radius:{radius}px}}"
        f"{i}:hover{{color:#c9d1d9!important}}"
        f"{i} p{{font-size:{font}px!important;font-weight:500;line-height:1.2;white-space:nowrap;margin:0!important;"
        f"color:inherit!important}}"
        f"{on}{{--gn-o:1;background:var(--gn-on)!important;color:#fff!important;" + corners.format(l=radius, r=radius) + ";"
        f"transition:{move},background-color .4s,color .4s;transition:{spring},background-color .4s,color .4s}}"
        f"{on}+{item}{{--gn-o:1;--gn-l:var(--gn-on);border-top-left-radius:{radius}px;border-bottom-left-radius:{radius}px}}"
        f"{i}:has(+{item}{active}){{border-top-right-radius:{radius}px;border-bottom-right-radius:{radius}px}}"
        f"{on}:not(:first-child){{--gn-r:var(--gn-on)}}"
        # the neck: a bridge across the opening gap whose top and bottom curve in until it pinches off
        f"{i}::before{{content:\"\";position:absolute;top:0;bottom:0;right:100%;width:calc(var(--gn-o)*{gap + 1}px);"
        f"pointer-events:none;background:linear-gradient(90deg,var(--gn-l),var(--gn-r));"
        f"opacity:clamp(0,calc((var(--gn-o) - {NECK_BREAK})*-60),1);"
        f"--gn-cut:calc(min(var(--gn-o)/{NECK_BREAK},1)*50%);"
        f"-webkit-mask:radial-gradient(50% var(--gn-cut) at 50% 0,#0000 98%,#000),"
        f"radial-gradient(50% var(--gn-cut) at 50% 100%,#0000 98%,#000);-webkit-mask-composite:source-in;"
        f"mask:radial-gradient(50% var(--gn-cut) at 50% 0,#0000 98%,#000) intersect,"
        f"radial-gradient(50% var(--gn-cut) at 50% 100%,#0000 98%,#000)}}"
        f"{i}:first-child::before{{display:none}}"
    )


_TABS = gooey_css('[data-testid="stTabs"] [role="tablist"]', '[role="tab"]', '[aria-selected="true"]', "md")
_ROW = ('[data-testid="stButtonGroup"] [role="radiogroup"]:has(>button[data-variant="segmented_control"])'
        + "".join(f":not({x} *)" for x in NO_GOOEY))
_BUTTONS = gooey_css(_ROW, 'button[data-variant="segmented_control"]', '[aria-checked="true"]', "sm")

CSS = (
    "@property --gn-o{syntax:'<number>';inherits:true;initial-value:0}"
    f":root{{--gn-bar:{BAR};--gn-on:{ACCENT};--gn-muted:{MUTED}}}"
    '[data-testid="stTabs"] .react-aria-SelectionIndicator{display:none}'
    + _TABS + _BUTTONS +
    f".st-key-{TOP_KEY}{{margin-bottom:-.35rem}}"
    # --- the sidebar: thinner, a plain list of pages and one dot that jumps to the open page
    f'[data-testid="stSidebar"]:not([data-collapsed="true"]){{width:{SIDEBAR_WIDTH}px!important;min-width:{SIDEBAR_WIDTH}px!important;'
    f'max-width:{SIDEBAR_WIDTH}px!important}}'
    '[data-testid="stSidebar"] [role="radiogroup"][aria-label="View"]{position:relative;gap:1px;padding-left:18px}'
    '[data-testid="stSidebar"] [aria-label="View"] [data-testid="stRadioOption"]>div>:first-child:not([data-testid])'
    '{display:none}'
    '[data-testid="stSidebar"] [aria-label="View"] [data-testid="stRadioOption"]{width:100%;padding:3px 6px;'
    'border-radius:8px;cursor:pointer;color:rgba(230,237,243,.5);background:transparent;'
    'transition:color .2s,background-color .2s}'
    '[data-testid="stSidebar"] [aria-label="View"] [data-testid="stRadioOption"][data-focus-visible="true"]'
    '{box-shadow:0 0 0 2px var(--accent)}'
    '[data-testid="stSidebar"] [aria-label="View"] [data-testid="stRadioOption"]:hover{color:rgba(230,237,243,.85);'
    'background:rgba(255,255,255,.04)}'
    '[data-testid="stSidebar"] [aria-label="View"] [data-testid="stRadioOption"][data-selected="true"]{color:#e6edf3}'
    '[data-testid="stSidebar"] [aria-label="View"] [data-testid="stRadioOption"] p{font-size:14.5px;color:inherit}'
    f'.iosg-bdot{{position:absolute;left:6px;top:0;width:6px;height:6px;border-radius:50%;background:{DOT};'
    'pointer-events:none;opacity:0;will-change:transform;transition:opacity .15s}'
)


def disabled_css(positions: list[int]) -> str:
    """Grey out pages of the page bar (0-based positions) until a file is uploaded, like the sidebar does."""
    rules = ",".join(f".st-key-{TOP_KEY} [role=radiogroup]>:nth-child({p + 1})" for p in positions)
    return f"<style>{rules}{{opacity:.35;pointer-events:none;cursor:not-allowed}}</style>" if rules else ""


def _go_top() -> None:
    from io_sudoku.ui import state
    picked = st.session_state.get(TOP_KEY)
    if picked in state.VIEWS:
        st.session_state["view"] = picked


def render_top(no_file: bool) -> None:
    """The page bar at the top of every page: the same pages as the sidebar, the open one highlighted."""
    from io_sudoku.ui import state
    st.session_state[TOP_KEY] = st.session_state.get("view", state.VIEWS[0])
    if no_file:
        st.markdown(disabled_css([state.VIEWS.index(v) for v in state.NEEDS_FILE]), unsafe_allow_html=True)
    st.segmented_control("Pages", state.VIEWS, key=TOP_KEY, required=True, on_change=_go_top,
                         label_visibility="collapsed")


def render_bounce() -> None:
    """The invisible frame that installs the sidebar dot (call once per run, in the sidebar)."""
    st.iframe(BOUNCE, height=1)


# Installed ONCE in the app page's own realm (like the links listener in nav.py), so it keeps working while this
# frame is redrawn.  It watches the page list; when the open page changes, the dot travels to it along a small arc
# that bows out to the left (motion's arc path: up to 7 px, less for short hops), 250 ms, easing out.  It only moves
# with transform, so the browser never has to lay the page out again.  No movement in Lite Mode or "reduce motion".
BOUNCE = r"""<!DOCTYPE html><html><body><script>(function(){
var w, d;
try { w = window.parent; d = w.document; } catch (e) { return; }
if (w.__iosgBounce1) return;
var code = "var queued = false, list = null;" +
  "var still = function (dot) { return w.matchMedia('(prefers-reduced-motion: reduce)').matches ||" +
  "  w.getComputedStyle(dot).transitionDuration === '0s'; };" +
  "var place = function (dot, y) { dot.style.transform = 'translate(0px,' + y + 'px)'; };" +
  "var sync = function (jump) { queued = false;" +
  "  var g = d.querySelector('[data-testid=stSidebar] [role=radiogroup][aria-label=View]'); if (!g) return;" +
  "  var dot = g.querySelector(':scope > .iosg-bdot'), fresh = !dot;" +
  "  if (fresh) { dot = d.createElement('span'); dot.className = 'iosg-bdot'; dot.setAttribute('aria-hidden', 'true'); g.appendChild(dot); }" +
  "  var on = g.querySelector(':scope > [data-selected=true]');" +
  "  if (!on) { dot.style.opacity = '0'; return; }" +
  "  var r = w.devicePixelRatio || 1, y = Math.round((on.offsetTop + on.offsetHeight / 2 - 3) * r) / r;" +
  "  if (dot.__y === y && !fresh) return;" +
  "  var from = dot.__y; dot.__y = y; dot.style.opacity = '1';" +
  "  if (dot.__anim) { from = new w.DOMMatrix(w.getComputedStyle(dot).transform).m42; dot.__anim.cancel(); dot.__anim = null; }" +
  "  if (fresh || jump || from == null || still(dot) || from === y) { place(dot, y); return; }" +
  "  var dist = Math.abs(y - from), bow = Math.min(0.8, 14 / dist) * dist / 2, frames = [];" +
  "  for (var i = 0; i <= 16; i++) { var t = i / 16;" +
  "    frames.push({transform: 'translate(' + (-bow * Math.sin(Math.PI * t)).toFixed(2) + 'px,' + (from + (y - from) * t).toFixed(2) + 'px)'}); }" +
  "  place(dot, y);" +
  "  var a = dot.animate(frames, {duration: 250, easing: 'ease-out'}); dot.__anim = a;" +
  "  a.onfinish = function () { if (dot.__anim === a) dot.__anim = null; }; };" +
  "var soon = function () { if (!queued) { queued = true; w.requestAnimationFrame(function () { sync(false); }); } };" +
  "new w.MutationObserver(soon).observe(d.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['data-selected']});" +
  "w.addEventListener('resize', function () { sync(true); });" +
  "if (d.fonts && d.fonts.ready) d.fonts.ready.then(function () { sync(true); });" +
  "soon();";
try { (new w.Function('d', 'w', code))(d, w); w.__iosgBounce1 = true; } catch (e) {}
})();</script></body></html>"""
