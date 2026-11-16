import zipfile

import pytest

import vault_backup as vb
import vault_restore as vr


@pytest.fixture
def backed_up(ws):
    assert vb.run_atomic_backup()
    return ws


def test_round_trip(backed_up, tmp_path):
    dest = tmp_path / "restored"
    assert vr.main(["--dest", str(dest)]) == 0
    assert (dest / "src" / "main.py").read_text() == "print('hi')\n"
    assert (dest / ".gitignore").exists()
    assert not (dest / ".env").exists()
    # every archived file came back byte-identical
    for _, rel in vb.collect_files(vb.get_config()):
        assert (dest / rel).read_bytes() == (backed_up / rel).read_bytes()


def test_dry_run_writes_nothing(backed_up, tmp_path, capsys):
    dest = tmp_path / "never"
    assert vr.main(["--dry-run", "--dest", str(dest)]) == 0
    assert not dest.exists()
    assert "Dry run" in capsys.readouterr().out


def test_refuses_overwrite_unless_force(backed_up, tmp_path):
    dest = tmp_path / "d"
    assert vr.main(["--dest", str(dest)]) == 0
    (dest / "README.md").write_text("my local edit")
    (dest / "src" / "extra.txt").write_text("untracked")
    assert vr.main(["--dest", str(dest)]) == 1
    assert (dest / "README.md").read_text() == "my local edit"
    assert vr.main(["--dest", str(dest), "--dry-run"]) == 1
    assert vr.main(["--dest", str(dest), "--force"]) == 0
    assert (dest / "README.md").read_text() == "# demo\n"
    assert (dest / "src" / "extra.txt").exists()  # restore never deletes


def test_identical_files_are_not_conflicts(backed_up, tmp_path):
    dest = tmp_path / "d"
    assert vr.main(["--dest", str(dest)]) == 0
    assert vr.main(["--dest", str(dest)]) == 0


def test_scripts_kept_without_force(ws, tmp_path):
    (ws / "vault_backup.py").write_text("# archived version")
    vb.run_atomic_backup()
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "vault_backup.py").write_text("# newer local version")
    assert vr.main(["--dest", str(dest)]) == 0
    assert (dest / "vault_backup.py").read_text() == "# newer local version"
    assert (dest / "README.md").exists()
    assert vr.main(["--dest", str(dest), "--force"]) == 0
    assert (dest / "vault_backup.py").read_text() == "# archived version"


def _evil_zip(tmp_path, name):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ok.txt", "fine")
        zf.writestr(name, "pwn")
    return z


@pytest.mark.parametrize("name", ["../escape.txt", "a/../../escape.txt", "/abs/escape.txt",
                                  "..\\escape.txt", "C:/escape.txt"])
def test_zip_slip_rejected(tmp_path, name, ws):
    z = _evil_zip(tmp_path, name)
    dest = tmp_path / "out" / "inner"
    assert vr.main(["--archive", str(z), "--dest", str(dest)]) == 1
    assert not (tmp_path / "out" / "escape.txt").exists()
    assert not (dest / "ok.txt").exists()  # nothing written at all


def test_manifest_mismatch_refused(backed_up, tmp_path):
    with open(vb.get_config().master_zip, "ab") as f:
        f.write(b"x")
    assert vr.main(["--dest", str(tmp_path / "d")]) == 1
    assert not (tmp_path / "d").exists()


def test_restore_older_rotated_archive_uses_its_hash(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_KEEP", "2")
    (ws / "v.txt").write_text("one")
    vb.run_atomic_backup()
    (ws / "v.txt").write_text("two")
    vb.run_atomic_backup()
    cfg = vb.get_config()
    dest = tmp_path / "d"
    assert vr.main(["--archive", str(cfg.backup_dir / "Master_Backup.1.zip"), "--dest", str(dest)]) == 0
    assert (dest / "v.txt").read_text() == "one"


def test_missing_archive(ws):
    assert vr.main([]) == 1
