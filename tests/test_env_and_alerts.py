import os
import urllib.parse

import vault_backup as vb


def test_parse_env_line_forms():
    p = vb.parse_env_line
    assert p("A=1") == ("A", "1")
    assert p("export B=two") == ("B", "two")
    assert p('C="quoted # not comment"  # real comment') == ("C", "quoted # not comment")
    assert p("D='single'") == ("D", "single")
    assert p("E=val # comment") == ("E", "val")
    assert p("F=a#b") == ("F", "a#b")
    assert p("G= # only comment") == ("G", "")
    assert p("H=") == ("H", "")
    assert p("I=a=b") == ("I", "a=b")
    assert p('J="unclosed') == ("J", "unclosed")
    for bad in ["", "# c", "no equals", "1BAD=x", "=x", "bad key=x"]:
        assert p(bad) is None


def test_load_env_does_not_override(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("export FOO_T=from_file\nBAR_T='x y'\n\x00weird\nBAZ_T=ok # c\n", encoding="utf-8")
    monkeypatch.setenv("FOO_T", "real")
    monkeypatch.delenv("BAR_T", raising=False)
    monkeypatch.delenv("BAZ_T", raising=False)
    try:
        applied = vb.load_env(f)
        assert os.environ["FOO_T"] == "real"
        assert os.environ["BAR_T"] == "x y" and os.environ["BAZ_T"] == "ok"
        assert "FOO_T" not in applied
    finally:
        os.environ.pop("BAR_T", None)
        os.environ.pop("BAZ_T", None)


def test_load_env_missing_file(tmp_path):
    assert vb.load_env(tmp_path / "nope") == []


def test_import_has_no_side_effects(tmp_path):
    import subprocess, sys
    code = ("import os, sys; sys.path.insert(0, %r); import vault_backup, vault_daemon, vault_restore, "
            "gdrive_sync, s3_sync; print(os.path.exists(%r))" % (str(vb.SCRIPT_DIR), str(vb.SCRIPT_DIR / "backups")))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() in ("False", "True")  # import itself must not crash or prompt


def test_schedule_parsing(monkeypatch):
    assert vb.parse_schedule("02:00") == (2, 0)
    assert vb.parse_schedule("7") == (7, 0)
    assert vb.parse_schedule("23:59") == (23, 59)
    assert vb.parse_schedule("24:00") is None and vb.parse_schedule("abc") is None
    monkeypatch.setenv("BACKUP_SCHEDULE_HOUR", "13:30")
    assert vb.get_config().schedule == (13, 30)
    monkeypatch.setenv("BACKUP_SCHEDULE_HOUR", "nope")
    cfg = vb.get_config()
    assert cfg.schedule == (2, 0) and cfg.warnings


def test_telegram_payload(sent, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:FAKE")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    assert vb.send_telegram_alert("hello <b>") is True
    req = sent[0]
    assert req.full_url == "https://api.telegram.org/bot123:FAKE/sendMessage"
    assert "Host" not in req.headers and req.get_header("Host") is None
    body = urllib.parse.parse_qs(req.data.decode())
    assert body["chat_id"] == ["42"] and body["text"] == ["hello <b>"]
    assert "parse_mode" not in body


def test_telegram_failure_does_not_leak_token(monkeypatch):
    logged = []
    monkeypatch.setattr(vb, "_logger", logged.append)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRETTOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    def boom(*a, **k):
        raise OSError("https://api.telegram.org/bot123:SECRETTOKEN/sendMessage unreachable")
    monkeypatch.setattr(vb.urllib.request, "urlopen", boom)
    assert vb.send_telegram_alert("x") is False
    assert logged and not any("SECRETTOKEN" in m for m in logged)


def test_ntfy_payload_default_and_custom_server(sent, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "my topic")
    assert vb.send_ntfy_alert("FAILED: x", title="T") is True
    req = sent[0]
    assert req.full_url == "https://ntfy.sh/my%20topic"
    assert req.data == b"FAILED: x"
    assert req.get_header("Tags") == "warning"
    monkeypatch.setenv("NTFY_SERVER", "https://ntfy.example.com/")
    vb.send_ntfy_alert("ok")
    assert sent[1].full_url == "https://ntfy.example.com/my%20topic"


def test_dispatch_reports_unconfigured(sent, monkeypatch):
    assert vb.dispatch_alerts("x") == {"telegram": None, "ntfy": None}
    assert sent == []
    assert vb.main(["--test-alert"]) == 1
    monkeypatch.setenv("NTFY_TOPIC", "t")
    assert vb.main(["--test-alert"]) == 0
