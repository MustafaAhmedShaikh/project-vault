"""
ProjectVault - backup engine.

Creates ONE verified zip of your project folder (``backups/Master_Backup.zip``),
optionally mirrors it to Google Drive or an S3-compatible bucket, and can send
Telegram / ntfy notifications. Standard library only; cloud SDKs are optional
and imported lazily.

Usage (run from anywhere; the project folder is the folder containing this file,
or ``WORKSPACE_DIR``):

    python vault_backup.py               # run a backup now
    python vault_backup.py --status      # show the last backup and configuration
    python vault_backup.py --verify      # re-check the archive against the manifest
    python vault_backup.py --test-alert  # send a test Telegram / ntfy message
    python vault_backup.py --test-cloud  # upload the current archive to the cloud target

How a backup works:
  1. Files are written to ``Master_Backup.zip.tmp`` (secrets and junk excluded).
  2. The temp archive is verified (zip CRC test + file count + SHA-256).
  3. Only then is it moved into place with ``os.replace``; the previous archive
     is never deleted before the new one is verified and in place.
  4. If STORAGE_TARGET asks for it, the archive is uploaded to the cloud. A cloud
     failure does NOT fail the local backup; it is recorded in the manifest and
     reported in the alert.

Configuration comes from environment variables, optionally loaded from a ``.env``
file next to this script (real environment variables always win). See
``.env.example``. Importing this module has no side effects.
"""

import argparse
import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

__version__ = "0.1.0"

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
MASTER_NAME = "Master_Backup.zip"
MANIFEST_NAME = "MANIFEST_VAULT.json"
IGNORE_FILE_NAME = ".vaultignore"

# Directories that are never backed up (matched by exact name at any depth).
EXCLUDED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "backups",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
}
# File name patterns that are never backed up (junk and generated files).
EXCLUDED_FILE_PATTERNS = [
    "*.pyc", "*.pyo", "*.tmp", "*.crdownload", "*.bak", "*.zip", "*.log",
    "TRIGGER_BACKUP",
]
# Likely secrets: skipped unless BACKUP_INCLUDE_SECRETS=true.
SECRET_FILE_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "credentials*.json",
    "*service_account*.json", "id_rsa*", "*.p12",
]
SECRET_ALLOWED = {".env.example"}

# The ProjectVault scripts themselves (restore will not overwrite these without --force).
SCRIPT_FILES = {
    "vault_backup.py", "vault_daemon.py", "vault_restore.py",
    "gdrive_sync.py", "s3_sync.py",
}

# --------------------------------------------------------------------------
# Logging (the daemon swaps in its own logger so everything lands in its log)
# --------------------------------------------------------------------------

_logger: Optional[Callable[[str], None]] = None


def set_logger(fn: Optional[Callable[[str], None]]) -> None:
    """Route this module's log lines through ``fn`` (None restores print)."""
    global _logger
    _logger = fn


_SECRET_ENV_NAMES = ("TELEGRAM_BOT_TOKEN", "S3_SECRET_KEY", "S3_ACCESS_KEY")
_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


def redact(text: str) -> str:
    """Mask configured secrets and anything that looks like a Telegram bot token."""
    for name in _SECRET_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if len(value) >= 6:
            text = text.replace(value, "***")
    return _TOKEN_RE.sub("***", text)


def log(msg: str) -> None:
    msg = redact(str(msg))
    if _logger is not None:
        _logger(msg)
        return
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:  # e.g. legacy Windows consoles
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

_ENV_LOADED = False


def parse_env_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse one ``.env`` line into (key, value); None for blanks/comments/bad lines.

    Supports ``export KEY=value``, single/double quotes, and inline comments
    (whitespace followed by ``#``) on unquoted values.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if re.match(r"export\s", line):
        line = line[6:].lstrip()
    if "=" not in line:
        return None
    key, raw = line.split("=", 1)
    key = key.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return None
    raw = raw.lstrip()
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        value = raw[1:end] if end != -1 else raw[1:]
    else:
        value = re.split(r"\s+#", " " + raw, maxsplit=1)[0].strip()
    return key, value


def load_env(path: Optional[Path] = None) -> List[str]:
    """Load a ``.env`` file into ``os.environ`` WITHOUT overriding existing variables.

    Returns the names that were set. Never raises on bad lines or a missing file.
    """
    path = Path(path) if path else ENV_FILE
    applied: List[str] = []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return applied
    for line in text.splitlines():
        try:
            parsed = parse_env_line(line)
        except Exception:
            parsed = None
        if parsed and parsed[0] not in os.environ:
            os.environ[parsed[0]] = parsed[1]
            applied.append(parsed[0])
    return applied


def _env(name: str, default: str = "") -> str:
    """Read an env var; unset or blank counts as 'not set'."""
    value = os.environ.get(name, "").strip()
    return value if value else default


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def parse_schedule(text: str) -> Optional[Tuple[int, int]]:
    """Parse 'HH:MM' (or just 'H') into (hour, minute); None if invalid."""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    return hour, minute


@dataclass
class Config:
    workspace: Path
    storage_target: str = "local"
    schedule: Tuple[int, int] = (2, 0)
    keep: int = 1
    exclude: List[str] = field(default_factory=list)
    include_secrets: bool = False
    port: int = 58745
    warnings: List[str] = field(default_factory=list)

    @property
    def backup_dir(self) -> Path:
        return self.workspace / "backups"

    @property
    def master_zip(self) -> Path:
        return self.backup_dir / MASTER_NAME

    @property
    def manifest_file(self) -> Path:
        return self.backup_dir / MANIFEST_NAME


def get_config() -> Config:
    """Read configuration from the environment (loading ``.env`` once per process)."""
    global _ENV_LOADED
    if not _ENV_LOADED:
        load_env()
        _ENV_LOADED = True

    warnings: List[str] = []
    ws = _env("WORKSPACE_DIR")
    workspace = Path(ws).expanduser().resolve() if ws else SCRIPT_DIR

    schedule = (2, 0)
    raw = _env("BACKUP_SCHEDULE_HOUR", "02:00")
    parsed = parse_schedule(raw)
    if parsed:
        schedule = parsed
    else:
        warnings.append(f"BACKUP_SCHEDULE_HOUR={raw!r} is not HH:MM; using 02:00")

    keep = 1
    raw = _env("BACKUP_KEEP", "1")
    try:
        keep = int(raw)
        if keep < 1:
            raise ValueError
    except ValueError:
        keep = 1
        warnings.append(f"BACKUP_KEEP={raw!r} is not an integer >= 1; using 1")

    port = 58745
    raw = _env("VAULT_DAEMON_PORT", "58745")
    try:
        port = int(raw)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        port = 58745
        warnings.append(f"VAULT_DAEMON_PORT={raw!r} is invalid; using 58745")

    return Config(
        workspace=workspace,
        storage_target=_env("STORAGE_TARGET", "local").lower(),
        schedule=schedule,
        keep=keep,
        exclude=[p.strip() for p in _env("BACKUP_EXCLUDE").split(",") if p.strip()],
        include_secrets=_truthy(_env("BACKUP_INCLUDE_SECRETS", "false")),
        port=port,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------

def telegram_configured() -> bool:
    return bool(_env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"))


def ntfy_configured() -> bool:
    return bool(_env("NTFY_TOPIC"))


def send_telegram_alert(message: str) -> bool:
    """Send a plain-text Telegram message via the normal, TLS-verified API host."""
    token, chat_id = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message[:4000],  # Telegram's limit is 4096 characters
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        headers={"User-Agent": f"ProjectVault/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:  # never log the URL: it contains the token
        log(f"[Alert] Telegram failed: {type(e).__name__}")
        return False


def send_ntfy_alert(message: str, title: str = "ProjectVault", priority: str = "default") -> bool:
    """Send a push notification through ntfy (default server https://ntfy.sh)."""
    topic = _env("NTFY_TOPIC")
    if not topic:
        return False
    server = _env("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    if urllib.parse.urlparse(server).scheme not in ("http", "https"):
        log("[Alert] ntfy failed: NTFY_SERVER must start with http:// or https://")
        return False
    failed = message.startswith("FAILED")
    req = urllib.request.Request(
        f"{server}/{urllib.parse.quote(topic, safe='')}",
        data=message.encode("utf-8"),
        headers={
            "Title": title.encode("ascii", "replace").decode("ascii"),
            "Priority": priority,
            "Tags": "warning" if failed else "package",
            "User-Agent": f"ProjectVault/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        log(f"[Alert] ntfy failed: {type(e).__name__}")
        return False


def dispatch_alerts(message: str, title: str = "ProjectVault", priority: str = "default") -> Dict[str, Optional[bool]]:
    """Send ``message`` to every configured channel. Value None = channel not configured."""
    message = redact(message)
    return {
        "telegram": send_telegram_alert(message) if telegram_configured() else None,
        "ntfy": send_ntfy_alert(message, title=title, priority=priority) if ntfy_configured() else None,
    }


# --------------------------------------------------------------------------
# What goes into the archive
# --------------------------------------------------------------------------

def _norm_pattern(p: str) -> str:
    p = p.strip().replace("\\", "/").lower()
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def _matches_user_pattern(parts: List[str], pattern: str) -> bool:
    """A pattern matches if it fits any single path component or any leading path prefix."""
    if not pattern:
        return False
    for i, comp in enumerate(parts):
        if fnmatch.fnmatchcase(comp, pattern):
            return True
        if fnmatch.fnmatchcase("/".join(parts[: i + 1]), pattern):
            return True
    return False


def should_exclude(rel_path: str, extra_patterns=(), include_secrets: bool = False, is_dir: bool = False) -> bool:
    """Decide whether a path (relative to the workspace) is left out of the backup.

    Matching is by path COMPONENT and file-name pattern, never by substring, so
    ``.gitignore`` and ``my_backups_plan.md`` are kept while ``.git/`` and
    ``backups/`` are skipped.
    """
    parts = [p for p in rel_path.replace("\\", "/").lower().split("/") if p and p != "."]
    if not parts:
        return False
    dirs = parts if is_dir else parts[:-1]
    if any(d in EXCLUDED_DIRS for d in dirs):
        return True
    name = parts[-1]
    if not is_dir:
        if any(fnmatch.fnmatchcase(name, pat.lower()) for pat in EXCLUDED_FILE_PATTERNS):
            return True
        if not include_secrets and name not in SECRET_ALLOWED:
            if any(fnmatch.fnmatchcase(name, pat) for pat in SECRET_FILE_PATTERNS):
                return True
    return any(_matches_user_pattern(parts, _norm_pattern(p)) for p in extra_patterns)


def load_ignore_file(workspace: Path) -> List[str]:
    """Read ``.vaultignore`` (one glob per line, ``#`` comments)."""
    try:
        text = (workspace / IGNORE_FILE_NAME).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def collect_files(cfg: Config) -> List[Tuple[Path, str]]:
    """Walk the workspace and return (absolute path, archive name) for every file to back up."""
    patterns = cfg.exclude + load_ignore_file(cfg.workspace)
    found: List[Tuple[Path, str]] = []
    for root, dirs, files in os.walk(cfg.workspace):  # symlinked dirs are not followed
        rel_root = os.path.relpath(root, cfg.workspace)
        rel_root = "" if rel_root == "." else rel_root.replace(os.sep, "/")
        dirs[:] = sorted(
            d for d in dirs
            if not should_exclude(f"{rel_root}/{d}".lstrip("/"), patterns, cfg.include_secrets, is_dir=True)
        )
        for f in sorted(files):
            rel = f"{rel_root}/{f}".lstrip("/")
            if os.path.islink(os.path.join(root, f)):
                continue  # symlinks are not followed (they could point outside the project)
            if not should_exclude(rel, patterns, cfg.include_secrets):
                found.append((Path(root) / f, rel))
    return found


# --------------------------------------------------------------------------
# Archive creation, verification, rotation
# --------------------------------------------------------------------------

def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_archive(path: Path, expected_files: Optional[int] = None, expected_sha: Optional[str] = None) -> Optional[str]:
    """Check an archive. Returns None if it is good, otherwise a short error message."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()
            if bad:
                return f"corrupt entry in archive: {bad}"
            if expected_files is not None and len(zf.namelist()) != expected_files:
                return f"archive has {len(zf.namelist())} entries, expected {expected_files}"
    except (zipfile.BadZipFile, OSError) as e:
        return f"cannot read archive: {e}"
    if expected_sha and compute_sha256(path) != expected_sha:
        return "SHA-256 does not match the manifest"
    return None


def archive_name(index: int) -> str:
    """Index 0 is the newest archive; 1, 2, ... are older kept versions."""
    return MASTER_NAME if index == 0 else f"Master_Backup.{index}.zip"


_OWN_ARCHIVE = re.compile(r"^Master_Backup(?:\.(\d+))?\.zip$")
_OWN_TMP = re.compile(r"^Master_Backup(?:\.\d+)?\.zip\.tmp$")


def install_archive(tmp_zip: Path, cfg: Config) -> None:
    """Move a VERIFIED temp archive into place, rotating older versions (BACKUP_KEEP).

    The current archive stays in place until ``os.replace`` swaps in the new one.
    """
    d = cfg.backup_dir
    for i in range(cfg.keep - 1, 0, -1):
        src, dst = d / archive_name(i - 1), d / archive_name(i)
        if not src.exists():
            continue
        if i == 1:  # copy (not move) so the newest archive is never missing
            part = d / (dst.name + ".tmp")
            shutil.copy2(src, part)
            os.replace(part, dst)
        else:
            os.replace(src, dst)
    os.replace(tmp_zip, cfg.master_zip)


def cleanup_old_backups(backup_dir: Path, keep: int) -> List[str]:
    """Delete ProjectVault's own leftovers only: archives beyond ``keep`` and stray .tmp files.

    Files that do not match ``Master_Backup[.N].zip`` / ``.zip.tmp`` are never touched.
    """
    removed: List[str] = []
    if not backup_dir.is_dir():
        return removed
    for item in sorted(backup_dir.iterdir()):
        if not item.is_file():
            continue
        m = _OWN_ARCHIVE.match(item.name)
        stale = _OWN_TMP.match(item.name) or (m and int(m.group(1) or 0) >= keep)
        if stale:
            try:
                item.unlink()
                removed.append(item.name)
                log(f"[Cleanup] Removed {item.name}")
            except OSError as e:
                log(f"[Cleanup] Could not remove {item.name}: {e}")
    return removed


def read_manifest(cfg: Config) -> Optional[dict]:
    try:
        data = json.loads(cfg.manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_manifest(cfg: Config, manifest: dict) -> None:
    tmp = cfg.manifest_file.with_name(MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, cfg.manifest_file)


def manifest_hashes(manifest: Optional[dict]) -> Dict[str, str]:
    """Map archive file name -> sha256 as recorded in a manifest."""
    if not isinstance(manifest, dict):
        return {}
    archives = manifest.get("archives")
    hashes = {str(k): v for k, v in archives.items() if isinstance(v, str)} if isinstance(archives, dict) else {}
    name, sha = manifest.get("archive_file"), manifest.get("sha256")
    if isinstance(name, str) and isinstance(sha, str) and name and sha:
        hashes.setdefault(name, sha)
    return hashes


# --------------------------------------------------------------------------
# Cloud
# --------------------------------------------------------------------------

_GDRIVE_ALIASES = {"gdrive", "google", "drive", "googledrive"}
_S3_ALIASES = {"s3", "r2", "b2", "minio", "aws"}
_ALL_ALIASES = {"both", "all", "cloud"}


def sync_to_cloud(local_archive: Path) -> dict:
    """Upload the archive according to STORAGE_TARGET. Never raises.

    STORAGE_TARGET: ``local`` (default, no upload), ``gdrive`` (alias google, drive),
    ``s3`` (aliases r2, b2, minio, aws) or ``both`` (aliases all, cloud) = every cloud
    that is configured. Returns {provider: result dict}; a result with
    status "error" means that upload failed.
    """
    target = _env("STORAGE_TARGET", "local").lower()
    if target == "local":
        return {}
    want_gdrive = target in _GDRIVE_ALIASES
    want_s3 = target in _S3_ALIASES
    everything = target in _ALL_ALIASES
    if not (want_gdrive or want_s3 or everything):
        return {"config": {"status": "error", "message": f"unknown STORAGE_TARGET {target!r}"}}

    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    results: dict = {}

    gdrive_ok = bool(_env("GDRIVE_LOCAL_PATH") or (_env("GDRIVE_FOLDER_ID") and _env("GDRIVE_SERVICE_ACCOUNT_PATH")))
    s3_ok = bool(_env("S3_BUCKET_NAME"))

    if want_gdrive or (everything and gdrive_ok):
        try:
            from gdrive_sync import sync_master_backup_to_gdrive
            results["gdrive"] = sync_master_backup_to_gdrive(
                local_archive_path=local_archive,
                folder_id=_env("GDRIVE_FOLDER_ID"),
                service_account_json=_env("GDRIVE_SERVICE_ACCOUNT_PATH") or None,
                local_sync_path=_env("GDRIVE_LOCAL_PATH") or None,
            )
        except Exception as e:
            results["gdrive"] = {"status": "error", "message": str(e)}
    if want_s3 or (everything and s3_ok):
        try:
            from s3_sync import upload_to_s3
            results["s3"] = upload_to_s3(
                local_archive_path=local_archive,
                bucket=_env("S3_BUCKET_NAME"),
                endpoint_url=_env("S3_ENDPOINT_URL") or None,
                access_key=_env("S3_ACCESS_KEY") or None,
                secret_key=_env("S3_SECRET_KEY") or None,
                region=_env("S3_REGION", "auto"),
                key_prefix=_env("S3_KEY_PREFIX"),
            )
        except Exception as e:
            results["s3"] = {"status": "error", "message": str(e)}
    if not results:
        results["config"] = {"status": "skipped", "message": "STORAGE_TARGET set but no cloud is configured"}

    for name, res in results.items():
        log(f"[Cloud] {name}: {res.get('status')} {res.get('message', '')}".rstrip())
    return results


def cloud_failures(cloud: dict) -> List[str]:
    return [f"{k}: {v.get('message', 'error')}" for k, v in cloud.items() if v.get("status") == "error"]


# --------------------------------------------------------------------------
# The backup itself
# --------------------------------------------------------------------------

class BackupError(Exception):
    """A backup step failed; the previous archive (if any) is untouched."""


class BackupBusy(BackupError):
    """Another backup (daemon or manual run) is already in progress."""


@contextlib.contextmanager
def backup_lock(cfg: Config):
    """Hold an exclusive OS file lock for the duration of a backup (released if the process dies)."""
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    fh = open(cfg.backup_dir / ".vault_backup.lock", "a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BackupBusy("another backup is already running")
        yield
    finally:
        fh.close()  # closing the file releases the lock


def _write_archive(cfg: Config, tmp_zip: Path) -> Tuple[int, int]:
    count = skipped = 0
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path, arcname in collect_files(cfg):
            try:
                zf.write(path, arcname=arcname)
                count += 1
            except (OSError, ValueError, UnicodeError) as e:
                # unreadable, vanished, broken symlink, or a name that is not valid text
                skipped += 1
                log(f"[Backup] Skipped {arcname.encode('utf-8', 'replace').decode('utf-8')}: {e}")
    return count, skipped


def create_backup(cfg: Config, reason: str) -> dict:
    """Do the local backup. Returns the manifest dict, raises BackupError on failure."""
    start = time.time()
    if not cfg.workspace.is_dir():
        raise BackupError(f"workspace does not exist: {cfg.workspace}")
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    with backup_lock(cfg):
        return _create_backup_locked(cfg, reason, start)


def _create_backup_locked(cfg: Config, reason: str, start: float) -> dict:
    tmp_zip = cfg.backup_dir / (MASTER_NAME + ".tmp")
    try:
        tmp_zip.unlink()
    except FileNotFoundError:
        pass
    try:
        count, skipped = _write_archive(cfg, tmp_zip)
        problem = verify_archive(tmp_zip, expected_files=count)
        if problem:
            raise BackupError(f"verification failed: {problem}")
        try:
            os.chmod(tmp_zip, 0o600)  # archives may hold project secrets; keep them owner-only
        except OSError:
            pass
        sha = compute_sha256(tmp_zip)
        size = tmp_zip.stat().st_size
        old_hashes = manifest_hashes(read_manifest(cfg))
        install_archive(tmp_zip, cfg)
    except BackupError:
        tmp_zip.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp_zip.unlink(missing_ok=True)
        raise BackupError(f"{type(e).__name__}: {e}") from e

    removed = cleanup_old_backups(cfg.backup_dir, cfg.keep)
    archives = {MASTER_NAME: sha}
    for i in range(1, cfg.keep):
        if (cfg.backup_dir / archive_name(i)).exists() and archive_name(i - 1) in old_hashes:
            archives[archive_name(i)] = old_hashes[archive_name(i - 1)]

    now = datetime.now()
    manifest = {
        "version": __version__,
        "last_backup_at": now.isoformat(),
        "last_backup_str": now.strftime("%Y-%m-%d %H:%M"),
        "archive_file": MASTER_NAME,
        "size_mb": round(size / (1024 * 1024), 2),
        "size_bytes": size,
        "file_count": count,
        "skipped_files": skipped,
        "sha256": sha,
        "archives": archives,
        "reason": reason,
        "elapsed_seconds": round(time.time() - start, 2),
        "cloud": {},
    }
    write_manifest(cfg, manifest)
    return manifest


def run_atomic_backup(reason: str = "Manual backup", alert_on_failure: bool = True) -> bool:
    """Run a full backup (local, then cloud if configured) and send an alert.

    Returns True if the LOCAL backup succeeded (a cloud failure is recorded and
    reported but does not make this False). Never raises.
    """
    cfg = get_config()
    log(f"=== ProjectVault {__version__}: backup started ({reason}) ===")
    for w in cfg.warnings:
        log(f"[Config] {w}")
    if cfg.include_secrets:
        log("[WARNING] BACKUP_INCLUDE_SECRETS=true: .env files, keys and credentials ARE in the "
            "archive (and in any cloud copy). Anyone who gets the archive gets your secrets.")

    try:
        manifest = create_backup(cfg, reason)
    except BackupBusy as e:
        log(f"[Backup] Skipped: {e}.")
        return False
    except Exception as e:
        log(f"[Backup] FAILED: {e}")
        if alert_on_failure:
            dispatch_alerts(
                f"FAILED: ProjectVault backup did not complete.\nReason: {e}\n"
                f"Trigger: {reason}\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                "Any previous archive is untouched.",
                title="ProjectVault FAILED", priority="high")
        return False

    try:
        manifest["cloud"] = sync_to_cloud(cfg.master_zip)
    except Exception as e:  # sync_to_cloud should not raise; be safe anyway
        manifest["cloud"] = {"cloud": {"status": "error", "message": str(e)}}
    write_manifest(cfg, manifest)

    failures = cloud_failures(manifest["cloud"])
    cloud_line = ", ".join(f"{k}={v.get('status')}" for k, v in manifest["cloud"].items()) or "local only"
    body = (
        f"Archive: {MASTER_NAME} ({manifest['size_mb']} MB, {manifest['file_count']} files"
        f"{', ' + str(manifest['skipped_files']) + ' skipped' if manifest['skipped_files'] else ''})\n"
        f"Trigger: {reason}\nTime: {manifest['last_backup_str']}\nCloud: {cloud_line}"
    )
    if failures:
        dispatch_alerts("FAILED: cloud sync failed (the local backup is OK).\n" + "\n".join(failures) + "\n" + body,
                        title="ProjectVault cloud FAILED", priority="high")
    else:
        dispatch_alerts("ProjectVault backup OK.\n" + body, title="ProjectVault backup OK")
    log(f"[Backup] Done: {cfg.master_zip} ({manifest['size_mb']} MB, {manifest['file_count']} files)")
    return True


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def cmd_status(cfg: Config) -> int:
    manifest = read_manifest(cfg)
    print(f"ProjectVault {__version__}")
    print(f"Workspace : {cfg.workspace}")
    print(f"Schedule  : {cfg.schedule[0]:02d}:{cfg.schedule[1]:02d} local time, keep {cfg.keep} archive(s), "
          f"target={cfg.storage_target}")
    print(f"Alerts    : telegram={'on' if telegram_configured() else 'off'}, ntfy={'on' if ntfy_configured() else 'off'}")
    if cfg.include_secrets:
        print("WARNING   : BACKUP_INCLUDE_SECRETS=true (secrets are included in archives)")
    if not manifest:
        print("No backup found yet. Run: python vault_backup.py")
        return 1
    print(f"Last backup: {manifest.get('last_backup_str')} ({manifest.get('reason')})")
    print(f"Archive   : {manifest.get('archive_file')}, {manifest.get('size_mb')} MB, "
          f"{manifest.get('file_count')} files, sha256 {str(manifest.get('sha256', ''))[:12]}...")
    for name, res in (manifest.get("cloud") or {}).items():
        print(f"Cloud     : {name} -> {res.get('status')} {res.get('message', '')}".rstrip())
    present = [archive_name(i) for i in range(cfg.keep + 5) if (cfg.backup_dir / archive_name(i)).exists()]
    print(f"On disk   : {', '.join(present) or 'nothing'}")
    return 0


def cmd_verify(cfg: Config) -> int:
    manifest = read_manifest(cfg)
    if not cfg.master_zip.exists():
        print(f"FAILED: {cfg.master_zip} not found")
        return 1
    sha = manifest_hashes(manifest).get(MASTER_NAME)
    if not sha:
        print("Note: no manifest found, checking zip integrity only.")
    problem = verify_archive(cfg.master_zip, expected_sha=sha)
    if problem:
        print(f"FAILED: {problem}")
        return 1
    print("OK: archive is intact" + (" and matches the manifest SHA-256." if sha else "."))
    return 0


def cmd_test_alert() -> int:
    results = dispatch_alerts("ProjectVault test alert: if you can read this, notifications work.", title="ProjectVault test")
    configured = {k: v for k, v in results.items() if v is not None}
    if not configured:
        print("No alert channel configured. Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID and/or NTFY_TOPIC.")
        return 1
    for name, ok in configured.items():
        print(f"{name}: {'sent' if ok else 'FAILED'}")
    return 0 if all(configured.values()) else 1


def cmd_test_cloud(cfg: Config) -> int:
    if cfg.storage_target == "local":
        print("STORAGE_TARGET is 'local'; set it to gdrive, s3 or both to test cloud upload.")
        return 1
    if not cfg.master_zip.exists():
        print("No archive to upload yet. Run a backup first: python vault_backup.py")
        return 1
    results = sync_to_cloud(cfg.master_zip)
    for name, res in results.items():
        print(redact(f"{name}: {res.get('status')} {res.get('message', '')}".rstrip()))
    bad = cloud_failures(results) or [k for k, v in results.items() if v.get("status") != "success"]
    return 1 if bad else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vault_backup.py",
        description="ProjectVault: create a verified backup of this project folder. "
                    "With no options, runs a backup now.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="show the last backup and current configuration")
    group.add_argument("--verify", action="store_true", help="re-check the archive against the manifest SHA-256")
    group.add_argument("--test-alert", action="store_true", help="send a test Telegram / ntfy notification")
    group.add_argument("--test-cloud", action="store_true", help="upload the current archive to STORAGE_TARGET")
    parser.add_argument("--version", action="version", version=f"ProjectVault {__version__}")
    args = parser.parse_args(argv)

    cfg = get_config()
    if args.status:
        return cmd_status(cfg)
    if args.verify:
        return cmd_verify(cfg)
    if args.test_alert:
        return cmd_test_alert()
    if args.test_cloud:
        return cmd_test_cloud(cfg)
    return 0 if run_atomic_backup(reason="Manual backup") else 1


if __name__ == "__main__":
    sys.exit(main())
