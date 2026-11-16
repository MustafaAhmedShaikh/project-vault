#!/usr/bin/env bash
# Installs the ProjectVault daemon as a macOS LaunchAgent (per-user, no admin needed).
# Uninstall with: ./uninstall_service_mac.sh
set -eu

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
LABEL="com.projectvault.daemon"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/$LABEL.plist"

die() { echo "ERROR: $*" >&2; exit 1; }

PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || die "python3 was not found on PATH. Install Python 3.9 or newer and re-run."
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || die "Python 3.9 or newer is required (found: $("$PYTHON" -V 2>&1))."
[ -f "$DIR/vault_daemon.py" ] || die "vault_daemon.py not found in $DIR."

# Escape XML special characters for the plist.
xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
X_PY="$(xml_escape "$PYTHON")"
X_DIR="$(xml_escape "$DIR")"

mkdir -p "$PLIST_DIR" "$DIR/backups"

cat > "$PLIST_FILE" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$X_PY</string>
        <string>$X_DIR/vault_daemon.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$X_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$X_DIR/backups/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$X_DIR/backups/launchd_stderr.log</string>
</dict>
</plist>
PLIST

UID_NUM="$(id -u)"
# Remove any previous registration first (ignore errors), then register.
launchctl bootout "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || launchctl unload "$PLIST_FILE" >/dev/null 2>&1 || true
if ! launchctl bootstrap "gui/$UID_NUM" "$PLIST_FILE" 2>/dev/null; then
    echo "launchctl bootstrap failed; falling back to 'launchctl load'."
    launchctl load "$PLIST_FILE" || die "Could not load the LaunchAgent."
fi

echo "ProjectVault LaunchAgent installed and started ($PLIST_FILE)."
echo
echo "Check status : launchctl list | grep $LABEL"
echo "Logs         : $DIR/backups/vault_daemon.log (launchd output: $DIR/backups/launchd_stderr.log)"
echo "Uninstall    : \"$DIR/uninstall_service_mac.sh\""
