# IO Signal Sudoku

A deterministic DeltaV IO allocation solver. Give it the customer IO list (MDB, Excel or CSV) and it produces:

- the 76-column **IO Allocation** workbook (every signal placed on a cabinet, CIOC, baseplate and channel),
- a **TQ register** (Technical Queries: every question a human must answer, with a suggested fix),
- a **revision impact report** (Added / Deleted / Moved / Renamed) that keeps unchanged cables where they were,
- a Streamlit dashboard with cabinet grids, drawings, rule check and rule impact, a parts list, a revision simulator
  and governed rule changes.

**No AI is used to allocate.** The same input always gives byte-identical output (a SHA-256 fingerprint proves it).
The optional AI box only drafts rule proposals; each one must be verified in the Review Queue, and the AI never changes your data.

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
  Searches for cells (Edit File, Rule Radar's Rule Check, Why Is It Here?, the file viewer) are **case-sensitive**; the search bar
  and the TQ search are not.
- **TQ Board**: filter the sign-off box (Errors, Waiting, Signed Off, Problem) and the question list (coloured
  Error / Warning / Info buttons), with classic page buttons `‹ 1 2 3 … 9 ›` (press **…** to type a page). The **▸**
  next to a question shows its suggested fix: write your own suggestion (kept in the workspace for the next person)
  or send it for verification, or talk it through with the **Helpdesk**. **Answer A Question** picks the tag from a list and then asks you to **verify** the answer: the tool
  re-allocates and says whether the question is really cleared (if not, an `ANSWER-UNRESOLVED` warning is raised).
- **TQ Board → Reviewed Before**: every Approve, Problem, Edit, answer, note and verified or rejected fix is
  remembered (who, when, in which revision, and where the signal sat). When a later allocation or a new revision
  raises a question again on a reviewed signal, cable or cabinet, it is listed here as **NEW PROBLEM** or **CAME
  BACK**. Hover the **i** for how often it was reviewed, approved, rejected and fixed; **▸** shows the whole history
  and the signal *then* next to *now*. The memory is saved in the workspace download. It never changes a sign-off.
- **Helpdesk** (the round **💬 Help** button at the bottom right of every page): a customer-support chat that slides
  in on the right; the page shrinks to make room and goes back when you close it. It explains pages, questions and
  rules, suggests how to fix a problem, and words suggestions and rules (it can also turn a request into a rule
  *proposal*, which still has to be verified on the Rules page). It runs on Google Gemini, tries the best Pro model first
  and falls back to the best model your key allows. It gives advice in words only: it has no tools, cannot change
  the file, the allocation, the rules or any code, never writes code, images or files, stays on this project, and its
  formal, family-friendly personality is fixed in `io_sudoku/core/helpdesk.py`. It sees a short summary of the project,
  never your whole file. **Ask The Helpdesk** buttons next to a TQ, the **Answer A Question** box, a Rule Check cell, a
  Rule Impact rule, *Why Is It Here?* and a revision change open it *about that thing*: it is already told the details
  (the question and its fix, the signal's row and position, the rules on it, its other questions; see
  `io_sudoku/core/helpcontext.py`), shown highlighted at the top of the chat, so you can ask straight away. Every topic
  is its own conversation: another question starts a fresh chat, and the **Conversation** list takes you back to an
  earlier one with only its own messages. To switch it on, add the secret `GEMINI_API_KEY` (locally in `.streamlit/secrets.toml`,
  which git ignores; on Streamlit Cloud under **Settings → Secrets**).
- **Rule Radar** has two tabs, **Rule Check** and **Rule Impact**.
- **Rule Check**: pick any cells (or click a slot or drawing cell on Cabinet Layout) and see a live log of every rule
  and constraint that applies to each: ✓ met, ✗ broken, ▲ to check, plus answers, pins and the solver's decisions.
  Point at **Signal Path** for the way from the field device to the controller.
- **Rule Impact**: Rule Check the other way round. Pick one rule or constraint (locked rules, pack settings, your
  project rules, answers and pins, open questions) and see every cell, CHARM type and signal it touches, met or broken:
  counts by cabinet and CHARM type, a cabinet map with those cells lit up (red = broken, dashed yellow = needs a look),
  and the full list, from which picked cells open on Rule Check. It uses the same checks as Rule Check, so they agree.
- **Cabinet Layout**: bigger slots and drawings; pick **All Cabinet Drawings** in the cabinet list to see every
  cabinet's front and rear in one scroll box, with **Why Is It Here?** for any tag below it. Cabinet alarms show a red
  **!**, and wired spares show their number in white on a small dark label.
- **Allocate buttons** are blue when something changed and turn grey (**✓ Allocation Up To Date**) once the
  allocation matches your current inputs. An out-of-date result is always shown as `DRAFT`.
- **Revision → Revision History**: every allocation of the session is saved (Original, Revision 1, 2 ...), with a
  summary; rename them, compare any two or more (Added / Deleted / Moved / Renamed), **Undo Last Revision** (its
  file, answers, pins, rules and sign-offs come back) or delete chosen revisions - both ask first.
- **Revision → Revision Simulator**: makes a pretend client revision (a share of the tags deleted, renamed, added or
  moved to another pair; the same seed always gives the same revision) and handles it two ways: starting again from
  scratch, and IO Sudoku keeping unchanged tags in place. It shows the tags moved, the estimated rework hours (they
  update as you change the minutes per change), a chart of where the hours go, the moved tags, and **Run For Every
  Size** (1-20%). Download the results or the pretend revision itself to try on Compare With A New MDB.
- Problems in the file are the questions on the **TQ Board** (Preflight shows the data quality score only). The
  assumptions the tool made are on **Solve → Assumptions Used In This Run** (with where each one comes from and who
  should confirm it) and in the downloaded TQ register and summary.
- **Revision → Compare With A New MDB**: each count has **View In Detail**; pick a signal to see every column that
  changed, the rules and decisions behind its new place, and open it on Rule Check. The impact report also opens as a
  web page in the browser (**View In The Browser**, or download the `.html`).
- **Revision → Check Allocation First**: allocates Rev B and shows it in a pop-up **before anything is saved**: better
  or worse than the allocation you have now (errors, set aside, warnings, cabinets, readiness), the rework hours
  keeping positions versus allocating again from scratch, the whole allocation, its questions (new, resolved, and
  items you reviewed before) and its changes. **Save This Revision** (with a name) or **Discard**.
- **Revision → Revision Library**: every saved revision by name; click a name to see all its data again, download its
  allocation and impact report, rename or delete it.
- **Rules**: propose **Settings** (their text fields list the values really in the allocation, with how many signals
  have each, and say how many signals the rule would cover) or **Columns And Checks**, one form for one column:
  1. **Which column**: a new project column (name, text or number, unit such as V), an active project column to
     change, or a column of the allocation itself (checks only).
  2. **Values**: type a value per signal in the table (find signals, then give all the shown ones one value at
     once), paste or upload tags and values, or, second, fill rules ("signals whose IO Type contains AI get 24") and
     one value for every other signal (or blank). A typed value wins, then the last fill rule, then that value.
  3. **Checks**: at most, at least, between, not blank, equal, one of, no duplicates ..., each on every signal or
     only some, each an **Error** (`PROJECT-CHECK-ERROR`, blocks the result) or a **Warning** (`PROJECT-RULE-BROKEN`,
     sign off). Each check shows live how many signals of the current allocation break it.
  The wording is written by code. The optional AI fills the form from a sentence or makes the purpose clearer; it
  never sees your data and never proposes anything. Active columns have **Edit** (opens them in the form) and
  **Remove** (a removal proposal). Project columns are never written into the locked 76-column allocation, and
  none of this can move a signal; the locked rules cannot be proposed at all. Every rule has **👁 Where It
  Applies**, and Preview lists every cell a new pack would change. Each proposal waits in the **Review Queue** (a
  scroll box, newest first) with **Verify** and **Reject**; a verified rule is used only after **Preview And
  Activate**.

To see how the tool handles bad input, upload a file from `test_cases/`. The 21 files there are copies of the sample
MDB with problems planted on purpose: messy formatting, tag, IO type, cable, pair, segregation and alarm errors, an
oversized project, and files that cannot be read at all. `test_cases/README.md` lists what each one should show, and
the test suite checks every file still gives that result. Rebuild them with `.venv/bin/python scripts/make_test_cases.py`.

Every output can be opened in the browser before you download it: the **Files** view (and a **View Here** switch on
Parts, Cabinet Layout and Revision) shows workbooks as searchable tables, pages as pages, JSON as a tree and ZIP
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
.venv/bin/python -m pytest          # about 690 tests: rules, golden output, fuzzing, scale, test cases, UI
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
