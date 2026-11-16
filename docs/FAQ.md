# FAQ

## What is ProjectVault?

A small Python tool you copy into a project folder. It makes a verified `Master_Backup.zip` of that folder every night, optionally copies it to Google Drive or S3-compatible storage, and can message you about the result.

## What is in the backup?

Everything in the project folder except:

- Skipped folders: `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.cache`, `backups`, `.mypy_cache`, `.pytest_cache`, `.idea`, `.vscode`.
- Skipped files: `*.pyc`, `*.pyo`, `*.tmp`, `*.crdownload`, `*.bak`, `*.zip`, `*.log`.
- Secrets: `.env` and `.env.*` (not `.env.example`), `*.pem`, `*.key`, `credentials*.json`, `*service_account*.json`, `id_rsa*`, `*.p12`.
- Anything in `BACKUP_EXCLUDE` or `.vaultignore`.

`.gitignore` and `.github/` are included. Because `.git` is skipped, your git history is not in the backup; push to a remote for that.

## Is it encrypted?

No. The zip is a normal zip. Keep it somewhere private. That is also why secrets are left out by default.

## How do I restore?

```bash
python vault_restore.py --dry-run     # preview
python vault_restore.py               # restore
```

See the [README](../README.md#restore) for options. Recreate your `.env` afterward.

## What is NOT protected?

- Secrets and `.env` (excluded by default; keep your own safe copy).
- Git history.
- Anything in skipped folders or patterns, and symbolic links (they are not followed).
- Anything changed after the last backup.
- Files on other drives that your project only points to.

## Is one copy enough?

Not always. By default there is a single backup that is replaced nightly. If your files get corrupted or encrypted by ransomware, or you delete something and notice a week later, the next backup will copy the damage over the good one. Set `BACKUP_KEEP="7"` (for example) to keep the newest 7 verified backups, and keep a copy somewhere that is not always connected to your computer.

## Can a failed backup destroy my last good one?

No. The new archive is written to a temporary file, verified, and only then moved into place.

## Does it work on Windows, macOS and Linux?

There are installers for all three. It is early software, so please report problems.

## Do I need to install anything?

Python 3.9 or newer. Cloud features need optional libraries from `requirements-optional.txt`.

## What if my computer is off at backup time?

The daemon runs a catch-up backup shortly after it is running again, if none has run that day and today's scheduled time has passed. A project that has never been backed up is backed up right away when the daemon starts.

## How do I run a backup right now?

`python vault_backup.py` (if the daemon is mid-backup, it will say another backup is already running), or create an empty file named `TRIGGER_BACKUP` in the project folder and the daemon will do it.

## Is S3 support ready?

It is beta. It is tested with mocks only. Run a backup, then `--test-cloud`, and check your bucket.

## Which AI assistants work with it?

Any assistant that can read a markdown file can follow [AGENT_INSTRUCTIONS.md](../AGENT_INSTRUCTIONS.md). The prompt is in the README.

## Does it send my data anywhere?

Only where you configure it: the cloud target you pick, and alert text (not your files) to Telegram or ntfy.

## How do I remove it?

Run the `uninstall_service_*` script for your system, then delete the ProjectVault files from the project.
