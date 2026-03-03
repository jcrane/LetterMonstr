# LetterMonstr

A serverless newsletter aggregator and summarizer that runs on Firebase. It fetches email newsletters via IMAP, crawls linked content, generates concise summaries using Claude, and delivers them to your inbox on a schedule.

## How It Works

```text
Gmail Inbox ──> Cloud Function (hourly) ──> Firestore
                   │  fetch emails             │
                   │  parse content             │
                   │  crawl links               │
                                                │
Firestore ─────> Cloud Function (daily) ──> Summary Email
                   │  deduplicate              to your inbox
                   │  summarize via Claude
                   │  send via SMTP
```

- **Fetch & Process** runs hourly via Cloud Scheduler, connecting to your Gmail over IMAP to pull new newsletters
- **Generate & Send Summary** runs daily, reading all unsummarized content from Firestore, generating a digest with Claude, and emailing it to you
- **Settings UI** at your Firebase Hosting URL lets you adjust configuration without redeploying
- **Manual trigger** button in the UI lets you generate and send a summary on demand

## Prerequisites

- [Firebase CLI](https://firebase.google.com/docs/cli) (`npm install -g firebase-tools`)
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) (`gcloud`)
- Python 3.12+
- A Gmail account with [2-Step Verification](https://myaccount.google.com/security) and an [App Password](https://myaccount.google.com/apppasswords)
- An [Anthropic API key](https://console.anthropic.com/)

## Deployment

### 1. Create a Firebase Project

```bash
firebase login
firebase projects:create YOUR_PROJECT_ID --display-name "LetterMonstr"
gcloud config set project YOUR_PROJECT_ID
```

Then upgrade to the **Blaze (pay-as-you-go) plan** in the [Firebase Console](https://console.firebase.google.com/). Cloud Functions, Cloud Scheduler, and Secret Manager require it. You will stay within the free tier for this workload.

### 2. Enable Required APIs

```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  --project=YOUR_PROJECT_ID
```

### 3. Provision Firestore

```bash
gcloud firestore databases create \
  --location=us-central1 \
  --type=firestore-native \
  --project=YOUR_PROJECT_ID
```

### 4. Store Secrets

```bash
echo -n "YOUR_GMAIL_APP_PASSWORD" | \
  gcloud secrets create gmail-app-password --data-file=- --project=YOUR_PROJECT_ID

echo -n "YOUR_ANTHROPIC_API_KEY" | \
  gcloud secrets create anthropic-api-key --data-file=- --project=YOUR_PROJECT_ID
```

Grant the Cloud Functions service account access:

```bash
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')

for SECRET in gmail-app-password anthropic-api-key; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" \
    --project=YOUR_PROJECT_ID
done
```

### 5. Enable Firebase Authentication

In the [Firebase Console](https://console.firebase.google.com/), go to **Authentication > Sign-in method > Google > Enable**, set a support email, and save. This provides Google Sign-In for the settings UI.

### 6. Create Deployment Config Files

Two files need to be created from their templates (both are gitignored):

**Frontend config** -- copy `public/env-config.template.js` to `public/env-config.js`:

```bash
cp public/env-config.template.js public/env-config.js
```

Edit `public/env-config.js` with your Firebase project values. You can get them by running:

```bash
firebase apps:sdkconfig web --project YOUR_PROJECT_ID
```

Set `authorizedEmail` to the Google account that should have admin access to the settings UI.

**Functions config** -- copy `functions/.env.template` to `functions/.env`:

```bash
cp functions/.env.template functions/.env
```

Set `AUTHORIZED_EMAIL` to the same email address.

### 7. Update Firestore Rules

Edit `firestore.rules` and replace the email address with your authorized admin email.

### 8. Deploy

```bash
firebase deploy --project YOUR_PROJECT_ID
```

This deploys Cloud Functions, Firestore security rules, and the hosting site in one command.

### 9. Set Up Scheduling

```bash
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')

FETCH_URL=$(gcloud functions describe fetch-and-process \
  --region=us-central1 --gen2 --project=YOUR_PROJECT_ID \
  --format='value(serviceConfig.uri)')

SUMMARY_URL=$(gcloud functions describe generate-and-send-summary \
  --region=us-central1 --gen2 --project=YOUR_PROJECT_ID \
  --format='value(serviceConfig.uri)')

# Fetch new emails every hour
gcloud scheduler jobs create http lettermonstr-fetch \
  --schedule="0 * * * *" \
  --uri="${FETCH_URL}" \
  --http-method=POST \
  --location=us-central1 \
  --oidc-service-account-email="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --project=YOUR_PROJECT_ID

# Generate and send summary daily at 18:00 UTC
gcloud scheduler jobs create http lettermonstr-summary \
  --schedule="0 18 * * *" \
  --uri="${SUMMARY_URL}" \
  --http-method=POST \
  --location=us-central1 \
  --oidc-service-account-email="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --project=YOUR_PROJECT_ID
```

### 10. Lock Down Scheduler Functions

Remove public access from the two scheduler-triggered functions (only the scheduler service account should call them):

```bash
gcloud run services remove-iam-policy-binding fetch-and-process \
  --region=us-central1 --project=YOUR_PROJECT_ID \
  --member="allUsers" --role="roles/run.invoker"

gcloud run services remove-iam-policy-binding generate-and-send-summary \
  --region=us-central1 --project=YOUR_PROJECT_ID \
  --member="allUsers" --role="roles/run.invoker"

for SVC in fetch-and-process generate-and-send-summary; do
  gcloud run services add-iam-policy-binding $SVC \
    --region=us-central1 --project=YOUR_PROJECT_ID \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/run.invoker"
done
```

The UI-facing functions (`trigger_summary`, `update_secrets`) need public invocation since they are called from the browser (protected by Firebase Auth + server-side token verification):

```bash
for FN in trigger-summary update-secrets; do
  gcloud functions add-invoker-policy-binding $FN \
    --region=us-central1 --project=YOUR_PROJECT_ID \
    --member="allUsers"
done
```

### 11. Verify

Visit `https://YOUR_PROJECT_ID.web.app`, sign in with your authorized Google account, and confirm settings are loaded. Use the **Send Summary Now** button to trigger a test run.

Check logs:

```bash
gcloud functions logs read fetch-and-process \
  --region=us-central1 --gen2 --project=YOUR_PROJECT_ID --limit=20

gcloud functions logs read generate-and-send-summary \
  --region=us-central1 --gen2 --project=YOUR_PROJECT_ID --limit=20
```

## Settings UI

Once deployed, the settings UI is available at `https://YOUR_PROJECT_ID.web.app`. It is protected by Google Sign-In and restricted to your authorized email via Firestore security rules and server-side token verification.

The UI lets you configure:

| Section | Settings |
| ------- | -------- |
| **Manual Summary** | Send a summary on demand from collected content |
| **Email / Inbox** | Fetch email, IMAP server/port, folders, lookback days, periodic fetch toggle |
| **Summary / Delivery** | Recipient email, sender email, SMTP server/port, subject prefix, frequency, delivery time |
| **LLM** | Model (Claude Opus 4.6, Claude Sonnet 4.6), max tokens, temperature |
| **Content / Crawling** | Max links per email, max link depth, request timeout, user agent, ad keywords |
| **Secrets** | Gmail App Password, Anthropic API Key (write-only) |

Changes take effect on the next scheduled function run with no redeployment needed.

## Architecture

```text
functions/
  main.py                       # Cloud Function entry points
  requirements.txt              # Python dependencies (pinned)
  .env                          # AUTHORIZED_EMAIL (gitignored)
  .env.template                 # Template for .env
  src/
    config.py                   # Loads config from Firestore + Secret Manager
    firestore_db.py             # Firestore data access layer
    mail_handling/
      fetcher.py                # IMAP email fetcher
      parser.py                 # Email content parser
      sender.py                 # SMTP summary sender
    crawl/
      crawler.py                # Web content crawler (with SSRF protection)
    summarize/
      generator.py              # Claude API integration
      claude_summarizer.py      # Prompt templates
      processor.py              # Content deduplication and filtering
public/
  index.html                    # Settings UI
  app.js                        # Firebase Auth + Firestore client logic
  style.css                     # UI styling
  env-config.js                 # Firebase project config (gitignored)
  env-config.template.js        # Template for env-config.js
firebase.json                   # Firebase project configuration
firestore.rules                 # Firestore security rules
```

## Gmail Setup

1. Enable [2-Step Verification](https://myaccount.google.com/security) on your Gmail account
2. Create an [App Password](https://myaccount.google.com/apppasswords) (select "Mail" and "Other")
3. Use this app password when storing the `gmail-app-password` secret

## Cost

The project runs entirely within Firebase/GCP free tier quotas:

- **Cloud Functions**: 2M invocations/month, 400K GB-seconds free
- **Cloud Firestore**: 1 GiB storage, 50K reads/day, 20K writes/day free
- **Cloud Scheduler**: 3 jobs free
- **Secret Manager**: 6 active secret versions free
- **Firebase Hosting**: 10 GB storage, 360 MB/day transfer free

The only external cost is the **Anthropic API** for Claude summaries (typically a few cents per summary).

## Security

- Secrets stored in Google Secret Manager (never in code or environment variables)
- Firestore security rules restrict settings access to a single authorized email
- Cloud Functions verify Firebase Auth ID tokens server-side
- Scheduler-triggered functions are locked to the Cloud Scheduler service account only
- Web crawler blocks private IPs and cloud metadata endpoints (SSRF protection)
- Firebase Hosting serves CSP, X-Frame-Options, and other security headers
- Dependencies pinned to specific versions in `requirements.txt`

## Troubleshooting

**No emails being fetched?**
Check that your Gmail App Password is correct and IMAP is enabled in Gmail settings. Review logs with `gcloud functions logs read fetch-and-process`.

**Summary not being sent?**
Verify SMTP settings and recipient email in the Settings UI. Check logs with `gcloud functions logs read generate-and-send-summary`.

**Settings UI shows "Missing Configuration"?**
You need to create `public/env-config.js` from the template before deploying hosting.

**403 error when calling functions?**
The scheduler functions are intentionally locked down. Only Cloud Scheduler can invoke them. Use the **Send Summary Now** button in the UI for manual triggers.

## License

MIT
