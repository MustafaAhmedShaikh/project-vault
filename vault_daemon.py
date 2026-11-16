"""
ProjectVault - background daemon.

Keeps running in the background and, every 30 seconds, decides whether a backup is due:

  * Scheduled: once per day at BACKUP_SCHEDULE_HOUR (``HH:MM``, local time). If the
    machine was off or asleep at that time, the backup runs as soon as the daemon
    notices ("catch-up"), because the decision is "has today's time passed and has
    no backup run today?", not "is it exactly 02:00?".
  * On demand: create a file named ``TRIGGER_BACKUP`` in the workspace.

If a backup fails, you get ONE failure alert for that episode (not one every 30
seconds). The daemon retries after RETRY_SECONDS and sends a normal alert once a
backup succeeds again. Only one daemon runs at a time (a localhost port acts as the
lock; set VAULT_DAEMON_PORT if the default clashes with something else).

Log file: ``backups/vault_daemon.log`` (rotated at about 1 MB, one old copy kept).
Importing this module has no side effects.
"""

import os
import socket
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import vault_backup  # noqa: E402
from vault_backup import dispatch_alerts, get_config, run_atomic_backup  # noqa: E402

CHECK_INTERVAL_SECONDS = 30
RETRY_SECONDS = 30 * 60          # wait this long before retrying a failed scheduled backup
MAX_LOG_BYTES = 1_000_000


# --------------------------------------------------------------------------
# Pure decision logic (easy to test)
# --------------------------------------------------------------------------

def should_run_backup(now: datetime, last_backup: Optional[datetime], schedule: Tuple[int, int],
                      run_if_never: bool = True) -> bool:
    """Should a scheduled backup run right now?

    True when today's scheduled time has passed and no backup has run today
    (``last_backup`` is the manifest's ``last_backup_at``). With ``run_if_never``,
    a workspace that has never been backed up gets its first backup immediately
    instead of waiting for the next scheduled time.
    """
    scheduled_today = now.replace(hour=schedule[0], minute=schedule[1], second=0, microsecond=0)
    if last_backup is None:
        return run_if_never or now >= scheduled_today
    return now >= scheduled_today and last_backup.date() < now.date()


def retry_due(now_ts: float, last_attempt_ts: Optional[float], retry_seconds: float = RETRY_SECONDS) -> bool:
    """True if enough time has passed since the last (failed) attempt."""
    return last_attempt_ts is None or now_ts - last_attempt_ts >= retry_seconds


def read_last_backup(cfg) -> Optional[datetime]:
    """Time of the last successful backup from the manifest (naive local time), or None."""
    manifest = vault_backup.read_manifest(cfg)
    try:
        ts = datetime.fromisoformat(manifest["last_backup_at"])
    except (TypeError, KeyError, ValueError):
        return None
    if ts.tzinfo is not None:
        ts = ts.astimezone().replace(tzinfo=None)
    return ts


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

def log_path(cfg) -> Path:
    return cfg.backup_dir / "vault_daemon.log"


def rotate_log(path: Path, max_bytes: Optional[int] = None) -> None:
    """If the log is larger than ``max_bytes``, move it to ``<name>.1`` (replacing the old one)."""
    limit = MAX_LOG_BYTES if max_bytes is None else max_bytes
    try:
        if path.exists() and path.stat().st_size > limit:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {vault_backup.redact(str(msg))}\n"
    try:
        print(line, end="", flush=True)
    except (UnicodeEncodeError, OSError):
        pass
    try:
        path = log_path(get_config())
        path.parent.mkdir(parents=True, exist_ok=True)
        rotate_log(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # logging must never crash the daemon


# --------------------------------------------------------------------------
# Daemon
# --------------------------------------------------------------------------

def ensure_single_instance(port: int) -> socket.socket:
    """Bind a localhost port as a lock. Exits quietly if another daemon already holds it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        return s
    except OSError:
        print(f"[Vault Daemon] Another instance is already running (port {port}). Exiting.", flush=True)
        sys.exit(0)


class DaemonState:
    def __init__(self):
        self.failing = False                      # inside a failure episode?
        self.last_attempt: Optional[float] = None  # time.time() of last scheduled attempt


def tick(state: DaemonState, now: Optional[datetime] = None, now_ts: Optional[float] = None) -> None:
    """One 30-second check: handle the on-demand trigger, then the schedule."""
    cfg = get_config()
    now = now or datetime.now()
    now_ts = time.time() if now_ts is None else now_ts

    trigger = cfg.workspace / "TRIGGER_BACKUP"
    if trigger.exists():
        try:
            trigger.unlink()
        except OSError:
            pass
        log("On-demand backup requested via TRIGGER_BACKUP file.")
        ok = run_atomic_backup(reason="On-demand (TRIGGER_BACKUP file)", alert_on_failure=True)
        state.failing = not ok
        return

    if should_run_backup(now, read_last_backup(cfg), cfg.schedule) and retry_due(now_ts, state.last_attempt):
        log("Backup is due. Running scheduled backup...")
        state.last_attempt = now_ts
        # Alert about a failure only the first time in an episode.
        ok = run_atomic_backup(reason=f"Scheduled ({cfg.schedule[0]:02d}:{cfg.schedule[1]:02d} local time)",
                               alert_on_failure=not state.failing)
        state.failing = not ok
        if not ok:
            log(f"Backup failed; will retry in {RETRY_SECONDS // 60} minutes (no further alerts until it succeeds).")


def run_daemon_loop() -> None:
    cfg = get_config()
    lock = ensure_single_instance(cfg.port)  # keep a reference so the socket stays open
    vault_backup.set_logger(log)
    log(f"=== ProjectVault daemon started (workspace {cfg.workspace}, "
        f"schedule {cfg.schedule[0]:02d}:{cfg.schedule[1]:02d} local time) ===")
    for w in cfg.warnings:
        log(f"[Config] {w}")
    dispatch_alerts("ProjectVault daemon started. Monitoring " + str(cfg.workspace), title="ProjectVault")

    state = DaemonState()
    while True:
        try:
            tick(state)
        except Exception as e:
            log(f"Daemon error: {type(e).__name__}: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)
    lock.close()  # pragma: no cover


def main() -> None:
    run_daemon_loop()


if __name__ == "__main__":
    main()
