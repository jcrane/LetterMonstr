#!/bin/bash
# Install LetterMonster as a macOS launchd service
# This provides automatic restart and better wake-from-sleep handling

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLIST_FILE="$SCRIPT_DIR/com.lettermonster.periodic.plist"
LAUNCHAGENTS_DIR="$HOME/Library/LaunchAgents"
INSTALLED_PLIST="$LAUNCHAGENTS_DIR/com.lettermonster.periodic.plist"

echo "=================================================="
echo "LetterMonster LaunchAgent Installation"
echo "=================================================="
echo ""

# Check if plist file exists
if [ ! -f "$PLIST_FILE" ]; then
    echo "❌ Error: $PLIST_FILE not found"
    exit 1
fi

# Create LaunchAgents directory if it doesn't exist
if [ ! -d "$LAUNCHAGENTS_DIR" ]; then
    echo "Creating LaunchAgents directory..."
    mkdir -p "$LAUNCHAGENTS_DIR"
fi

# Unload existing service if running
if launchctl list | grep -q "com.lettermonster.periodic"; then
    echo "Stopping existing service..."
    launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true
fi

# Copy plist to LaunchAgents
echo "Installing service..."
cp "$PLIST_FILE" "$INSTALLED_PLIST"

# Load the service
echo "Starting service..."
launchctl load "$INSTALLED_PLIST"

echo ""
echo "✓ LetterMonster service installed successfully!"
echo ""
echo "The service will:"
echo "  • Start automatically at login"
echo "  • Restart automatically if it crashes"
echo "  • Attempt to restart after system wake"
echo ""
echo "Useful commands:"
echo "  Check status:    launchctl list | grep lettermonster"
echo "  View logs:       tail -f $SCRIPT_DIR/data/lettermonstr_periodic.log"
echo "  Uninstall:       ./uninstall_service.sh"
echo ""

