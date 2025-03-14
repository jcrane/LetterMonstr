# LetterMonstr

A personal newsletter aggregator and summarizer for macOS that processes email newsletters and generates concise summaries using Claude 3.7 Sonnet.

## Important Note

LetterMonstr is designed specifically for macOS and meant to run on a local Mac machine. It has not been tested on and is not supported on:

- Windows or Linux operating systems
- Server environments (including cloud servers)
- Production deployment scenarios

To run LetterMonstr in a production server environment, you would need to make your own modifications to the code, such as:

- Implementing proper security measures
- Setting up service monitoring and auto-restart capabilities
- Configuring proper logging and error handling for remote environments
- Managing database backups and data persistence

## Features

- Fetches newsletters from a designated Gmail account
- Processes unread emails and marks them as read after successful processing
- Follows links within newsletters to gather additional content
- Removes redundant information across similar newsletters
- Filters out advertisements and paid placements
- Includes source links for each summarized item, allowing you to dive deeper into topics of interest
- Effectively handles forwarded newsletters from Gmail
- Summarizes content using Claude 3.7 Sonnet LLM
- Delivers summaries at configurable intervals (daily, weekly, or monthly)
- **NEW**: Supports periodic email fetching throughout the day for improved reliability and performance

## Periodic Email Fetching

LetterMonstr supports periodic email fetching throughout the day, which can significantly improve overall processing time and reliability.

### How It Works

1. **Periodic Fetching**: Instead of fetching all emails at once at the scheduled time, LetterMonstr can fetch and process emails periodically (e.g., every hour) throughout the day.
2. **Incremental Processing**: Each fetch processes only new emails since the last fetch, spreading the processing load.
3. **Final Summary**: At the scheduled delivery time, all processed content is combined, summarized, and sent as your regular newsletter digest.

### Benefits

- **Faster Processing**: The final summary generation is much faster since individual emails are already processed.
- **More Reliable**: Less likely to hit API rate limits or timeouts by distributing processing throughout the day.
- **Up-to-date Summaries**: Content is processed closer to when it arrives rather than all at once.
- **Better Deduplication**: Content is properly deduplicated across all fetched emails.

### Setup

1. Enable periodic fetching in your configuration:

```yaml
email:
  # ... your existing email settings ...
  periodic_fetch: true
  fetch_interval_hours: 1  # Run every hour
  mark_read_after_summarization: true  # Only mark emails as read after summary is sent
```

1. Run LetterMonstr using the standard runner script:

```bash
./run_lettermonstr.sh
```

The script will automatically detect your configuration and start in the appropriate mode.

### How Operating Modes Work

LetterMonstr now supports two operating modes that are automatically selected based on your configuration:

1. **Traditional Mode** (default): All emails are fetched and processed at the scheduled delivery time.
2. **Periodic Mode**: Emails are fetched and processed throughout the day, with summaries generated at the scheduled time.

The `run_lettermonstr.sh` script detects which mode to use by checking your configuration file. There's no need to use different commands for different modes - the system adapts automatically.

### Configuration Options

- `periodic_fetch`: Enable/disable periodic fetching (default: false)
- `fetch_interval_hours`: How often to fetch emails in hours (default: 1)
- `mark_read_after_summarization`: Whether to mark emails as read only after summarization (default: true)

### Database Changes

The system now uses a new `ProcessedContent` table to track content that has been processed but not yet summarized. This ensures proper deduplication and tracking across multiple fetches.

A database migration script (`db_migrate.py`) is automatically run when starting the application to ensure your database schema is up to date.

## Useful Commands

LetterMonstr provides several useful scripts to manage and interact with the system:

- **Start the service**: `./run_lettermonstr.sh` (automatically runs in the appropriate mode)
- **Check status**: `./status_lettermonstr.sh` (shows status of either periodic or traditional process)
- **Stop the service**: `./stop_lettermonstr.sh` (stops all running LetterMonstr processes)
- **View latest summary**: `./view_latest_summary.sh`
- **Force summary generation**: `./force_summary.sh` (processes unread emails and immediately generates/sends a summary)
- **Force process emails**: `./force_process.sh` or `python force_process_unread.py`
- **Send pending summaries**: `python send_pending_summaries.py [summary_id]`
- **Reset database**: `./reset_database.py` (resets database while creating a backup)
- **Fix missing content**: `./fix_content_processing.py` (diagnoses and fixes content processing issues)
- **Generate a test newsletter**: `python test_newsletter.py`

## Requirements

- macOS (10.15 Catalina or later recommended)
- Python 3.9+
- Gmail account for receiving newsletters
- Gmail App Password (requires 2-Step Verification to be enabled)
- Anthropic API key for Claude access
- Required packages (install via `pip install -r requirements.txt`):
  - pyyaml
  - schedule
  - sqlalchemy
  - python-dotenv
  - beautifulsoup4
  - requests
  - anthropic
  - langchain
  - langchain-community

## Installation

1. Clone this repository
2. Create a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip3 install -r requirements.txt
   ```

4. Run the configuration script:

   ```bash
   python3 setup_config.py
   ```

   This will guide you through setting up:
   - Your Gmail credentials
   - Email delivery preferences
   - Anthropic API key

5. Run the application:

   ```bash
   ./run_lettermonstr.sh
   ```

## Running as a Service

LetterMonstr includes scripts to manage it as a background service on macOS:

### Starting the Service

To run LetterMonstr in the background:

```bash
./run_lettermonstr.sh
```

This script:

- Activates the virtual environment (creates it if needed)
- Checks if configuration exists (runs setup if needed)
- Runs database migrations if needed
- Detects whether to use periodic or traditional mode based on your configuration
- Starts LetterMonstr as a background process
- Saves the process ID for management

### Checking Status

To check if LetterMonstr is running and view recent logs:

```bash
./status_lettermonstr.sh
```

This shows:

- Which mode is enabled (periodic or traditional)
- Process status and details
- Recent log entries for the active process
- Database statistics, including processed content items and unsummarized content

### Stopping the Service

To stop all LetterMonstr processes:

```bash
./stop_lettermonstr.sh
```

This will gracefully shut down both the traditional and periodic processes if they're running.

### Viewing Summaries

To view the most recently generated summary:

```bash
./view_latest_summary.sh
```

This will display:

- Summary metadata (type, date range, delivery status)
- The full content of the most recent summary
- A list of other available summaries

## Sleep & Restart Behavior

- When your Mac goes to sleep, LetterMonstr will be suspended
- Upon wake, LetterMonstr will resume automatically
- If your Mac is rebooted, you'll need to manually restart LetterMonstr
- Your configuration and processed emails will be maintained between restarts

## Testing

### Test Newsletter Generator

For testing the application without waiting for real newsletters, use the test newsletter generator:

```bash
python test_newsletter.py
```

This script:

- Creates a simulated newsletter with random content and links
- Sends it to your configured Gmail account
- Includes test elements like sponsored content for ad filtering tests

The test newsletter will be processed during the next application cycle, or you can manually trigger processing by running the force processing script: `python src/force_process_unread.py`.

## Configuration

LetterMonstr uses a YAML configuration file located at `config/config.yaml`. This file is automatically created by the setup script and contains your personal settings.

**Important Security Note**: The `config/config.yaml` file contains sensitive information and is automatically added to `.gitignore` to prevent it from being committed to version control.

### Configuration Template

A template configuration file is provided at `config/config.template.yaml`. You can use this as a reference for the available settings.

Key configuration options include:

- **Email Settings**:
  - Gmail account credentials
  - IMAP server settings
  - Initial email lookback period
  - Periodic fetching options
  - Email marking behavior

- **Content Processing**:
  - Link crawling depth and limits
  - Advertisement filtering keywords

- **Summary Delivery**:
  - Recipient email address
  - Delivery frequency (daily, weekly, monthly)
  - Delivery time

- **LLM Settings**:
  - Anthropic API key
  - Claude model selection
  - Token limits and temperature (increase max_tokens for longer summaries)

### Customizing Summaries

You can customize the summaries generated by LetterMonstr by modifying:

1. **Token Length**: Increase `max_tokens` in the LLM settings section for longer, more detailed summaries
2. **Source Links**: By default, the system includes source links for each major topic to allow further reading
3. **Summary Style**: Edit the prompt in `src/summarize/generator.py` to change the style and format of summaries

## Project Structure

```text
lettermonstr/
├── config/                # Configuration files
│   ├── config.yaml        # Your personal configuration (gitignored)
│   └── config.template.yaml  # Template for reference
├── data/                  # Storage for processed content
├── src/                   # Source code
│   ├── mail_handling/     # Email fetching and processing
│   ├── crawl/             # Web crawling components
│   ├── summarize/         # LLM summarization logic
│   ├── database/          # Database models and functions
│   ├── main.py            # Traditional main application
│   ├── periodic_runner.py # Periodic fetching process
│   ├── fetch_process.py   # Email fetching and processing logic
│   ├── db_migrate.py      # Database migration script
│   └── force_process_unread.py # Script to force process emails
├── run_lettermonstr.sh    # Script to run as background service (any mode)
├── status_lettermonstr.sh # Script to check service status
├── stop_lettermonstr.sh   # Script to stop the service
├── view_latest_summary.sh # Script to view recent summaries
├── send_pending_summaries.py # Script to send unsent summaries
├── test_newsletter.py     # Script to generate test newsletters
└── requirements.txt       # Python package requirements
```

## Gmail Setup

### Creating a Dedicated Gmail Account (Recommended)

It's recommended to create a dedicated Gmail account for your newsletters:

1. Visit [Gmail's signup page](https://accounts.google.com/signup)
2. Fill in the required information to create a new account
3. Complete the verification process
4. Once your account is created, log in and set up your profile

### Setting Up App Password

To use LetterMonstr with Gmail:

1. Enable 2-Step Verification on your Gmail account:
   - Go to your [Google Account](https://myaccount.google.com)
   - Select "Security" from the left navigation
   - Under "Signing in to Google," select "2-Step Verification"
   - Follow the steps to turn on 2-Step Verification
   - You may need to provide a phone number and choose verification method

2. Create an App Password:
   - After enabling 2-Step Verification, go to [App Passwords](https://myaccount.google.com/apppasswords)
   - Under "Select app," choose "Mail"
   - Under "Select device," choose "Other" and enter "LetterMonstr"
   - Click "Generate"
   - You'll see a 16-character app password (four groups of four characters)
   - Copy this password and use it in the LetterMonstr configuration
   - Note: This password will only be shown once

3. Configure your account to keep emails after processing (optional):
   - If you want to keep your newsletters in Gmail after LetterMonstr processes them
   - Go to Gmail Settings > Forwarding and POP/IMAP
   - Under "IMAP access," ensure IMAP is enabled
   - Choose "Keep Gmail's copy in the Inbox" for the option "When a message is accessed with IMAP"

## Obtaining API Keys

### Anthropic API Key

To get an API key for Claude:

1. Visit [Anthropic's website](https://www.anthropic.com/claude)
2. Click "Get API access" or sign up for an account
3. Follow the signup/login process
4. Once your account is approved, navigate to the API section of your account
5. Generate a new API key
6. Copy the API key for use in LetterMonstr configuration
7. Note: Keep this key secure as it provides access to paid API services

### API Key Configuration

When running `setup_config.py`, you'll be prompted to enter:

1. Your Gmail credentials (email and app password)
2. Your Anthropic API key
3. Other configuration options

Alternatively, you can manually edit the `config/config.yaml` file to update these values:

```yaml
email:
  fetch_email: "your-newsletter-email@example.com"
  password: "your-app-password"
  periodic_fetch: true  # Enable periodic fetching
  fetch_interval_hours: 1
  # other email settings...

llm:
  anthropic_api_key: "your-anthropic-api-key"
  # other LLM settings...
```

## Usage

1. Subscribe to newsletters using your configured Gmail account
2. Run LetterMonstr using `./run_lettermonstr.sh`
3. The system will automatically:
   - If in periodic mode: Fetch and process emails throughout the day
   - If in traditional mode: Fetch and process emails at the scheduled time
4. Newsletters are marked as read in Gmail after successful processing (or after summary is sent, depending on your configuration)
5. Summaries will be delivered to your specified email address at the configured frequency
6. Click on source links in the summary to read full articles on topics of interest
7. You can view summaries directly using `./view_latest_summary.sh`
8. For testing, send a simulated newsletter using `python test_newsletter.py`

## Recent Improvements

Recent updates to LetterMonstr include:

1. **Periodic Email Fetching**: Emails can now be fetched and processed throughout the day for improved reliability
2. **Unified Running Script**: Single `run_lettermonstr.sh` script that adapts to your configuration
3. **Enhanced Status & Monitoring**: Improved status script showing more details about the running process and database
4. **Database Migrations**: Automatic database schema updates to support new features
5. **Source Links**: Summaries include clickable links to the original articles and web versions of newsletters
6. **Gmail Integration**: Processes unread emails and marks them as read after successful processing
7. **Advanced Forwarded Email Handling**: Significantly improved content extraction from forwarded newsletters across multiple email clients
8. **Empty Summary Prevention**: Intelligent detection of empty or meaningless content to prevent sending empty summaries
9. **JSON Serialization Fixes**: Enhanced handling of datetime objects for reliable content storage
10. **Improved Error Handling**: Better handling of database locking and connection issues
11. **Database Reset Tool**: Easily reset the database while maintaining backups
12. **Content Processing Diagnostics**: New tool to diagnose and fix content processing issues

## Troubleshooting

If you encounter issues:

1. Check the application logs:
   - Traditional mode: `data/lettermonstr.log` and `data/lettermonstr_runner.log`
   - Periodic mode: `data/lettermonstr_periodic.log` and `data/lettermonstr_periodic_runner.log`
2. Run `./status_lettermonstr.sh` to see process status and database information
3. Ensure you're running on a supported macOS version (10.15 Catalina or later)
4. Verify that Python 3.9+ is installed and accessible via `python3` command
5. Check that your Gmail App Password is correct and 2-Step Verification is enabled
6. Verify that your Anthropic API key is valid and has sufficient credits
7. Make sure all dependencies are installed correctly with `pip3 install -r requirements.txt`
8. If the application crashes or fails to process emails, try stopping and restarting it:

   ```bash
   ./stop_lettermonstr.sh
   ./run_lettermonstr.sh
   ```

### Debug Mode

For more detailed diagnostic information, LetterMonstr includes a debug mode:

```bash
./run_lettermonstr_debug.sh
```

This script:

- Runs the application in the foreground (not as a background process)
- Displays more verbose output for troubleshooting
- Shows Python environment details and import diagnostics
- Provides real-time console output without having to check log files

Use debug mode when you need to troubleshoot startup issues or want to monitor the application's behavior in real-time.

### No Summaries Being Sent

1. Check that you have new unread emails in the configured email account
2. Verify your Gmail API is properly set up and credentials are valid
3. Run `./status_lettermonstr.sh` to check if the process is running and if there are unsummarized content items
4. Check logs in `data/lettermonstr_periodic_runner.log` for any errors
5. Ensure your summary schedule in `config.json` is correct (default is daily at 17:00)
6. Try forcing a summary with `./force_summary.sh` to see if it generates and sends

### Empty or Missing Content in Summaries

1. Forwarded newsletters may not be parsed correctly if they use uncommon formatting
2. LetterMonstr will not send completely empty summaries (this is by design)
3. Check `data/lettermonstr_periodic_runner.log` for warnings about content extraction failures
4. Different email clients format forwarded emails differently; try forwarding from Gmail directly
5. If needed, use `python force_process_unread.py` to reprocess specific emails with improved parsing

### Forwarded Email Handling

LetterMonstr now includes enhanced support for:

- Gmail forwarded newsletters
- Outlook forwarded content
- Apple Mail forwarded messages
- Plain text forwards

If a specific newsletter format isn't being parsed correctly, please submit an issue with a sample of the email format (with personal information removed).

### Common Issues and Solutions

#### Email Processing Issues

If emails are marked as processed but their content isn't being stored:

1. Run the diagnostics tool: `./fix_content_processing.py`
2. Check if there are any JSON serialization errors in the logs
3. Verify that the database isn't locked by another process

#### Database Issues

If you encounter database locking or corruption issues:

1. Stop all LetterMonstr processes: `./stop_lettermonstr.sh`
2. Reset the database (a backup will be created): `./reset_database.py`
3. Restart the application: `./run_lettermonstr.sh`

#### System Date Issues

If you encounter issues related to email fetching dates:

1. Check your system's date and time settings to ensure they're correct
2. Review the `fetch_status.json` file to see the last fetch date
3. Reset the fetch status by editing `data/fetch_status.json` or running the database reset script

### Running on Servers (Unsupported)

LetterMonstr is designed as a personal tool for local Mac use, not as a production service. If you attempt to run it on a server:

- You may encounter permission and security issues
- The application isn't designed for multi-tenant usage
- There are no built-in protections against API key overusage
- The database isn't optimized for high-volume usage
- Service monitoring and self-healing are not implemented

If you need a server-based newsletter aggregation solution, consider adapting this codebase with proper server-oriented modifications or exploring enterprise solutions designed for that purpose.
