# LetterMonstr

A personal newsletter aggregator and summarizer that processes email newsletters and generates concise summaries using Claude 3.7 Sonnet.

## Features

- Fetches newsletters from a designated Gmail account
- Follows links within newsletters to gather additional content
- Removes redundant information across similar newsletters
- Filters out advertisements and paid placements
- Summarizes content using Claude 3.7 Sonnet LLM
- Delivers summaries at configurable intervals (daily, weekly, or monthly)

## Requirements

- Python 3.9+
- Gmail account for receiving newsletters
- Gmail App Password (requires 2-Step Verification to be enabled)
- Anthropic API key for Claude access

## Setup

1. Clone this repository
2. Create a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
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
   python3 src/main.py
   ```

## Running as a Service

LetterMonstr includes scripts to manage it as a background service:

### Starting the Service

To run LetterMonstr in the background:

```bash
./run_lettermonstr.sh
```

This script:

- Activates the virtual environment (creates it if needed)
- Checks if configuration exists (runs setup if needed)
- Starts LetterMonstr as a background process
- Saves the process ID for management

### Checking Status

To check if LetterMonstr is running and view recent logs:

```bash
./status_lettermonstr.sh
```

This shows:

- Process status and details
- Recent log entries
- Database statistics (if SQLite is available)

### Stopping the Service

To stop the LetterMonstr service:

```bash
./stop_lettermonstr.sh
```

### Viewing Summaries

To view the most recently generated summary:

```bash
./view_latest_summary.sh
```

This will display:

- Summary metadata (type, date range, delivery status)
- The full content of the most recent summary
- A list of other available summaries

## Testing

### Test Newsletter Generator

For testing the application without waiting for real newsletters, use the test newsletter generator:

```bash
./test_newsletter.py
```

This script:

- Creates a simulated newsletter with random content and links
- Sends it to your configured Gmail account
- Includes test elements like sponsored content for ad filtering tests

The test newsletter will be processed during the next application cycle, or you can manually trigger processing by running `python3 src/main.py`.

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
  - Token limits and temperature

## Project Structure

```text
lettermonstr/
├── config/           # Configuration files
│   ├── config.yaml   # Your personal configuration (gitignored)
│   └── config.template.yaml  # Template for reference
├── data/             # Storage for processed content
├── src/              # Source code
│   ├── email/        # Email fetching and processing
│   ├── crawl/        # Web crawling components
│   ├── summarize/    # LLM summarization logic
│   └── scheduler/    # Scheduling components
├── run_lettermonstr.sh  # Script to run as background service
├── status_lettermonstr.sh # Script to check service status
├── stop_lettermonstr.sh  # Script to stop the service
├── view_latest_summary.sh # Script to view recent summaries
├── test_newsletter.py # Script to generate test newsletters
└── tests/            # Test files
```

## Gmail Setup

To use LetterMonstr with Gmail:

1. Enable 2-Step Verification on your Gmail account:
   - Go to <https://myaccount.google.com/security>
   - Turn on 2-Step Verification

2. Create an App Password:
   - Go to <https://myaccount.google.com/apppasswords>
   - Select "Mail" as the app and name the device "LetterMonstr"
   - Use the generated password in the LetterMonstr configuration

## Usage

1. Subscribe to newsletters using your configured Gmail account
2. LetterMonstr will automatically fetch and process new newsletters
3. Summaries will be delivered to your specified email address at the configured frequency
4. You can view summaries directly using `./view_latest_summary.sh`
5. For testing, send a simulated newsletter using `./test_newsletter.py`

## Troubleshooting

If you encounter issues:

1. Check the application logs in `data/lettermonstr.log`
2. Check the runner logs in `data/lettermonstr_runner.log`
3. Use `./status_lettermonstr.sh` to see the current status
4. Ensure your Gmail App Password is correct
5. Verify that your Anthropic API key is valid
6. On macOS, ensure you use `python3` instead of `python` for all commands
