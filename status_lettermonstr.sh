#!/bin/bash
# LetterMonstr Status Script
# This script checks the status of LetterMonstr and shows recent logs

# Configuration
PID_FILE="data/lettermonstr.pid"
PERIODIC_PID_FILE="data/lettermonstr_periodic.pid"
LOG_FILE="data/lettermonstr_runner.log"
PERIODIC_LOG_FILE="data/lettermonstr_periodic_runner.log"
APP_LOG_FILE="data/lettermonstr.log"
PERIODIC_APP_LOG_FILE="data/lettermonstr_periodic.log"
LAUNCHAGENT_PLIST="$HOME/Library/LaunchAgents/com.lettermonster.periodic.plist"

# Ensure we're in the project directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Check process status
check_process_status() {
    local pid_file=$1
    local process_name=$2
    
    if [ ! -f "$pid_file" ]; then
        echo "$process_name is not running (no PID file found)"
        return 1
    fi
    
    local PID=$(cat "$pid_file")
    
    if ps -p $PID > /dev/null; then
        echo "$process_name is running with PID $PID"
        
        # Show process info
        echo "Process details:"
        ps -f -p $PID
        
        # Show how long it's been running
        echo -e "\nRunning since:"
        ps -o lstart= -p $PID
        
        return 0
    else
        echo "$process_name is not running (stale PID file found)"
        echo "Last PID was: $PID"
        return 1
    fi
}

# Show recent logs
show_logs() {
    local log_file=$1
    local app_log_file=$2
    local name=$3
    
    echo -e "\n--- Recent $name Runner Logs ---"
    if [ -f "$log_file" ]; then
        tail -n 20 "$log_file"
    else
        echo "No runner logs found at $log_file"
    fi
    
    echo -e "\n--- Recent $name Application Logs ---"
    if [ -f "$app_log_file" ]; then
        tail -n 20 "$app_log_file"
    else
        echo "No application logs found at $app_log_file"
    fi
}

# Show database info
show_db_info() {
    DB_FILE="data/lettermonstr.db"
    
    if [ -f "$DB_FILE" ]; then
        echo -e "\n--- Database Information ---"
        echo "Database file: $DB_FILE"
        echo "Size: $(du -h "$DB_FILE" | cut -f1)"
        
        # Check if sqlite3 is available
        if command -v sqlite3 >/dev/null 2>&1; then
            echo -e "\nProcessed emails: $(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM processed_emails;")"
            
            # Check if processed_content table exists
            if sqlite3 "$DB_FILE" ".tables" | grep -q processed_content; then
                echo "Processed content items: $(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM processed_content;")"
                echo "Unsummarized content items: $(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM processed_content WHERE is_summarized=0;")"
            fi
            
            echo "Latest summaries:"
            sqlite3 -header -column "$DB_FILE" "SELECT id, summary_type, period_start, period_end, sent FROM summaries ORDER BY creation_date DESC LIMIT 3;"
        else
            echo "Install sqlite3 to see database statistics"
        fi
    else
        echo -e "\nNo database file found at $DB_FILE"
    fi
}

# Check periodic fetching configuration
is_periodic_enabled() {
    # Check if config file exists
    if [ ! -f "config/config.yaml" ]; then
        echo "Config file not found."
        return 1
    fi
    
    # Use python3 explicitly and check if it's available
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_CMD="python"
    else
        echo "Python command not found. Please make sure Python is installed."
        return 1
    fi
    
    # Check config using the available Python command
    local result=$($PYTHON_CMD -c "
import yaml
try:
    with open('config/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
        print(str(config.get('email', {}).get('periodic_fetch', False)).lower())
except Exception as e:
    print('false')
")
    
    if [ "$result" = "true" ]; then
        return 0
    else
        return 1
    fi
}

# Main execution
echo "LetterMonstr Status Check"
echo "======================="

# Check for LaunchAgent service first
any_running=false
if [ -f "$LAUNCHAGENT_PLIST" ]; then
    if launchctl list | grep -q "com.lettermonster.periodic"; then
        PID=$(launchctl list | grep lettermonster | awk '{print $1}')
        echo "✓ LaunchAgent Service: RUNNING"
        if [ "$PID" != "-" ]; then
            echo "  Process ID: $PID"
            echo "  Running since: $(ps -o lstart= -p $PID 2>/dev/null || echo 'Unknown')"
        fi
        any_running=true
    else
        echo "○ LaunchAgent Service: INSTALLED but not running"
    fi
    echo ""
else
    echo "○ LaunchAgent Service: NOT INSTALLED"
    echo ""
fi

# Check periodic fetching configuration
is_periodic_enabled
periodic_enabled=$?

if [ $periodic_enabled -eq 0 ]; then
    echo "Periodic fetching is enabled in configuration."
    
    echo -e "\n--- Periodic Fetcher Status (PID-based) ---"
    check_process_status "$PERIODIC_PID_FILE" "LetterMonstr Periodic Fetcher"
    periodic_status=$?
    
    if [ $periodic_status -eq 0 ]; then
        any_running=true
        show_logs "$PERIODIC_LOG_FILE" "$PERIODIC_APP_LOG_FILE" "Periodic Fetcher"
    fi
else
    echo "Periodic fetching is not enabled in configuration."
    
    echo -e "\n--- Traditional Process Status ---"
    check_process_status "$PID_FILE" "LetterMonstr"
    traditional_status=$?
    
    if [ $traditional_status -eq 0 ]; then
        any_running=true
        show_logs "$LOG_FILE" "$APP_LOG_FILE" "LetterMonstr"
    fi
fi

# Show database info for both cases
show_db_info

# Provide instructions to user
echo -e "\n=================================================="
if [ "$any_running" = "true" ]; then
    echo "Status: RUNNING"
    echo ""
    echo "To stop: ./stop_lettermonstr.sh"
    if [ -f "$LAUNCHAGENT_PLIST" ]; then
        echo "To restart service: ./restart_service.sh"
    fi
else
    echo "Status: NOT RUNNING"
    echo ""
    echo "To start:"
    echo "  LaunchAgent service: ./install_service.sh"
    echo "  Traditional mode:    ./run_lettermonstr.sh"
fi
echo "==================================================" 