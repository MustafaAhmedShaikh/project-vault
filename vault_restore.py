"""
ProjectVault - restore.

Rebuilds a project folder from ``Master_Backup.zip`` (default: ``backups/Master_Backup.zip``).

    python vault_restore.py --dry-run            # show what would happen, write nothing
    python vault_restore.py                      # restore into the workspace
    python vault_restore.py --dest ../new-copy   # restore somewhere else
    python vault_restore.py --archive /path/to/Master_Backup.zip
    python vault_restore.py --force              # allow overwriting existing files

Safety rules:
  * The archive is checked first (zip CRC test, plus SHA-256 against the manifest
    next to the archive when one exists). A mismatch stops the restore.
  * Entries that would land outside the destination folder ("zip-slip", absolute
    paths, ``..``) make the restore abort before anything is written.
  * Existing files that differ from the archive are NOT overwritten unless you pass
    ``--force``; the restore stops and lists them. Identical files are left alone.
  * The ProjectVault scripts themselves are kept as they are unless ``--force``.
  * Secrets (``.env``, keys) are not in the archive by default; recreate them by hand.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import vault_backup  # noqa: E402


class RestoreError(Exception):
    pass


def safe_target(dest: Path, member: str) -> Path:
    """Map an archive entry name to a path inside ``dest`` or raise RestoreError (zip-slip guard)."""
    name = member.replace("\\", "/")
    p = PurePosixPath(name)
    if p.is_absolute() or (len(name) > 1 and name[1] == ":") or ".." in p.parts:
        raise RestoreError(f"unsafe path in archive: {member!r}")
    target = (dest / Path(*p.parts)).resolve() if p.parts else dest
    root = dest.resolve()
    if target != root and root not in target.parents:
        raise RestoreError(f"unsafe path in archive: {member!r}")
    return target


def find_archive(workspace: Path, explicit: Optional[str]) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise RestoreError(f"archive not found: {path}")
        return path
    for cand in (workspace / "backups" / vault_backup.MASTER_NAME, workspace / vault_backup.MASTER_NAME):
        if cand.is_file():
            return cand
    raise RestoreError("Master_Backup.zip not found in backups/ or the project root (use --archive).")


def check_archive(archive: Path) -> None:
    """Zip integrity plus SHA-256 against the manifest beside the archive, if present."""
    try:
        manifest = json.loads((archive.parent / vault_backup.MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = None
    expected = vault_backup.manifest_hashes(manifest).get(archive.name)
    problem = vault_backup.verify_archive(archive, expected_sha=expected)
    if problem:
        raise RestoreError(f"{problem}. Refusing to restore. (If you know the archive is fine, "
                           "copy it somewhere without a manifest and use --archive.)")
    print("Archive check: OK" + (" (SHA-256 matches manifest)" if expected else " (no manifest, zip test only)"))


def _same_content(zi: zipfile.ZipInfo, zf: zipfile.ZipFile, target: Path) -> bool:
    if not target.is_file() or target.stat().st_size != zi.file_size:
        return False
    h = hashlib.sha256()
    with zf.open(zi) as src:
        for chunk in iter(lambda: src.read(65536), b""):
            h.update(chunk)
    return h.hexdigest() == vault_backup.compute_sha256(target)


def plan_restore(zf: zipfile.ZipFile, dest: Path, force: bool) -> Tuple[list, list, list, list]:
    """Return (to_write, unchanged, kept_scripts, conflicts) as lists of (ZipInfo, target)/names."""
    to_write, unchanged, kept, conflicts = [], [], [], []
    for zi in zf.infolist():
        target = safe_target(dest, zi.filename)  # raises on any unsafe entry
        if zi.is_dir():
            continue
        if not target.exists():
            to_write.append((zi, target))
        elif target.is_dir():
            conflicts.append(zi.filename)
        elif _same_content(zi, zf, target):
            unchanged.append(zi.filename)
        elif force:
            to_write.append((zi, target))
        elif target.parent == dest.resolve() and target.name in vault_backup.SCRIPT_FILES:
            kept.append(zi.filename)
        else:
            conflicts.append(zi.filename)
    return to_write, unchanged, kept, conflicts


def restore(archive: Path, dest: Path, force: bool = False, dry_run: bool = False) -> int:
    check_archive(archive)
    with zipfile.ZipFile(archive) as zf:
        to_write, unchanged, kept, conflicts = plan_restore(zf, dest, force)
        print(f"Destination: {dest.resolve()}")
        print(f"{len(to_write)} file(s) to write, {len(unchanged)} already identical, "
              f"{len(kept)} ProjectVault script(s) kept as-is.")
        if conflicts:
            print(f"\n{len(conflicts)} existing file(s) differ and would be overwritten:")
            for name in conflicts[:20]:
                print(f"  {name}")
            if len(conflicts) > 20:
                print(f"  ... and {len(conflicts) - 20} more")
            print("Nothing was written. Use --force to overwrite, or --dest to restore elsewhere.")
            return 1
        if dry_run:
            for _, target in to_write[:50]:
                print(f"  would write {target}")
            print("Dry run: nothing was written.")
            return 0
        dest.mkdir(parents=True, exist_ok=True)
        for zi, target in to_write:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(zi) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            mode = (zi.external_attr >> 16) & 0o777
            if mode & stat.S_IXUSR:  # keep executable bits (e.g. shell scripts)
                os.chmod(target, mode & 0o755)  # never group/world-writable
    print(f"\nRestore complete: {len(to_write)} file(s) written.")
    print("Recreate your .env / credentials by hand (secrets are not backed up by default).")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="vault_restore.py",
                                     description="Restore a project folder from an ProjectVault backup.")
    parser.add_argument("--archive", help="path to the zip (default: backups/Master_Backup.zip)")
    parser.add_argument("--dest", help="folder to restore into (default: the workspace)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be restored; write nothing")
    parser.add_argument("--force", action="store_true", help="overwrite existing files that differ")
    args = parser.parse_args(argv)

    cfg = vault_backup.get_config()
    try:
        archive = find_archive(cfg.workspace, args.archive)
        dest = Path(args.dest).expanduser() if args.dest else cfg.workspace
        print(f"ProjectVault restore from {archive}")
        return restore(archive, dest, force=args.force, dry_run=args.dry_run)
    except (RestoreError, zipfile.BadZipFile, OSError) as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
