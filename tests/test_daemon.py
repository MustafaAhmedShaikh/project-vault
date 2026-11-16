import json
import os
from datetime import datetime, timedelta

import pytest

import vault_backup as vb
import vault_daemon as vd

SCHED = (2, 0)


def dt(day, h, m=0):
    return datetime(2026, 3, day, h, m)


def test_before_schedule_no_run():
    assert not vd.should_run_backup(dt(10, 1, 59), dt(9, 2, 0), SCHED)


def test_at_schedule_runs_even_at_odd_minute():
    assert vd.should_run_backup(dt(10, 2, 0), dt(9, 2, 0), SCHED)
    assert vd.should_run_backup(dt(10, 2, 17), dt(9, 2, 0), SCHED)


def test_catch_up_after_missed_window():
    assert vd.should_run_backup(dt(10, 14, 30), dt(9, 2, 0), SCHED)   # machine was off at 02:00
    assert vd.should_run_backup(dt(10, 9, 0), dt(7, 2, 0), SCHED)     # off for days


def test_no_second_run_same_day():
    assert not vd.should_run_backup(dt(10, 14, 30), dt(10, 2, 1), SCHED)
    assert not vd.should_run_backup(dt(10, 23, 59), dt(10, 8, 0), SCHED)  # on-demand backup counts


def test_never_backed_up():
    assert vd.should_run_backup(dt(10, 0, 5), None, SCHED)
    assert not vd.should_run_backup(dt(10, 0, 5), None, SCHED, run_if_never=False)
    assert vd.should_run_backup(dt(10, 3, 0), None, SCHED, run_if_never=False)


def test_custom_schedule():
    assert not vd.should_run_backup(dt(10, 13, 29), dt(9, 13, 30), (13, 30))
    assert vd.should_run_backup(dt(10, 13, 30), dt(9, 13, 30), (13, 30))


def test_retry_due():
    assert vd.retry_due(1000.0, None)
    assert not vd.retry_due(1000.0, 900.0, 600)
    assert vd.retry_due(1500.0, 900.0, 600)


def test_rotate_log(tmp_path):
    p = tmp_path / "vault_daemon.log"
    p.write_text("x" * 100)
    vd.rotate_log(p, max_bytes=50)
    assert not p.exists() and (tmp_path / "vault_daemon.log.1").read_text() == "x" * 100
    p.write_text("small")
    vd.rotate_log(p, max_bytes=50)
    assert p.read_text() == "small"


def test_log_writes_and_rotates(ws, monkeypatch):
    monkeypatch.setattr(vd, "MAX_LOG_BYTES", 200)
    for i in range(20):
        vd.log(f"line {i} " + "y" * 30)
    d = vb.get_config().backup_dir
    assert (d / "vault_daemon.log").exists() and (d / "vault_daemon.log.1").exists()
    assert not (d / "vault_daemon.log.2").exists()


def test_read_last_backup(ws):
    cfg = vb.get_config()
    assert vd.read_last_backup(cfg) is None
    cfg.backup_dir.mkdir()
    cfg.manifest_file.write_text(json.dumps({"last_backup_at": "2026-03-09T02:00:00"}))
    assert vd.read_last_backup(cfg) == datetime(2026, 3, 9, 2, 0)
    cfg.manifest_file.write_text("not json")
    assert vd.read_last_backup(cfg) is None


def test_failure_alert_once_per_episode(ws, monkeypatch):
    calls = []
    results = iter([False, False, False, True, False])

    def fake_backup(reason="", alert_on_failure=True):
        calls.append(alert_on_failure)
        return next(results)

    monkeypatch.setattr(vd, "run_atomic_backup", fake_backup)
    state = vd.DaemonState()
    now = dt(10, 5, 0)
    t = 10_000.0
    vd.tick(state, now, t)                       # fail 1 -> alerts
    vd.tick(state, now, t + 30)                  # too soon to retry -> no call
    assert calls == [True]
    vd.tick(state, now, t + vd.RETRY_SECONDS)    # fail 2 -> suppressed
    vd.tick(state, now, t + 2 * vd.RETRY_SECONDS)  # fail 3 -> suppressed
    assert calls == [True, False, False]
    vd.tick(state, now, t + 3 * vd.RETRY_SECONDS)  # success -> episode ends
    assert state.failing is False
    vd.tick(state, now, t + 4 * vd.RETRY_SECONDS)  # new episode -> alerts again
    assert calls == [True, False, False, False, True]


def test_tick_runs_scheduled_then_not_again(ws, monkeypatch):
    monkeypatch.setenv("BACKUP_SCHEDULE_HOUR", "02:00")
    state = vd.DaemonState()
    now = datetime.now().replace(hour=23, minute=0)
    vd.tick(state, now, 1.0)
    cfg = vb.get_config()
    assert cfg.master_zip.exists()
    first = vb.read_manifest(cfg)["last_backup_at"]
    vd.tick(state, now, 1000.0)
    assert vb.read_manifest(cfg)["last_backup_at"] == first


def test_trigger_file(ws):
    (ws / "TRIGGER_BACKUP").write_text("")
    state = vd.DaemonState()
    vd.tick(state, datetime.now(), 1.0)
    assert not (ws / "TRIGGER_BACKUP").exists()
    assert vb.get_config().master_zip.exists()
    assert "TRIGGER_BACKUP" not in __import__("zipfile").ZipFile(vb.get_config().master_zip).namelist()


def test_port_config(monkeypatch):
    assert vb.get_config().port == 58745
    monkeypatch.setenv("VAULT_DAEMON_PORT", "60000")
    assert vb.get_config().port == 60000
    monkeypatch.setenv("VAULT_DAEMON_PORT", "99999")
    assert vb.get_config().port == 58745
