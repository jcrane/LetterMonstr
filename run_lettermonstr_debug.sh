#!/bin/bash
# LetterMonstr Debug Runner Script
# This script runs LetterMonstr with verbose debug output

# Ensure we're in the project directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Stop any existing process
./stop_lettermonstr.sh 2>/dev/null || true

# Create data directory if it doesn't exist
mkdir -p data

# Check if the virtual environment exists and activate it
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Print Python information
echo "Python executable: $(which python3)"
echo "Python version: $(python3 --version)"
echo "PYTHONPATH before execution: $PYTHONPATH"
echo "sys.path contents:"
python3 -c "import sys; print('\n'.join(sys.path))"

# Try importing email.header module
echo "Testing email.header import..."
python3 -c "from email import header; print('Import successful!')" || echo "Import failed!"

# Run the script directly (not in the background) for better debugging
echo "Running LetterMonstr Periodic Runner..."
python3 src/periodic_runner.py 