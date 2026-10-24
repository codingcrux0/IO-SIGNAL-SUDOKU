"""Text cleaning helpers - the first line of defence against messy Excel data.

Excel cells arrive as strings, floats (320.0), dates, NaN, "-", "None", cells with
non-breaking spaces, full-width digits and so on.  Every function in this module
accepts ANY Python object and NEVER raises: bad input simply becomes None / "".

Key idea (important for tag names):
  * clean()     strips only the ENDS of a text.  Tags such as "320-FT   -20645-A"
                contain deliberate internal spaces that must survive.
  * match_key() is used to COMPARE two texts: case-folded and with every run of
                whitespace collapsed to one space.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime

from io_sudoku.core.constants import BUILTIN_IO_ALIASES

# Texts that mean "nothing here" (compared case-insensitively after cleaning).
BLANK_TOKENS = frozenset({"", "-", "none", "nan", "n/a", "na", "null"})
# Every dash-like character; a cell made only of these is a blank placeholder.
DASH_CHARS = "-‐‑‒–—―−"

_WS_RUN = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


def _to_text(value: object) -> str | None:
    """Turn any cell value into text (or None for 'no value')."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


def _normalise(text: str) -> str:
    """NFKC (full-width -> normal, NBSP -> space), drop zero-width chars, strip ends."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    return text.strip()


def is_blank(value: object) -> bool:
    """True when the value carries no information (None, NaN, '', '-', 'None', ...)."""
    try:
        text = _to_text(value)
        if text is None:
            return True
        text = _normalise(text)
        if text == "":
            return True
        if all(ch in DASH_CHARS for ch in text):
            return True
        return text.casefold() in BLANK_TOKENS
    except Exception:  # never crash on a strange cell
        return True


def clean(value: object) -> str | None:
    """Strip the ends of a value's text; internal spacing is kept. Blank -> None."""
    try:
        text = _to_text(value)
        if text is None:
            return None
        text = _normalise(text)
        return None if is_blank(text) else text
    except Exception:
        return None


def match_key(value: object) -> str | None:
    """Comparison key: cleaned, case-folded, whitespace runs collapsed to one space."""
    try:
        text = clean(value)
        if text is None:
            return None
        return _WS_RUN.sub(" ", text.casefold())
    except Exception:
        return None


def text_key(value: object) -> str:
    """Like match_key but never None ('' for blank) - used for exact header matching."""
    try:
        text = _to_text(value)
        if text is None:
            return ""
        return _WS_RUN.sub(" ", _normalise(text).casefold())
    except Exception:
        return ""


def header_key(value: object) -> str:
    """Looser header key: lower-case letters and digits only ('Tag No.' -> 'tagno')."""
    try:
        text = _to_text(value)
        if text is None:
            return ""
        text = unicodedata.normalize("NFKC", text).casefold()
        return re.sub(r"[^a-z0-9]", "", text)
    except Exception:
        return ""


def to_int(value: object) -> int | None:
    """First whole number found: 'Pair 12' -> 12, 'Triad 1' -> 1, 320.0 -> 320."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        text = _to_text(value)
        if text is None:
            return None
        match = _DIGITS.search(unicodedata.normalize("NFKC", text))
        return int(match.group(0)) if match else None
    except Exception:
        return None


def normalise_io_type(value: object, extra_aliases: dict[str, str] | None = None) -> str | None:
    """AI->AIR, DI->DIR, DO->DOR, AO->AOR. Unknown text comes back upper-cased."""
    try:
        text = clean(value)
        if text is None:
            return None
        upper = text.upper()
        if upper in BUILTIN_IO_ALIASES:
            return BUILTIN_IO_ALIASES[upper]
        if extra_aliases:
            extra = {str(k).strip().upper(): v for k, v in extra_aliases.items()}
            if upper in extra:
                return extra[upper]
        return upper
    except Exception:
        return None
