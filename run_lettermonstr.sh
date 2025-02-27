#!/bin/bash
# LetterMonstr Runner Script
# This script runs LetterMonstr as a background process

# Configuration
LOG_FILE="data/lettermonstr_runner.log"
PID_FILE="data/lettermonstr.pid"

# Create data directory if it doesn't exist
mkdir -p data

# Ensure we're in the project directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if the virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Check if configuration exists
if [ ! -f "config/config.yaml" ]; then
    echo "Configuration file not found. Running setup script..."
    python3 setup_config.py
    
    # If setup failed, exit
    if [ $? -ne 0 ]; then
        echo "Configuration setup failed. Exiting."
        exit 1
    fi
fi

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null; then
        echo "LetterMonstr is already running with PID $PID"
        echo "To stop it, run: kill $PID"
        exit 0
    else
        echo "Stale PID file found. Previous instance may have crashed."
        rm "$PID_FILE"
    fi
fi

# Start LetterMonstr in the background
echo "Starting LetterMonstr..."
nohup python3 src/main.py > "$LOG_FILE" 2>&1 &
PID=$!

# Store the PID
echo $PID > "$PID_FILE"
echo "LetterMonstr started with PID $PID"
echo "Logs are available at $LOG_FILE"
echo "To stop the process, run: kill $PID" 