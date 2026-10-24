from __future__ import annotations

from datetime import date, datetime

import pytest

from io_sudoku.core import constants as k
from io_sudoku.core.textnorm import (
    clean, header_key, is_blank, match_key, normalise_io_type, text_key, to_int,
)


def test_constants_capacity():
    assert k.SLOTS_PER_CAB == k.CIOCS_PER_CAB * k.BPS_PER_CIOC * k.SLOTS_PER_BP == 384


def test_clean_keeps_internal_spaces_but_strips_ends():
    assert clean("  320-FT   -20645-A ") == "320-FT   -20645-A"


def test_match_key_ignores_case_and_space_runs():
    assert match_key("320-FT   -20645-A ") == match_key("320-ft -20645-a")


@pytest.mark.parametrize("v", [None, float("nan"), "", "-", " - ", "None", "NaN", " ", "—", "–", "n/a", "NA", "--"])
def test_is_blank_true(v):
    assert is_blank(v) is True


@pytest.mark.parametrize("v", [0, "0", "AIR", False, "x"])
def test_is_blank_false(v):
    assert is_blank(v) is False


def test_clean_numbers():
    assert clean(320.0) == "320"
    assert clean(12.5) == "12.5"
    assert clean(7) == "7"


def test_to_int():
    assert to_int("Pair 12") == 12
    assert to_int("Triad 1") == 1
    assert to_int(7.0) == 7
    assert to_int("３２０") == 320  # full-width digits
    assert to_int("Internal Wiring") is None
    assert to_int("-") is None
    assert to_int(None) is None
    assert to_int(True) is None


def test_normalise_io_type():
    assert [normalise_io_type(x) for x in ("AI", "di", "DO ", "AO", "AIR")] == ["AIR", "DIR", "DOR", "AOR", "AIR"]
    assert normalise_io_type("XYZ") == "XYZ"
    assert normalise_io_type("-") is None
    assert normalise_io_type("dox", {"DOX": "DOR"}) == "DOR"
    assert normalise_io_type("DO", {"DO": "AIR"}) == "DOR"  # built-ins win


def test_full_width_tags_match():
    assert match_key("320-ＦＴ-1") == match_key("320-FT-1")


def test_header_key_and_text_key():
    assert header_key("Splitter/Relay/\nExternal PWR\nTB(+)") == "splitterrelayexternalpwrtb"
    assert header_key("Tag No.") == "tagno"
    assert text_key("  Tag   Number ") == "tag number"
    assert text_key(None) == ""


@pytest.mark.parametrize("weird", [object(), b"\xff", datetime(2024, 1, 2), date(2024, 1, 2), [1, 2], {"a": 1}, float("inf")])
def test_nothing_raises(weird):
    for fn in (is_blank, clean, match_key, to_int, normalise_io_type, header_key, text_key):
        fn(weird)  # must not raise


def test_dates_become_iso_text():
    assert clean(datetime(2024, 6, 14)) == "2024-06-14T00:00:00"
