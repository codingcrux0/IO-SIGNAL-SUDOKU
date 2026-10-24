# IO Signal Sudoku

A deterministic DeltaV IO allocation solver. Give it the customer IO list (MDB, Excel or CSV) and it produces:

- the 76-column **IO Allocation** workbook (every signal placed on a cabinet, CIOC, baseplate and channel),
- a **TQ register** (Technical Queries: every question a human must answer, with a suggested fix),
- a **revision impact report** (Added / Deleted / Moved / Renamed) that keeps unchanged cables where they were,
- a Streamlit dashboard with cabinet grids, drawings, a parts list, a health check and governed rule changes.

**No AI is used to allocate.** The same input always gives byte-identical output (a SHA-256 fingerprint proves it).
The optional AI box only drafts rule proposals; a different person must approve them, and the AI never sees your data.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt        # exact tested versions: requirements.lock.txt
.venv/bin/streamlit run app.py
```

Open the address Streamlit prints, press **Try With Sample Data**, and explore the views in the sidebar.

To see how the tool handles bad input, upload a file from `test_cases/`. The 21 files there are copies of the sample
MDB with problems planted on purpose: messy formatting, tag, IO type, cable, pair, segregation and alarm errors, an
oversized project, and files that cannot be read at all. `test_cases/README.md` lists what each one should show, and
the test suite checks every file still gives that result. Rebuild them with `.venv/bin/python scripts/make_test_cases.py`.

Every output can be opened in the browser before you download it: the **Files** view (and a **View Here** switch on
Parts, Drawings, Revision and Health) shows workbooks as searchable tables, pages as pages, JSON as a tree and ZIP
bundles file by file. The viewer is read-only; **Download This View (.csv)** exports exactly the rows you filtered, and
**Download Everything (.zip)** gets every file at once.

## Command line (no browser)

```bash
.venv/bin/python -m io_sudoku selftest                          # checks the install in about a second
.venv/bin/python -m io_sudoku solve MDB.xlsx --out out/         # allocation, TQ register, parts, drawings, manifest
.venv/bin/python -m io_sudoku revise REV_A.xlsx MDB_B.xlsx --out out/
.venv/bin/python -m io_sudoku audit SOME_ALLOCATION.xlsx --out out/   # health-check any allocation
```

Exit codes: `0` ISSUE-READY, `1` DRAFT (open TQs), `2` BLOCKED. Run `--help` on any command for its options.

## Test it

```bash
.venv/bin/python -m pytest          # about 600 tests: rules, golden output, fuzzing, scale, test cases, UI
```

## Layout

| Path | What it holds |
|---|---|
| `app.py` | Streamlit entry point |
| `io_sudoku/core/` | the solver: ingest, validate, place, spares, rows, verify, revision, reports, rule packs |
| `io_sudoku/ui/` | state, theme, error boundary and one file per view |
| `io_sudoku/data/` | template, topology, column aliases, hardware catalogue, rule pack, sample files |
| `tests/` | unit, golden, robustness (fuzz), scale, UI smoke tests |
| `test_cases/` | 21 MDB files (clean, messy, broken) for trying the website, with a README of expected results |
| `docs/DEMO.md` | the 5-minute demo script |
| `DEPLOY.md` | hosting on Streamlit Community Cloud, Docker or any server |

## How the answer is reached

Cables are the atomic unit (pair N lands on channel N). Logic groups share a cabinet. Cabinets are filled
worst-fit-decreasing, family A and B never share a CIOC, CIOC 1 baseplate 1 holds only cabinet alarms,
10% wired spares per controller and IO type are converted from unused pairs, and the last baseplates stay empty
for future growth. An independent verifier (rules V01 to V16) re-checks the finished allocation, and a readiness
gate marks the result `ISSUE-READY`, `DRAFT` or `BLOCKED`. Bad data never crashes the tool: it becomes a TQ.
On the website a result with warnings stays `DRAFT` until an engineer approves every warning under
**Sign Off The Warnings** on the TQ Board; one marked as a problem keeps it in `DRAFT`. **Re-allocate** re-runs
the solve, and approvals stay on warnings that come back unchanged. The command line has no review step, so
there warnings are only listed.
The Rules view shows exactly which rules are locked and which projects may tune.
