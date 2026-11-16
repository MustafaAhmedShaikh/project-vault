"""Regression tests for defects found in the pre-release audit."""
import json
import os
import zipfile

import pytest

import vault_backup as vb
import vault_restore as vr


def _cfg():
    return vb.get_config()


@pytest.mark.skipif(os.name == "nt", reason="raw byte file names are POSIX only")
def test_non_utf8_filename_is_skipped_not_fatal(ws):
    try:
        os.makedirs(os.fsencode(str(ws)) + b"/odd", exist_ok=True)
        with open(os.fsencode(str(ws)) + b"/odd/bad\xff.txt", "w") as f:
            f.write("x")
    except (OSError, ValueError, UnicodeError):
        pytest.skip("filesystem does not allow non-UTF8 names")
    manifest = vb.create_backup(_cfg(), "test")
    assert manifest["skipped_files"] >= 1
    assert vb.verify_archive(_cfg().master_zip) is None


def test_symlinked_file_is_not_followed(ws, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    try:
        os.symlink(outside, ws / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    vb.create_backup(_cfg(), "test")
    with zipfile.ZipFile(_cfg().master_zip) as zf:
        assert "link.txt" not in zf.namelist()


def test_concurrent_backup_is_refused_and_keeps_archive(ws):
    vb.create_backup(_cfg(), "first")
    before = _cfg().master_zip.read_bytes()
    with vb.backup_lock(_cfg()):
        with pytest.raises(vb.BackupBusy):
            vb.create_backup(_cfg(), "second")
        assert vb.run_atomic_backup(reason="third") is False
    assert _cfg().master_zip.read_bytes() == before
    vb.create_backup(_cfg(), "after lock released")  # lock is released


@pytest.mark.parametrize("junk", [
    '{"archive_file": "C:\\\\x\\\\Master_Backup.zip", "sha256": 5, "archives": [1]}',
    '[1, 2]', 'null', '{"archives": "x"}',
])
def test_garbage_manifest_does_not_crash(ws, junk):
    vb.create_backup(_cfg(), "x")
    _cfg().manifest_file.write_text(junk)
    assert isinstance(vb.manifest_hashes(vb.read_manifest(_cfg())), dict)
    assert vb.cmd_verify(_cfg()) in (0, 1)
    vr.check_archive(_cfg().master_zip)  # must not raise a TypeError


def test_redact_masks_token_and_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABC-DEF_replace-with-your-own-token")
    monkeypatch.setenv("S3_SECRET_KEY", "supersecretvalue")
    text = "HTTPError https://api.telegram.org/bot123456789:ABC-DEF_replace-with-your-own-token/sendMessage supersecretvalue"
    out = vb.redact(text)
    assert "ABC-DEF" not in out and "supersecretvalue" not in out


def test_logs_and_alerts_are_redacted(ws, monkeypatch, sent):
    token = "123456789:ABC-DEF_replace-with-your-own-token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    lines = []
    monkeypatch.setattr(vb, "_logger", lines.append)
    vb.log(f"boom {token}")
    assert token not in lines[0]
    monkeypatch.setattr(vb, "create_backup", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"url {token}")))
    vb.run_atomic_backup()
    for req in sent:
        assert token not in req.data.decode()


def test_ntfy_server_must_be_http(monkeypatch, sent):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("NTFY_SERVER", "file:///etc")
    assert vb.send_ntfy_alert("hi") is False
    assert sent == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_archive_is_owner_only(ws):
    vb.create_backup(_cfg(), "x")
    assert _cfg().master_zip.stat().st_mode & 0o077 == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_restore_never_makes_world_writable(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zi = zipfile.ZipInfo("run.sh")
        zi.external_attr = 0o100777 << 16
        zf.writestr(zi, "#!/bin/sh\n")
    dest = tmp_path / "out"
    assert vr.restore(z, dest) == 0
    assert (dest / "run.sh").stat().st_mode & 0o022 == 0
