# LetterMonstr

A personal newsletter aggregator and summarizer for macOS that processes email newsletters and generates concise summaries using Claude 3.7 Sonnet.

## Features

- Fetches newsletters from a Gmail account
- Processes forwarded emails and extracts links
- Generates summaries using Claude 3.7 Sonnet
- Delivers summaries at configurable intervals (daily, weekly, or monthly)
- Filters out advertisements and duplicate content

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

- **Start service**: `./run_lettermonstr.sh`
- **Check status**: `./status_lettermonstr.sh`
- **Stop service**: `./stop_lettermonstr.sh`
- **View latest summary**: `./view_latest_summary.sh`
- **Force summary generation**: `./force_summary.sh`
- **Reset database**: `./reset_database.py`
- **Generate test newsletter**: `python test_newsletter.py`

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
