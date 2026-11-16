# Security Policy

## Supported versions

ProjectVault is an early release. Only the latest 0.1.x release gets security fixes.

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| older | No |

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Include what you found, the steps to reproduce it, and the version (`python vault_backup.py --version` shows it).

This is a volunteer project. We will try to reply within a few days, but we cannot promise a fixed timeline.

## Threat model (what ProjectVault does and does not protect)

- **Backups are not encrypted.** `Master_Backup.zip` is a plain zip. Anyone who can read the file can read its contents. Cloud copies are only as private as your cloud account.
- **Secrets are excluded by default.** `.env` files, `*.pem`, `*.key`, `credentials*.json`, service-account files, SSH keys and `*.p12` are left out unless you set `BACKUP_INCLUDE_SECRETS="true"`. Turning that on puts secrets in an unencrypted zip, so only do it if you accept that.
- **Archives are owner-only on Linux/macOS** (mode 600) but still unencrypted. Alert messages and logs are scrubbed of the Telegram token and S3 keys, but file names appear in logs.
- **The daemon listens on 127.0.0.1 only.** The port (default 58745) is used to stop two copies running. It does not accept commands.
- **Credentials live in `.env`.** Keep it out of git, and keep your cloud keys least-privilege (see [the cloud guide](docs/CLOUD_STORAGE_SETUP_GUIDE.md)).
- **Restore checks archive paths.** The restore script rejects zip entries that try to escape the destination folder (including through symbolic links already in it). It does not limit the unpacked size, so do not restore archives you do not trust.
- **A single backup is not a defence against ransomware or bad overwrites.** Use `BACKUP_KEEP` to retain older versions.
