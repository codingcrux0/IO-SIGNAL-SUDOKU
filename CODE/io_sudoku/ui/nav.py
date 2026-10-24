"""Links inside sentences: "... on the [TQ Board](#go-tq-board)" opens that page (and tab, and section).

How it works, without reloading the page (a reload would start a new session and lose the upload):
  * `link()` writes an ordinary Markdown link whose address is '#go-<slug>' of a search place.
  * One hidden button per place ('navgo_<slug>') sits in a hidden box in the sidebar; its callback is
    go(place) - the same jump the search bar makes.
  * A tiny invisible frame adds ONE click listener to the app page: a click on a '#go-' link presses
    the matching hidden button.  So a link costs one normal re-run, exactly like a sidebar click.
Only sentences that send you somewhere get a link; everything else stays plain text.
"""
from __future__ import annotations

import re

import streamlit as st

from io_sudoku.ui import search

BOX_KEY = "iosg_nav"


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")


SLUGS: dict[str, search.Place] = {slug(p.label): p for p in search.PLACES}


def _place(view: str, heading: str = "") -> search.Place:
    for p in search.PLACES:
        if p.view == view and p.heading == heading:
            return p
    return next(p for p in search.PLACES if p.view == view and not p.heading)


def link(text: str, view: str, heading: str = "") -> str:
    """Markdown for a link that opens `view` (and scrolls to `heading`, one of the search sections)."""
    clean = text.replace("[", "(").replace("]", ")")
    return f"[{clean}](#go-{slug(_place(view, heading).label)})"


def go(place: search.Place) -> None:
    """Open a place: its view, its tab, then scroll to its heading (or to the top of the view).
    Used by the links and by the search bar."""
    from io_sudoku.ui import state
    s = st.session_state
    if place.view in state.NEEDS_FILE and not s.get("mdb_bytes"):
        state.flash("info", "Upload a file (or load the sample data) first.")
        return
    s["view"] = place.view
    if place.tab_key:
        s[place.tab_key] = place.tab
    s["scroll_to"] = place.heading or "__top__"


def render_targets() -> None:
    """The hidden buttons the links press, and the listener frame (call once per run, in the sidebar)."""
    with st.container(key=BOX_KEY):
        for key, place in SLUGS.items():
            st.button(place.label, key=f"navgo_{key}", on_click=go, args=(place,))
    st.iframe(LISTENER, height=1)


# Installs the listener in the APP page's own realm, once, so it keeps working when this frame is redrawn.
# If the page forbids that, this frame owns the listener and replaces its predecessor's on every load.
LISTENER = r"""<!DOCTYPE html><html><body><script>(function(){
var w, d;
try { w = window.parent; d = w.document; } catch (e) { return; }
if (w.__iosgNav) return;
var code = "var f = function (e) {" +
  "var a = e.target && e.target.closest ? e.target.closest('a[href^=\"#go-\"]') : null;" +
  "if (!a) return; e.preventDefault(); e.stopPropagation();" +
  "var b = d.querySelector('.st-key-navgo_' + a.getAttribute('href').slice(4) + ' button');" +
  "if (b) b.click(); };" +
  "d.addEventListener('click', f, true); return function () { d.removeEventListener('click', f, true); };";
try { (new w.Function('d', code))(d); w.__iosgNav = true; return; } catch (e) {}
try { if (w.__iosgNavOff) w.__iosgNavOff(); } catch (e) {}
w.__iosgNavOff = (new Function('d', code))(d);
})();</script></body></html>"""
