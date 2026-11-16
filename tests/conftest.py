"""Shared fixtures. All tests are offline and never touch the real environment or .env."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import vault_backup  # noqa: E402

ENV_VARS = [
    "WORKSPACE_DIR", "STORAGE_TARGET", "BACKUP_SCHEDULE_HOUR", "BACKUP_KEEP", "BACKUP_EXCLUDE",
    "BACKUP_INCLUDE_SECRETS", "VAULT_DAEMON_PORT", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "NTFY_TOPIC", "NTFY_SERVER", "GDRIVE_FOLDER_ID", "GDRIVE_SERVICE_ACCOUNT_PATH",
    "GDRIVE_LOCAL_PATH", "S3_BUCKET_NAME", "S3_ENDPOINT_URL", "S3_ACCESS_KEY", "S3_SECRET_KEY",
    "S3_REGION", "S3_KEY_PREFIX",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(vault_backup, "_ENV_LOADED", True)  # never read a real .env
    monkeypatch.setattr(vault_backup, "_logger", lambda msg: None)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A small fake project used as the workspace."""
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n")
    (root / "README.md").write_text("# demo\n")
    (root / ".gitignore").write_text("*.pyc\n")
    (root / ".env").write_text("TOKEN=super-secret\n")
    monkeypatch.setenv("WORKSPACE_DIR", str(root))
    return root


@pytest.fixture
def sent(monkeypatch):
    """Capture urllib requests instead of sending them."""
    calls = []

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return Resp()

    monkeypatch.setattr(vault_backup.urllib.request, "urlopen", fake_urlopen)
    return calls
