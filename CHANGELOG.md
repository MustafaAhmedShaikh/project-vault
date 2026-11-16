# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-17

First public release. Early software: expect rough edges.

### Added
- Background daemon that creates a verified `Master_Backup.zip` on a daily schedule (`BACKUP_SCHEDULE_HOUR`) and on demand (a `TRIGGER_BACKUP` file). It catches up if the computer was off at the scheduled time.
- Safe replacement: the archive is written to a temporary file, verified (zip test and SHA-256), then moved into place. The old backup is never removed first.
- `BACKUP_KEEP` to keep more than one verified backup.
- Secrets excluded by default, plus `BACKUP_EXCLUDE` and a `.vaultignore` file.
- Optional copies to Google Drive (service account or desktop-folder method) and to S3-compatible storage (beta).
- Optional Telegram and ntfy alerts for success and failure.
- `vault_backup.py` flags: `--status`, `--verify`, `--test-alert`, `--test-cloud`, `--version`, `--help`.
- A file lock so two backups cannot run at once, and redaction of tokens and keys in logs and alerts.
- `vault_restore.py` with `--dry-run`, `--archive`, `--dest`, `--force`. Identical files are skipped; conflicts abort the restore before anything is written.
- Service installers and uninstallers for Windows, macOS and Linux.
- Markdown templates and `AGENT_INSTRUCTIONS.md` for AI assistants.

### Known limitations
- By default only one backup is kept.
- Backups are not encrypted.
- S3 support is beta (tested with mocks only).
