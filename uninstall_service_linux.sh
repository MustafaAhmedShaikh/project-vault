#!/usr/bin/env bash
# Removes the ProjectVault systemd user service. Safe to run more than once.
# Does not touch your project files or backups.
set -u

UNIT_NAME="projectvault.service"
UNIT_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$UNIT_NAME"

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop "$UNIT_NAME" >/dev/null 2>&1 || true
    systemctl --user disable "$UNIT_NAME" >/dev/null 2>&1 || true
fi
if [ -f "$UNIT_FILE" ]; then
    rm -f "$UNIT_FILE"
    echo "Removed $UNIT_FILE"
else
    echo "No unit file found (already uninstalled)."
fi
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
fi
echo "ProjectVault service uninstalled. Your files and backups were not touched."
