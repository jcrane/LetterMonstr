#!/bin/bash
# Restart LetterMonster launchd service

LAUNCHAGENTS_DIR="$HOME/Library/LaunchAgents"
INSTALLED_PLIST="$LAUNCHAGENTS_DIR/com.lettermonster.periodic.plist"

echo "=================================================="
echo "LetterMonster Service Restart"
echo "=================================================="
echo ""

# Check if service is installed
if [ ! -f "$INSTALLED_PLIST" ]; then
    echo "❌ Service is not installed. Run ./install_service.sh first"
    exit 1
fi

# Unload the service
if launchctl list | grep -q "com.lettermonster.periodic"; then
    echo "Stopping service..."
    launchctl unload "$INSTALLED_PLIST"
    sleep 2
fi

# Reload the service
echo "Starting service..."
launchctl load "$INSTALLED_PLIST"

echo ""
echo "✓ Service restarted successfully!"
echo ""
echo "Check status: launchctl list | grep lettermonster"
echo "View logs:    tail -f $(pwd)/data/lettermonstr_periodic.log"
echo ""

