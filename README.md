# LetterMonstr

A personal newsletter aggregator and summarizer for macOS that processes email newsletters and generates concise summaries using Claude Sonnet 4.

## Features

- Fetches newsletters from a Gmail account
- Processes forwarded emails and extracts links
- Generates summaries using Claude Sonnet 4
- Delivers summaries at configurable intervals (daily, weekly, or monthly)
- Filters out advertisements and duplicate content
- **Robust sleep/wake handling** - automatically recovers after laptop sleep
- **Optional LaunchAgent service** - runs automatically with crash recovery

## Requirements

- macOS (10.15 Catalina or later)
- Python 3.9+
- Gmail account for receiving newsletters
- Gmail App Password (requires 2-Step Verification)
- Anthropic API key for Claude access

## Quick Start

1. **Clone this repository**

2. **Create a virtual environment**:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip3 install -r requirements.txt
   ```

3. **Configure LetterMonstr**:

   ```bash
   python3 setup_config.py
   ```

   This will guide you through setting up Gmail credentials and your Anthropic API key.

4. **Initialize the database**:

   ```bash
   python3 init_db.py
   ```

5. **Run LetterMonstr**:

   ```bash
   ./run_lettermonstr.sh
   ```

## Gmail Setup

1. **Enable 2-Step Verification** on your Gmail account:
   - Go to your [Google Account](https://myaccount.google.com) > Security > 2-Step Verification

2. **Create an App Password**:
   - Go to [App Passwords](https://myaccount.google.com/apppasswords)
   - Select app: "Mail", device: "Other (LetterMonstr)"
   - Copy the 16-character password for configuration

## Usage

1. **Forward newsletters** to your configured Gmail account

2. **Start LetterMonstr**:

   ```bash
   ./run_lettermonstr.sh
   ```

3. **Check status**:

   ```bash
   ./status_lettermonstr.sh
   ```

4. **Stop the service**:

   ```bash
   ./stop_lettermonstr.sh
   ```

5. **View the latest summary**:

   ```bash
   ./view_latest_summary.sh
   ```

## Key Commands

### Quick Reference

| Command | Description |
|---------|-------------|
| `./install_service.sh` | **Install as LaunchAgent service** (recommended for laptops - auto-restart & sleep recovery) |
| `./run_lettermonstr.sh` | Run traditionally (manual start) |
| `./status_lettermonstr.sh` | Check status of any running instance |
| `./stop_lettermonstr.sh` | Stop any running instance (LaunchAgent or traditional) |
| `./restart_service.sh` | Restart LaunchAgent service |
| `./uninstall_service.sh` | Remove LaunchAgent service completely |
| `./view_latest_summary.sh` | View the most recent summary |
| `./force_summary.sh` | Force generate a summary now |
| `./test_sleep_recovery.sh` | Test/diagnose sleep/wake handling |

### Utility Commands

- **Reset database**: `python3 utils/db_tools/reset_database.py`
- **Generate test newsletter**: `python3 utils/debug/test_newsletter.py`
- **View logs**: `tail -f data/lettermonstr_periodic.log`

### Documentation

- **Sleep/Wake Guide**: [SLEEP_WAKE_HANDLING.md](SLEEP_WAKE_HANDLING.md) - Detailed info on sleep/wake recovery
- **Quick Start**: [QUICK_START_SLEEP_FIX.md](QUICK_START_SLEEP_FIX.md) - Get running in 2 minutes
- **Technical Details**: [SLEEP_WAKE_FIX_SUMMARY.md](SLEEP_WAKE_FIX_SUMMARY.md) - What was fixed

## Troubleshooting

- **No emails being processed?** Verify your Gmail credentials and ensure emails are unread.
- **Database issues?** Run `./reset_database.py` to create a fresh database.
- **No summaries being sent?** Check logs in `data/lettermonstr_periodic_runner.log` and verify your email settings.
- **Application crashes?** Run `./run_lettermonstr.sh` to restart it.
- **Forwarded email issues?** Try forwarding directly from Gmail for best compatibility.

## Troubleshooting Scripts

LetterMonstr includes several utility scripts to diagnose and fix specific issues:

- **`reset_database.py`**: Creates a fresh database with a backup of the old one.

  ```bash
  python reset_database.py
  ```

- **`reprocess_emails.py`**: Resets processed emails to be processed again.

  ```bash
  python reprocess_emails.py  # Offers options for all or only forwarded emails
  ```

- **`reprocess_forwarded_emails.py`**: Specifically reprocesses forwarded emails.

  ```bash
  python reprocess_forwarded_emails.py
  ```

- **`fix_content_processing.py`**: Diagnoses and fixes issues with email content processing.

  ```bash
  python fix_content_processing.py
  ```

- **`fix_database_locks.py`**: Resolves database locking issues.

  ```bash
  python fix_database_locks.py
  ```

- **`fix_email_content.py`**: Repairs issues with stored email content.

  ```bash
  python fix_email_content.py
  ```

- **`fix_summary_sending.py`**: Troubleshoots and fixes summary delivery problems.

  ```bash
  python fix_summary_sending.py
  ```

- **`debug_summaries.py`**: Examines summary generation issues.

  ```bash
  python debug_summaries.py
  ```

- **`send_pending_summaries.py`**: Resends summaries that failed to deliver.

  ```bash
  python send_pending_summaries.py  # Send all pending
  python send_pending_summaries.py <summary_id>  # Send specific summary
  ```

- **`reset_processed_content.py`**: Resets content processing status without affecting email records.

  ```bash
  python reset_processed_content.py
  ```

- **`send_summary_now.py`**: Generates and sends a summary immediately.

  ```bash
  python send_summary_now.py
  ```

## Logs

- Main log: `data/lettermonstr.log`
- Periodic process log: `data/lettermonstr_periodic_runner.log`
