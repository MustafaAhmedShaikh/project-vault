# Cloud Storage Setup

By default ProjectVault keeps backups only on your computer (`STORAGE_TARGET="local"`). You can also copy the verified archive to the cloud. The local backup is always made first. If the cloud copy fails, the local backup still stands and the failure is reported in the alert and in `backups/MANIFEST_VAULT.json`.

Cloud libraries are optional extras:

```bash
pip install -r requirements-optional.txt
```

## Choosing a target

| `STORAGE_TARGET` | Meaning |
|---|---|
| `local` | Local only (default) |
| `gdrive` | Local, plus Google Drive |
| `s3` | Local, plus S3-compatible storage (beta) |
| `both` | Local, plus every cloud that is configured |

The cloud copy is the same file each time (`Master_Backup.zip`), overwritten on each backup.

## Test it first

```bash
python vault_backup.py --test-cloud
```

This uploads the archive that already exists in `backups/` to your cloud target (it does not make a new backup, so run `python vault_backup.py` once first). It prints the result for each cloud and exits non-zero if an upload failed. `GDRIVE_LOCAL_PATH` must point to an existing folder; a missing folder is reported as an error.

## Google Drive, method 1: desktop folder (simplest)

If you have the Google Drive desktop app, point ProjectVault at a synced folder. No API setup needed.

```ini
STORAGE_TARGET="gdrive"
GDRIVE_LOCAL_PATH="/path/to/Google Drive/My Automation Backups"
```

The archive is copied into that folder and the desktop app uploads it. Create the folder first. ProjectVault only copies the file; it does not check that the desktop app finished uploading.

## Google Drive, method 2: service account (no desktop app)

1. Open the [Google Cloud console](https://console.cloud.google.com/), create or pick a project, and enable the **Google Drive API**.
2. Create a **service account** (IAM and Admin, then Service Accounts). Create a JSON key for it and download the file.
3. Save the JSON file outside your project folder if you can, for example `~/.config/projectvault/service_account.json`.
4. In Google Drive, create a folder (for example `My Automation Backups`) and share it with the service account's email address (it ends in `iam.gserviceaccount.com`), giving it **Editor** access.
5. Open the folder in your browser. The folder ID is the last part of the address: `https://drive.google.com/drive/folders/<FOLDER_ID>`.
6. Set:

   ```ini
   STORAGE_TARGET="gdrive"
   GDRIVE_FOLDER_ID="<FOLDER_ID>"
   GDRIVE_SERVICE_ACCOUNT_PATH="/home/me/.config/projectvault/service_account.json"
   ```

7. Run `python vault_backup.py --test-cloud`.

Service accounts have no storage quota of their own on a personal Google Drive, so uploads into a normal "My Drive" folder can fail with a quota error. If that happens, use method 1 or put the folder in a Shared Drive that the service account is a member of. This path has not been tested by the project against every account type; run `--test-cloud` first.

## S3-compatible storage (beta)

**Beta:** S3 support is unit-tested with mocks only and has not been tried against every provider. Test with `--test-cloud` and check the bucket yourself before relying on it.

It works with AWS S3, Cloudflare R2, Backblaze B2 (S3 API) and MinIO. Install `boto3` through `requirements-optional.txt`.

```ini
STORAGE_TARGET="s3"
S3_BUCKET_NAME="my-project-backups"
S3_ACCESS_KEY="replace-with-access-key-id"
S3_SECRET_KEY="replace-with-secret-access-key"
S3_REGION="auto"
S3_ENDPOINT_URL=""
S3_KEY_PREFIX="my-project/"
```

- **AWS S3:** leave `S3_ENDPOINT_URL` empty and set `S3_REGION` to your bucket's region, for example `us-east-1`.
- **Cloudflare R2:** `S3_ENDPOINT_URL="https://<account-id>.r2.cloudflarestorage.com"`, region `auto`.
- **Backblaze B2:** use the endpoint shown for your bucket, such as `https://s3.<region>.backblazeb2.com`, and the region from the same page.
- **MinIO:** use your server's URL, for example `http://localhost:9000`.

The object is stored as `<S3_KEY_PREFIX>Master_Backup.zip`.

## Security notes

- Backups are not encrypted. Anyone with access to your cloud folder or bucket can read the archive. Keep it private.
- Use least-privilege credentials. For S3-style storage, create a key limited to one bucket with permission to put and read objects (`s3:PutObject` and `s3:GetObject`). ProjectVault reads the object's size back after uploading to confirm it arrived, so a write-only key will be reported as a failed cloud copy. For Google, share only one folder with the service account.
- Never commit credentials. `.env` and service-account JSON files are excluded from backups by default and should be in `.gitignore`.
- If a key leaks, revoke it in your provider's console and create a new one.
- Because the cloud file is overwritten, it has the same single-version weakness as the local one. Use `BACKUP_KEEP` for local history, and turn on object versioning in your bucket or Drive if you want cloud history.

## Not working?

See [Troubleshooting](TROUBLESHOOTING.md).
