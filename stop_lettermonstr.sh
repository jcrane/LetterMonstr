#!/bin/bash
# LetterMonstr Stop Script
# This script stops running LetterMonstr processes (both traditional and LaunchAgent)

# Configuration
PID_FILE="data/lettermonstr.pid"
PERIODIC_PID_FILE="data/lettermonstr_periodic.pid"
LAUNCHAGENT_PLIST="$HOME/Library/LaunchAgents/com.lettermonster.periodic.plist"

# Function to stop a process
stop_process() {
    local pid_file=$1
    local process_name=$2
    
    # Check if PID file exists
    if [ ! -f "$pid_file" ]; then
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
        echo "✓ $process_name stopped"
    else
        # Remove stale PID file
        rm "$pid_file"
    fi
}

echo "=================================================="
echo "Stopping LetterMonstr"
echo "=================================================="
echo ""

# Check for LaunchAgent service first
if [ -f "$LAUNCHAGENT_PLIST" ]; then
    if launchctl list | grep -q "com.lettermonster.periodic"; then
        echo "Stopping LaunchAgent service..."
        launchctl unload "$LAUNCHAGENT_PLIST"
        echo "✓ LaunchAgent service stopped"
        echo ""
        echo "Note: To permanently remove the service, run: ./uninstall_service.sh"
    fi
fi

# Stop PID-based processes
pid_based_stopped=false

if [ -f "$PID_FILE" ] || [ -f "$PERIODIC_PID_FILE" ]; then
    echo "Checking for PID-based processes..."
    
    # Stop the traditional process if running
    if [ -f "$PID_FILE" ]; then
        stop_process "$PID_FILE" "LetterMonstr (traditional mode)"
        pid_based_stopped=true
    fi
    
    # Stop the periodic process if running
    if [ -f "$PERIODIC_PID_FILE" ]; then
        stop_process "$PERIODIC_PID_FILE" "LetterMonstr (periodic mode)"
        pid_based_stopped=true
    fi
fi

# Check for any remaining Python processes
remaining=$(ps aux | grep -E "periodic_runner.py|src/main.py" | grep -v grep | awk '{print $2}')
if [ -n "$remaining" ]; then
    echo ""
    echo "⚠️  Warning: Found additional LetterMonstr processes:"
    ps aux | grep -E "periodic_runner.py|src/main.py" | grep -v grep | awk '{print "  PID " $2 ": " $11 " " $12 " " $13}'
    echo ""
    read -p "Kill these processes? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for pid in $remaining; do
            echo "Killing process $pid..."
            kill $pid 2>/dev/null || kill -9 $pid 2>/dev/null
        done
        echo "✓ Additional processes stopped"
    fi
fi

echo ""
echo "✓ All LetterMonstr processes have been stopped." 