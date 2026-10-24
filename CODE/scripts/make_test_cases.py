"""Build the MDB test cases in test_cases/: clean files, messy-but-fixable files and files with planted errors.

Every case starts from the real sample MDB (190 rows, 143 columns) so the format is exactly the customer's,
then changes a few cells on purpose.  After writing the files the script solves each one and writes
test_cases/README.md with what the tool really reported, so the table can never drift from the code.

    python scripts/make_test_cases.py
"""
from __future__ import annotations

import csv
import io
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openpyxl  # noqa: E402

from io_sudoku.core.pipeline import solve      # noqa: E402
from io_sudoku.samples import sample_mdb_bytes  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "test_cases"

Table = tuple[list[Any], list[list[Any]]]


# ------------------------------------------------------------------ reading and writing tables
def sample_table() -> Table:
    wb = openpyxl.load_workbook(io.BytesIO(sample_mdb_bytes()), data_only=True)
    ws = wb.worksheets[0]
    rows = [[ws.cell(r, c).value for c in range(1, ws.max_column + 1)] for r in range(1, ws.max_row + 1)]
    wb.close()
    return list(rows[0]), [list(r) for r in rows[1:] if any(v is not None for v in r)]


def xlsx_bytes(headers: list[Any], rows: list[list[Any]], title_rows: list[list[Any]] | None = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MDB-1"
    for row in title_rows or []:
        ws.append(row)
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_bytes(headers: list[Any], rows: list[list[Any]], delimiter: str = ",") -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return buf.getvalue().encode("utf-8-sig")


class Sheet:
    """The sample table plus small helpers to change it by tag and header name."""

    def __init__(self) -> None:
        self.headers, self.rows = sample_table()

    def col(self, name: str) -> int:
        return self.headers.index(name)

    def row(self, tag: str) -> list[Any]:
        t = self.col("Tag Number")
        for r in self.rows:
            if r[t] == tag:
                return r
        raise KeyError(tag)

    def set(self, tag: str, **values: Any) -> None:
        """set('320-FT   -80002', **{'Pair Number': 'Pair 3'}) - keys are header names."""
        r = self.row(tag)
        for name, value in values.items():
            r[self.col(name)] = value

    def where(self, name: str, value: Any) -> list[list[Any]]:
        c = self.col(name)
        return [r for r in self.rows if r[c] == value]

    def cable(self, cable_no: str) -> list[list[Any]]:
        return self.where("Multipair Cable No.", cable_no)

    def tag_of(self, r: list[Any]) -> str:
        return r[self.col("Tag Number")]


# ------------------------------------------------------------------ the cases
@dataclass(frozen=True)
class Case:
    file: str
    group: str
    what: str            # what was changed, in plain words
    expect: str          # ISSUE-READY / DRAFT / BLOCKED
    build: Callable[[], bytes]


def clean_full() -> bytes:
    s = Sheet()
    return xlsx_bytes(s.headers, s.rows)


def clean_one_room() -> bytes:
    s = Sheet()
    return xlsx_bytes(s.headers, s.where("Technical Room (Signal Location 2)", "PIB-24"))


def messy_formatting() -> bytes:
    s = Sheet()
    headers = list(s.headers)
    headers[s.col("Tag Number")] = "  TAG NUMBER "
    headers[s.col("I/O Type Name")] = "i/o type name"
    headers[s.col("Pair Number")] = "Pair  Number"
    tag, io_c, room = s.col("Tag Number"), s.col("I/O Type Name"), s.col("Technical Room (Signal Location 2)")
    for i, r in enumerate(s.rows):
        if i % 3 == 0 and isinstance(r[tag], str):
            r[tag] = f"  {r[tag]}  "
        if i % 4 == 0 and isinstance(r[io_c], str):
            r[io_c] = f" {r[io_c].lower()} "
        if i % 5 == 0 and isinstance(r[room], str):
            r[room] = r[room].lower()
    title = [["VIT Demo Plant - Customer IO MDB"], ["Issued for allocation, revision 00"], []]
    return xlsx_bytes(headers, s.rows, title_rows=title)


def clean_csv() -> bytes:
    s = Sheet()
    return csv_bytes(s.headers, s.rows)


def clean_semicolon_csv() -> bytes:
    s = Sheet()
    return csv_bytes(s.headers, s.where("Technical Room (Signal Location 2)", "PIB-24"), delimiter=";")


def tag_errors() -> bytes:
    s = Sheet()
    s.set("320-FT   -80004", **{"Tag Number": None})
    s.set("320-LT   -80002", **{"Tag Number": "   "})
    s.set("320-LT   -80001", **{"Tag Number": "320-FV   -20645"})          # same tag as another row
    s.set("320-LT   -81209", **{"Status": "DELETED"})                       # the sample already deletes 320-FT -80002
    return xlsx_bytes(s.headers, s.rows)


def io_type_errors() -> bytes:
    s = Sheet()
    tags = [s.tag_of(r) for r in s.cable("320-CE-0004")]
    s.set(tags[0], **{"I/O Type Name": None})
    s.set(tags[1], **{"I/O Type Name": "4-20mA"})
    s.set(tags[2], **{"I/O Type Name": "PULSE"})
    s.set(tags[3], **{"I/O Type Name": "AIR", "I/O Type Name 2": "DIR"})     # not a normal pair
    return xlsx_bytes(s.headers, s.rows)


def cable_pair_errors() -> bytes:
    s = Sheet()
    a = [s.tag_of(r) for r in s.cable("320-CE-0040")]
    s.set(a[0], **{"Multipair Cable No.": None})
    s.set(a[1], **{"Pair Number": "-"})
    s.set(a[3], **{"Pair Number": s.row(a[2])[s.col("Pair Number")]})       # two signals on one pair
    s.set(a[4], **{"Pair Number": "Pair 30"})                                # a 24-pair cable has no pair 30
    for r in s.cable("320-CE-0083")[:2]:
        r[s.col("Multi-cable / Cable")] = "12PX1MM2/FR/IND&OS/ARM/NIS"     # the other rows say 24 pairs
    for r in s.cable("320-CS-0005"):
        r[s.col("Multi-cable / Cable")] = "-"                                 # no size at all: inferred
    return xlsx_bytes(s.headers, s.rows)


def segregation_errors() -> bytes:
    s = Sheet()
    seg = s.col("IO Grouping")
    a_cable = next(r[s.col("Multipair Cable No.")] for r in s.rows if r[seg] == "A")
    first = s.cable(a_cable)
    first[-1][seg] = "B"                                                     # A and B on the same cable
    plain = s.cable("320-CE-0087")
    plain[0][seg] = "Z"                                                      # a code nobody defined
    plain[1][seg] = "SIL3"
    return xlsx_bytes(s.headers, s.rows)


def out_of_scope() -> bytes:
    s = Sheet()
    tags = [s.tag_of(r) for r in s.cable("320-CE-0001")]
    s.set(tags[2], Execution="IS")
    s.set(tags[3], Execution="Ex i")
    s.set(tags[4], **{"Tag Service 1 and 2": "Pump P-101 run status from MCC"})
    s.set(tags[5], **{"Equipment Name": "IRC-320-01"})
    return xlsx_bytes(s.headers, s.rows)


def new_room() -> bytes:
    s = Sheet()
    room = s.col("Technical Room (Signal Location 2)")
    for r in s.cable("320-CE-0040") + s.cable("320-CS-0008"):           # cables that share no logic with others
        r[room] = "PIB-40"                                                   # a room with no cabinet yet
    return xlsx_bytes(s.headers, s.rows)


def alarm_errors() -> bytes:
    s = Sheet()
    s.set("320-EJA  -01004-T", **{"Tag Number": "320-EJA  -01004-X"})       # unknown alarm kind
    s.set("320-EJA  -01004-AC", **{"Equipment Name": "P99-DCM-99999-01"})  # cabinet that does not exist
    return xlsx_bytes(s.headers, s.rows)


def big_project() -> bytes:
    """About 1,600 field signals in one room: far more than one cabinet holds, so cabinets are added."""
    s = Sheet()
    template = s.cable("320-CE-0001")[0]
    c = {name: s.col(name) for name in ("Tag Number", "TagNumber", "I/O Type Name", "Multi-cable / Cable",
                                         "Multipair Cable No.", "Pair Number", "IO Grouping", "Logic Number",
                                         "Instrument Type Description", "Signal Level", "Signal Type",
                                         "I/O Type Name 2", "Status", "Old Tag Number")}
    kinds = [("AIR", "Pressure Transmitter", "2-Wire", "4-20 ma HART"),
             ("DIR", "Position Limit Switch", "Voltfree-contact", "-"),
             ("AOR", "Control Valve", "2-Wire", "4-20 ma HART"),
             ("DOR", "Solenoid Valve", "Volt-contact", "-")]
    rows = [r for r in s.rows if "Cabinet Diagnostic Alarm" in str(r[c["Instrument Type Description"]])]
    n = 0
    for cable in range(1, 81):
        io_type, desc, level, sig = kinds[cable % 4]
        family = {0: "A", 1: "B"}.get(cable % 10, "-")
        for pair in range(1, 21):                                            # 20 of 24 pairs used
            n += 1
            r = list(template)
            r[c["Tag Number"]] = f"330-XT   -{n:05d}"
            r[c["TagNumber"]] = f"330XT{n:05d}"
            r[c["Old Tag Number"]] = "-"
            r[c["I/O Type Name"]], r[c["Instrument Type Description"]] = io_type, desc
            r[c["Signal Level"]], r[c["Signal Type"]], r[c["I/O Type Name 2"]] = level, sig, "-"
            r[c["Multi-cable / Cable"]] = "24PX1MM2/FR/IND&OS/ARM/NIS"
            r[c["Multipair Cable No."]] = f"330-CE-{cable:04d}"
            r[c["Pair Number"]] = f"Pair {pair}"
            r[c["IO Grouping"]] = family
            r[c["Logic Number"]] = f"330-UC-{(cable + 1) // 2:05d}"
            r[c["Status"]] = "New"
            rows.append(r)
    return xlsx_bytes(s.headers, rows)


def cable_too_large() -> bytes:
    s = Sheet()
    for r in s.cable("320-CE-0083"):
        r[s.col("Multi-cable / Cable")] = "120PX1MM2/FR/IND&OS/ARM/NIS"
    return xlsx_bytes(s.headers, s.rows)


def missing_column() -> bytes:
    s = Sheet()
    gone = s.col("I/O Type Name")
    headers = [h for i, h in enumerate(s.headers) if i != gone]
    rows = [[v for i, v in enumerate(r) if i != gone] for r in s.rows]
    return xlsx_bytes(headers, rows)


def header_only() -> bytes:
    return xlsx_bytes(Sheet().headers, [])


def corrupt_xlsx() -> bytes:
    return b"PK\x03\x04" + bytes((i * 37) % 256 for i in range(4000))


def old_xls_renamed() -> bytes:
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 4000


def not_a_table() -> bytes:
    return ("Hi team,\r\nPlease find the IO list attached in the next email.\r\nThanks\r\n").encode()


def formula_text() -> bytes:
    s = Sheet()
    tags = [s.tag_of(r) for r in s.cable("320-CE-0004")]
    s.set(tags[0], **{"Tag Service 1 and 2": '=HYPERLINK("http://example.com","click me")'})
    s.set(tags[1], **{"Tag Service 1 and 2": "+SUM(1,2)"})
    s.set(tags[2], **{"Tag Service 1 and 2": "@cmd /c calc"})
    s.set(tags[3], **{"Tag Service 1 and 2": "-2+3 <b>bold</b> & 'quotes'"})
    return csv_bytes(s.headers, s.rows)


def everything_wrong() -> bytes:
    s = Sheet()
    s.set("320-FT   -80004", **{"Tag Number": None})
    s.set("320-LT   -80001", **{"Tag Number": "320-FV   -20645"})
    a = [s.tag_of(r) for r in s.cable("320-CE-0040")]
    s.set(a[0], **{"I/O Type Name": "PULSE"})
    s.set(a[1], **{"Pair Number": "Pair 30"})
    s.set(a[2], **{"Multipair Cable No.": None})
    s.set(a[3], Execution="IS")
    seg = s.col("IO Grouping")
    a_cable = next(r[s.col("Multipair Cable No.")] for r in s.rows if r[seg] == "A")
    s.cable(a_cable)[-1][seg] = "B"
    s.set("320-EJA  -01004-T", **{"Tag Number": "320-EJA  -01004-X"})
    return xlsx_bytes(s.headers, s.rows)


CASES = [
    Case("01_clean_full_sample.xlsx", "Clean", "The official sample MDB, unchanged (190 rows, 2 rooms).",
         "ISSUE-READY", clean_full),
    Case("02_clean_one_room_PIB-24.xlsx", "Clean", "Only the 46 rows of room PIB-24.", "ISSUE-READY", clean_one_room),
    Case("03_messy_but_fixable.xlsx", "Clean", "Title rows above the header, odd header case and spaces, extra spaces "
         "around tags, lower-case IO types and room names. The tool cleans all of it.", "ISSUE-READY", messy_formatting),
    Case("04_clean_sample.csv", "Clean", "The full sample saved as a comma CSV.", "ISSUE-READY", clean_csv),
    Case("05_clean_semicolon_PIB-24.csv", "Clean", "Room PIB-24 as a semicolon CSV (European Excel).",
         "ISSUE-READY", clean_semicolon_csv),
    Case("06_formula_text_safety.csv", "Clean", "Service texts that look like Excel formulas or HTML "
         "(=HYPERLINK, +SUM, @cmd, <b>). They must show as plain text, never run.", "ISSUE-READY", formula_text),
    Case("07_tag_errors.xlsx", "Data errors", "Two rows with no tag, one tag used twice, one more row marked "
         "DELETED.", "DRAFT", tag_errors),
    Case("08_io_type_errors.xlsx", "Data errors", "Cable 320-CE-0004: one IO type blank, '4-20mA', 'PULSE', and an "
         "AIR signal whose second IO type is DIR.", "DRAFT", io_type_errors),
    Case("09_cable_and_pair_errors.xlsx", "Data errors", "Cable 320-CE-0040: no cable number, pair '-', two signals "
         "on one pair, pair 30 on a 24-pair cable. 320-CE-0083 has two sizes. 320-CS-0005 has no size.",
         "DRAFT", cable_pair_errors),
    Case("10_segregation_errors.xlsx", "Data errors", "A B signal on an A cable, and the unknown codes 'Z' and "
         "'SIL3' on cable 320-CE-0087.", "DRAFT", segregation_errors),
    Case("11_out_of_scope_signals.xlsx", "Data errors", "Two intrinsically safe signals (IS, Ex i), one MCC signal "
         "and one IRC signal. The tool does not allocate these.", "DRAFT", out_of_scope),
    Case("12_alarm_errors.xlsx", "Data errors", "A cabinet alarm tag ending in -X, and an alarm naming a cabinet "
         "that does not exist.", "DRAFT", alarm_errors),
    Case("13_everything_wrong.xlsx", "Data errors", "Many of the errors above in one file.", "DRAFT", everything_wrong),
    Case("14_cable_too_large.xlsx", "Capacity", "Cable 320-CE-0083 says 120 pairs; one CIOC holds 96.",
         "DRAFT", cable_too_large),
    Case("15_new_room_PIB-40.xlsx", "Capacity", "Cables 320-CE-0040 and 320-CS-0008 moved to room PIB-40, which has "
         "no cabinet yet. The tool names one and asks you to confirm.", "ISSUE-READY", new_room),
    Case("16_big_project_1600_signals.xlsx", "Capacity", "1,600 signals on 80 cables in one room: more than one "
         "cabinet holds, so cabinets are added and listed as TQs.", "ISSUE-READY", big_project),
    Case("17_missing_io_type_column.xlsx", "Blocked", "The I/O Type Name column was deleted.", "BLOCKED",
         missing_column),
    Case("18_header_only.xlsx", "Blocked", "Only the header row, no signals.", "BLOCKED", header_only),
    Case("19_corrupt_file.xlsx", "Blocked", "Random bytes saved with an .xlsx name.", "BLOCKED", corrupt_xlsx),
    Case("20_old_excel_renamed.xlsx", "Blocked", "An old .xls (Excel 97) file renamed to .xlsx.", "BLOCKED",
         old_xls_renamed),
    Case("21_not_a_table.csv", "Blocked", "An e-mail text saved as .csv.", "BLOCKED", not_a_table),
]


# ------------------------------------------------------------------ solve and document
def summarise(data: bytes) -> dict[str, Any]:
    result = solve(data)
    status = result.readiness.status if result.readiness else "?"
    kinds = Counter((t.severity, t.tq_id) for t in result.tqs)
    order = {"error": 0, "warning": 1, "info": 2}
    tqs = sorted(kinds.items(), key=lambda kv: (order.get(kv[0][0], 3), kv[0][1]))
    field_rows = sum(1 for r in result.rows if r.get("Tag Status") == "Field")
    return {"status": status, "placed": field_rows, "quarantined": len(result.quarantined),
            "tqs": [f"{tq_id} ×{n}" if n > 1 else tq_id for (sev, tq_id), n in tqs if sev != "info"],
            "info": [tq_id for (sev, tq_id), _ in tqs if sev == "info"],
            "cabinets": len({r.get("Electronic/ Marshalling Cabinet") for r in result.rows}),
            "violations": len(result.violations)}


README_HEAD = """# Test Cases For The Website

Upload any of these files on the **Upload** view, press **Run Allocation**, then look at the
readiness badge, the **Questions** (TQs) and the **Files** view.

All files use the customer MDB format. Each one is the real sample MDB with a few cells changed on purpose.
The table below was written by `scripts/make_test_cases.py` after solving every file,
so it shows what the tool really does.

- **ISSUE-READY**: clean enough to issue. Warnings may still be listed for you to confirm.
- **DRAFT**: allocated, but some signals were held back or need an answer first.
- **BLOCKED**: nothing could be allocated (the file itself is the problem).

Rebuild the files with `python scripts/make_test_cases.py`.

"""


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    lines = [README_HEAD]
    wrong = []
    group = None
    for case in CASES:
        data = case.build()
        (OUT_DIR / case.file).write_bytes(data)
        got = summarise(data)
        if got["status"] != case.expect or got["violations"]:
            wrong.append(f"{case.file}: expected {case.expect}, got {got['status']} ({got['violations']} violations)")
        if case.group != group:
            group = case.group
            lines.append(f"\n## {group}\n\n| File | What was changed | Result | Signals placed | Held back | "
                         f"Cabinets | Main questions raised |\n|---|---|---|---|---|---|---|")
        tqs = ", ".join(f"`{t}`" for t in got["tqs"]) or "none"
        if got["info"]:
            tqs += " (info: " + ", ".join(got["info"]) + ")"
        lines.append(f"| `{case.file}` | {case.what} | **{got['status']}** | {got['placed']} | {got['quarantined']} "
                     f"| {got['cabinets']} | {tqs} |")
        print(f"{got['status']:<12} {case.file}")
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if wrong:
        print("\nNot as expected:\n  " + "\n  ".join(wrong))
        return 1
    print(f"\n{len(CASES)} files written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
