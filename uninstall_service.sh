#!/bin/bash
# Uninstall LetterMonster launchd service

set -e

LAUNCHAGENTS_DIR="$HOME/Library/LaunchAgents"
INSTALLED_PLIST="$LAUNCHAGENTS_DIR/com.lettermonster.periodic.plist"

echo "=================================================="
echo "LetterMonster LaunchAgent Uninstallation"
echo "=================================================="
echo ""

# Check if service is installed
if [ ! -f "$INSTALLED_PLIST" ]; then
    echo "❌ Service is not installed"
    exit 1
fi

# Unload the service
if launchctl list | grep -q "com.lettermonster.periodic"; then
    echo "Stopping service..."
    launchctl unload "$INSTALLED_PLIST"
else
    echo "Service is not currently running"
fi

# Remove plist file
echo "Removing service file..."
rm "$INSTALLED_PLIST"

echo ""
echo "✓ LetterMonster service uninstalled successfully!"
echo ""

