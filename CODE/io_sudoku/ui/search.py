"""The search bar at the top of every page: type, and jump to the closest page or section of the app.

Fast by design: the box is a Streamlit selectbox, so the matching while you type (fuzzy: the letters in
order, best match first) happens IN THE BROWSER - no server round trip, no rerun per keystroke.  The
server only acts once you pick something.  If you type a word that matches nothing and press Enter,
the closest entry is chosen with difflib.  The index is a fixed list of pages and sections only (tags
and cables are searched where they live: Why Is It Here?, the TQ Board and the Files viewer).
The same list is the target of the in-sentence links (see nav.py).
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass

import streamlit as st

KEY = "global_search"


@dataclass(frozen=True)
class Place:
    label: str                 # what the user sees and the fuzzy filter matches
    view: str
    heading: str = ""          # scroll to the heading with this text after opening the view
    tab_key: str = ""          # a tab to open first (session-state key of an st.tabs)
    tab: str = ""
    words: str = ""            # extra words for the 'closest match' fallback


def _p(view: str, heading: str = "", words: str = "", tab_key: str = "", tab: str = "", label: str = "") -> Place:
    return Place(label or (f"{view} › {heading}" if heading else view), view, heading, tab_key, tab, words)


PLACES: tuple[Place, ...] = (
    _p("Upload", words="upload mdb file excel csv home start"),
    _p("Upload", "Try With Sample Data", "sample demo example", label="Upload › Try With Sample Data"),
    _p("Upload", "Use Your Own Allocation Template (optional)", "template 76 columns", label="Upload › Your Own Template"),
    _p("Upload", "Continue A Saved Project (workspace .zip)", "workspace zip saved project continue", label="Upload › Continue A Saved Project"),
    _p("Upload", "Check How Your Columns Were Understood", "columns mapping headers", label="Upload › Column Mapping"),
    _p("Edit File", words="edit change cell fix correct value mdb"),
    _p("Edit File", "Find A Cell", "search row column cell edit table"),
    _p("Edit File", "Your Changes", "undo history log download edited file"),
    _p("Upload", "", "saved file revisions versions use this file earlier file edited suggested go back", label="Saved File Revisions"),
    _p("Preflight", words="preflight quality score data check before"),
    _p("Preflight", "Suggested Fixed File", "suggested fixed file repair auto fix errors reduce extra columns explain "
       "why use download"),
    _p("Preflight", "Fixed Automatically", "auto fixed cleaned spelling"),
    _p("Preflight", "Column Completeness", "columns filled blank missing"),
    _p("Solve", words="solve run allocate allocation kpi summary self-test readiness"),
    _p("Solve", "Wired Spares Per Controller", "spares 10% quota controller compliance"),
    _p("Solve", "Assumptions Used In This Run", "assumptions defaults a01 confirm senior engineer"),
    _p("Solve", "Self-Test Details", "self test checks passed"),
    _p("Solve", "Stage Timings", "timings speed performance"),
    _p("Cabinet Layout", words="cabinet grid map slots drawings layout"),
    _p("Cabinet Layout", "Slot Map", "grid slots map cioc baseplate channel charm", "cab_tab", "Slot Map", label="Cabinet Layout › Slot Map"),
    _p("Cabinet Layout", "Why Is It Here?", "why trace reason decision explain", "cab_tab", "Slot Map"),
    _p("Cabinet Layout", "Front (CIOC 1–2)", "drawings elevation front rear print", "cab_tab", "Front & Rear Drawings",
       label="Cabinet Layout › Front & Rear Drawings"),
    _p("Audit", words="audit rule radar rules constraints check impact cells signals"),
    _p("Audit", "", "rule check rules constraints one cell signal path live log why", "rule_tab", "Rule Check",
       label="Audit › Rule Check"),
    _p("Audit", "Pick The Cells To Check", "pick find cell charm slot tag search", "rule_tab", "Rule Check",
       label="Audit › Rule Check › Pick The Cells"),
    _p("Audit", "Live Rule Log", "log rules applied constraints signal path", "rule_tab", "Rule Check",
       label="Audit › Rule Check › Live Rule Log"),
    _p("Audit", "", "rule impact which cells constraint affects where charms signals hits", "rule_tab", "Rule Impact",
       label="Audit › Rule Impact"),
    _p("Audit", "Pick A Rule", "pick rule constraint locked project setting list", "rule_tab", "Rule Impact",
       label="Audit › Rule Impact › Pick A Rule"),
    _p("Audit", "Where It Hits", "cells charms signals cabinet map highlighted affected", "rule_tab", "Rule Impact",
       label="Audit › Rule Impact › Where It Hits"),
    _p("TQ Board", words="tq questions errors warnings board"),
    _p("TQ Board", "Sign Off The Warnings", "warnings errors fix edit approve problem verify sign off", "signoff_show", "All"),
    _p("TQ Board", "Sign Off The Warnings", "errors fix must", "signoff_show", "Errors", label="TQ Board › Errors To Fix"),
    _p("TQ Board", "Sign Off The Warnings", "waiting approve pending", "signoff_show", "Waiting",
       label="TQ Board › Warnings Still Waiting For Sign-Off"),
    _p("TQ Board", "Sign Off The Warnings", "approved signed off done", "signoff_show", "Signed Off",
       label="TQ Board › Warnings Already Signed Off"),
    _p("TQ Board", "Sign Off The Warnings", "problem rejected marked", "signoff_show", "Problem",
       label="TQ Board › Warnings Marked As A Problem By You"),
    _p("TQ Board", "All Questions", "questions table filter search tqs"),
    _p("TQ Board", "Copy Questions For An Owner", "email owner copy send"),
    _p("TQ Board", "Answer A Question", "answer override suggested"),
    _p("TQ Board", "Pin A Cable", "pin cable cioc fix position"),
    _p("TQ Board", "Problems Again On Items You Reviewed Before", "reviewed before history came back again past decisions "
       "approved rejected memory", label="TQ Board › Reviewed Before"),
    _p("TQ Board", "Everything Reviewed So Far", "reviewed history all items past decisions",
       label="TQ Board › Reviewed Before › Everything Reviewed"),
    _p("Parts", words="parts bom bill of materials charms"),
    _p("Parts", "Bill Of Materials", "bom charm terminal baseplate buy"),
    _p("Parts", "Cable Utilisation", "cable use smaller right-size"),
    _p("Parts", "Room To Grow", "headroom growth space"),
    _p("Revision", words="revision rev a rev b changes impact"),
    _p("Revision", "Compare With A New MDB", "rev a rev b new mdb pinned impact redline", "rev_tab", "Compare With A New MDB"),
    _p("Revision", "Hardware Changes And Spare Conversions", "hardware spare conversions deleted", "rev_tab",
       "Compare With A New MDB"),
    _p("Revision", "Question Lifecycle", "tq lifecycle still open new resolved", "rev_tab", "Compare With A New MDB"),
    _p("Revision", "Downloads For This Revision", "impact report redline download", "rev_tab", "Compare With A New MDB"),
    _p("Revision", "", "check allocation first preview allocation before save pop-up better worse rework time",
       "rev_tab", "Compare With A New MDB", label="Revision › Check Allocation First (Preview)"),
    _p("Revision", "", "revision library saved revisions names open whole data every revision", "rev_tab",
       "Revision Library", label="Revision › Revision Library"),
    _p("Revision", "Revision History", "history saved revisions original compare versions", "rev_tab", "Revision History"),
    _p("Revision", "Saved Revisions", "saved rename delete summary", "rev_tab", "Revision History"),
    _p("Revision", "Compare Revisions", "compare multiple revisions versions", "rev_tab", "Revision History"),
    _p("Revision", "Revision Simulator", "simulator what if rework hours churn 5% pretend revision", "rev_tab",
       "Revision Simulator", label="Revision › Revision Simulator"),
    _p("Revision", "Make A Pretend Revision", "minutes rework team effort seed share", "rev_tab", "Revision Simulator",
       label="Revision › Simulator › Minutes Of Rework"),
    _p("Revision", "Where The Hours Go", "hours chart rework saved breakdown", "rev_tab", "Revision Simulator",
       label="Revision › Simulator › Where The Hours Go"),
    _p("Revision", "Try Several Sizes", "sizes sweep 1% 20% chart", "rev_tab", "Revision Simulator",
       label="Revision › Simulator › Try Several Sizes"),
    _p("Rules", words="rules locked pack"),
    _p("Rules", "Locked Rules", "locked fixed cannot change hard rules", label="Rules › Locked Rules"),
    _p("Rules", "Propose A Rule", "propose rule change template engineering settings spare percent future space alias "
       "cabinet segregation code instrument hardware high current", label="Rules › Engineering Settings"),
    _p("Rules", "Propose A Rule", "add new signal tag row later arrives input cable pair room", "rule_group", "Add A Signal",
       label="Rules › Add A Signal"),
    _p("Rules", "Propose A Rule", "column columns checks constraint new project column voltage values per signal max "
       "min between blank one of duplicate error warning paste upload fill", "rule_group", "Columns And Checks",
       label="Rules › Columns And Checks"),
    _p("Rules", "Review Queue", "approve verify reject proposal"),
    _p("Rules", "Preview And Activate", "preview activate impact new pack version view changes"),
    _p("Rules", "Project Rules And Where They Apply", "project column constraint check where applies charm signals edit remove",
       label="Rules › Project Columns And Constraints"),
    _p("Rules", "Suggested Fixes Waiting For Verification", "suggestion approve verify note fix", label="Rules › Suggested Fixes"),
    _p("Rules", "Ask The AI Assistant (optional)", "ai assistant draft"),
    _p("Rules", "Rule Pack And Audit Log", "audit log pack version"),
    _p("Files", words="files downloads export view"),
    _p("Files", "View A File", "open view file viewer"),
    _p("Files", "Download Files", "download zip everything"),
)


def closest(text: str, labels: list[str]) -> str | None:
    """The label closest to free text: a label containing it, else the best difflib match."""
    needle = (text or "").strip().casefold()
    if not needle:
        return None
    by_place = {p.label: f"{p.label} {p.words}".casefold() for p in PLACES}
    for pool in ([l for l in labels if needle in l.casefold()],                     # the name itself first
                 [l for l in labels if needle in by_place.get(l, l.casefold())]):   # then its keywords
        if pool:
            return min(pool, key=len)
    for source in (lambda l: l.casefold(), lambda l: by_place.get(l, l.casefold())):   # names first, then keywords
        words: dict[str, str] = {}
        for l in labels:
            for w in source(l).replace("›", " ").split():
                if w not in words or len(l) < len(words[w]):
                    words[w] = l
        hit = difflib.get_close_matches(needle, list(words), n=1, cutoff=0.6)
        if hit:
            return words[hit[0]]
    hit = difflib.get_close_matches(needle, [l.casefold() for l in labels], n=1, cutoff=0.4)
    return next((l for l in labels if l.casefold() == hit[0]), None) if hit else None


# ------------------------------------------------------------------ the widget
BY_LABEL: dict[str, Place] = {p.label: p for p in PLACES}


def render() -> None:
    """The search box at the top of the page (matching runs in the browser while you type)."""
    st.selectbox("Search the app", list(BY_LABEL), index=None, key=KEY, on_change=on_pick, accept_new_options=True,
                 placeholder="\U0001F50E Search pages and sections…", label_visibility="collapsed",
                 help="Type a few letters: the closest pages and sections are listed as you type. Pick one to go there.")


def on_pick() -> None:
    from io_sudoku.ui import state
    s = st.session_state
    picked = s.get(KEY)
    s[KEY] = None                                         # the box is empty again after every jump
    if not picked:
        return
    if picked not in BY_LABEL:
        near = closest(picked, list(BY_LABEL))
        if near is None:
            state.flash("info", f"Nothing in the app matches “{picked}”.")
            return
        state.flash("info", f"Closest match for “{picked}”: {near}")
        picked = near
    from io_sudoku.ui import nav
    nav.go(BY_LABEL[picked])


def scroll_page(heading: str, nonce: int) -> str:
    """A tiny page for an invisible iframe that scrolls the APP (its parent, same origin) to the heading
    with this text.  It waits for the heading to appear, then scrolls again a few times while the page
    settles.  (st.html strips a script that stands alone, so an iframe is used, like the drawings.)"""
    want = json.dumps(heading.strip().casefold())
    return ("<!DOCTYPE html><html><body><script>/*" + str(int(nonce)) + "*/(function(){var d;"
            "try{d=window.parent.document;}catch(e){return;}var want=" + want + ",n=0;"
            "function find(){var els=d.querySelectorAll('h1,h2,h3,h4,summary');"
            "for(var i=0;i<els.length;i++){var t=(els[i].textContent||'').trim().toLowerCase();"
            "if(t===want||t.indexOf(want)===0)return els[i];}return null;}"
            "function go(){if(want==='__top__'){var m=d.querySelector('[data-testid=stMain]');if(m)m.scrollTo(0,0);"
            "window.parent.scrollTo(0,0);return;}var el=find();if(!el){if(++n<40)setTimeout(go,100);return;}"
            "[0,300,700,1300].forEach(function(ms){setTimeout(function(){var e=find();"
            "if(e)e.scrollIntoView({block:'start'});},ms);});}"
            "setTimeout(go,100);})();</script></body></html>")
