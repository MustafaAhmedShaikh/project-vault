# Recovery Runbook

Copy this file to `docs/RECOVERY_RUNBOOK.md` and fill it in. Goal: someone can rebuild this project on a new computer using only this page.

**Project:** [name] | **Last tested:** [YYYY-MM-DD, or "never"]

## 1. Prompt for an AI assistant

```text
Read docs/RECOVERY_RUNBOOK.md and AGENT_INSTRUCTIONS.md. Rebuild this project
on this computer, following the steps in order. Do not edit .env. Tell me
what I need to fill in myself.
```

## 2. Steps

### Step 1: Install the basics

- [runtime and version, e.g. Python 3.11]
- [other tools]

### Step 2: Get the files

- Get the ProjectVault scripts (`vault_restore.py`, `vault_backup.py`) onto the new computer: download them from the ProjectVault repository, or unzip them from `Master_Backup.zip`.
- Put `Master_Backup.zip` in `backups/` next to the scripts, or point to it with `--archive`.
- Preview the restore: `python vault_restore.py --dry-run`
- Restore: `python vault_restore.py --dest [folder]`

### Step 3: Secrets

Backups leave secrets out by default. Recreate `.env` from `.env.example`.

| Setting | Where to get it |
|---|---|
| [NAME] | [e.g. my password manager] |

### Step 4: Install dependencies

```bash
[command]
```

### Step 5: Start the backup service again

- Windows: run `install_service_windows.bat`
- macOS: `bash install_service_mac.sh`
- Linux: `bash install_service_linux.sh`

### Step 6: Check it works

```bash
python vault_backup.py --status
[your own check, e.g. run the tests]
```

## 3. Things to know

- [anything that is not obvious]
