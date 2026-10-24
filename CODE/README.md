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

Moving around and fixing things:

- **Search bar** (top of every page): type a few letters to jump to any page or section of the app; the matching
  runs in your browser, and Enter on a misspelt word takes you to the closest match. (Tags and cables are searched
  where they live: **Why Is It Here?**, the TQ Board and the Files viewer.)
- **Links in sentences**: when a message sends you somewhere ("open the TQ Board", "on the Revision view"), the
  page name is a link that takes you straight there, to the right tab and section, without reloading the page.
- **Short questions**: long questions on the TQ Board show as one short line; point at the small **i** next to
  one to read the whole text, the suggested fix and the owner. Long explanations everywhere sit behind an **i**.
- **Messages where they belong**: a saved change, an error or a confirmation appears right under the heading of the
  section it is about, not at the top of the page.
- **Edit File**: change any cell of the uploaded file in the page. Every **✎ Edit** button (Upload, and each error
  and warning on the TQ Board) opens this page at the exact cell and brings you back when you save. A question about
  a whole cable lists every row of that cable; one about a whole cabinet opens that cabinet; one about a column opens
  the column mapping. Changes are listed, the last one can be undone, and all can be deleted (both ask first).
  Searches for cells (Edit File, Rule Check, Why Is It Here?, the file viewer) are **case-sensitive**; the search bar
  and the TQ search are not.
- **TQ Board**: filter the sign-off box (Errors, Waiting, Signed Off, Problem) and the question list (coloured
  Error / Warning / Info buttons), with classic page buttons `‹ 1 2 3 … 9 ›` (press **…** to type a page). The **▸**
  next to a question shows its suggested fix: write your own suggestion (kept in the workspace for the next person)
  or send it for approval, or talk it through in the **Suggestion Assistant** in the sidebar. The assistant's AI is
  not connected yet; when it is, it may only discuss and reword the suggestion and can never change a file, rule or
  code. **Answer A Question** picks the tag from a list and then asks you to **verify** the answer: the tool
  re-allocates and says whether the question is really cleared (if not, an `ANSWER-UNRESOLVED` warning is raised).
- **Rule Check**: pick any cells (or click a slot or drawing cell on Cabinet Layout) and see a live log of every rule
  and constraint that applies to each: ✓ met, ✗ broken, ▲ to check, plus answers, pins and the solver's decisions.
  Point at **Signal Path** for the way from the field device to the controller.
- **Cabinet Layout**: bigger slots and drawings; pick **All Cabinet Drawings** in the cabinet list to see every
  cabinet's front and rear in one scroll box.
- **Allocate buttons** are blue when something changed and turn grey (**✓ Allocation Up To Date**) once the
  allocation matches your current inputs. An out-of-date result is always shown as `DRAFT`.
- **Revision → Revision History**: every allocation of the session is saved (Original, Revision 1, 2 ...), with a
  summary; rename them, compare any two or more (Added / Deleted / Moved / Renamed), **Undo Last Revision** (its
  file, answers, pins, rules and sign-offs come back) or delete chosen revisions - both ask first.
- **Revision → Compare With A New MDB**: each count has **View In Detail**; pick a signal to see every column that
  changed, the rules and decisions behind its new place, and open it on Rule Check. The impact report also opens as a
  web page in the browser (**View In The Browser**, or download the `.html`).
- **Rules**: propose **Settings**, **New Columns** (a project label on some CHARM signals, never written into the
  locked 76-column allocation) or **Constraints** (checks every covered signal must pass; a broken one becomes a
  `PROJECT-RULE-BROKEN` warning). Every rule has **👁 Where It Applies**, and Preview lists every cell a new pack
  would change, signal by signal. None of them can move a signal, and the locked rules cannot be proposed at all.

To see how the tool handles bad input, upload a file from `test_cases/`. The 21 files there are copies of the sample
MDB with problems planted on purpose: messy formatting, tag, IO type, cable, pair, segregation and alarm errors, an
oversized project, and files that cannot be read at all. `test_cases/README.md` lists what each one should show, and
the test suite checks every file still gives that result. Rebuild them with `.venv/bin/python scripts/make_test_cases.py`.

Every output can be opened in the browser before you download it: the **Files** view (and a **View Here** switch on
Parts, Cabinet Layout, Revision and Health) shows workbooks as searchable tables, pages as pages, JSON as a tree and ZIP
bundles file by file. The viewer is read-only; **Download This View (.csv)** exports exactly the rows you filtered, and
**Download Everything (.zip)** gets every file at once.

## Command line (no browser)

```bash
.venv/bin/python -m io_sudoku selftest                          # checks the install in about a second
.venv/bin/python -m io_sudoku solve MDB.xlsx --out out/         # allocation, TQ register, parts, drawings, manifest
.venv/bin/python -m io_sudoku revise REV_A.xlsx MDB_B.xlsx --out out/
.venv/bin/python -m io_sudoku audit SOME_ALLOCATION.xlsx --out out/   # health-check any allocation
```

Exit codes: `0` the outputs were written (the readiness status is printed and is part of the file names),
`1` the input could not be read or nothing could be allocated, `2` wrong command-line arguments.
Run `--help` on any command for its options.

## Test it

```bash
.venv/bin/python -m pytest          # about 670 tests: rules, golden output, fuzzing, scale, test cases, UI
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
The gate is strict: any error (an error TQ, a broken rule, or a signal that had to be set aside) makes the result
`BLOCKED`. The clean signals are still allocated so you can see them, but nothing can be issued until every error
is fixed and the allocation is run again. `DRAFT` means there are no errors left, only warnings to sign off.
On the website a result with warnings stays `DRAFT` until an engineer approves every warning under
**Sign Off The Warnings** on the TQ Board; one marked as a problem keeps it in `DRAFT`. **Re-allocate** re-runs
the solve, and approvals stay on warnings that come back unchanged. The command line has no review step, so
there warnings are only listed.
The Rules view shows exactly which rules are locked and which projects may tune.
