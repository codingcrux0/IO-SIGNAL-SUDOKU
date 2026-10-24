# The 5-minute demo

Open the app (`streamlit run app.py`). Keep **Try With Sample Data** as the offline fallback and **Lite Mode** for slow machines.

1. **Problem (15 s).** "10,000 tags, error-prone Excel, a 5% client change costs weeks." Show the green *Self-test passed* badge on **Solve**.
2. **Health check of the human sample (45 s).** On **Health**, upload `io_sudoku/data/sample/sample_allocation.xlsx` and press *Run Health Check*.
   The score is below 100 and the 10% wired-spare rule (V10) is broken. "This is what manual allocation looks like."
3. **Preflight and solve (45 s).** On **Upload** load the sample MDB (or press the sample button), open **Preflight**
   (score 100, 83 IO-type spellings auto-fixed), then **Solve → Run Allocation**: about a second, 1,152 rows, 0 violations, `DRAFT` with 2 warnings to sign off. Click the **TQs Raised** box, approve both warnings under **Sign Off The Warnings**, and the badge turns `ISSUE-READY`.
4. **Human vs IO Sudoku (20 s).** Run the health check again with a result present: the side-by-side scorecard appears.
5. **Cabinet Layout (40 s).** **Slot Map** tab: alarms on baseplate 1, empty end baseplates, A and B in separate CIOCs;
   point at a slot for its details, and pick a tag under *Why Is It Here?*. **Front & Rear Drawings** tab: the elevations.
6. **TQs (25 s).** **TQ Board**: grouped by owner with e-mail-ready text. Apply a suggested answer, press *Re-solve*.
7. **The 5% revision (50 s).** **Simulator** at 5%: starting from scratch moves many tags, IO Sudoku moves none (estimate in hours).
   Then **Revision**: Rev A = current result, upload a Rev B MDB, *Compare Revisions*, show the four tables and the redline download.
8. **Governed rules and AI (35 s).** **Rules**: propose a rule, show that the author cannot approve it, a second person approves with the passcode,
   *Preview Impact*, *Activate*. The AI box drafts only a *pending* proposal. "AI never touches the allocation."
9. **Trust (15 s).** **Files**: open the run manifest in the page; it carries the SHA-256 fingerprint; re-running gives the same hash. Parts list and headroom on **Parts**.
