# Hosting IO Signal Sudoku

Everything lives in this folder, so hosting is: install, run `streamlit run app.py`.

## Streamlit Community Cloud (free, simplest)

1. Push this folder to a GitHub repository (the folder that contains `app.py` should be the repository root,
   or set the app's "Main file path" to `CODE/app.py`).
2. On share.streamlit.io choose **New app**, pick the repository and branch, and set the main file to `app.py`.
3. Under **Advanced settings → Secrets** paste (all optional):

   ```toml
   APPROVER_PASSCODE = "choose-a-long-phrase"     # enables rule approval on the Rules view
   GEMINI_API_KEY = "your-gemini-key"             # switches on the Helpdesk chat and AI rule drafting
   ```
   The Helpdesk needs no extra package (it uses the Python standard library). Optionally,
   `ANTHROPIC_API_KEY` instead drafts rules with Claude (then add `anthropic>=1.0` to `requirements.txt`).
4. Deploy. The sidebar shows a green **Self-test passed** badge on the Solve view when the install is healthy.

Without the passcode, rule approval is switched off (rules can still be proposed). Without an AI key the Helpdesk
says it is not set up and the AI drafting box is greyed out; nothing else changes. Never commit a key: locally it
lives in `.streamlit/secrets.toml`, which git ignores.

## Any server or laptop

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
APPROVER_PASSCODE=letmein .venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

## Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

## Notes

- All processing is in memory: uploads are never written to disk and never leave the server (except the optional AI
  request text of at most 500 characters).
- Upload limit is 50 MB (`.streamlit/config.toml`). Large inputs (10,000 signals) solve in a few seconds.
- Python 3.10 or newer. `requirements.lock.txt` records the exact versions the tests passed with.
