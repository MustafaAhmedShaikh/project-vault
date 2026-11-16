#!/usr/bin/env bash
# Installs the ProjectVault daemon as a systemd *user* service (no root needed).
# Uninstall with: ./uninstall_service_linux.sh
set -eu

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
UNIT_NAME="projectvault.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/$UNIT_NAME"

die() { echo "ERROR: $*" >&2; exit 1; }

PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || die "python3 was not found on PATH. Install Python 3.9 or newer and re-run."
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || die "Python 3.9 or newer is required (found: $("$PYTHON" -V 2>&1))."
command -v systemctl >/dev/null 2>&1 || die "systemctl was not found. This installer needs systemd."
[ -f "$DIR/vault_daemon.py" ] || die "vault_daemon.py not found in $DIR."

# systemd treats unquoted spaces as argument separators; reject characters we cannot escape safely.
case "$DIR$PYTHON" in
    *'"'*|*'%'*|*$'\n'*) die "Path contains a quote, percent sign or newline, which systemd units cannot hold safely." ;;
esac

mkdir -p "$UNIT_DIR" "$DIR/backups"

cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=ProjectVault backup daemon
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart="$PYTHON" "$DIR/vault_daemon.py"
Restart=on-failure
RestartSec=60

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable "$UNIT_NAME"
systemctl --user restart "$UNIT_NAME"

echo "ProjectVault service installed and started (user unit: $UNIT_FILE)."
echo
echo "Check status : systemctl --user status $UNIT_NAME"
echo "View logs    : journalctl --user -u $UNIT_NAME   (also: $DIR/backups/vault_daemon.log)"
echo "Uninstall    : \"$DIR/uninstall_service_linux.sh\""
echo
echo "Note: a user service normally runs only while you are logged in."
echo "To start it at boot without logging in, run once:  loginctl enable-linger \"$USER\""
