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

## Requirements

- macOS (10.15 Catalina or later recommended)
- Python 3.9+
- Gmail account for receiving newsletters
- Gmail App Password (requires 2-Step Verification to be enabled)
- Anthropic API key for Claude access

## Setup

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
   python3 src/main.py
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

## Sleep & Restart Behavior

- When your Mac goes to sleep, LetterMonstr will be suspended
- Upon wake, LetterMonstr will resume automatically
- If your Mac is rebooted, you'll need to manually restart LetterMonstr
- Your configuration and processed emails will be maintained between restarts

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
  - Token limits and temperature (increase max_tokens for longer summaries)

### Customizing Summaries

You can customize the summaries generated by LetterMonstr by modifying:

1. **Token Length**: Increase `max_tokens` in the LLM settings section for longer, more detailed summaries
2. **Source Links**: By default, the system includes source links for each major topic to allow further reading
3. **Summary Style**: Edit the prompt in `src/summarize/generator.py` to change the style and format of summaries

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
  fetch_email: "your-newsletter-email@gmail.com"
  password: "your-app-password"
  # other email settings...

llm:
  anthropic_api_key: "your-anthropic-api-key"
  # other LLM settings...
```

## Usage

1. Subscribe to newsletters using your configured Gmail account
2. LetterMonstr will automatically fetch and process unread newsletters
3. Newsletters are marked as read in Gmail after successful processing
4. Summaries will be delivered to your specified email address at the configured frequency
5. Click on source links in the summary to read full articles on topics of interest
6. You can view summaries directly using `./view_latest_summary.sh`
7. For testing, send a simulated newsletter using `./test_newsletter.py`

## Recent Improvements

Recent updates to LetterMonstr include:

1. **Source Links**: Summaries now include clickable links to the original articles and web versions of newsletters, allowing you to dive deeper into topics of interest
2. **Gmail Integration**: The app now processes unread emails and marks them as read after successful processing
3. **Improved Content Extraction**: Better handling of forwarded newsletters from Gmail
4. **Enhanced HTML Parsing**: More reliable extraction of content from complex HTML newsletters
5. **Database Optimization**: Better tracking of processed emails to prevent duplication

## Troubleshooting

If you encounter issues:

1. Check the application logs in `data/lettermonstr.log`
2. Ensure you're running on a supported macOS version (10.15 Catalina or later)
3. Verify that Python 3.9+ is installed and accessible via `python3` command
4. Check that your Gmail App Password is correct and 2-Step Verification is enabled
5. Verify that your Anthropic API key is valid and has sufficient credits
6. Make sure all dependencies are installed correctly with `pip3 install -r requirements.txt`
7. If the application crashes or fails to process emails, try restarting it

### Running on Servers (Unsupported)

LetterMonstr is designed as a personal tool for local Mac use, not as a production service. If you attempt to run it on a server:

- You may encounter permission and security issues
- The application isn't designed for multi-tenant usage
- There are no built-in protections against API key overusage
- The database isn't optimized for high-volume usage
- Service monitoring and self-healing are not implemented

If you need a server-based newsletter aggregation solution, consider adapting this codebase with proper server-oriented modifications or exploring enterprise solutions designed for that purpose.
