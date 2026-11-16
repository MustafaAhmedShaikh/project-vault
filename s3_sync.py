"""
ProjectVault - S3-compatible upload (beta).

Uploads ``Master_Backup.zip`` to a bucket, always under the same key so each backup
overwrites the previous one. Works with AWS S3, Cloudflare R2, Backblaze B2, MinIO and
other S3-compatible services (set S3_ENDPOINT_URL for anything that is not AWS).
Needs ``pip install boto3``.

Status: beta. It is covered by unit tests that use a fake boto3 only; it has not been
run against a real bucket by the project. Turn on bucket versioning if you want history.

Returns a result dict ``{"status": "success" | "error", ...}``; it does not raise.
"""

from pathlib import Path
from typing import Optional

REMOTE_NAME = "Master_Backup.zip"


def build_key(key_prefix: str = "") -> str:
    prefix = (key_prefix or "").strip().strip("/")
    return f"{prefix}/{REMOTE_NAME}" if prefix else REMOTE_NAME


def upload_to_s3(local_archive_path, bucket: str, endpoint_url: Optional[str] = None,
                 access_key: Optional[str] = None, secret_key: Optional[str] = None,
                 region: Optional[str] = "auto", key_prefix: str = "") -> dict:
    archive = Path(local_archive_path)
    if not archive.exists():
        return {"status": "error", "provider": "s3", "message": f"local archive {archive} does not exist"}
    if not bucket:
        return {"status": "error", "provider": "s3", "message": "S3_BUCKET_NAME is not set"}
    try:
        import boto3
    except ImportError:
        return {"status": "error", "provider": "s3", "message": "boto3 missing: pip install boto3"}

    key = build_key(key_prefix)
    try:
        # "auto" is what Cloudflare R2 expects; plain AWS wants a real region or none.
        region_name = None if (not region or (region == "auto" and not endpoint_url)) else region
        client = boto3.client(
            "s3", endpoint_url=endpoint_url or None, region_name=region_name,
            aws_access_key_id=access_key or None, aws_secret_access_key=secret_key or None)
        client.upload_file(str(archive), bucket, key)
        size = archive.stat().st_size
        remote = client.head_object(Bucket=bucket, Key=key).get("ContentLength")
        if remote != size:
            return {"status": "error", "provider": "s3",
                    "message": f"uploaded size {remote} does not match local size {size}"}
        return {"status": "success", "provider": "s3", "bucket": bucket, "key": key, "size_bytes": size}
    except Exception as e:
        return {"status": "error", "provider": "s3", "message": f"{type(e).__name__}: {e}"}
