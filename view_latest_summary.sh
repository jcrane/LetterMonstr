#!/bin/bash
# LetterMonstr Summary Viewer
# This script displays the most recent summary from the database

# Configuration
DB_FILE="data/lettermonstr.db"

# Check if database exists
if [ ! -f "$DB_FILE" ]; then
    echo "Database file not found at $DB_FILE"
    echo "No summaries available yet."
    exit 1
fi

# Check if sqlite3 is available
if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "Error: sqlite3 command not found"
    echo "Please install SQLite to use this script"
    exit 1
fi

# Get summary count
SUMMARY_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM summaries;")

if [ "$SUMMARY_COUNT" -eq 0 ]; then
    echo "No summaries found in the database."
    exit 0
fi

echo "LetterMonstr Latest Summary"
echo "=========================="
echo

# Show summary metadata
echo "--- Summary Information ---"
sqlite3 -header -column "$DB_FILE" "SELECT id, summary_type, period_start, period_end, sent, sent_date FROM summaries ORDER BY creation_date DESC LIMIT 1;"
echo

# Display the actual summary text
echo "--- Summary Content ---"
echo
sqlite3 "$DB_FILE" "SELECT summary_text FROM summaries ORDER BY creation_date DESC LIMIT 1;" | sed 's/\\n/\n/g'

# Show options to view older summaries
echo
echo "To view a different summary, use:"
echo "sqlite3 $DB_FILE \"SELECT summary_text FROM summaries WHERE id=<ID>;\""
echo
echo "Available summaries:"
sqlite3 -header -column "$DB_FILE" "SELECT id, summary_type, period_start, period_end FROM summaries ORDER BY creation_date DESC LIMIT 5;" 