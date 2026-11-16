import sys
import types

import gdrive_sync
import s3_sync


def _archive(tmp_path):
    p = tmp_path / "Master_Backup.zip"
    p.write_bytes(b"12345")
    return p


# ---- S3 ---------------------------------------------------------------------

class FakeS3Client:
    def __init__(self, fail=False, remote_size=None):
        self.uploads, self.fail, self.remote_size = [], fail, remote_size

    def upload_file(self, path, bucket, key):
        if self.fail:
            raise RuntimeError("AccessDenied")
        self.uploads.append((path, bucket, key))

    def head_object(self, Bucket, Key):
        return {"ContentLength": 5 if self.remote_size is None else self.remote_size}


def _fake_boto3(monkeypatch, client):
    calls = {}
    mod = types.ModuleType("boto3")

    def make(service, **kw):
        calls.update(kw, service=service)
        return client
    mod.client = make
    monkeypatch.setitem(sys.modules, "boto3", mod)
    return calls


def test_s3_upload_success(tmp_path, monkeypatch):
    client = FakeS3Client()
    calls = _fake_boto3(monkeypatch, client)
    res = s3_sync.upload_to_s3(_archive(tmp_path), "bkt", endpoint_url="https://x.example.com",
                               access_key="AK", secret_key="SK", region="auto", key_prefix="/proj/")
    assert res["status"] == "success" and res["key"] == "proj/Master_Backup.zip"
    assert client.uploads[0][1:] == ("bkt", "proj/Master_Backup.zip")
    assert calls["endpoint_url"] == "https://x.example.com" and calls["region_name"] == "auto"
    assert calls["aws_access_key_id"] == "AK"


def test_s3_aws_region_auto_is_dropped(tmp_path, monkeypatch):
    calls = _fake_boto3(monkeypatch, FakeS3Client())
    s3_sync.upload_to_s3(_archive(tmp_path), "bkt")
    assert calls["region_name"] is None and calls["endpoint_url"] is None


def test_s3_errors_do_not_raise(tmp_path, monkeypatch):
    _fake_boto3(monkeypatch, FakeS3Client(fail=True))
    res = s3_sync.upload_to_s3(_archive(tmp_path), "bkt", access_key="AK", secret_key="TOPSECRET")
    assert res["status"] == "error" and "AccessDenied" in res["message"] and "TOPSECRET" not in str(res)
    _fake_boto3(monkeypatch, FakeS3Client(remote_size=1))
    assert "does not match" in s3_sync.upload_to_s3(_archive(tmp_path), "bkt")["message"]
    assert s3_sync.upload_to_s3(tmp_path / "missing.zip", "bkt")["status"] == "error"
    assert s3_sync.upload_to_s3(_archive(tmp_path), "")["status"] == "error"


def test_s3_missing_boto3(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)  # makes `import boto3` raise ImportError
    res = s3_sync.upload_to_s3(_archive(tmp_path), "bkt")
    assert res["status"] == "error" and "pip install boto3" in res["message"]


def test_s3_wired_through_sync_to_cloud(tmp_path, monkeypatch):
    import vault_backup as vb
    client = FakeS3Client()
    _fake_boto3(monkeypatch, client)
    monkeypatch.setenv("STORAGE_TARGET", "r2")
    monkeypatch.setenv("S3_BUCKET_NAME", "bkt")
    monkeypatch.setenv("S3_KEY_PREFIX", "p")
    res = vb.sync_to_cloud(_archive(tmp_path))
    assert res["s3"]["status"] == "success" and client.uploads[0][2] == "p/Master_Backup.zip"


# ---- Google Drive -------------------------------------------------------------

def test_gdrive_local_path_replaces_and_keeps_others(tmp_path):
    arc = _archive(tmp_path)
    dest = tmp_path / "drive"
    dest.mkdir()
    (dest / "Master_Backup.zip").write_bytes(b"old")
    (dest / "holiday.zip").write_bytes(b"mine")
    res = gdrive_sync.sync_master_backup_to_gdrive(arc, None, None, str(dest))
    assert res["status"] == "success"
    assert (dest / "Master_Backup.zip").read_bytes() == b"12345"
    assert (dest / "holiday.zip").read_bytes() == b"mine"
    assert not (dest / "Master_Backup.zip.tmp").exists()


def test_gdrive_bad_inputs(tmp_path):
    arc = _archive(tmp_path)
    assert gdrive_sync.sync_master_backup_to_gdrive(arc, None, None, str(tmp_path / "nope"))["status"] == "error"
    assert gdrive_sync.sync_master_backup_to_gdrive(arc, None, None, None)["status"] == "skipped"
    assert gdrive_sync.sync_master_backup_to_gdrive(arc, "fid", str(tmp_path / "sa.json"), None)["status"] == "error"
    assert gdrive_sync.sync_master_backup_to_gdrive(tmp_path / "x.zip", "f")["status"] == "error"


class _Exec:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class FakeDriveFiles:
    def __init__(self, existing):
        self.existing, self.calls = existing, []
    def list(self, **kw):
        self.calls.append(("list", kw)); return _Exec({"files": self.existing})
    def update(self, **kw):
        self.calls.append(("update", kw)); return _Exec({"id": kw["fileId"], "name": "Master_Backup.zip"})
    def create(self, **kw):
        self.calls.append(("create", kw)); return _Exec({"id": "new1", "name": "Master_Backup.zip"})


def _fake_google(monkeypatch, files):
    service = types.SimpleNamespace(files=lambda: files)
    mods = {
        "google": types.ModuleType("google"),
        "google.oauth2": types.ModuleType("google.oauth2"),
        "google.oauth2.service_account": types.ModuleType("google.oauth2.service_account"),
        "googleapiclient": types.ModuleType("googleapiclient"),
        "googleapiclient.discovery": types.ModuleType("googleapiclient.discovery"),
        "googleapiclient.http": types.ModuleType("googleapiclient.http"),
    }
    sa = mods["google.oauth2.service_account"]
    sa.Credentials = types.SimpleNamespace(from_service_account_file=lambda p, scopes: "creds")
    mods["google.oauth2"].service_account = sa
    mods["googleapiclient.discovery"].build = lambda *a, **k: service
    mods["googleapiclient.http"].MediaFileUpload = lambda path, **k: ("media", path)
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)


def test_gdrive_api_create_and_update(tmp_path, monkeypatch):
    arc = _archive(tmp_path)
    sa = tmp_path / "sa.json"
    sa.write_text("{}")
    files = FakeDriveFiles([])
    _fake_google(monkeypatch, files)
    res = gdrive_sync.sync_master_backup_to_gdrive(arc, "folder'1", str(sa))
    assert res["status"] == "success" and res["action"] == "uploaded_new"
    assert "folder\\'1" in files.calls[0][1]["q"]  # quote escaped
    assert files.calls[1][1]["body"]["parents"] == ["folder'1"]

    files2 = FakeDriveFiles([{"id": "abc", "name": "Master_Backup.zip"}])
    _fake_google(monkeypatch, files2)
    res = gdrive_sync.sync_master_backup_to_gdrive(arc, "f", str(sa))
    assert res["action"] == "replaced_in_place" and files2.calls[1][1]["fileId"] == "abc"


def test_gdrive_missing_libs(tmp_path, monkeypatch):
    sa = tmp_path / "sa.json"
    sa.write_text("{}")
    for name in ("google", "google.oauth2", "googleapiclient"):
        monkeypatch.setitem(sys.modules, name, None)
    res = gdrive_sync.sync_master_backup_to_gdrive(_archive(tmp_path), "f", str(sa))
    assert res["status"] == "error" and "pip install" in res["message"]
