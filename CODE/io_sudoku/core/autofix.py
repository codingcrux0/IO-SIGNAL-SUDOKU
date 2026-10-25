"""Suggested Fixed File: a copy of a messy MDB with every problem the file itself can answer already fixed.

No AI and no guessing.  Each fix is a fixed rule, and each change says why it was made, with the evidence from
the file.  Problems the file cannot answer (a missing tag, a missing pair number, an intrinsically safe signal ...)
are NOT touched: they are listed for the engineer with the reason.

Two kinds of fix (each group can be switched off):
  sure        only the WAY something is written changes, never what it means: the reader already reads it the
              same way (spaces at the ends, 'ai' -> 'AIR', 'pib-24' -> 'PIB-24', 'a' -> 'A'), your own column
              choices, and exact copies of a row.
  from file   a value worked out from the rest of the same file, only when the evidence is unanimous:
              a column found by what it holds, a blank filled from a second column with the same data (that
              agrees on every row where both are filled), the room or cable size of a cable taken from its other
              rows, an IO type taken from at least 3 signals of the same instrument and signal type that all agree,
              and a cable size that cannot be right (smaller than a pair used on the cable) replaced by the only
              size that fits.

Safety net: the original and the suggested file are both allocated by the real solver.  If the suggestion had
more errors, or a signal that was placed before would no longer be placed, the 'from file' fixes are dropped; if
it is still worse, no file is suggested at all.  The solver and its rules are not changed in any way: the
suggested file is just another input file, and it is used only if the engineer chooses it.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from io_sudoku.core.columnmap import ColumnMatch, MANDATORY_FIELDS, load_aliases, map_columns, missing_mandatory
from io_sudoku.core.config import Config, copy_config, load_config
from io_sudoku.core.constants import BUILTIN_IO_ALIASES, IO_TYPES, MAX_CABLE_PAIRS
from io_sudoku.core.ingest import _OLE_MAGIC, _csv_tables, _pick_header, _xlsx_tables
from io_sudoku.core.textnorm import clean, header_key, is_blank, match_key, normalise_io_type, text_key, to_int
from io_sudoku.core.validate import parse_cable_size

MIN_PEERS = 3                     # signals of the same instrument that must agree before an IO type is filled in
MIN_OVERLAP = 3                   # rows where two columns are both filled before one may fill the other
CONTENT_SHARE = 0.8               # share of values that must look right before a column is recognised by content
MAX_LISTED = 2000                 # changes kept in the explanation


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    sure: bool
    why: str


GROUPS: dict[str, Group] = {g.key: g for g in (
    Group("column_choice", "Your column choices written into the header", True,
          "On Upload you told the tool which column holds this field. The header is renamed to the standard name, so "
          "the file is read the same way without your choice."),
    Group("column_found", "Columns recognised by what they hold", False,
          "No header matched this field (or only a look-alike did), but exactly one column holds values of that kind. "
          "Its header is renamed to the standard name so the solver reads it."),
    Group("column_merge", "Blanks filled from a second column with the same data", False,
          "Your file has two columns for the same field. Where the main one is blank, the value of the other one is "
          "used. This is done only when the two columns agree on every row where both hold a usable value."),
    Group("spaces", "Spaces removed from the ends of cells", True,
          "The solver already ignores these spaces; the file is only made tidy. Spaces inside a tag are kept."),
    Group("io_spelling", "IO types written the standard way", True,
          "The solver already reads these as a standard IO type ('ai ' as AI, a name from the rule pack as its IO "
          "type); the file now says so. AI and AIR are both standard, so they are kept as written."),
    Group("room_spelling", "Technical rooms written as configured", True,
          "Only upper/lower case or spacing differed from the room's configured name."),
    Group("seg_case", "Segregation codes in capitals", True,
          "Only upper/lower case differed from a known segregation code."),
    Group("duplicate_row", "Exact copies of a row removed", True,
          "Every cell of the row is the same as an earlier row: it is the same signal pasted twice. Without the copy "
          "the tag is no longer a duplicate."),
    Group("room_from_cable", "Technical room taken from the rest of its cable", False,
          "One cable runs to one technical room. This row's room was blank or not a configured room, and every other "
          "row of the same cable names the same configured room."),
    Group("size_from_cable", "Cable size taken from the rest of its cable", False,
          "This row had no readable cable size, and every other row of the same cable gives the same size."),
    Group("size_conflict", "Impossible cable size corrected", False,
          "The rows of one cable gave different sizes. A cable cannot be smaller than a pair number it uses, so only "
          "one of the sizes is possible; every row of the cable now gives that size."),
    Group("io_from_peers", "IO type worked out from the same kind of instrument", False,
          f"This row's IO type was blank or unknown. At least {MIN_PEERS} other signals with the same instrument type "
          "and the same signal type have an IO type, and they all agree."),
)}


@dataclass(frozen=True)
class Change:
    group: str
    sheet: str
    row: int                       # Excel row (1-based); the header row for a column rename
    column: str                    # the column's header as it was
    old: Any
    new: Any                       # REMOVED for a removed row
    why: str


REMOVED = "(row removed)"


@dataclass(frozen=True)
class Measures:
    status: str
    errors: int
    warnings: int
    held_back: int
    placed: int
    placed_tags: frozenset[str] = frozenset()


@dataclass
class Suggestion:
    data: bytes | None                       # the suggested file (None = nothing safe to suggest)
    file_name: str
    changes: list[Change] = field(default_factory=list)
    before: Measures | None = None
    after: Measures | None = None
    left: list[tuple[str, str, str, str]] = field(default_factory=list)   # (TQ id, severity, ref, why it was not fixed)
    unused: list[tuple[str, int, dict[str, str]]] = field(default_factory=list)  # (header, filled, {tag key: value})
    notes: list[str] = field(default_factory=list)
    dropped: tuple[str, ...] = ()            # groups dropped by the safety net

    def counts(self) -> dict[str, int]:
        return dict(Counter(c.group for c in self.changes))


# --------------------------------------------------------------------------------------- why not fixed
LEFT_WHY: dict[str, str] = {
    "BLANK-TAG": "A tag is a name only the engineer knows, so it is never made up. Type it on Edit File.",
    "DUPLICATE-TAG": "Two different rows use the same tag. Only the engineer knows which one is right.",
    "IS-SIGNAL-UNSUPPORTED": "By design the tool does not allocate intrinsically safe signals; they stay held back.",
    "OUT-OF-SCOPE-SIGNAL": "By design the tool does not allocate IRC / MCC signals; they stay held back.",
    "MISSING-IO-TYPE": f"Fewer than {MIN_PEERS} signals of the same instrument and signal type agree on an IO type, so it "
                       "is not filled in.",
    "UNKNOWN-IO-TYPE": f"It is not a known spelling, and fewer than {MIN_PEERS} signals of the same instrument and signal "
                       "type agree on one. If it is a real name, add it on Rules (New IO type name).",
    "MISSING-CABLE": "A cable number is a wiring fact: guessing one could wire the signal to the wrong cable.",
    "MISSING-PAIR": "A pair number is a wiring fact: guessing one could wire the signal to the wrong pair.",
    "DUPLICATE-PAIR": "Two signals use the same pair. Only the engineer knows which pair is right.",
    "PAIR-BEYOND-CABLE": "The pair number is higher than the cable has. Either could be wrong, so neither is changed.",
    "CABLE-SIZE-CONFLICT": "The rows of the cable give different sizes and more than one of them fits the pairs used.",
    "BAD-CABLE-SIZE": "No row of the cable gives a readable size and no pair number shows it.",
    "CABLE-SIZE-INFERRED": "The solver already assumes the smallest standard size that fits; please confirm it.",
    "UNSUPPORTED-SEGREGATION": "An unknown segregation code is never replaced. If it is a real code, define it on Rules "
                               "(Segregation code); otherwise correct it on Edit File.",
    "MIXED-SEGREGATION": "A and B signals share one cable. Only the engineer knows which signal is wrong.",
    "NO-CABINET-FOR-ROOM": "The room is not configured and the other rows of its cable do not name one either.",
    "TOPOLOGY-INFERRED": "A room without a cabinet: the tool proposed one. Please confirm it on the TQ Board.",
    "GROUP-SPANS-ROOMS": "Signals of one logic group sit in different rooms; only the engineer knows which room is right.",
    "MISSING-COLUMN": "No column holds this field by its name or by what it holds (or two columns could). Pick it on "
                      "Upload (Check How Your Columns Were Understood).",
    "COLUMN-FUZZY-MATCHED": "The column was matched by a similar name, and its values could not confirm it. Please check it.",
    "IO-TYPE-CONFLICT": "The second IO type does not pair with the first. Either could be right, so neither is changed.",
    "ALARMS-MISSING-FOR-CABINET": "The file has no cabinet alarm rows for this cabinet. Alarm tags are real signals, so "
                                  "they are never made up: add them to the file, or approve the warning.",
    "CABINET-AUTO-ADDED": "There were more signals than the room's cabinets hold, so a cabinet was added. Please confirm it.",
    "CABLE-TOO-LARGE": "The cable has more pairs than one controller holds. Only the engineer can split it.",
    "ALARM-UNKNOWN-KIND": "The alarm tag does not end in a known kind (-T, -AC, -DC ...). Only the engineer knows which it is.",
    "NO-CABINET-FOR-ALARM": "The alarm names a cabinet that is not configured. Only the engineer knows the right cabinet.",
    "MISSING-SIGNAL-LEVEL": "The signal level is an instrument fact, so it is never guessed.",
    "DIR-CONTACT-CHECK": "The contact type is an instrument fact: only the engineer can confirm the input is a dry contact.",
    "UNKNOWN-DOR-DUTY": "The output's duty (normal or high current) cannot be told from the file; please confirm it.",
    "ROW-MISALIGNED": "The values of the row slipped out of their columns in a way that cannot be repaired safely.",
}
DEFAULT_WHY = "This needs an engineer's decision. See the suggested fix on the TQ Board."


# --------------------------------------------------------------------------------------- reading
@dataclass
class _Sheet:
    name: str
    rows: list[list[Any]]                    # every row of the sheet (index 0 = Excel row 1)
    header: int                              # index of the header row
    mapping: dict[str, ColumnMatch]
    usable: bool = False

    def col(self, fld: str) -> int | None:
        match = self.mapping.get(fld)
        return match.index if match is not None else None

    def data(self) -> list[int]:
        """Indexes of the non-blank rows below the header."""
        return [i for i in range(self.header + 1, len(self.rows)) if any(not is_blank(c) for c in self.rows[i])]


def _tables(data: bytes) -> list[tuple[str, list[tuple[Any, ...]]]]:
    if not data or data[:4] == _OLE_MAGIC:
        raise ValueError("not a readable table")
    return _xlsx_tables(data) if data[:2] == b"PK" else _csv_tables(data)


def _sheets(data: bytes, aliases: dict[str, list[str]], overrides: dict[str, str] | None) -> list[_Sheet]:
    out = []
    for name, rows in _tables(data):
        if not any(any(not is_blank(c) for c in r) for r in rows):
            continue
        header, mapping = _pick_header(rows, aliases, overrides)
        width = max((len(r) for r in rows), default=0)
        grid = [list(r) + [None] * (width - len(r)) for r in rows]
        out.append(_Sheet(name, grid, header, mapping, not missing_mandatory(mapping)))
    return out


# --------------------------------------------------------------------------------------- the plan
class _Plan:
    def __init__(self, skip: set[str]) -> None:
        self.skip = skip
        self.cells: dict[tuple[str, int, int], Change] = {}
        self.removed: dict[tuple[str, int], Change] = {}

    def set(self, sheet: _Sheet, i: int, col: int, new: Any, group: str, why: str) -> bool:
        """Change one cell (also in the working grid, so later rules see it).  Returns False when skipped."""
        if group in self.skip:
            return False
        old = sheet.rows[i][col]
        if _same(old, new):
            return False
        key = (sheet.name, i, col)
        first = self.cells.get(key)
        header = _header(sheet, col)
        self.cells[key] = Change(group, sheet.name, i + 1, header, first.old if first else old, new, why)
        sheet.rows[i][col] = new
        return True

    def remove(self, sheet: _Sheet, i: int, why: str) -> None:
        if "duplicate_row" not in self.skip:
            self.removed[(sheet.name, i)] = Change("duplicate_row", sheet.name, i + 1, "(whole row)", "", REMOVED, why)

    def changes(self) -> list[Change]:
        gone = {(sheet, i + 1) for sheet, i in self.removed}
        both = [c for c in self.cells.values() if (c.sheet, c.row) not in gone] + list(self.removed.values())
        order = list(GROUPS)
        return sorted(both, key=lambda c: (order.index(c.group), c.sheet, c.row, c.column))


def _same(a: Any, b: Any) -> bool:
    def norm(v: Any) -> str:
        if v is None or (isinstance(v, float) and v != v):
            return ""
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    return norm(a) == norm(b)


def _header(sheet: _Sheet, col: int) -> str:
    row = sheet.rows[sheet.header]
    value = row[col] if col < len(row) else None
    return str(value).strip() if value not in (None, "") else f"Column {col + 1}"


def _text(value: Any) -> str:
    return clean(value) or ""


# ------------------------------------------------------------------------------- 1. columns
def _looks_like(fld: str, values: list[Any], header: str, cfg: Config) -> bool:
    """True when a column's values (and, for tags and cables, its header) show it holds this field."""
    vals = [v for v in values if not is_blank(v)]
    if len(vals) < 3:
        return False

    def share(test) -> float:
        return sum(1 for v in vals if test(v)) / len(vals)
    hkey = header_key(header)
    if fld in ("io_type", "io_type2"):
        return share(lambda v: normalise_io_type(v, cfg.rules.io_aliases) in IO_TYPES) >= CONTENT_SHARE
    if fld == "tech_room":
        return share(lambda v: bool(cfg.cabinets_in_room(_text(v)))) >= CONTENT_SHARE
    if fld == "cable_size":
        return share(lambda v: re.match(r"^\s*\d+\s*[PT]", _text(v), re.I) is not None) >= CONTENT_SHARE
    if fld == "pair_no":
        return share(lambda v: re.match(r"^\s*(pair|triad|quad)\s*\d+\s*$", _text(v), re.I) is not None) >= CONTENT_SHARE
    if fld == "tag":
        keys = [match_key(v) for v in vals]
        return ("tag" in hkey and "old" not in hkey and len(set(keys)) >= 0.95 * len(keys)
                and share(lambda v: bool(re.search(r"\d", _text(v))) and bool(re.search(r"[A-Za-z]", _text(v)))) >= 0.9)
    if fld == "cable_no":
        counts = Counter(match_key(v) for v in vals)
        return ("cable" in hkey and not any(w in hkey for w in ("size", "type", "core"))
                and share(lambda v: bool(re.search(r"\d", _text(v)))) >= 0.9
                and sum(n for n in counts.values() if n > 1) >= 0.5 * len(vals))
    return False


CONTENT_FIELDS = ("tag", "io_type", "tech_room", "cable_no", "pair_no", "cable_size")


def _fix_columns(sheet: _Sheet, aliases: dict[str, list[str]], overrides: dict[str, str], cfg: Config, plan: _Plan,
                 notes: list[str]) -> None:
    header_row = sheet.rows[sheet.header]
    data = sheet.data()
    pending = dict(overrides)                            # column choices not yet written into the header

    def rename(fld: str, col: int, group: str, why: str) -> None:
        name = aliases[fld][0]
        if any(text_key(h) == text_key(name) for c, h in enumerate(header_row) if c != col):
            return                                       # the standard name is used by another column already
        before = {f: m.index for f, m in sheet.mapping.items() if m.index is not None}
        trial = list(header_row)
        trial[col] = name
        rest = {k: v for k, v in pending.items() if k != fld}
        after = map_columns(trial, aliases, rest)
        if after[fld].index != col or any(after[f].index != i for f, i in before.items() if f != fld):
            return                                       # renaming would move another field: leave it
        if plan.set(sheet, sheet.header, col, name, group, why):
            pending.pop(fld, None)
            sheet.mapping = after

    for fld, match in list(sheet.mapping.items()):
        if match.method == "override" and match.index is not None and fld in aliases:
            rename(fld, match.index, "column_choice",
                   f"You chose “{match.header}” for the {_words(fld)} on Upload; renamed to “{aliases[fld][0]}”.")
    taken = {m.index for m in sheet.mapping.values() if m.index is not None}
    for fld in CONTENT_FIELDS:
        match = sheet.mapping.get(fld)
        if match is not None and match.index is not None and match.method not in ("fuzzy",):
            continue
        candidates = []
        for col, head in enumerate(header_row):
            if is_blank(head) or (col in taken and not (match and match.index == col)):
                continue
            if _looks_like(fld, [sheet.rows[i][col] for i in data], str(head), cfg):
                candidates.append(col)
        if len(candidates) == 1:
            col = candidates[0]
            values = [sheet.rows[i][col] for i in data if not is_blank(sheet.rows[i][col])]
            how = "a look-alike name" if match and match.index == col else "no matching name"
            rename(fld, col, "column_found", f"Column “{_header(sheet, col)}” had {how}, and {len(values):,} of its values "
                                             f"are {_KIND_WORDS[fld]}, so it holds the {_words(fld)}.")
            taken.add(col)
        elif len(candidates) > 1 and (match is None or match.index is None):
            notes.append(f"Sheet {sheet.name}: the columns " + ", ".join(f"“{_header(sheet, c)}”" for c in candidates)
                         + f" all look like the {_words(fld)}. Pick the right one on Upload (Check How Your Columns Were Understood).")
    sheet.usable = not missing_mandatory(sheet.mapping)


FIELD_WORDS = {"tag": "tag", "io_type": "IO type", "io_type2": "second IO type", "tech_room": "technical room",
               "cable_no": "cable number", "pair_no": "pair number", "cable_size": "cable size", "segregation": "segregation",
               "instrument_type": "instrument type", "service": "service"}


def _words(fld: str) -> str:
    return FIELD_WORDS.get(fld, fld.replace("_", " "))


_KIND_WORDS = {"tag": "unique tag names", "io_type": "IO types (AIR / AOR / DIR / DOR)",
               "tech_room": "configured technical rooms", "cable_no": "cable numbers shared by several rows",
               "pair_no": "pair numbers (Pair 1, Pair 2 ...)", "cable_size": "cable sizes (24PX1MM2 ...)"}


def _merge_columns(sheet: _Sheet, aliases: dict[str, list[str]], cfg: Config, plan: _Plan) -> None:
    """A second column for the same field fills the main column's blanks, when the two always agree."""
    header_row = sheet.rows[sheet.header]
    taken = {m.index for m in sheet.mapping.values() if m.index is not None}
    data = sheet.data()

    def key(fld: str, value: Any) -> str:
        if fld in ("io_type", "io_type2"):
            return normalise_io_type(value, cfg.rules.io_aliases) or ""
        return match_key(value) or ""

    def valid(fld: str, value: Any) -> bool:
        """A value the solver can use (an IO type, a configured room ...); typos are left out of the comparison."""
        if is_blank(value):
            return False
        if fld in ("io_type", "io_type2"):
            return key(fld, value) in IO_TYPES
        if fld == "tech_room":
            return bool(cfg.cabinets_in_room(_text(value)))
        return True
    for fld, match in sheet.mapping.items():
        if match.index is None or fld not in aliases:
            continue
        names = [header_key(n) for n in aliases[fld]] + [header_key(match.header)]
        for col, head in enumerate(header_row):
            if col in taken or is_blank(head):
                continue
            hkey = header_key(head)
            if not hkey or not any(n and (hkey == n or SequenceMatcher(None, hkey, n).ratio() >= 0.88) for n in names):
                continue
            both = [(key(fld, sheet.rows[i][match.index]), key(fld, sheet.rows[i][col])) for i in data
                    if valid(fld, sheet.rows[i][match.index]) and valid(fld, sheet.rows[i][col])]
            if len(both) < MIN_OVERLAP or any(a != b for a, b in both):
                continue
            for i in data:
                if is_blank(sheet.rows[i][match.index]) and valid(fld, sheet.rows[i][col]):
                    plan.set(sheet, i, match.index, _text(sheet.rows[i][col]), "column_merge",
                             f"Taken from the column “{_header(sheet, col)}”, which agrees with “{match.header}” on all "
                             f"{len(both):,} rows where both hold a usable value.")


# ------------------------------------------------------------------------------- 2. values
def _status(sheet: _Sheet, i: int) -> str:
    col = sheet.col("status")
    return (_text(sheet.rows[i][col]).casefold() if col is not None else "")


def _fix_values(sheet: _Sheet, cfg: Config, plan: _Plan) -> None:
    data = [i for i in sheet.data() if _status(sheet, i) != "deleted"]
    rooms = {match_key(r): r for r in cfg.known_rooms()}
    rules = cfg.rules
    families = {c.upper() for c in rules.a_codes + rules.b_codes + rules.neutral_codes}
    used = {f: sheet.col(f) for f in sheet.mapping}

    # spaces at the ends of text cells of the fields the solver reads
    for fld, col in used.items():
        if col is None:
            continue
        for i in sheet.data():
            v = sheet.rows[i][col]
            if isinstance(v, str) and v.strip() != v and v.strip():
                plan.set(sheet, i, col, v.strip(), "spaces", "Spaces at the ends removed.")
    # spellings the solver already understands
    for fld in ("io_type", "io_type2"):
        col = used.get(fld)
        for i in data if col is not None else []:
            v = sheet.rows[i][col]
            n, text = normalise_io_type(v, rules.io_aliases), _text(v)
            if n not in IO_TYPES or text in BUILTIN_IO_ALIASES:       # AI and AIR are both standard: kept as written
                continue
            target = text.upper() if text.upper() in BUILTIN_IO_ALIASES else n
            plan.set(sheet, i, col, target, "io_spelling", f"“{text}” is read as {n}.")
    col = used.get("tech_room")
    for i in data if col is not None else []:
        v = sheet.rows[i][col]
        room = rooms.get(match_key(v))
        if room and _text(v) != room:
            plan.set(sheet, i, col, room, "room_spelling", f"“{_text(v)}” is the configured room {room}.")
    col = used.get("segregation")
    for i in data if col is not None else []:
        v = _text(sheet.rows[i][col])
        if v and v.upper() in families and v != v.upper():
            plan.set(sheet, i, col, v.upper(), "seg_case", f"“{v}” is the segregation code {v.upper()}.")

    _duplicate_rows(sheet, plan)
    _rooms_from_cable(sheet, data, cfg, plan)
    _sizes(sheet, data, plan)
    _io_from_peers(sheet, data, rules, plan)


def _duplicate_rows(sheet: _Sheet, plan: _Plan) -> None:
    tag = sheet.col("tag")
    if tag is None:
        return
    seen: dict[tuple, int] = {}
    for i in sheet.data():
        if is_blank(sheet.rows[i][tag]):
            continue
        key = tuple(_text(v) for v in sheet.rows[i])
        if key in seen:
            plan.remove(sheet, i, f"Row {i + 1} is an exact copy of row {seen[key] + 1} (tag {_text(sheet.rows[i][tag])}).")
        else:
            seen[key] = i


def _by_cable(sheet: _Sheet, data: list[int]) -> dict[str, list[int]]:
    col = sheet.col("cable_no")
    out: dict[str, list[int]] = defaultdict(list)
    for i in data if col is not None else []:
        key = match_key(sheet.rows[i][col])
        if key:
            out[key].append(i)
    return out


def _rooms_from_cable(sheet: _Sheet, data: list[int], cfg: Config, plan: _Plan) -> None:
    col, cable = sheet.col("tech_room"), sheet.col("cable_no")
    if col is None or cable is None:
        return
    for key, members in _by_cable(sheet, data).items():
        for i in members:
            own = _text(sheet.rows[i][col])
            if own and cfg.cabinets_in_room(own):
                continue
            peers = [j for j in members if j != i and _text(sheet.rows[j][col])]
            others = {_text(sheet.rows[j][col]) for j in peers}
            if len(others) == 1:
                room = next(iter(others))
                if cfg.cabinets_in_room(room):
                    plan.set(sheet, i, col, room, "room_from_cable",
                             f"The other {len(peers):,} row(s) of cable {_text(sheet.rows[i][cable])} are all in {room}"
                             + (f"; “{own}” is not a configured room." if own else "."))


def _sizes(sheet: _Sheet, data: list[int], plan: _Plan) -> None:
    col, cable, pair = sheet.col("cable_size"), sheet.col("cable_no"), sheet.col("pair_no")
    if col is None or cable is None:
        return
    for key, members in _by_cable(sheet, data).items():
        name = _text(sheet.rows[members[0]][cable])
        sizes = {i: parse_cable_size(_text(sheet.rows[i][col])) for i in members}
        found = {s for s in sizes.values() if s is not None}
        if len(found) == 1:
            texts = {match_key(sheet.rows[i][col]) for i in members if sizes[i] is not None}
            if len(texts) == 1:
                text = next(_text(sheet.rows[i][col]) for i in members if sizes[i] is not None)
                for i in members:
                    if sizes[i] is None:
                        plan.set(sheet, i, col, text, "size_from_cable",
                                 f"The other rows of cable {name} all give the size {text}.")
        elif len(found) > 1 and pair is not None:
            pairs = [to_int(sheet.rows[i][pair]) for i in members]
            highest = max((p for p in pairs if p is not None and p >= 1), default=0)
            fits = sorted(s for s in found if s >= highest and s <= MAX_CABLE_PAIRS)
            if len(fits) != 1 or highest == 0:
                continue
            good = fits[0]
            texts = Counter(_text(sheet.rows[i][col]) for i in members if sizes[i] == good)
            text = sorted(texts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            wrong = sorted(s for s in found if s != good)
            for i in members:
                if sizes[i] != good:
                    plan.set(sheet, i, col, text, "size_conflict",
                             f"Cable {name} uses pair {highest}, so it cannot have "
                             + " or ".join(f"{w} pairs" for w in wrong) + f"; its other rows give {text} ({good} pairs).")


def _io_from_peers(sheet: _Sheet, data: list[int], rules: Any, plan: _Plan) -> None:
    col, inst, sig = sheet.col("io_type"), sheet.col("instrument_type"), sheet.col("signal_type")
    if col is None or inst is None:
        return

    def kind(i: int) -> tuple[str, str]:
        return (match_key(sheet.rows[i][inst]) or "", match_key(sheet.rows[i][sig]) if sig is not None else "")
    known: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for i in data:
        io_type = normalise_io_type(sheet.rows[i][col], rules.io_aliases)
        if io_type in IO_TYPES and kind(i)[0]:
            known[kind(i)][io_type] += 1
    for i in data:
        own = sheet.rows[i][col]
        if normalise_io_type(own, rules.io_aliases) in IO_TYPES or not kind(i)[0]:
            continue
        peers = known.get(kind(i)) or Counter()
        if len(peers) == 1 and sum(peers.values()) >= MIN_PEERS:
            io_type, n = next(iter(peers.items()))
            what = _text(sheet.rows[i][inst]) + (f" / {_text(sheet.rows[i][sig])}" if sig is not None and
                                                 _text(sheet.rows[i][sig]) else "")
            plan.set(sheet, i, col, io_type, "io_from_peers",
                     f"All {n:,} other signals of the kind “{what}” are {io_type}"
                     + (f"; “{_text(own)}” is not an IO type." if _text(own) else "."))


# ------------------------------------------------------------------------------- 3. unused columns
def _unused(sheets: list[_Sheet]) -> list[tuple[str, int, dict[str, str]]]:
    """Columns the solver does not read, with their values by tag (they can become project columns)."""
    out: dict[str, dict[str, str]] = {}
    for sheet in sheets:
        tag = sheet.col("tag")
        if not sheet.usable or tag is None:
            continue
        taken = {m.index for m in sheet.mapping.values() if m.index is not None}
        for col, head in enumerate(sheet.rows[sheet.header]):
            if col in taken or is_blank(head):
                continue
            values = out.setdefault(str(head).strip(), {})
            for i in sheet.data():
                key, value = match_key(sheet.rows[i][tag]), _text(sheet.rows[i][col])
                if key and value and key not in values:
                    values[key] = value
    return [(h, len(v), v) for h, v in out.items() if v]


# ------------------------------------------------------------------------------- writing
def _write(data: bytes, file_name: str, plan: _Plan, sheets: list[_Sheet]) -> bytes:
    """The original file with the planned cells changed and the duplicate rows removed (formatting kept)."""
    names = {s.name for s in sheets}
    if data[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), keep_vba=str(file_name).lower().endswith(".xlsm"))
        for (sheet, i, col), change in plan.cells.items():
            if sheet in wb.sheetnames:
                wb[sheet].cell(row=i + 1, column=col + 1).value = change.new
        for sheet, i in sorted(plan.removed, key=lambda k: (k[0], -k[1])):
            if sheet in wb.sheetnames:
                wb[sheet].delete_rows(i + 1)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text, encoding = data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = data.decode("latin-1"), "latin-1"
    first = text.splitlines()[0] if text.strip() else ""
    delimiter = max(",;\t|", key=first.count)
    grid = [list(r) for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    for (sheet, i, col), change in plan.cells.items():
        if sheet in names and i < len(grid):
            grid[i].extend([""] * (col + 1 - len(grid[i])))
            grid[i][col] = "" if change.new is None else str(change.new)
    gone = {i for sheet, i in plan.removed}
    grid = [r for i, r in enumerate(grid) if i not in gone]
    out = io.StringIO()
    csv.writer(out, delimiter=delimiter, lineterminator="\r\n").writerows(grid)
    body = out.getvalue().encode(encoding)
    return (b"\xef\xbb\xbf" + body) if bom and encoding == "utf-8" else body


# ------------------------------------------------------------------------------- measuring
def measure(data: bytes, cfg: Config, column_overrides: dict[str, str] | None = None) -> Measures:
    """How the real solver does on a file (no sign-offs): readiness, errors, warnings, held back, placed."""
    from io_sudoku.core.pipeline import solve
    result = solve(data, copy_config(cfg), "00", column_overrides=column_overrides)
    placed = frozenset(match_key(r.get("Tag Name")) or "" for r in result.rows if r.get("Tag Status") in ("Field", "Cabinet Alarm"))
    return Measures(result.readiness.status if result.readiness else "?",
                    sum(1 for t in result.tqs if t.severity == "error") + len(result.violations),
                    sum(1 for t in result.tqs if t.severity == "warning"), len(result.quarantined),
                    sum(1 for r in result.rows if r.get("Tag Status") == "Field"), placed - {""})


def _leftovers(data: bytes, cfg: Config, column_overrides: dict[str, str] | None) -> list[tuple[str, str, str, str]]:
    from io_sudoku.core.pipeline import solve
    result = solve(data, copy_config(cfg), "00", column_overrides=column_overrides)
    order = {"error": 0, "warning": 1}
    tqs = sorted((t for t in result.tqs if t.severity in order), key=lambda t: (order[t.severity], t.tq_id, t.ref))
    return [(t.tq_id, t.severity, t.ref, LEFT_WHY.get(t.tq_id, DEFAULT_WHY)) for t in tqs]


def _worse(before: Measures, after: Measures) -> bool:
    """Worse = a signal placed before is no longer placed, fewer signals are placed, or as many are placed with more
    errors.  (A file the solver could not read at all places nothing: placing its signals is better even when they
    raise new questions.)"""
    if before.placed_tags - after.placed_tags or after.placed < before.placed:
        return True
    return after.placed == before.placed and (after.errors > before.errors or after.held_back > before.held_back)


# ------------------------------------------------------------------------------- public API
def _build(data: bytes, file_name: str, cfg: Config, overrides: dict[str, str], skip: set[str]
           ) -> tuple[bytes | None, list[Change], list[_Sheet], list[str]]:
    aliases = load_aliases()
    sheets = _sheets(data, aliases, overrides)
    plan, notes = _Plan(skip), []
    with_data = [s for s in sheets if s.data()]
    if not any(s.usable for s in sheets) and with_data:
        candidates = [max(with_data, key=lambda s: len(s.data()))]
    else:
        candidates = [s for s in with_data if s.usable or any(s.col(f) is not None for f in MANDATORY_FIELDS)]
    for sheet in candidates:
        _fix_columns(sheet, aliases, overrides, cfg, plan, notes)
    for sheet in sheets:
        if sheet.usable:
            _merge_columns(sheet, aliases, cfg, plan)
            _fix_values(sheet, cfg, plan)
    if not plan.cells and not plan.removed:
        return None, [], sheets, notes
    return _write(data, file_name, plan, sheets), plan.changes(), sheets, notes


def suggest(data: bytes, file_name: str = "MDB.xlsx", cfg: Config | None = None,
            column_overrides: dict[str, str] | None = None, skip: tuple[str, ...] | list[str] = ()) -> Suggestion:
    """The Suggested Fixed File for an MDB, with every change explained.  `skip` = groups switched off.
    Never raises: an unreadable file gives a Suggestion with no data and a note."""
    cfg = copy_config(cfg) if cfg is not None else load_config()
    overrides = dict(column_overrides or {})
    out = Suggestion(None, _suggested_name(file_name))
    try:
        before = measure(data, cfg, overrides)
        out.before = before
        fixed, changes, sheets, notes = _build(data, file_name, cfg, overrides, set(skip))
        out.notes = notes
        out.unused = _unused(sheets)
        if fixed is not None:
            after = measure(fixed, cfg, overrides)
            dropped: list[str] = []
            unsure = [g for g, x in reversed(GROUPS.items()) if not x.sure and g not in skip]
            while _worse(before, after) and fixed is not None:            # the safety net
                if not unsure:
                    fixed, changes, after = None, [], None
                    out.notes.append("No safe suggestion: every set of fixes made the result worse, so none is offered.")
                    break
                dropped.append(unsure.pop(0))
                fixed, changes, _, _ = _build(data, file_name, cfg, overrides, set(skip) | set(dropped))
                after = measure(fixed, cfg, overrides) if fixed is not None else None
                if after is None:
                    break
            if dropped and fixed is not None:
                out.dropped = tuple(dropped)
                out.notes.append("Left out because the result was not better with them: "
                                 + ", ".join(GROUPS[g].title.lower() for g in dropped) + ".")
            out.data, out.changes, out.after = fixed, changes[:MAX_LISTED], after
        out.left = _leftovers(fixed if fixed is not None else data, cfg, overrides)
    except Exception:  # noqa: BLE001 - a file the reader cannot open has nothing to suggest
        out.data, out.changes = None, []
        out.notes.append("The file could not be read as a table, so no fixed file can be suggested. Open it in Excel, "
                         "save it as .xlsx, and upload it again.")
    return out


def _suggested_name(file_name: str) -> str:
    stem, dot, ext = (file_name or "MDB.xlsx").rpartition(".")
    return f"{stem}_suggested_fix.{ext}" if dot else f"{file_name}_suggested_fix"
