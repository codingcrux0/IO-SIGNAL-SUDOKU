# The 5-minute demo

Open the app (`streamlit run app.py`). Keep **Try With Sample Data** as the offline fallback and **Lite Mode** for slow machines.

1. **Problem (15 s).** "10,000 tags, error-prone Excel, a 5% client change costs weeks." Show the green *Self-test passed* badge on **Solve**.
2. **Rule Impact (45 s).** After solving, open **Rule Radar → Rule Impact**: every rule and constraint with the cells it touches. Pick
   *Segregation A and B never share a CIOC*: the signals, CHARM types and cabinets it covers, lit up on the cabinet map.
3. **Preflight and solve (45 s).** On **Upload** load the sample MDB (or press the sample button), open **Preflight**
   (score 100, 83 IO-type spellings auto-fixed), then **Solve → Run Allocation**: about a second, 1,152 rows, 0 violations, `DRAFT` with 2 warnings to sign off. Click the **TQs Raised** box, approve both warnings under **Sign Off The Warnings**, and the badge turns `ISSUE-READY`.
4. **Rule Check (20 s).** Click any slot on Cabinet Layout: **Rule Radar → Rule Check** lists every rule that applies to
   it, live. Press **Ask AI** on its card: the Helpdesk opens already knowing that cell.
5. **Cabinet Layout (40 s).** **Slot Map** tab: alarms on baseplate 1, empty end baseplates, A and B in separate CIOCs;
   point at a slot for its details, and pick a tag under *Why Is It Here?*. **Front & Rear Drawings** tab: the elevations.
   **All Cabinet Drawings** in the cabinet list: every cabinet in one scroll box, with *Why Is It Here?* below it.
6. **TQs (25 s).** **TQ Board**: grouped by owner with e-mail-ready text. Apply a suggested answer, press *Re-solve*.
7. **The 5% revision (50 s).** **Revision → Revision Simulator** at 5%: starting from scratch moves many tags, IO Sudoku
   only the changed ones (estimate in hours, with a chart; *Run For Every Size* shows 1-20%).
   Then **Compare With A New MDB**: Rev A = current result, upload a Rev B MDB, *Compare Revisions*, show the four tables and the redline download.
8. **Governed rules and AI (35 s).** **Rules**: propose a rule, press **Verify** beside it in the Review Queue,
   *Preview Impact*, *Activate*. The AI box drafts only a *pending* proposal. "AI never touches the allocation."
9. **Trust (15 s).** **Files**: open the run manifest in the page; it carries the SHA-256 fingerprint; re-running gives the same hash. Parts list and headroom on **Parts**.
