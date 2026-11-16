# ProjectVault

A small backup tool you copy into any project folder. It makes one verified `Master_Backup.zip` of your project every night, keeps it safe, and can copy it to Google Drive or S3-compatible storage. It can also message you on Telegram or ntfy when a backup works or fails.

**Status: 0.1.0 early release.** It works, but it is young. Read [Limitations](#limitations) before you rely on it.

License: MIT. Python 3.9 or newer. No packages to install for the core tool.

## What you get

- A background daemon that backs up your project once a day (default 02:00 local time) and on demand.
- A catch-up: if your computer was off at backup time, a backup runs shortly after the daemon is running again. A project that has never been backed up gets its first backup as soon as the daemon starts.
- One archive, `backups/Master_Backup.zip`, checked before it replaces the old one. A failed backup never destroys your last good one.
- Optional: keep the newest N backups (`BACKUP_KEEP`).
- Secrets (`.env`, keys, credentials) left out of the zip by default.
- Optional copy to Google Drive or S3-compatible storage (AWS S3, Cloudflare R2, Backblaze B2, MinIO).
- Optional Telegram and ntfy alerts for success and for failure.
- A restore script that rebuilds the project and will not overwrite your files unless you say so.
- Markdown templates and [`AGENT_INSTRUCTIONS.md`](AGENT_INSTRUCTIONS.md) so an AI assistant can keep your project docs up to date.

## What it does NOT do

- It does not encrypt backups.
- It does not keep history by default: one backup, replaced each night.
- It does not back up secrets unless you turn that on.
- It does not protect against a bad change you notice too late if you only keep one backup. Raise `BACKUP_KEEP`.
- It is not a replacement for git or a full disk backup.

## 60-second quickstart

1. Copy this folder's files into the root of the project you want to protect.
2. Create your settings file:

   ```bash
   cp .env.example .env          # Windows: copy .env.example .env
   ```

3. Run a first backup:

   ```bash
   python vault_backup.py
   ```

   Your archive is now at `backups/Master_Backup.zip`. Check it with `python vault_backup.py --status`.

4. Install the background service so backups run every night. Run the one for your system from the project folder:

   | System | Install | Remove |
   |---|---|---|
   | Windows | `install_service_windows.bat` (double-click, no admin needed) | `uninstall_service_windows.bat` |
   | macOS | `bash install_service_mac.sh` | `bash uninstall_service_mac.sh` |
   | Linux | `bash install_service_linux.sh` | `bash uninstall_service_linux.sh` |

   On Linux, run `loginctl enable-linger $USER` once if you want the service to start at boot without you logging in.

5. Restore when you need to (see [Restore](#restore)).

## Everyday commands

```bash
python vault_backup.py              # run a backup now
python vault_backup.py --status     # show the last backup
python vault_backup.py --verify     # re-check the archive against its recorded checksum
python vault_backup.py --test-alert # send a test Telegram / ntfy message
python vault_backup.py --test-cloud # upload the existing archive to your cloud target
python vault_backup.py --version
python vault_backup.py --help
```

To ask the running daemon for a backup, create an empty file named `TRIGGER_BACKUP` in the project folder. The daemon checks every 30 seconds, removes the file and runs the backup. The file itself is never put in the archive. Only one backup runs at a time; if you start `python vault_backup.py` while another is running, it exits with a "another backup is already running" message.

## Restore

First, see what would happen. Nothing is written:

```bash
python vault_restore.py --dry-run
```

Then restore:

```bash
python vault_restore.py                       # restore into the project folder
python vault_restore.py --dest ../restored    # restore somewhere else
python vault_restore.py --archive /path/to/Master_Backup.zip
```

Files that already exist with identical content are left alone. If any existing file differs, the restore stops before writing anything and lists the conflicts; add `--force` to overwrite them. Differing ProjectVault scripts in the project root are kept as they are unless you use `--force`. If a manifest is next to the archive, the archive's SHA-256 is checked first and a mismatch stops the restore. Because secrets are excluded by default, you will need to recreate your `.env` after a restore.

## Configuration

Settings live in `.env` (copied from [`.env.example`](.env.example)). Variables already set in your real environment take priority.

| Variable | Default | What it does |
|---|---|---|
| `WORKSPACE_DIR` | folder containing the scripts | Folder to back up |
| `STORAGE_TARGET` | `local` | `local`, `gdrive`, `s3`, or `both` (local plus every cloud you configured) |
| `BACKUP_SCHEDULE_HOUR` | `02:00` | Daily time, `HH:MM`, local time |
| `BACKUP_KEEP` | `1` | Number of verified backups to keep |
| `BACKUP_EXCLUDE` | empty | Extra patterns to skip, comma-separated |
| `BACKUP_INCLUDE_SECRETS` | `false` | Put secrets in the zip (not recommended) |
| `VAULT_DAEMON_PORT` | `58745` | Local port used to allow only one daemon |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | empty | Telegram alerts, see [the guide](docs/TELEGRAM_BOT_SETUP_GUIDE.md) |
| `NTFY_TOPIC`, `NTFY_SERVER` | empty, `https://ntfy.sh` | ntfy alerts |
| `GDRIVE_FOLDER_ID`, `GDRIVE_SERVICE_ACCOUNT_PATH`, `GDRIVE_LOCAL_PATH` | empty | Google Drive, see [the cloud guide](docs/CLOUD_STORAGE_SETUP_GUIDE.md) |
| `S3_BUCKET_NAME`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, `S3_KEY_PREFIX` | empty (`S3_REGION` is `auto`) | S3-compatible storage (beta) |

Cloud copies need extra libraries, installed only if you use them: `pip install -r requirements-optional.txt`.

### What is skipped

Always skipped: `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.cache`, `backups`, `.mypy_cache`, `.pytest_cache`, `.idea`, `.vscode`, and files ending in `.pyc`, `.pyo`, `.tmp`, `.crdownload`, `.bak`, `.zip`, `.log`.

Skipped unless `BACKUP_INCLUDE_SECRETS="true"`: `.env` and `.env.*` (but not `.env.example`), `*.pem`, `*.key`, `credentials*.json`, `*service_account*.json`, `id_rsa*`, `*.p12`.

Symbolic links are skipped (they are not followed). A file that cannot be read, or has a name that is not valid text, is skipped and counted under `skipped_files` in the manifest instead of failing the backup. The `TRIGGER_BACKUP` file is never archived.

Add your own with `BACKUP_EXCLUDE` or a `.vaultignore` file in the project folder (one glob pattern per line, `#` for comments).

## Using it with an AI assistant

It works with any AI assistant that can read a markdown file. Paste this prompt:

```text
Read AGENT_INSTRUCTIONS.md in this project and follow it. Then copy the files
from templates/ into docs/ and fill them in for this project.
```

## More documentation

- [Architecture](docs/SYSTEM_RELATIONSHIPS_AND_ARCHITECTURE.md)
- [Telegram setup](docs/TELEGRAM_BOT_SETUP_GUIDE.md)
- [Cloud storage setup](docs/CLOUD_STORAGE_SETUP_GUIDE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [FAQ](docs/FAQ.md)
- [Changelog](CHANGELOG.md), [Contributing](CONTRIBUTING.md), [Security](SECURITY.md), [Code of Conduct](CODE_OF_CONDUCT.md)

## Limitations

- By default only one backup exists. Set `BACKUP_KEEP` higher for history.
- Backups are not encrypted.
- Secrets are not in the backup unless you opt in.
- S3 support is beta and has only been tested with mocks.
- Archives are created readable by you only (mode 600 on Linux/macOS), but they are not encrypted.
- The scheduler uses your computer's local clock and only runs while the computer is on.

## License

MIT. See [LICENSE](LICENSE).
