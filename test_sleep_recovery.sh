#!/bin/bash
# Test script to verify sleep/wake recovery is working
# This simulates what you should see in the logs after laptop wake

echo "=================================================="
echo "LetterMonster Sleep/Wake Recovery Test"
echo "=================================================="
echo ""

LOG_FILE="data/lettermonstr_periodic.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ Log file not found at $LOG_FILE"
    echo "   Make sure LetterMonster has been run at least once."
    exit 1
fi

echo "📋 Checking recent log entries for sleep/wake events..."
echo ""

# Check for sleep detection
SLEEP_EVENTS=$(grep "SLEEP DETECTED" "$LOG_FILE" | tail -5)
if [ -n "$SLEEP_EVENTS" ]; then
    echo "✓ Found sleep detection events:"
    echo "$SLEEP_EVENTS" | while read line; do echo "  $line"; done
    echo ""
else
    echo "ℹ️  No sleep events detected yet"
    echo "   (This is normal if laptop hasn't slept since starting)"
    echo ""
fi

# Check for network readiness
NETWORK_CHECKS=$(grep "Network is ready\|Network not ready" "$LOG_FILE" | tail -5)
if [ -n "$NETWORK_CHECKS" ]; then
    echo "✓ Network readiness checks:"
    echo "$NETWORK_CHECKS" | while read line; do echo "  $line"; done
    echo ""
fi

# Check for recovery completion
RECOVERY_EVENTS=$(grep "Sleep recovery completed" "$LOG_FILE" | tail -3)
if [ -n "$RECOVERY_EVENTS" ]; then
    echo "✓ Recovery completions:"
    echo "$RECOVERY_EVENTS" | while read line; do echo "  $line"; done
    echo ""
fi

# Check for IMAP connection status
echo "📡 Recent IMAP connection status:"
IMAP_STATUS=$(grep "IMAP connection\|Connecting to imap" "$LOG_FILE" | tail -5)
if [ -n "$IMAP_STATUS" ]; then
    echo "$IMAP_STATUS" | while read line; do echo "  $line"; done
else
    echo "  No recent IMAP connection logs"
fi
echo ""

# Check for recent errors
echo "⚠️  Recent errors (if any):"
RECENT_ERRORS=$(grep -i "error\|failed" "$LOG_FILE" | grep -v "No linter errors" | tail -5)
if [ -n "$RECENT_ERRORS" ]; then
    echo "$RECENT_ERRORS" | while read line; do echo "  $line"; done
else
    echo "  No recent errors ✓"
fi
echo ""

# Check if service is running
echo "🔍 Service status:"
if launchctl list | grep -q "com.lettermonster.periodic"; then
    echo "  ✓ LaunchAgent service is running"
    PID=$(launchctl list | grep lettermonster | awk '{print $1}')
    echo "  Process ID: $PID"
elif ps aux | grep -v grep | grep -q "periodic_runner.py"; then
    echo "  ✓ Running manually (not as LaunchAgent)"
    PID=$(ps aux | grep -v grep | grep "periodic_runner.py" | awk '{print $2}')
    echo "  Process ID: $PID"
else
    echo "  ❌ Not running"
fi
echo ""

echo "=================================================="
echo "Test Complete"
echo "=================================================="
echo ""
echo "To monitor in real-time:"
echo "  tail -f $LOG_FILE"
echo ""
echo "To test sleep recovery:"
echo "  1. Let it run for a minute to see normal operations"
echo "  2. Put your laptop to sleep for 5+ minutes"
echo "  3. Wake it up and check the logs"
echo "  4. You should see sleep detection and recovery messages"
echo ""

