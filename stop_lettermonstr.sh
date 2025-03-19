#!/bin/bash
# LetterMonstr Stop Script
# This script stops running LetterMonstr processes

# Configuration
PID_FILE="data/lettermonstr.pid"
PERIODIC_PID_FILE="data/lettermonstr_periodic.pid"

# Function to stop a process
stop_process() {
    local pid_file=$1
    local process_name=$2
    
    # Check if PID file exists
    if [ ! -f "$pid_file" ]; then
        echo "$process_name is not running (no PID file found)"
        return 0
    fi
    
    # Read the PID
    local PID=$(cat "$pid_file")
    
    # Check if process is running
    if ps -p $PID > /dev/null; then
        echo "Stopping $process_name (PID: $PID)..."
        kill $PID
        
        # Wait for process to terminate
        for i in {1..10}; do
            if ! ps -p $PID > /dev/null; then
                break
            fi
            echo "Waiting for $process_name to stop..."
            sleep 1
        done
        
        # Force kill if still running
        if ps -p $PID > /dev/null; then
            echo "$process_name is not responding. Force killing..."
            kill -9 $PID
        fi
        
        # Remove PID file
        rm "$pid_file"
        echo "$process_name stopped successfully"
    else
        echo "No running $process_name found with PID $PID"
        echo "Removing stale PID file"
        rm "$pid_file"
    fi
}

# Stop both processes
echo "Checking for running LetterMonstr processes..."

# Stop the traditional process if running
stop_process "$PID_FILE" "LetterMonstr"

# Stop the periodic process if running
stop_process "$PERIODIC_PID_FILE" "LetterMonstr Periodic Fetcher"

echo "All LetterMonstr processes have been stopped." 