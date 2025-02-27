#!/bin/bash
# LetterMonstr Stop Script
# This script stops a running LetterMonstr process

# Configuration
PID_FILE="data/lettermonstr.pid"

# Check if PID file exists
if [ ! -f "$PID_FILE" ]; then
    echo "LetterMonstr is not running (no PID file found)"
    exit 0
fi

# Read the PID
PID=$(cat "$PID_FILE")

# Check if process is running
if ps -p $PID > /dev/null; then
    echo "Stopping LetterMonstr (PID: $PID)..."
    kill $PID
    
    # Wait for process to terminate
    for i in {1..10}; do
        if ! ps -p $PID > /dev/null; then
            break
        fi
        echo "Waiting for LetterMonstr to stop..."
        sleep 1
    done
    
    # Force kill if still running
    if ps -p $PID > /dev/null; then
        echo "LetterMonstr is not responding. Force killing..."
        kill -9 $PID
    fi
    
    # Remove PID file
    rm "$PID_FILE"
    echo "LetterMonstr stopped successfully"
else
    echo "No running LetterMonstr process found with PID $PID"
    echo "Removing stale PID file"
    rm "$PID_FILE"
fi 