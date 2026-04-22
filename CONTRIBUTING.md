# Contributing to LetterMonstr

LetterMonstr is a small personal project, but PRs and issues are welcome if something's useful to you. This document covers how the codebase is laid out and how to make changes safely.

## Project shape

LetterMonstr runs entirely on Firebase / Google Cloud — there is no local daemon. See `README.md` for the full deployment walkthrough.

- `functions/` — Python 3.12 Cloud Functions (IMAP fetch, crawl, summarize, SMTP send, UI-facing HTTP endpoints)
- `public/` — static settings UI (Firebase Hosting)
- `firestore.rules` — admin-only access to `settings/app_config`
- `firebase.json` — hosting + functions + CSP configuration

`CLAUDE.md` has a more detailed architecture summary if you're picking the project up cold.

## Development setup

### Prerequisites

- Python 3.12
- [Firebase CLI](https://firebase.google.com/docs/cli) (`npm install -g firebase-tools`)
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) (for log inspection and manual deploys)
- A Firebase project (see `README.md` for setup)

### Local environment

```bash
cd functions
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running tests

```bash
cd functions
source venv/bin/activate
pytest                                          # full suite
pytest tests/test_crawler_safety.py             # one file
pytest tests/test_utils.py::test_name           # one test
```

Tests are fast (under a second) and mostly cover crawler SSRF safety, import sanity, and frontend file presence. There's no end-to-end harness for the IMAP → Claude → SMTP pipeline — after changes that touch the pipeline, run a manual end-to-end check via the **Send Summary Now** button in the deployed UI.

### Deploying

```bash
firebase deploy --project YOUR_PROJECT_ID                      # everything
firebase deploy --only functions --project YOUR_PROJECT_ID     # just functions
firebase deploy --only hosting --project YOUR_PROJECT_ID       # just UI
```

Two gitignored files must exist locally before deploying: `public/env-config.js` (from `env-config.template.js`) and `functions/.env` (from `.env.template`). The admin email has to match in three places — see `CLAUDE.md` § "UI ↔ backend contract".

## Change guidelines

- **Scope** — one feature or fix per PR. Keep changes focused.
- **Config schema** — adding a new setting means touching `_ENV_DEFAULTS` in `functions/src/config.py`, the coercion sets (`INT_FIELDS` / `FLOAT_FIELDS` / `LIST_FIELDS`) in `public/app.js`, and the form field in `public/index.html`. The `_filter_firestore_settings` allowlist will drop anything you miss.
- **Secrets** — only `gmail-app-password` and `anthropic-api-key` are recognized (enforced by `ALLOWED_SECRETS` in `main.py` and `SECRET_NAMES` in `config.py`). Keep them in sync.
- **Firestore** — all access goes through `functions/src/firestore_db.py`; don't instantiate clients elsewhere.
- **Dependencies** — pinned in `functions/requirements.txt`. Bump deliberately and re-run `pytest`.

## Commit and PR style

- Lowercase, present-tense commit summaries (`fix timeouts`, `firebase refactor`)
- Reference issues with `Fixes #N` in the PR description when applicable
- Don't commit `.env`, `env-config.js`, or anything under `data/` (all gitignored)

## Reporting issues

Use GitHub Issues. Include: what you expected, what happened, and relevant logs (`gcloud functions logs read <function-name> --region=us-central1 --gen2`).
