# Troubleshooting

Start with:

```bash
python vault_backup.py --status
```

and look at `backups/vault_daemon.log`.

## No backup was made last night

- Is the daemon running? Linux: `systemctl --user status projectvault`. macOS: `launchctl list | grep projectvault`. Windows: open Task Scheduler and look for `ProjectVault_Daemon`.
- Was the computer off? The daemon catches up shortly after it is running again (it checks every 30 seconds), so check again after it has been on for a minute.
- Did the last backup fail? After a failure you get one alert, and the daemon retries every 30 minutes until one succeeds. The reason is in `backups/vault_daemon.log`.
- Did you set `BACKUP_SCHEDULE_HOUR` as `HH:MM` (for example `02:00`)? It is local time.
- Check the log for an error line.

## The daemon will not start ("already running" or port in use)

Only one daemon can run. Either one is already running, or another program uses the port. Change it in `.env`:

```ini
VAULT_DAEMON_PORT="58746"
```

Then restart the service.

## Linux: service does not start at boot

User services start when you log in. To start at boot:

```bash
loginctl enable-linger $USER
```

## Windows: a console window flashes or backups stop after logout

The installer registers a per-user logon task and uses `pythonw.exe` when it is available. If you do not see the task, run `install_service_windows.bat` again. No administrator rights are needed.

## Backup is smaller or larger than expected

- Folders like `node_modules`, `.venv`, `.git` and `backups` are skipped on purpose.
- `*.zip` and `*.log` files are skipped.
- Add your own skips with `BACKUP_EXCLUDE` or `.vaultignore`.
- `.env` and key files are skipped unless `BACKUP_INCLUDE_SECRETS="true"`.

## "Missing module" for Google Drive or S3

Install the optional libraries:

```bash
pip install -r requirements-optional.txt
```

## Cloud copy fails

Run a backup first, then `python vault_backup.py --test-cloud` (it uploads the existing archive) and read the message.

- Google service account: is the folder shared with the service account's email as Editor? Is `GDRIVE_FOLDER_ID` correct?
- Desktop folder: does the folder in `GDRIVE_LOCAL_PATH` exist?
- S3: check the bucket name, keys, region and endpoint URL. R2 and B2 need `S3_ENDPOINT_URL`.
- The local backup is still fine. The failure is recorded under `cloud` in `backups/MANIFEST_VAULT.json`.

## No Telegram or ntfy messages

Run `python vault_backup.py --test-alert`.

- Telegram: did you press Start in your bot's chat? Is the chat ID a number? See [the Telegram guide](TELEGRAM_BOT_SETUP_GUIDE.md).
- If Telegram is blocked where you are, set `HTTPS_PROXY` or use ntfy.
- ntfy: the topic must match the one in your phone app.

## "another backup is already running"

A backup (from the daemon or from you) was already in progress. Wait for it to finish and try again.

## `--verify` reports a mismatch

The archive no longer matches the checksum in the manifest. It may be corrupted or may have been changed. Run a new backup. If you keep several (`BACKUP_KEEP`), try restoring an older one with `--archive`.

## Restore says files already exist

That is the safety default: if any existing file differs from the archive, nothing is written and the differing files are listed. Identical files are not a problem. Restore into an empty folder with `--dest`, or add `--force` if you really want to overwrite. Try `--dry-run` first.

## My `.env` is missing after restore

Secrets are not backed up by default. Recreate `.env` from `.env.example` and your own saved copy of the values.

## Still stuck?

Open an issue using the bug report template. Remove tokens and keys from anything you paste.
