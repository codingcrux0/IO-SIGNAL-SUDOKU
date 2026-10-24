"""Rule Impact: pick one rule or constraint and see every cell, CHARM and signal it affects - met or broken.

Rule Check goes from cells to rules; this page goes from a rule to its cells.  The list is worked out from
the current allocation on every new allocation (core.ruleimpact, built on the same checks as Rule Check), so
the two pages always agree.  Nothing here changes the allocation.
"""
from __future__ import annotations

import csv
import io
import json
from functools import partial

import pandas as pd
import streamlit as st

from io_sudoku.core import ruleimpact as ri
from io_sudoku.core.overrides import overrides_to_json
from io_sudoku.ui import state, theme, ui_logic
from io_sudoku.ui.nav import link
from io_sudoku.ui.views._common import heading, md_escape, result_or_empty

CURRENT, REV_B = "Current Allocation", "Rev B Comparison"
ALL_GROUPS = "All"
ICON = {ri.PASS: "✓ met", ri.FAIL: "✗ broken", ri.WARN: "▲ to check", ri.INFO: "• applies"}
MAX_CELLS = 2000


def _source():
    """(result, its key) of the allocation being looked at."""
    s = st.session_state
    if s.get("rev_b_result") is not None and s.get("ri_source") == REV_B:
        return s["rev_b_result"], "revb_" + (s.get("rev_key") or "")
    return s["result"], s["result_key"] or ""


@st.cache_data(max_entries=8, show_spinner=False)
def _impacts(key: str, _result, _overrides, _pins) -> list[ri.Impact]:
    return ri.rule_impact(_result, _overrides, _pins)


@st.cache_data(max_entries=32, show_spinner=False)
def _map(key: str, rule_key: str, cabinet: str, _rows: list, _marks: dict) -> str:
    return ui_logic.cabinet_grid_html(_rows, cabinet, _marks)


def render() -> None:
    s = st.session_state
    st.header("Rule Impact", help="Pick one rule or constraint and see every cell (slot), CHARM and signal it "
                                  "applies to, and where it is met or broken: the locked rules, the pack settings, "
                                  "your project rules, answers and pins, and open questions. Rule Check is the other "
                                  "way round (pick cells, see their rules). Nothing here changes the allocation.")
    if result_or_empty("the rule impact", "ri") is None:
        return
    if s.get("rev_b_result") is not None:
        st.radio("Look At", (CURRENT, REV_B), key="ri_source", horizontal=True,
                 help="Rev B Comparison = the new revision worked out on the Revision page.")
    result, key = _source()
    if s.get("stale") and key == (s["result_key"] or ""):
        st.warning("Your inputs changed after this allocation: this page shows the last allocation. Re-allocate to refresh it.")
    full_key = ui_logic.sha256_hex("|".join([key, overrides_to_json(s["overrides"]),
                                             json.dumps({k: list(v) for k, v in sorted(s["pins"].items())})]))
    impacts = _impacts(full_key, result, s["overrides"], s["pins"])
    n = ri.summary(impacts)
    st.markdown(theme.kpi_html([("Rules That Apply", f"{n['rules']:,}"), ("Met Everywhere", f"{n['met']:,}"),
                                ("Broken Somewhere", f"{n['broken']:,}"), ("Need A Look", f"{n['to_check']:,}")]),
                unsafe_allow_html=True)
    picked = _pick(impacts, full_key)
    _where(picked, result, full_key)


# ------------------------------------------------------------------ the rule list
def _picked(widget: str, keys: list[str]) -> None:
    s = st.session_state
    rows = ((s.get(widget) or {}).get("selection") or {}).get("rows") or []
    s["ri_pick"] = keys[rows[0]] if rows and rows[0] < len(keys) else None


def _pick(impacts: list[ri.Impact], full_key: str) -> ri.Impact | None:
    s = st.session_state
    heading("Pick A Rule", "Tick a row to see where that rule applies. Filter by kind of rule, show only the rules "
                           "broken or needing a look somewhere, or search the rule's words (not case-sensitive). "
                           + " ".join(f"{g}: {h}" for g, h in ri.GROUP_HELP.items()))
    groups = [ALL_GROUPS] + [g for g in ri.GROUPS if any(x.group == g for x in impacts)]
    if s.get("ri_group") not in groups:
        s["ri_group"] = ALL_GROUPS
    with st.container(horizontal=True, gap="medium", vertical_alignment="center", key="ri_filters"):
        st.segmented_control("Kind Of Rule", groups, key="ri_group", label_visibility="collapsed")
        st.toggle("Problems Only", key="ri_problems", help="Only rules that are broken or need a look somewhere.")
    needle = st.text_input("Search The Rules", key="ri_find", autocomplete="off",
                           placeholder="For example spares, segregation, CHARM, V06, a TQ name…").strip().casefold()
    group = s.get("ri_group") or ALL_GROUPS
    shown = [x for x in impacts if (group == ALL_GROUPS or x.group == group) and (not s.get("ri_problems") or x.problems)
             and (not needle or needle in f"{x.group} {x.rule} {x.title}".casefold())]
    if not shown:
        st.info("No rule matches. Clear the search or the filters.")
        return next((x for x in impacts if x.key == s.get("ri_pick")), None)
    keys = [x.key for x in shown]
    frame = pd.DataFrame([{"Kind": x.group, "Rule": x.rule, "What It Checks": x.title, "Cells": len(x.hits),
                           "✓ Met": x.count(ri.PASS), "✗ Broken": x.count(ri.FAIL), "▲ To Check": x.count(ri.WARN),
                           "• Notes": x.count(ri.INFO)} for x in shown])
    widget = "ri_table_" + ui_logic.sha256_hex("|".join([full_key[:12], group, needle, str(bool(s.get("ri_problems"))),
                                                         s.get("ri_pick") or ""]))[:12]
    chosen = [i for i, k in enumerate(keys) if k == s.get("ri_pick")]
    st.dataframe(frame, key=widget, on_select=partial(_picked, widget, keys), selection_mode="single-row",
                 hide_index=True, width="stretch", height=min(420, 38 + 35 * len(shown)),
                 selection_default={"selection": {"rows": chosen}},
                 column_config={"What It Checks": st.column_config.TextColumn(width="large")})
    return next((x for x in impacts if x.key == s.get("ri_pick")), None)


# ------------------------------------------------------------------ where the picked rule hits
def _to_rule_check(sids: list[str]) -> None:
    from io_sudoku.ui.views import rulecheck
    s = st.session_state
    opened = sids[:rulecheck.MAX_CARDS]
    for sid in reversed(opened):                 # pick() puts each one first, so the list keeps its order
        rulecheck.pick(sid)
    if s.get("ri_source") == REV_B:
        s["rc_source"] = rulecheck.REV_B
    if len(opened) > 1:
        state.flash("info", f"Showing the rules of the {len(opened)} cells picked on Rule Impact.", "Live Rule Log")


def _where(impact: ri.Impact | None, result, full_key: str) -> None:
    s = st.session_state
    heading("Where It Hits", "Every cell the picked rule applies to: how many signals and CHARMs, which cabinets, a "
                             "cabinet map with those cells lit up (red outline = broken, dashed yellow = needs a look, "
                             "faded = the rule does not apply there), and the full list. Click a cell on the map, or "
                             "tick cells in the list, to open them on Rule Check.")
    if impact is None:
        st.info("Pick a rule in the list above to see every cell, CHARM and signal it affects.")
        return
    broken, look = impact.count(ri.FAIL), impact.count(ri.WARN)
    verdict = ("✗ broken in " + f"{broken:,} cell(s)") if broken else ("▲ needs a look in " + f"{look:,} cell(s)") if look \
        else ("✓ met everywhere it applies" if impact.count(ri.PASS) else "• applies as information")
    st.markdown(f"**{md_escape(impact.title)}** &nbsp;<small>{md_escape(impact.rule)} · {md_escape(impact.group)} · "
                f"{verdict}</small>", unsafe_allow_html=True)
    st.caption(ri.GROUP_HELP.get(impact.group, ""))
    if not impact.hits:
        st.info("This rule applies to no cell of this allocation yet (no signal matches what it covers). Check what "
                f"it covers on the {link('Rules', 'Rules', 'Project Rules And Where They Apply')} page.")
        return
    st.markdown(theme.kpi_html([("Cells", f"{len(impact.hits):,}"), ("Signals (Tags)", f"{len(impact.signals):,}"),
                                ("CHARM Types", f"{len(impact.charms):,}"), ("Cabinets", f"{len(impact.cabinets):,}"),
                                ("✗ Broken", f"{broken:,}"), ("▲ To Check", f"{look:,}")]), unsafe_allow_html=True)
    by_cab, by_charm = st.columns([3, 2])
    with by_cab:
        st.markdown("**By Cabinet**")
        lines = []
        for cab in impact.cabinets:
            mine = [h for h in impact.hits if h.cabinet == cab]
            lines.append({"Cabinet": cab, "Cells": len(mine), "✓ Met": sum(h.status == ri.PASS for h in mine),
                          "✗ Broken": sum(h.status == ri.FAIL for h in mine), "▲ To Check": sum(h.status == ri.WARN for h in mine)})
        st.dataframe(lines, hide_index=True, width="stretch", height=min(250, 38 + 35 * len(lines)))
    with by_charm:
        st.markdown("**By CHARM Type**")
        charms = [{"CHARM Type": c, "Cells": n} for c, n in impact.charms.items()]
        st.dataframe(charms, hide_index=True, width="stretch", height=min(250, 38 + 35 * len(charms)))
    _cabinet_map(impact, result, full_key)
    _cells(impact)


def _cabinet_map(impact: ri.Impact, result, full_key: str) -> None:
    s = st.session_state
    cabs = impact.cabinets
    worst = max(cabs, key=lambda c: (sum(h.status == ri.FAIL for h in impact.hits if h.cabinet == c),
                                     sum(h.status == ri.WARN for h in impact.hits if h.cabinet == c),
                                     sum(h.cabinet == c for h in impact.hits)))
    widget = "ri_cab_" + ui_logic.sha256_hex(impact.key)[:8]
    if s.get(widget) not in cabs:
        s[widget] = worst
    st.markdown("**On The Cabinet**")
    cab = st.selectbox("Cabinet To Show", cabs, key=widget, help="Starts on the cabinet where the rule is broken most.")
    st.markdown('<div class="iosg-marks"><span><i style="outline:2px solid #ff7b72;background:#30363d"></i>Broken</span>'
                '<span><i style="outline:2px dashed #e3b341;background:#30363d"></i>Needs a look</span>'
                '<span><i style="background:#8b949e"></i>Applies (met)</span>'
                '<span><i style="background:#8b949e;opacity:.2"></i>Rule does not apply</span></div>',
                unsafe_allow_html=True)
    marks = {h.sid: h.status for h in impact.hits if h.cabinet == cab}
    st.html(_map(full_key, impact.key, cab, result.rows, marks))


def _cells(impact: ri.Impact) -> None:
    s = st.session_state
    st.markdown("**Every Cell It Applies To**")
    left, right = st.columns([2, 3], vertical_alignment="bottom")
    only = left.segmented_control("Show Cells", ("Every Cell", "Problems Only"), key="ri_cells_show",
                                  default="Every Cell", label_visibility="collapsed") == "Problems Only"
    find = right.text_input("Find A Cell (case-sensitive)", key="ri_cells_find", autocomplete="off",
                            placeholder="A tag, cable, CHARM type or cabinet…").strip()
    hits = [h for h in impact.hits if (not only or h.status in (ri.FAIL, ri.WARN))
            and (not find or find in f"{h.tag} {h.cable} {h.charm} {h.cabinet} {h.kind} {h.io}")]
    shown = hits[:MAX_CELLS]
    st.caption(f"{len(hits):,} cells" + (f" · showing the first {len(shown):,}" if len(hits) > len(shown) else ""))
    if not shown:
        st.info("No cell matches. Check the spelling and the capital letters, or show every cell.")
        return
    widget = "ri_cells_" + ui_logic.sha256_hex(f"{impact.key}|{only}|{find}")[:12]
    event = st.dataframe(pd.DataFrame([{"Result": ICON[h.status], "Tag": h.tag, "Status": h.kind, "Cabinet": h.cabinet,
                                        "CIOC": h.cioc, "BP": h.bp, "CH": h.ch, "CHARM Type": h.charm, "IO": h.io,
                                        "Cable": h.cable, "Detail": h.detail} for h in shown]),
                         key=widget, on_select="rerun", selection_mode="multi-row", hide_index=True, width="stretch",
                         height=min(420, 38 + 35 * len(shown)))
    rows = event.selection.rows if event is not None else []
    sids = [shown[i].sid for i in rows if i < len(shown)]
    with st.container(horizontal=True, gap="small"):
        st.button(f"Open {len(sids):,} Picked Cell(s) In Rule Check" if sids else "Open Picked Cells In Rule Check",
                  key="ri_to_rc", on_click=_to_rule_check, args=(sids,), disabled=not sids, type="primary",
                  help="Tick cells in the list first (up to 12 open at once)." if not sids else
                  "See every rule that applies to these cells, with their signal paths.")
        st.download_button("Download This List (.csv)", data=_csv(impact, hits), mime="text/csv", on_click="ignore",
                           file_name=f"Rule_Impact_{ui_logic.sha256_hex(impact.key)[:6]}.csv", key="ri_csv")


def _csv(impact: ri.Impact, hits: list[ri.Hit]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Rule", impact.rule, impact.title, impact.group])
    w.writerow(["Result", "Tag", "Status", "Cabinet", "CIOC", "Baseplate", "Channel", "CHARM Type", "IO Type", "Cable",
                "Detail"])
    for h in hits:
        w.writerow([ICON[h.status], h.tag, h.kind, h.cabinet, h.cioc, h.bp, h.ch, h.charm, h.io, h.cable, h.detail])
    return out.getvalue().encode("utf-8")
