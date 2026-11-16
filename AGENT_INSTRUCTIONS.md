# Instructions for AI assistants

You are working in a project that uses ProjectVault, a backup tool. Read this file first. Keep to it.

## Hard rules

1. Never edit `.env`. Never print, copy or commit its contents. If a setting needs changing, tell the user which variable to edit.
2. Never put secrets (tokens, keys, passwords, private URLs) in any doc, comment, commit or chat message.
3. Do not edit or delete anything in `backups/`.
4. Do not edit the ProjectVault scripts (`vault_*.py`, `gdrive_sync.py`, `s3_sync.py`, `install_service_*`) unless the user asked you to.
5. Keep docs short. Prefer a few accurate lines over long text. Do not invent facts; if you are unsure, write "unknown" or ask.

## Where docs live

- The files in `templates/` are blank starting points. Do not fill them in place.
- Copy them into `docs/` once, then edit the copies:

  ```bash
  mkdir -p docs
  cp -n templates/*.md docs/
  ```

  Windows (PowerShell): `New-Item -ItemType Directory -Force docs; Copy-Item templates\*.md docs\`

  If a file already exists in `docs/`, do not overwrite it (`cp -n` skips existing files; on Windows check first). Merge instead.
- Replace every `[placeholder]` in the copies with real information about this project.

## The templates

| File | Keep it up to date with |
|---|---|
| `docs/PROJECT_DNA.md` | What the project is, its tech stack, and its rules |
| `docs/ARCHITECTURE.md` | Main parts, how data flows, what each folder does |
| `docs/CHANGELOG.md` | One short line per meaningful change, newest first |
| `docs/EXPERIMENTS_LOG.md` | Decisions made, and approaches tried and dropped, with why |
| `docs/RECOVERY_RUNBOOK.md` | How to rebuild the project on a new computer |

## When to update docs

- After you add, remove or rename a major file or feature: update `ARCHITECTURE.md` and add a `CHANGELOG.md` line.
- After a decision with trade-offs: add an entry to `EXPERIMENTS_LOG.md`.
- After a change to setup or dependencies: update `RECOVERY_RUNBOOK.md`.
- Use dates in `YYYY-MM-DD` format.

## Backups: what you can do

```bash
python vault_backup.py --status      # show last backup
python vault_backup.py               # run a backup now
python vault_backup.py --verify      # re-check the archive
```

Run a backup before large or risky changes, if the user agrees. Backups exclude secrets by default, so tell the user to keep their own copy of `.env` somewhere safe.

## Restoring

Always run `python vault_restore.py --dry-run` first and show the user the result. Only use `--force` if the user says so.
