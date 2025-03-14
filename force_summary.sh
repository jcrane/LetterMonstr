#!/bin/bash
# Force Process and Generate Summary Script for LetterMonstr
# This script forces the processing of unread emails and immediately generates a summary

# Change to the directory where the script is located
cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Add script directory to PYTHONPATH
SCRIPT_DIR="$(pwd)"
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Check if LetterMonstr is running and store the state
WAS_RUNNING=0
echo "Checking if LetterMonstr is running..."
if pgrep -f "src/periodic_runner.py" > /dev/null || pgrep -f "src/main.py" > /dev/null; then
    echo "LetterMonstr is currently running."
    echo "Temporarily stopping LetterMonstr for clean processing..."
    WAS_RUNNING=1
    ./stop_lettermonstr.sh
    sleep 2
else
    echo "LetterMonstr is not currently running."
fi

# Run the force process script to process unread emails
echo "Step 1: Processing unread emails..."
python3 ./force_process_unread.py

echo "Step 2: Generating and sending summary..."
python3 ./send_pending_summaries.py

echo "Force summary process completed!"

# Restart LetterMonstr if it was running before
if [ $WAS_RUNNING -eq 1 ]; then
    echo "Restarting LetterMonstr to resume normal operation..."
    ./run_lettermonstr.sh
    echo "LetterMonstr has been restarted."
else
    echo "LetterMonstr was not running before, so it remains stopped."
fi

# Deactivate virtual environment if it was activated
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Deactivating virtual environment..."
    deactivate
fi 