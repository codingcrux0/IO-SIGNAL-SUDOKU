"""Find which spreadsheet column holds which piece of data, even when headers drift.

The customer MDB has 143 columns whose names are not guaranteed to stay the same.
map_columns() matches each wanted field to a header in strict order of trust:

  0. override  the engineer told us the header text
  1. exact     the preferred header text (case/space-insensitive)
  2. alias     any other accepted header text
  3. key       same letters/digits once punctuation is ignored
  4. fuzzy     a similar-looking header (difflib ratio >= 0.88)

IMPORTANT (fixes audit finding F02): the MDB contains BOTH 'Tag Number'
('320-FT   -20645-A') and 'TagNumber' ('320FT20645A').  They look the same once
punctuation is dropped, so the exact tier runs first and 'TagNumber' is claimed by
its own field (tag_compact).  The fuzzy tier runs LAST, only for fields still
unmatched, so a guess can never steal another field's exact match.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from io_sudoku.core.textnorm import clean, header_key, text_key

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Fields without which nothing can be allocated.
MANDATORY_FIELDS = ("tag", "io_type", "tech_room")

_BUILTIN_ALIASES: dict[str, list[str]] = {
    "tag": ["Tag Number"], "tag_compact": ["TagNumber", "System Tag Name"],
    "io_type": ["I/O Type Name", "IO Type"], "io_type2": ["I/O Type Name 2"],
    "tech_room": ["Technical Room (Signal Location 2)", "Technical Room"],
    "operating_area": ["OA No.", "Operating Area"], "risk_area": ["Design Area", "Risk Area"],
    "unit": ["WBS", "Unit"], "segregation": ["IO Grouping", "Segregation"],
    "service": ["Tag Service 1 and 2", "Service Description", "Service"],
    "location": ["Location"], "signal_type": ["Signal Type"], "signal_level": ["Signal Level"],
    "execution": ["Execution", "NON-IS / IS"], "ext_power": ["External Power Supply", "External Power"],
    "equipment": ["Equipment Name"], "cable_no": ["Multipair Cable No.", "Field Cable No"],
    "cable_size": ["Multi-cable / Cable", "Field Cable Size"],
    "pair_no": ["Pair Number", "Field Cable Pair"], "logic_no": ["Logic Number"],
    "instrument_type": ["Instrument Type Description", "Instrument type"],
    "instrument_code": ["Instrument Type"], "loop_name": ["Loop Name"],
    "old_tag": ["Old Tag Number", "Old Tag"], "system2": ["System 2"], "status": ["Status"],
}


@dataclass(frozen=True)
class ColumnMatch:
    field: str
    header: str | None   # the header text found (None if missing)
    index: int | None    # 0-based column position (None if missing)
    method: str          # 'override' | 'exact' | 'alias' | 'fuzzy' | 'missing'
    score: float


def load_aliases() -> dict[str, list[str]]:
    """Bundled aliases.json, or the built-in copy if the file is unreadable."""
    try:
        data = json.loads((DATA_DIR / "aliases.json").read_text(encoding="utf-8"))
        aliases = {str(k): [str(a) for a in v] for k, v in data.items()}
        if aliases:
            return aliases
    except Exception:
        pass
    return {k: list(v) for k, v in _BUILTIN_ALIASES.items()}


def _leftmost(columns: list[tuple[int, str, str]], taken: set[int], wanted: str, use_key: bool) -> int | None:
    """Leftmost untaken column whose text_key (or header_key) equals `wanted`."""
    if not wanted:
        return None
    for idx, tkey, hkey in columns:
        if idx in taken:
            continue
        if (hkey if use_key else tkey) == wanted:
            return idx
    return None


def map_columns(headers: list[object], aliases: dict[str, list[str]] | None = None,
                overrides: dict[str, str] | None = None, fuzzy_min: float = 0.88) -> dict[str, ColumnMatch]:
    """Map every field in `aliases` to a column index. Always returns one entry per field."""
    aliases = aliases if aliases is not None else load_aliases()
    overrides = overrides or {}
    texts: list[str | None] = [clean(h) for h in headers]
    columns = [(i, text_key(t), header_key(t)) for i, t in enumerate(texts) if t]
    taken: set[int] = set()
    result: dict[str, ColumnMatch] = {}

    def claim(field: str, idx: int, method: str, score: float) -> None:
        taken.add(idx)
        result[field] = ColumnMatch(field, texts[idx], idx, method, score)

    # Pass 0: engineer overrides (highest trust).
    for field in aliases:
        wanted = overrides.get(field)
        if not wanted:
            continue
        idx = _leftmost(columns, taken, text_key(wanted), False)
        if idx is None:
            idx = _leftmost(columns, taken, header_key(wanted), True)
        if idx is not None:
            claim(field, idx, "override", 1.0)

    # Pass 1a: the PREFERRED header text of every field (exact tier).
    for field, names in aliases.items():
        if field in result or not names:
            continue
        idx = _leftmost(columns, taken, text_key(names[0]), False)
        if idx is not None:
            claim(field, idx, "exact", 1.0)

    # Pass 1b: the other accepted header texts (alias tier).
    for field, names in aliases.items():
        if field in result:
            continue
        for name in names:
            idx = _leftmost(columns, taken, text_key(name), False)
            if idx is not None:
                claim(field, idx, "alias", 1.0)
                break

    # Pass 1c: same letters/digits ignoring punctuation (key tier). It runs only after
    # EVERY field has had its exact-text chance, so e.g. the field 'tag' can never take
    # the 'TagNumber' column that belongs to 'tag_compact'.
    for field, names in aliases.items():
        if field in result:
            continue
        for name in names:
            idx = _leftmost(columns, taken, header_key(name), True)
            if idx is not None:
                claim(field, idx, "alias", 0.99)
                break

    # Pass 2: fuzzy tier, only for fields that are still unmatched.
    for field, names in aliases.items():
        if field in result:
            continue
        best: tuple[float, int, int] | None = None   # (score, alias order, column index)
        for idx, _tkey, hkey in columns:
            if idx in taken or not hkey:
                continue
            for order, name in enumerate(names):
                akey = header_key(name)
                if not akey:
                    continue
                score = SequenceMatcher(None, akey, hkey).ratio()
                if score >= fuzzy_min:
                    candidate = (score, -order, -idx)   # higher score, earlier alias, leftmost column
                    if best is None or candidate > (best[0], -best[1], -best[2]):
                        best = (score, order, idx)
        if best is not None:
            claim(field, best[2], "fuzzy", round(best[0], 3))

    for field in aliases:
        result.setdefault(field, ColumnMatch(field, None, None, "missing", 0.0))
    return result


def missing_mandatory(mapping: dict[str, ColumnMatch]) -> list[str]:
    """Mandatory fields that no column was found for."""
    return [f for f in MANDATORY_FIELDS if mapping.get(f) is None or mapping[f].index is None]
