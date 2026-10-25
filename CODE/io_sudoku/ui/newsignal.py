"""Add A Signal: put one new row into the uploaded file from a few basic facts.

Pure logic (no widgets), so it is testable without a browser.
  options(sheets, index)        what the file already holds (rooms, cables, sizes, codes ...) for the dropdowns
  problems(values, opts)        what stops the signal from being added (a tag already used, a pair taken ...)
  warnings(values, opts)        what is allowed but will raise a question (no cable or pair ...)
  plan(values, opts, sheets)    the cells of the new row, written the way the file already writes them

A new signal is an ordinary edit of the INPUT file: it is listed under Your Changes, saved as a file revision,
and the allocation is out of date (DRAFT) until you re-allocate.  The solver reads it exactly like any other row.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from io_sudoku.core.constants import IO_TYPES, MAX_CABLE_PAIRS
from io_sudoku.core.textnorm import clean, match_key, to_int

# (field, label) in the order they are asked; the first three are required
FIELDS = (("tag", "Tag"), ("io_type", "IO Type"), ("tech_room", "Technical Room"), ("cable_no", "Cable Number"),
          ("pair_no", "Pair Number"), ("cable_size", "Cable Size"), ("segregation", "Segregation"),
          ("instrument_type", "Instrument Type"), ("signal_type", "Signal Type"), ("service", "Service"))
REQUIRED = ("tag", "io_type", "tech_room")
PICKED = ("tech_room", "cable_size", "segregation", "instrument_type", "signal_type")


@dataclass
class Cable:
    text: str
    size: str = ""
    room: str = ""
    pairs: dict[int, str] = field(default_factory=dict)     # pair number -> tag

    def next_pair(self) -> int:
        n = 1
        while n in self.pairs:
            n += 1
        return n


@dataclass
class Options:
    sheet: str | None                                        # the sheet the signals are on
    columns: dict[str, int]                                  # field -> column position in that sheet
    tags: set[str]                                           # match keys of the tags already in the file
    values: dict[str, Counter]                               # field -> the values already used, with counts
    cables: dict[str, Cable]                                 # cable match key -> what the file says about it
    pair_word: str = ""                                      # 'Pair' when pairs are written 'Pair 3', '' for 3
    compact_ok: bool = False                                 # the TagNumber column is the tag without punctuation


def _text(value: Any) -> str:
    return clean(value) or ""


def compact(tag: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", tag or "")


def options(sheets: list[Any], index: Any) -> Options:
    """What the file already holds, read with the solver's own column mapping (`index` = editing.build_index)."""
    where = Counter(sheet for sheet, _ in index.tags.values())
    name = where.most_common(1)[0][0] if where else (sheets[0].name if sheets else None)
    sheet = next((x for x in sheets if x.name == name), None)
    columns = {f: m.index for f, m in index.mapping.items() if m.index is not None}
    out = Options(name, columns, set(index.tags), {f: Counter() for f, _ in FIELDS}, {})
    if sheet is None:
        return out
    words, compact_hits, compact_rows = Counter(), 0, 0
    for _, row in sheet.rows:
        def cell(f: str) -> str:
            col = columns.get(f)
            return _text(row[col]) if col is not None and col < len(row) else ""
        for f, _ in FIELDS:
            if cell(f):
                out.values[f][cell(f)] += 1
        cable = cell("cable_no")
        if cable:
            c = out.cables.setdefault(match_key(cable) or cable, Cable(cable))
            c.size = c.size or cell("cable_size")
            c.room = c.room or cell("tech_room")
            pair = to_int(cell("pair_no"))
            if pair:
                c.pairs.setdefault(pair, cell("tag"))
        word = re.match(r"^\s*([A-Za-z]+)\s*\d+\s*$", cell("pair_no"))
        words[word.group(1).title() if word else ""] += 1 if cell("pair_no") else 0
        if cell("tag") and "tag_compact" in columns:
            compact_rows += 1
            compact_hits += cell("tag_compact") == compact(cell("tag"))
    words = +words                                       # only the spellings really used
    out.pair_word = words.most_common(1)[0][0] if words else ""
    out.compact_ok = compact_rows > 0 and compact_hits >= 0.95 * compact_rows
    return out


def problems(values: dict[str, Any], opts: Options) -> list[str]:
    """Why the signal cannot be added yet ([] = it can)."""
    out = []
    labels = dict(FIELDS)
    for f in REQUIRED:
        if not _text(values.get(f)):
            out.append(f"{labels[f]} is required.")
    tag = _text(values.get("tag"))
    if tag and (match_key(tag) or "") in opts.tags:
        out.append(f"The tag {tag} is already in the file. Every signal needs its own tag.")
    if tag and len(tag) > 60:
        out.append("Keep the tag under 60 characters.")
    io_type = _text(values.get("io_type")).upper()
    if io_type and io_type not in IO_TYPES:
        out.append(f"IO Type must be one of {', '.join(IO_TYPES)}.")
    for f in ("tag", "io_type", "tech_room"):
        if f not in opts.columns:
            out.append(f"Your file has no {labels[f]} column, so the signal cannot be written into it.")
    cable, pair = _text(values.get("cable_no")), to_int(values.get("pair_no"))
    known = opts.cables.get(match_key(cable) or "") if cable else None
    if known and pair and pair in known.pairs:
        out.append(f"Pair {pair} of cable {known.text} is already used by {known.pairs[pair] or 'another signal'}. "
                   f"The next free pair is {known.next_pair()}.")
    if pair is not None and not 1 <= pair <= MAX_CABLE_PAIRS:
        out.append(f"The pair number must be between 1 and {MAX_CABLE_PAIRS}.")
    return out


def warnings(values: dict[str, Any], opts: Options) -> list[str]:
    """Allowed, but the solver will ask about it."""
    out = []
    cable, pair = _text(values.get("cable_no")), to_int(values.get("pair_no"))
    if not cable:
        out.append("Without a cable number the signal is held back (MISSING-CABLE) until you fill it in.")
    elif not pair:
        out.append("Without a pair number the signal is held back (MISSING-PAIR) until you fill it in.")
    known = opts.cables.get(match_key(cable) or "") if cable else None
    room = _text(values.get("tech_room"))
    if known and known.room and room and match_key(known.room) != match_key(room):
        out.append(f"Cable {known.text} is in {known.room}, not {room}. One cable runs to one room.")
    if known and known.size and _text(values.get("cable_size")) and match_key(known.size) != match_key(values.get("cable_size")):
        out.append(f"Cable {known.text} is written as {known.size} on its other rows.")
    return out


def plan(values: dict[str, Any], opts: Options, sheets: list[Any]) -> tuple[str, int, list[tuple[int, str, Any]]]:
    """(sheet, Excel row, [(column, header, value)]) of the new row: right below the last row of the sheet."""
    sheet = next(x for x in sheets if x.name == opts.sheet)
    row = (max((r for r, _ in sheet.rows), default=sheet.header_row) + 1)
    cells: list[tuple[int, str, Any]] = []
    for f, _ in FIELDS:
        value = _text(values.get(f))
        if not value or f not in opts.columns:
            continue
        if f == "io_type":
            value = value.upper()
        if f == "pair_no":
            n = to_int(value)
            value = f"{opts.pair_word} {n}" if opts.pair_word else n
        col = opts.columns[f]
        cells.append((col, sheet.headers[col] if col < len(sheet.headers) else f"Column {col + 1}", value))
    tag = _text(values.get("tag"))
    if opts.compact_ok and "tag_compact" in opts.columns and tag:
        col = opts.columns["tag_compact"]
        cells.append((col, sheet.headers[col] if col < len(sheet.headers) else f"Column {col + 1}", compact(tag)))
    return sheet.name, row, cells
