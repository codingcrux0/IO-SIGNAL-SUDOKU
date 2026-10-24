"""The search bar at the top of every page: type, and jump to the closest page, section, tag, cable or question.

Fast by design: the box is a Streamlit selectbox, so the matching while you type (fuzzy: the letters in
order, best match first) happens IN THE BROWSER - no server round trip, no rerun per keystroke.  The
server only acts once you pick something.  If you type a word that matches nothing and press Enter,
the closest entry is chosen with difflib.  The index of pages and sections is a fixed list; tags,
cables and questions come from the current result and are cached per result.
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
    _p("Preflight", words="preflight quality score data check before"),
    _p("Preflight", "Fixed Automatically", "auto fixed cleaned spelling"),
    _p("Preflight", "Column Completeness", "columns filled blank missing"),
    _p("Preflight", "Needs A Human", "problems issues"),
    _p("Solve", words="solve run allocate allocation kpi summary self-test readiness"),
    _p("Solve", "Wired Spares Per Controller", "spares 10% quota controller compliance"),
    _p("Solve", "Assumptions Used In This Run", "assumptions defaults a01"),
    _p("Solve", "Stage Timings", "timings speed performance"),
    _p("Cabinet Layout", words="cabinet grid map slots drawings layout"),
    _p("Cabinet Layout", "Slot Map", "grid slots map cioc baseplate channel charm", "cab_tab", "Slot Map", label="Cabinet Layout › Slot Map"),
    _p("Cabinet Layout", "Why Is It Here?", "why trace reason decision explain", "cab_tab", "Slot Map"),
    _p("Cabinet Layout", "Front (CIOC 1–2)", "drawings elevation front rear print", "cab_tab", "Front & Rear Drawings",
       label="Cabinet Layout › Front & Rear Drawings"),
    _p("TQ Board", words="tq questions errors warnings board"),
    _p("TQ Board", "Sign Off The Warnings", "warnings errors fix edit approve problem verify sign off"),
    _p("TQ Board", "All Questions", "questions table filter search tqs"),
    _p("TQ Board", "Answer A Question", "answer override suggested"),
    _p("TQ Board", "Pin A Cable", "pin cable cioc fix position"),
    _p("Health", words="health audit check score human allocation"),
    _p("Health", "Rules Broken", "violations broken rules"),
    _p("Health", "Human Allocation vs IO Sudoku", "human vs tool scorecard compare"),
    _p("Parts", words="parts bom bill of materials charms"),
    _p("Parts", "Bill Of Materials", "bom charm terminal baseplate buy"),
    _p("Parts", "Cable Utilisation", "cable use smaller right-size"),
    _p("Parts", "Room To Grow", "headroom growth space"),
    _p("Revision", words="revision rev a rev b changes impact"),
    _p("Revision", "Compare With A New MDB", "rev a rev b new mdb pinned impact redline", "rev_tab", "Compare With A New MDB"),
    _p("Revision", "Revision History", "history saved revisions original compare versions", "rev_tab", "Revision History"),
    _p("Simulator", words="simulator what if rework hours churn 5%"),
    _p("Rules", words="rules locked pack"),
    _p("Rules", "Propose A Rule", "propose rule change template"),
    _p("Rules", "Review Queue", "approve reject proposal"),
    _p("Rules", "Ask The AI Assistant (optional)", "ai assistant claude"),
    _p("Rules", "Rule Pack And Audit Log", "audit log pack version"),
    _p("Files", words="files downloads export view"),
    _p("Files", "View A File", "open view file viewer"),
    _p("Files", "Download Files", "download zip everything"),
)


@st.cache_data(max_entries=8, show_spinner=False)
def data_places(result_key: str, _rows: list, _tqs: list) -> tuple[tuple[str, str], ...]:
    """(label, json action) for every tag, cable and question of a result (cached per result)."""
    out: list[tuple[str, str]] = []
    cables: dict[str, str] = {}
    for r in _rows:
        status = r.get("Tag Status")
        cab = str(r.get("Electronic/ Marshalling Cabinet") or "")
        if status in ("Field", "Cabinet Alarm", "Wired Spare"):
            tag = str(r.get("Tag Name") or "")
            if tag and tag != "-":
                out.append((f"Tag {tag} · {cab}", json.dumps({"kind": "tag", "tag": tag, "cab": cab})))
        cable = str(r.get("Field Cable No") or "")
        if status == "Field" and cable and cable != "-" and cable not in cables:
            cables[cable] = cab
    out += [(f"Cable {c} · {cab}", json.dumps({"kind": "cable", "cable": c, "cab": cab})) for c, cab in sorted(cables.items())]
    ids = sorted({t.tq_id for t in _tqs})
    out += [(f"Question {i}", json.dumps({"kind": "tq", "id": i})) for i in ids]
    return tuple(out)


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
def _data_entries() -> dict[str, str]:
    s = st.session_state
    result = s.get("result")
    if result is None:
        return {}
    return dict(data_places(s.get("result_key") or "", result.rows, result.tqs))


def render() -> None:
    """The search box at the top of the page (matching runs in the browser while you type)."""
    labels = [p.label for p in PLACES] + list(_data_entries())
    st.selectbox("Search the app", labels, index=None, key=KEY, on_change=on_pick, accept_new_options=True,
                 placeholder="\U0001F50E Search pages, sections, tags, cables or questions…",
                 label_visibility="collapsed",
                 help="Type a few letters: the closest matches are listed as you type. Pick one to go there.")


def on_pick() -> None:
    from io_sudoku.ui import state
    s = st.session_state
    picked = s.get(KEY)
    s[KEY] = None                                         # the box is empty again after every jump
    if not picked:
        return
    places = {p.label: p for p in PLACES}
    data = _data_entries()
    if picked not in places and picked not in data:
        near = closest(picked, list(places) + list(data))
        if near is None:
            state.flash("info", f"Nothing in the app matches “{picked}”.")
            return
        state.flash("info", f"Closest match for “{picked}”: {near}")
        picked = near
    if picked in places:
        place = places[picked]
        s["view"] = place.view
        if place.tab_key:
            s[place.tab_key] = place.tab
        s["scroll_to"] = place.heading or None
        return
    action = json.loads(data[picked])
    if action["kind"] in ("tag", "cable"):
        s.update(view="Cabinet Layout", selected_cabinet=action["cab"], scroll_to="Why Is It Here?")
        s["cab_tab"] = "Slot Map"
        if action["kind"] == "tag":
            s["why_tag"], s["why_cable"] = action["tag"], ""
        else:
            s["why_tag"], s["why_cable"] = "(Pick a tag)", action["cable"]
    elif action["kind"] == "tq":
        s.update(view="TQ Board", tq_filter="all", tq_page=0, tq_search=action["id"], scroll_to="All Questions")


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
