#!/bin/bash
# Force Process Unread Emails Script for LetterMonstr

# Change to the directory where the script is located
cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Run the force process script
echo "Running Force Process Unread Emails script..."
python force_process_unread.py

# Deactivate virtual environment if it was activated
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Deactivating virtual environment..."
    deactivate
fi 