import json
import zipfile

import pytest

import vault_backup as vb


# ---- exclusion rules -------------------------------------------------------

@pytest.mark.parametrize("path", [
    ".gitignore", ".github/workflows/ci.yml", "my_backups_plan.md", "catalog.md",
    "notes/server.log.md", ".env.example", "src/main.py", "docs/venv_setup.md",
])
def test_included(path):
    assert not vb.should_exclude(path)


@pytest.mark.parametrize("path", [
    ".git/config", "node_modules/x/index.js", "a/b/node_modules/y.js", "backups/Master_Backup.zip",
    ".venv/bin/python", "pkg/__pycache__/m.pyc", "debug.log", "x.pyc", "old.zip", "a.tmp", "b.bak",
    ".env", ".env.local", "certs/server.pem", "id_rsa", "deploy.key", "credentials.json",
    "my_service_account_prod.json", "cert.p12", ".idea/x.xml",
])
def test_excluded(path):
    assert vb.should_exclude(path)


def test_include_secrets_flag():
    assert not vb.should_exclude(".env", include_secrets=True)
    assert vb.should_exclude("node_modules/a.js", include_secrets=True)


def test_user_patterns():
    assert vb.should_exclude("scratch/a.txt", ["scratch"])
    assert vb.should_exclude("docs/drafts/a.md", ["docs/drafts"])
    assert vb.should_exclude("a/b.csv", ["*.csv"])
    assert not vb.should_exclude("a/b.txt", ["*.csv"])


def test_vaultignore_and_env_exclude(ws, monkeypatch):
    (ws / ".vaultignore").write_text("# comment\nbig_data\n\n*.dump\n")
    (ws / "big_data").mkdir()
    (ws / "big_data" / "x.bin").write_text("x")
    (ws / "a.dump").write_text("x")
    (ws / "drafts").mkdir()
    (ws / "drafts" / "d.md").write_text("x")
    monkeypatch.setenv("BACKUP_EXCLUDE", "drafts, nothing")
    names = {n for _, n in vb.collect_files(vb.get_config())}
    assert "README.md" in names and ".gitignore" in names
    assert not any(n.startswith(("big_data", "drafts")) or n.endswith(".dump") for n in names)


# ---- backup / verify / restore ----------------------------------------------

def test_backup_contents_and_manifest(ws):
    assert vb.run_atomic_backup()
    cfg = vb.get_config()
    names = set(zipfile.ZipFile(cfg.master_zip).namelist())
    assert {"README.md", ".gitignore", "src/main.py"} <= names
    assert ".env" not in names
    m = vb.read_manifest(cfg)
    assert m["version"] == vb.__version__ == "0.1.0"
    assert m["file_count"] == len(names)
    assert m["sha256"] == vb.compute_sha256(cfg.master_zip)
    assert m["cloud"] == {}
    assert not (cfg.backup_dir / "Master_Backup.zip.tmp").exists()
    assert vb.main(["--verify"]) == 0


def test_verify_detects_tampering(ws, capsys):
    vb.run_atomic_backup()
    with open(vb.get_config().master_zip, "ab") as f:
        f.write(b"junk")
    assert vb.main(["--verify"]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_status_and_help(ws, capsys):
    assert vb.main(["--status"]) == 1  # nothing yet
    vb.run_atomic_backup()
    assert vb.main(["--status"]) == 0
    out = capsys.readouterr().out
    assert "Last backup" in out
    with pytest.raises(SystemExit) as e:
        vb.main(["--help"])
    assert e.value.code == 0


def test_failed_verification_keeps_old_archive(ws, monkeypatch, sent):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    assert vb.run_atomic_backup()
    cfg = vb.get_config()
    old_bytes = cfg.master_zip.read_bytes()
    old_manifest = cfg.manifest_file.read_text()
    (ws / "new.txt").write_text("new")
    monkeypatch.setattr(vb, "verify_archive", lambda *a, **k: "simulated corruption")
    sent.clear()
    assert vb.run_atomic_backup() is False
    assert cfg.master_zip.read_bytes() == old_bytes
    assert cfg.manifest_file.read_text() == old_manifest
    assert not (cfg.backup_dir / "Master_Backup.zip.tmp").exists()
    assert sent and sent[0].data.decode().startswith("FAILED")


def test_failure_alert_can_be_suppressed(ws, monkeypatch, sent):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setattr(vb, "verify_archive", lambda *a, **k: "bad")
    assert vb.run_atomic_backup(alert_on_failure=False) is False
    assert sent == []


def test_keep_rotation(ws, monkeypatch):
    monkeypatch.setenv("BACKUP_KEEP", "3")
    cfg = vb.get_config()
    hashes = []
    for i in range(5):
        (ws / "counter.txt").write_text(str(i))
        assert vb.run_atomic_backup()
        hashes.append(vb.compute_sha256(cfg.master_zip))
    files = sorted(p.name for p in cfg.backup_dir.glob("Master_Backup*.zip"))
    assert files == ["Master_Backup.1.zip", "Master_Backup.2.zip", "Master_Backup.zip"]
    assert vb.compute_sha256(cfg.master_zip) == hashes[4]
    assert vb.compute_sha256(cfg.backup_dir / "Master_Backup.1.zip") == hashes[3]
    assert vb.compute_sha256(cfg.backup_dir / "Master_Backup.2.zip") == hashes[2]
    arch = vb.read_manifest(cfg)["archives"]
    assert arch["Master_Backup.1.zip"] == hashes[3] and arch["Master_Backup.2.zip"] == hashes[2]


def test_keep_reduced_removes_extra(ws, monkeypatch):
    monkeypatch.setenv("BACKUP_KEEP", "3")
    for i in range(3):
        (ws / "c.txt").write_text(str(i))
        vb.run_atomic_backup()
    monkeypatch.setenv("BACKUP_KEEP", "1")
    vb.run_atomic_backup()
    cfg = vb.get_config()
    assert [p.name for p in cfg.backup_dir.glob("*.zip")] == ["Master_Backup.zip"]


def test_invalid_keep_falls_back(monkeypatch):
    monkeypatch.setenv("BACKUP_KEEP", "zero")
    cfg = vb.get_config()
    assert cfg.keep == 1 and cfg.warnings


def test_cleanup_leaves_unrelated_files(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    for name in ["Master_Backup.zip", "Master_Backup.1.zip", "Master_Backup.5.zip",
                 "Master_Backup.zip.tmp", "my_photos.zip", "notes.tmp", "old.bak", "MANIFEST_VAULT.json"]:
        (d / name).write_text("x")
    removed = vb.cleanup_old_backups(d, keep=2)
    assert sorted(removed) == ["Master_Backup.5.zip", "Master_Backup.zip.tmp"]
    assert {p.name for p in d.iterdir()} == {
        "Master_Backup.zip", "Master_Backup.1.zip", "my_photos.zip", "notes.tmp", "old.bak", "MANIFEST_VAULT.json"}


# ---- cloud -----------------------------------------------------------------

def test_cloud_failure_does_not_fail_backup(ws, monkeypatch, sent):
    monkeypatch.setenv("STORAGE_TARGET", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "b")
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.delitem(__import__("sys").modules, "boto3", raising=False)
    import s3_sync

    def boom(**kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(s3_sync, "upload_to_s3", boom)
    assert vb.run_atomic_backup() is True
    cfg = vb.get_config()
    assert cfg.master_zip.exists()
    cloud = vb.read_manifest(cfg)["cloud"]
    assert cloud["s3"]["status"] == "error" and "network down" in cloud["s3"]["message"]
    assert sent[-1].data.decode().startswith("FAILED")
    assert "network down" in sent[-1].data.decode()


def test_sync_called_and_recorded(ws, monkeypatch):
    monkeypatch.setenv("STORAGE_TARGET", "gdrive")
    dest = ws.parent / "drive"
    dest.mkdir()
    monkeypatch.setenv("GDRIVE_LOCAL_PATH", str(dest))
    assert vb.run_atomic_backup()
    assert (dest / "Master_Backup.zip").exists()
    assert vb.read_manifest(vb.get_config())["cloud"]["gdrive"]["status"] == "success"


def test_target_aliases_and_unknown(ws, monkeypatch):
    monkeypatch.setenv("STORAGE_TARGET", "banana")
    assert vb.cloud_failures(vb.sync_to_cloud(ws / "x"))
    monkeypatch.setenv("STORAGE_TARGET", "both")
    res = vb.sync_to_cloud(ws / "x")  # nothing configured
    assert res["config"]["status"] == "skipped"
    monkeypatch.setenv("STORAGE_TARGET", "local")
    assert vb.sync_to_cloud(ws / "x") == {}


def test_test_cloud_flag(ws, monkeypatch, capsys):
    assert vb.main(["--test-cloud"]) == 1  # local target
    monkeypatch.setenv("STORAGE_TARGET", "gdrive")
    assert vb.main(["--test-cloud"]) == 1  # no archive
    dest = ws.parent / "drive"
    dest.mkdir()
    monkeypatch.setenv("GDRIVE_LOCAL_PATH", str(dest))
    vb.run_atomic_backup()
    assert vb.main(["--test-cloud"]) == 0
