# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Layout

All live code is under `functions/` (Python 3.12 Firebase Cloud Functions) and `public/` (static settings UI). `README.md` is the authoritative reference. `CONTRIBUTING.md` predates the Firebase refactor and is out of date — ignore it unless explicitly asked.

## Common commands

Run these from `functions/` with its venv activated (`source functions/venv/bin/activate`):

```bash
pytest                           # all tests
pytest tests/test_crawler_safety.py::test_name   # single test
pip install -r requirements.txt  # pinned deps
```

Firebase / GCP operations (from repo root):

```bash
firebase deploy --project YOUR_PROJECT_ID                          # functions + hosting + rules
firebase deploy --only functions --project YOUR_PROJECT_ID         # just functions
firebase deploy --only hosting --project YOUR_PROJECT_ID           # just UI
gcloud functions logs read fetch-and-process --region=us-central1 --gen2 --limit=20
gcloud functions logs read generate-and-send-summary --region=us-central1 --gen2 --limit=20
```

There is no linter config — match existing style (4-space indent, ~100 char lines, module-level docstrings).

## Architecture

Four Cloud Functions defined in `functions/main.py`, all `us-central1`, 512 MB, 540 s timeout, `max_instances=1`:

| Function | Trigger | Auth model |
|---|---|---|
| `fetch_and_process` | Cloud Scheduler (hourly) | OIDC; Run IAM locked to scheduler SA |
| `generate_and_send_summary` | Cloud Scheduler (daily) | OIDC; Run IAM locked to scheduler SA |
| `trigger_summary` | UI button | Public invocation; verifies Firebase ID token against `AUTHORIZED_EMAIL` env var |
| `update_secrets` | UI form | Same as `trigger_summary`; writes new versions to Secret Manager |

`trigger_summary` and `generate_and_send_summary` share `_do_generate_and_send()` — don't duplicate that logic. When adding a new UI-facing endpoint, reuse `_cors_preflight`, `_cors_headers`, and `_verify_caller`; `ALLOWED_ORIGIN` is hardcoded to `https://lettermonstr.web.app`.

### Data flow

1. **fetch_and_process** → `EmailFetcher` (IMAP) → `EmailParser` → `WebCrawler` (follows links, SSRF-protected) → writes `processed_emails`, `email_contents`, `links`, `crawled_contents`, and `processed_content` Firestore docs. A sha256 of `subject + content[:1000]` (`_generate_content_hash`) gates dedup before writing `processed_content`.
2. **generate_and_send_summary** → reads unsummarized `processed_content` → `ContentProcessor.process_and_deduplicate` → filters against `summarized_content_history` (last 5 days) → batches to ~25k tokens → `SummaryGenerator` (Anthropic) per batch → `combine_summaries` if >1 batch → writes `summaries` doc, marks source docs summarized, writes per-item history rows, sends via `EmailSender` (SMTP), then `mark_summary_sent`.

### Config layering (`functions/src/config.py`)

Priority, lowest to highest: hardcoded defaults → env vars (`_ENV_DEFAULTS`) → Firestore `settings/app_config` → Secret Manager. The config is cached in `_config`; call `invalidate_cache()` if you need a reload within a process. Only keys present in `_ENV_DEFAULTS` are accepted from Firestore — unknown keys are logged and dropped. Type coercion is keyed by field name via `BOOL_FIELDS`, `INT_FIELDS`, `FLOAT_FIELDS`, `COMMA_SPLIT_FIELDS`. **When adding a new setting, update `_ENV_DEFAULTS` and (if non-string) the coercion sets in `config.py`, then the matching set in `public/app.js` (`INT_FIELDS`, `FLOAT_FIELDS`, `LIST_FIELDS`), and the form field in `public/index.html`.**

### Firestore collections

`processed_emails` (doc id = IMAP message_id), `email_contents`, `links`, `crawled_contents`, `processed_content` (carries `content_hash` and `summarized_flag`), `summaries`, `summarized_content_history`, and `settings/app_config` (the one user-writable doc). All access goes through `functions/src/firestore_db.py` — don't instantiate Firestore clients elsewhere.

### Secrets

Only two are recognized: `gmail-app-password` → `config["email"]["password"]`, `anthropic-api-key` → `config["llm"]["anthropic_api_key"]`. These IDs are enforced by `ALLOWED_SECRETS` in `main.py` and `SECRET_NAMES` in `config.py` — keep them in sync. `update_secrets` caps values at 256 bytes.

### UI ↔ backend contract

`public/app.js` writes the config document at `settings/app_config` directly via the Firestore web SDK (allowed by `firestore.rules`), and POSTs to `trigger_summary` / `update_secrets` with a Firebase ID token. The backend enforces the allowlist via `AUTHORIZED_EMAIL` (set in `functions/.env`); Firestore rules enforce it via a hardcoded email string. **Both must match the same admin email** — update `firestore.rules` AND `functions/.env` AND `public/env-config.js` together.

## Deployment gotchas

- `public/env-config.js` and `functions/.env` are gitignored. They must exist locally before `firebase deploy`, or the UI shows "Missing Configuration" and the functions reject every request. Templates: `public/env-config.template.js`, `functions/.env.template`.
- `firestore.rules` has a hardcoded admin email (currently `jeremycrane@gmail.com`) that must be edited for other deployments.
- After first deploy, the two scheduler-triggered functions must be manually locked down to the scheduler SA (README §10). A fresh deploy does not re-apply this — re-run those `gcloud run services` bindings if functions are recreated.
- `firebase.json` CSP allows `script-src` only from `self`, `gstatic.com`, `apis.google.com`; adding new frontend CDNs requires updating it.

## Commits

Do not add a `Co-Authored-By: Claude …` trailer to commits in this repo. Write the commit message as the sole author.

## Testing

Tests live in `functions/tests/`; `functions/pyproject.toml` sets `testpaths = ["tests"]`. `conftest.py` adds `functions/` to `sys.path` and provides a `mock_content_config` fixture. Existing coverage is focused on crawler SSRF safety, import sanity, and frontend file presence — there is no end-to-end harness for the IMAP → Claude → SMTP path, so exercise that manually via the UI's "Send Summary Now" after UI- or pipeline-affecting changes.
