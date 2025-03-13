#!/bin/bash
# LetterMonstr Runner Script
# This script runs LetterMonstr as a background process

# Configuration
LOG_FILE="data/lettermonstr_runner.log"
PERIODIC_LOG_FILE="data/lettermonstr_periodic_runner.log"
PID_FILE="data/lettermonstr.pid"
PERIODIC_PID_FILE="data/lettermonstr_periodic.pid"

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

# Run database migration if needed
echo "Running database migration..."
python3 src/db_migrate.py

# Check if periodic fetching is enabled in the config
PERIODIC_FETCH=$(python3 -c "
import yaml
try:
    with open('config/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
        print(config.get('email', {}).get('periodic_fetch', False))
except Exception as e:
    print('False')
")

# Check if either process is already running
check_process() {
    local pid_file=$1
    local process_name=$2
    
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if ps -p $PID > /dev/null; then
            echo "$process_name is already running with PID $PID"
            echo "To stop it, run: ./stop_lettermonstr.sh"
            return 1
        else
            echo "Stale PID file found for $process_name. Previous instance may have crashed."
            rm "$pid_file"
            return 0
        fi
    fi
    return 0
}

# Start a process in the background
start_process() {
    local command=$1
    local log_file=$2
    local pid_file=$3
    local process_name=$4
    
    echo "Starting $process_name..."
    # Export PYTHONPATH to ensure Python can find all modules
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    nohup $command > "$log_file" 2>&1 &
    PID=$!
    
    # Store the PID
    echo $PID > "$pid_file"
    echo "$process_name started with PID $PID"
    echo "Logs are available at $log_file"
}

# Main execution
if [ "$PERIODIC_FETCH" = "True" ]; then
    echo "Periodic fetching mode is enabled in config."
    
    # Check if periodic process is already running
    check_process "$PERIODIC_PID_FILE" "LetterMonstr Periodic Fetcher" || exit 0
    
    # Start the periodic runner
    start_process "python3 src/periodic_runner.py" "$PERIODIC_LOG_FILE" "$PERIODIC_PID_FILE" "LetterMonstr Periodic Fetcher"
    
    echo "LetterMonstr is running in periodic fetching mode."
    echo "The system will periodically fetch and process emails throughout the day."
    echo "Summaries will be generated and sent at the scheduled delivery time."
    echo "To check status, run: ./status_lettermonstr.sh"
    echo "To stop, run: ./stop_lettermonstr.sh"
else
    echo "Running in traditional mode (periodic fetching not enabled in config)."
    
    # Check if traditional process is already running
    check_process "$PID_FILE" "LetterMonstr" || exit 0
    
    # Start LetterMonstr in the background (traditional mode)
    start_process "python3 src/main.py" "$LOG_FILE" "$PID_FILE" "LetterMonstr"
    
    echo "LetterMonstr started in traditional mode."
    echo "To check status, run: ./status_lettermonstr.sh"
    echo "To stop, run: ./stop_lettermonstr.sh"
fi 