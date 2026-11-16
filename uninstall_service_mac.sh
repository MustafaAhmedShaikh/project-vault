#!/usr/bin/env bash
# Removes the ProjectVault LaunchAgent. Safe to run more than once.
# Does not touch your project files or backups.
set -u

LABEL="com.projectvault.daemon"
PLIST_FILE="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 \
    || { [ -f "$PLIST_FILE" ] && launchctl unload "$PLIST_FILE" >/dev/null 2>&1; } \
    || true
if [ -f "$PLIST_FILE" ]; then
    rm -f "$PLIST_FILE"
    echo "Removed $PLIST_FILE"
else
    echo "No LaunchAgent plist found (already uninstalled)."
fi
echo "ProjectVault LaunchAgent uninstalled. Your files and backups were not touched."
