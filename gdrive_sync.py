"""
ProjectVault - Google Drive upload.

Keeps exactly one file called ``Master_Backup.zip`` in the target place and replaces
its contents on every backup. Two ways to reach Drive:

  1. GDRIVE_LOCAL_PATH: a folder that Google Drive for Desktop already syncs. The
     archive is copied there (temp file, then ``os.replace``). No extra packages.
  2. Drive API with a service account (GDRIVE_FOLDER_ID + GDRIVE_SERVICE_ACCOUNT_PATH).
     Needs ``pip install google-api-python-client google-auth``. The folder must be
     shared with the service account's e-mail address.

Other files in the folder are never deleted. Returns a result dict:
``{"status": "success" | "error" | "skipped", ...}``; it does not raise.
"""

import os
import shutil
from pathlib import Path
from typing import Optional

REMOTE_NAME = "Master_Backup.zip"


def _copy_to_local_folder(archive: Path, folder: Path) -> dict:
    dest = folder / REMOTE_NAME
    tmp = folder / (REMOTE_NAME + ".tmp")
    try:
        shutil.copy2(archive, tmp)
        os.replace(tmp, dest)
    except OSError as e:
        return {"status": "error", "provider": "gdrive_desktop", "message": str(e)}
    return {"status": "success", "provider": "gdrive_desktop", "file": str(dest)}


def sync_master_backup_to_gdrive(local_archive_path, folder_id: Optional[str] = None,
                                 service_account_json: Optional[str] = None,
                                 local_sync_path: Optional[str] = None) -> dict:
    archive = Path(local_archive_path)
    if not archive.exists():
        return {"status": "error", "message": f"local archive {archive} does not exist"}

    # Method 1: folder synced by Google Drive for Desktop.
    if local_sync_path:
        folder = Path(local_sync_path).expanduser()
        if not folder.is_dir():
            return {"status": "error", "provider": "gdrive_desktop",
                    "message": f"GDRIVE_LOCAL_PATH does not exist: {folder}"}
        return _copy_to_local_folder(archive, folder)

    # Method 2: Drive API with a service account.
    if not folder_id:
        return {"status": "skipped", "message": "GDRIVE_FOLDER_ID not configured"}
    sa_path = Path(service_account_json).expanduser() if service_account_json else None
    if not sa_path or not sa_path.is_file():
        return {"status": "error", "provider": "gdrive_api",
                "message": "GDRIVE_SERVICE_ACCOUNT_PATH is not set or the file does not exist"}

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return {"status": "error", "provider": "gdrive_api",
                "message": "Google libraries missing: pip install google-api-python-client google-auth"}

    try:
        creds = service_account.Credentials.from_service_account_file(
            str(sa_path), scopes=["https://www.googleapis.com/auth/drive"])
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        safe_folder = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        query = f"'{safe_folder}' in parents and name = '{REMOTE_NAME}' and trashed = false"
        found = service.files().list(
            q=query, fields="files(id, name)",
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
        media = MediaFileUpload(str(archive), mimetype="application/zip", resumable=True)
        if found:  # replace contents in place (keeps the file id and share settings)
            f = service.files().update(fileId=found[0]["id"], media_body=media,
                                       fields="id, name", supportsAllDrives=True).execute()
            action = "replaced_in_place"
        else:
            f = service.files().create(body={"name": REMOTE_NAME, "parents": [folder_id]}, media_body=media,
                                       fields="id, name", supportsAllDrives=True).execute()
            action = "uploaded_new"
        return {"status": "success", "provider": "gdrive_api", "action": action, "file_id": f.get("id")}
    except Exception as e:
        return {"status": "error", "provider": "gdrive_api", "message": str(e)}
