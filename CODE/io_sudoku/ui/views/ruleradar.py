"""Rule Radar: Rule Check and Rule Impact on one page, as two tabs (the same way Revision holds its tabs).

  * Rule Check  - pick cells, see every rule that applies to each (cells -> rules);
  * Rule Impact - pick one rule or constraint, see every cell, CHARM and signal it touches (rule -> cells).
The two tabs are exactly the old pages (views/rulecheck.py and views/ruleimpact.py), moved under one heading.
The open tab is remembered (state.RULE_TAB_KEY), so links, the search bar and a click on a slot open the right one.
"""
from __future__ import annotations

import streamlit as st

from io_sudoku.ui import state


def render() -> None:
    from io_sudoku.ui.views import rulecheck, ruleimpact
    s = st.session_state
    st.header("Rule Radar", help="Every rule and constraint, seen two ways. Rule Check: pick any cell and see every rule "
                                 "that applies to it. Rule Impact: pick one rule and see every cell, CHARM and signal it "
                                 "affects, met or broken. Nothing here changes the allocation.")
    if s.get(state.RULE_TAB_KEY) not in state.RULE_TABS:
        s[state.RULE_TAB_KEY] = state.RULE_TABS[0]
    check_tab, impact_tab = st.tabs(list(state.RULE_TABS), key=state.RULE_TAB_KEY, on_change="rerun")
    with check_tab:
        rulecheck.render()
    with impact_tab:
        ruleimpact.render()
