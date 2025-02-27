#!/bin/bash
# LetterMonstr Status Script
# This script checks the status of LetterMonstr and shows recent logs

# Configuration
PID_FILE="data/lettermonstr.pid"
LOG_FILE="data/lettermonstr_runner.log"
APP_LOG_FILE="data/lettermonstr.log"

# Check process status
check_status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "LetterMonstr is not running (no PID file found)"
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    
    if ps -p $PID > /dev/null; then
        echo "LetterMonstr is running with PID $PID"
        
        # Show process info
        echo "Process details:"
        ps -f -p $PID
        
        # Show how long it's been running
        echo -e "\nRunning since:"
        ps -o lstart= -p $PID
        
        return 0
    else
        echo "LetterMonstr is not running (stale PID file found)"
        echo "Last PID was: $PID"
        return 1
    fi
}

# Show recent logs
show_logs() {
    echo -e "\n--- Recent Runner Logs ---"
    if [ -f "$LOG_FILE" ]; then
        tail -n 20 "$LOG_FILE"
    else
        echo "No runner logs found at $LOG_FILE"
    fi
    
    echo -e "\n--- Recent Application Logs ---"
    if [ -f "$APP_LOG_FILE" ]; then
        tail -n 20 "$APP_LOG_FILE"
    else
        echo "No application logs found at $APP_LOG_FILE"
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
            echo "Latest summaries:"
            sqlite3 -header -column "$DB_FILE" "SELECT id, summary_type, period_start, period_end, sent FROM summaries ORDER BY creation_date DESC LIMIT 3;"
        else
            echo "Install sqlite3 to see database statistics"
        fi
    else
        echo -e "\nNo database file found at $DB_FILE"
    fi
}

# Main execution
echo "LetterMonstr Status Check"
echo "======================="

check_status
status=$?

if [ $status -eq 0 ]; then
    # Show additional info if running
    show_logs
    show_db_info
    
    echo -e "\nTo stop LetterMonstr, run: ./stop_lettermonstr.sh"
else
    # Offer to start if not running
    echo -e "\nTo start LetterMonstr, run: ./run_lettermonstr.sh"
fi 