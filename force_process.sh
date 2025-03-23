#!/bin/bash
# Force Process Unread Emails Script for LetterMonstr

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

# Run the force process script
echo "Running Force Process Unread Emails script..."
python3 ./utils/email_tools/force_process_unread.py

# Deactivate virtual environment if it was activated
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Deactivating virtual environment..."
    deactivate
fi 