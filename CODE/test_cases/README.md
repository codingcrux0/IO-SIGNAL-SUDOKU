# Test Cases For The Website

Upload any of these files on the **Upload** view, press **Run Allocation**, then look at the
readiness badge, the **Questions** (TQs) and the **Files** view.

All files use the customer MDB format. Each one is the real sample MDB with a few cells changed on purpose.
The table below was written by `scripts/make_test_cases.py` after solving every file,
so it shows what the tool really does.

- **ISSUE-READY**: clean enough to issue, and every warning has been approved.
- **DRAFT**: allocated, but some signals were held back, an error needs an answer, or a warning is not approved yet.
  Approve warnings under **Sign Off The Warnings** on the TQ Board.
- **BLOCKED**: nothing could be allocated (the file itself is the problem).

Rebuild the files with `python scripts/make_test_cases.py`.



## Clean

| File | What was changed | Result | Signals placed | Held back | Cabinets | Main questions raised |
|---|---|---|---|---|---|---|
| `01_clean_full_sample.xlsx` | The official sample MDB, unchanged (190 rows, 2 rooms). | **DRAFT** until 2 warnings signed off, then **ISSUE-READY** | 177 | 0 | 3 | `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `02_clean_one_room_PIB-24.xlsx` | Only the 46 rows of room PIB-24. | **DRAFT** until 1 warning signed off, then **ISSUE-READY** | 43 | 0 | 1 | `ALARMS-MISSING-FOR-CABINET` (info: IO-TYPE2-NOTED) |
| `03_messy_but_fixable.xlsx` | Title rows above the header, odd header case and spaces, extra spaces around tags, lower-case IO types and room names. The tool cleans all of it. | **DRAFT** until 2 warnings signed off, then **ISSUE-READY** | 177 | 0 | 3 | `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `04_clean_sample.csv` | The full sample saved as a comma CSV. | **DRAFT** until 2 warnings signed off, then **ISSUE-READY** | 177 | 0 | 3 | `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `05_clean_semicolon_PIB-24.csv` | Room PIB-24 as a semicolon CSV (European Excel). | **DRAFT** until 1 warning signed off, then **ISSUE-READY** | 43 | 0 | 1 | `ALARMS-MISSING-FOR-CABINET` (info: IO-TYPE2-NOTED) |
| `06_formula_text_safety.csv` | Service texts that look like Excel formulas or HTML (=HYPERLINK, +SUM, @cmd, <b>). They must show as plain text, never run. | **DRAFT** until 2 warnings signed off, then **ISSUE-READY** | 177 | 0 | 3 | `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |

## Data errors

| File | What was changed | Result | Signals placed | Held back | Cabinets | Main questions raised |
|---|---|---|---|---|---|---|
| `07_tag_errors.xlsx` | Two rows with no tag, one tag used twice, one more row marked DELETED. | **DRAFT** | 172 | 4 | 3 | `BLANK-TAG ×2`, `DUPLICATE-TAG ×2`, `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `08_io_type_errors.xlsx` | Cable 320-CE-0004: one IO type blank, '4-20mA', 'PULSE', and an AIR signal whose second IO type is DIR. | **DRAFT** | 174 | 3 | 3 | `MISSING-IO-TYPE`, `UNKNOWN-IO-TYPE ×2`, `ALARMS-MISSING-FOR-CABINET ×2`, `IO-TYPE-CONFLICT` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `09_cable_and_pair_errors.xlsx` | Cable 320-CE-0040: no cable number, pair '-', two signals on one pair, pair 30 on a 24-pair cable. 320-CE-0083 has two sizes. 320-CS-0005 has no size. | **DRAFT** | 153 | 24 | 3 | `CABLE-SIZE-CONFLICT`, `DUPLICATE-PAIR ×2`, `MISSING-CABLE`, `MISSING-PAIR`, `PAIR-BEYOND-CABLE`, `ALARMS-MISSING-FOR-CABINET ×2`, `CABLE-SIZE-INFERRED` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `10_segregation_errors.xlsx` | A B signal on an A cable, and the unknown codes 'Z' and 'SIL3' on cable 320-CE-0087. | **DRAFT** | 157 | 20 | 3 | `MIXED-SEGREGATION`, `UNSUPPORTED-SEGREGATION ×2`, `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `11_out_of_scope_signals.xlsx` | Two intrinsically safe signals (IS, Ex i), one MCC signal and one IRC signal. The tool does not allocate these. | **DRAFT** | 174 | 3 | 3 | `IS-SIGNAL-UNSUPPORTED`, `OUT-OF-SCOPE-SIGNAL ×2`, `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `12_alarm_errors.xlsx` | A cabinet alarm tag ending in -X, and an alarm naming a cabinet that does not exist. | **DRAFT** | 177 | 2 | 3 | `ALARM-UNKNOWN-KIND`, `NO-CABINET-FOR-ALARM`, `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `13_everything_wrong.xlsx` | Many of the errors above in one file. | **DRAFT** | 155 | 23 | 3 | `ALARM-UNKNOWN-KIND`, `BLANK-TAG`, `DUPLICATE-TAG ×2`, `IS-SIGNAL-UNSUPPORTED`, `MISSING-CABLE`, `MIXED-SEGREGATION`, `PAIR-BEYOND-CABLE`, `UNKNOWN-IO-TYPE`, `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |

## Capacity

| File | What was changed | Result | Signals placed | Held back | Cabinets | Main questions raised |
|---|---|---|---|---|---|---|
| `14_cable_too_large.xlsx` | Cable 320-CE-0083 says 120 pairs; one CIOC holds 96. | **DRAFT** | 158 | 19 | 3 | `CABLE-TOO-LARGE`, `ALARMS-MISSING-FOR-CABINET ×2` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `15_new_room_PIB-40.xlsx` | Cables 320-CE-0040 and 320-CS-0008 moved to room PIB-40, which has no cabinet yet. The tool names one and asks you to confirm. | **DRAFT** until 3 warnings signed off, then **ISSUE-READY** | 177 | 0 | 4 | `ALARMS-MISSING-FOR-CABINET ×2`, `TOPOLOGY-INFERRED` (info: DELETED-IN-MDB, HIGH-CURRENT-VERIFY, IO-TYPE2-NOTED) |
| `16_big_project_1600_signals.xlsx` | 1,600 signals on 80 cables in one room: more than one cabinet holds, so cabinets are added and listed as TQs. | **DRAFT** until 7 warnings signed off, then **ISSUE-READY** | 1600 | 0 | 8 | `ALARMS-MISSING-FOR-CABINET ×2`, `CABINET-AUTO-ADDED ×5` (info: HIGH-CURRENT-VERIFY) |

## Blocked

| File | What was changed | Result | Signals placed | Held back | Cabinets | Main questions raised |
|---|---|---|---|---|---|---|
| `17_missing_io_type_column.xlsx` | The I/O Type Name column was deleted. | **BLOCKED** | 0 | 0 | 0 | `MISSING-COLUMN` |
| `18_header_only.xlsx` | Only the header row, no signals. | **BLOCKED** | 0 | 0 | 0 | none |
| `19_corrupt_file.xlsx` | Random bytes saved with an .xlsx name. | **BLOCKED** | 0 | 0 | 0 | `UNREADABLE-FILE` |
| `20_old_excel_renamed.xlsx` | An old .xls (Excel 97) file renamed to .xlsx. | **BLOCKED** | 0 | 0 | 0 | `UNSUPPORTED-FORMAT` |
| `21_not_a_table.csv` | An e-mail text saved as .csv. | **BLOCKED** | 0 | 0 | 0 | `MISSING-COLUMN ×3` |
