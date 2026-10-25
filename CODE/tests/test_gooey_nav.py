"""Smooth navigation: the gooey tab bars, the page bar at the top and the bouncing sidebar dot (ui/gooey.py)."""
from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from io_sudoku.ui import gooey, state

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_the_spring_settles_without_bouncing_past_the_end():
    curve, ms = gooey.spring_easing()
    values = [float(v) for v in re.findall(r"[\d.]+", curve)]
    assert values[0] == 0 and values[-1] == 1 and len(values) >= 20
    assert all(b >= a for a, b in zip(values, values[1:]))               # never goes back (no overshoot)
    assert 300 <= ms <= 900


def test_every_tab_bar_and_one_choice_row_is_gooey_but_the_row_sign_off_is_not():
    css = gooey.CSS
    assert "@property --gn-o" in css and "inherits:true" in css
    assert '[data-testid="stTabs"] [role="tablist"]>[role="tab"][aria-selected="true"]' in css
    assert 'button[data-variant="segmented_control"][aria-checked="true"]' in css
    assert ':not([class*="st-key-signoff_"]:not(.st-key-signoff_show) *)' in css     # the TQ Show filter stays gooey
    assert ".react-aria-SelectionIndicator{display:none}" in css
    assert gooey.SPRING in css                                            # the design's spring, as a CSS curve


def test_the_chosen_item_opens_a_gap_on_both_sides_and_its_neighbours_round_their_corners():
    css = gooey.gooey_css(".bar", ".it", ".on", "md")
    height, pad, font, radius, gap = gooey.SIZES["md"]
    assert f".bar>.it.on{{--gn-o:1;" in css                                # the gap on its left
    assert f".bar>.it.on+.it{{--gn-o:1;" in css                            # and on its right
    assert f".bar>.it:has(+.it.on){{border-top-right-radius:{radius}px" in css
    assert f"calc(var(--gn-o)*{gap + 1}px - 1px)" in css                   # closed seams overlap by a pixel
    assert f"(var(--gn-o) - {gooey.NECK_BREAK})" in css                    # the neck pinches off at 22 % open
    assert ".bar>.it:first-child::before{display:none}" in css


def test_the_sidebar_is_thinner_only_while_open_and_the_dot_moves_with_transform_only():
    assert f"width:{gooey.SIDEBAR_WIDTH}px!important" in gooey.CSS and gooey.SIDEBAR_WIDTH < 300
    assert '[data-testid="stSidebar"]:not([data-collapsed="true"])' in gooey.CSS
    js = gooey.BOUNCE
    assert "__iosgBounce1" in js and "prefers-reduced-motion" in js and "transitionDuration" in js
    assert "translate(" in js and "top =" not in js and ".style.top" not in js
    assert "MutationObserver" in js and "requestAnimationFrame" in js


def test_lite_mode_still_switches_every_motion_off():
    from io_sudoku.ui import theme
    assert "transition:none!important" in theme.LITE_CSS


def test_the_page_bar_follows_the_sidebar_and_opens_the_page_picked():
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["view"] = "Upload"
    at.run()
    bar = at.button_group(key=gooey.TOP_KEY)
    assert not at.exception and bar.value == "Upload" and list(bar.options) == list(state.VIEWS)
    next(b for b in at.button if b.label == "Try With Sample Data").click().run()
    at.button_group(key=gooey.TOP_KEY).set_value("Rules").run()
    assert not at.exception and at.session_state["view"] == "Rules"
    at.session_state["view"] = "TQ Board"                                 # moved by the sidebar or a link
    at.run()
    assert at.button_group(key=gooey.TOP_KEY).value == "TQ Board"


def test_without_a_file_the_page_bar_greys_out_edit_file():
    css = gooey.disabled_css([state.VIEWS.index(v) for v in state.NEEDS_FILE])
    assert f".st-key-{gooey.TOP_KEY} [role=radiogroup]>:nth-child({state.VIEWS.index('Edit File') + 1})" in css
    assert "pointer-events:none" in css and gooey.disabled_css([]) == ""
