"""Accept a finished IO Allocation workbook as the input file, safely.

People often have only an allocation (an older revision, or one made by hand) instead of the MDB.
The 76-column allocation carries every MDB field the solver needs (tag, IO type, room, segregation,
cable, pair ...), so ingest can read it - with three rules:

  1. Only rows whose Tag Status is 'Field' or 'Cabinet Alarm' are read.  Wired spares and spare
     slots are NOT copied: the solver creates them itself from the rules, as for any MDB.
     The old positions are ignored (to keep them, use the Revision view with this file as Rev A).
  2. Rows whose values slipped one or two columns away from their headers are put back ONLY when
     the shift is unambiguous: the Tag Status must land on a valid status, only blank cells may be
     dropped, and for Field rows the cable, size and pair columns must then look right.
  3. Every repair, and every row that could not be repaired, becomes a TQ.  Nothing is silent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from io_sudoku.core.allocio import _to_canonical
from io_sudoku.core.constants import IO_TYPES
from io_sudoku.core.textnorm import is_blank, match_key, normalise_io_type

MIN_TEMPLATE_HEADERS = 60            # of 76: below this the sheet is treated as a normal MDB
REQUIRED = ("Tag Name", "Tag Status", "Field Cable No", "Electronic/ Marshalling Cabinet", "Baseplate")
STATUSES = {"field": "Field", "cabinet alarm": "Cabinet Alarm", "wired spare": "Wired Spare", "spare slot": "Spare Slot"}
SHIFTS = (1, -1, 2, -2)              # tried in this order; +k = values sit k columns to the right
_PAIR = re.compile(r"^(pair\s*)?\d+$", re.I)
_SIZE = re.compile(r"\d+\s*P", re.I)


def _blank(value: Any) -> bool:
    return is_blank(value) or str(value).strip() in ("-", "_")


@dataclass(frozen=True)
class AllocationLayout:
    """Column positions of an allocation header row (only built when the header really is one)."""
    headers: tuple[str, ...]
    index: dict[str, int]

    def _at(self, row: list[Any], name: str) -> Any:
        i = self.index.get(name)
        return row[i] if i is not None and i < len(row) else None

    def status(self, row: list[Any] | tuple[Any, ...]) -> str | None:
        """'Field' / 'Cabinet Alarm' / 'Wired Spare' / 'Spare Slot', or None."""
        return STATUSES.get(match_key(self._at(list(row), "Tag Status")) or "")

    def _score(self, row: list[Any]) -> int:
        """How well a row fits its headers (higher is better).  -1 = Tag Status not valid."""
        status = self.status(row)
        if status is None:
            return -1
        score = 1
        io = normalise_io_type(self._at(row, "IO Type"))
        score += io in IO_TYPES
        score += "cbp" in str(self._at(row, "Baseplate") or "").lower()
        if status == "Field":
            score += not _blank(self._at(row, "Field Cable No"))
            score += bool(_SIZE.search(str(self._at(row, "Field Cable Size") or "")))
            score += bool(_PAIR.match(str(self._at(row, "Field Cable Pair") or "").strip()))
        return score

    def _field_ok(self, row: list[Any]) -> bool:
        return self.status(row) != "Field" or (
            not _blank(self._at(row, "Field Cable No"))
            and bool(_PAIR.match(str(self._at(row, "Field Cable Pair") or "").strip())))

    def realign(self, row: tuple[Any, ...] | list[Any]) -> tuple[list[Any] | None, int, str]:
        """(row in header positions, shift that was undone, first header that moved).

        Shift 0 = the row was already aligned.  None = it is misaligned and cannot be repaired safely."""
        cells = list(row)
        if self.status(cells) is not None:
            return cells, 0, ""
        status_i = self.index["Tag Status"]
        found = [k for k in SHIFTS if 0 <= status_i + k < len(cells)
                 and STATUSES.get(match_key(cells[status_i + k]) or "")]
        if not found:
            return None, 0, ""
        k = found[0]
        if -k in found:
            return None, k, ""                          # both directions look valid: ambiguous
        best: tuple[int, int, list[Any]] | None = None
        for s in range(1, status_i + 1):
            if k > 0:
                if not all(_blank(c) for c in cells[s:s + k]):
                    continue
                candidate = cells[:s] + cells[s + k:]
            else:
                if s > status_i + k:
                    break
                candidate = cells[:s] + [None] * (-k) + cells[s:]
            score = self._score(candidate)
            if score >= 0 and (best is None or score >= best[0]):   # ties: the latest start moves fewest values
                best = (score, s, candidate)
        if best is None or not self._field_ok(best[2]):
            return None, k, ""
        return best[2], k, self.headers[best[1]] if best[1] < len(self.headers) else ""


def detect(header_row: tuple[Any, ...] | list[Any]) -> AllocationLayout | None:
    """An AllocationLayout if this header row is the IO Allocation template, else None."""
    try:
        canonical = [_to_canonical(h) for h in header_row]
        index: dict[str, int] = {}
        for i, name in enumerate(canonical):
            if name is not None and name not in index:
                index[name] = i
        if len(index) < MIN_TEMPLATE_HEADERS or any(r not in index for r in REQUIRED):
            return None
        headers = tuple(c if c is not None else str(h or "") for c, h in zip(canonical, header_row))
        return AllocationLayout(headers, index)
    except Exception:  # noqa: BLE001 - detection is optional; a normal MDB read follows
        return None


def rows_text(rows: list[int], limit: int = 10) -> str:
    """'6, 7, 8 and 5 more' for TQ messages."""
    shown = ", ".join(str(r) for r in rows[:limit])
    return shown + (f" and {len(rows) - limit} more" if len(rows) > limit else "")
