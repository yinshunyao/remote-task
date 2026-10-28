from __future__ import annotations

import json
from pathlib import Path

import pytest

from remote_task.config import parse_user_host, resolve_host
from remote_task.ssh.backend import can_use_local_tools


def test_parse_user_host():
    assert parse_user_host("alice@example.com") == ("alice", "example.com")
    with pytest.raises(ValueError):
        parse_user_host("no-at-sign")


def test_resolve_host_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RTASK_SSH", "u@h")
    monkeypatch.setenv("RTASK_SSH_PORT", "2222")
    monkeypatch.setenv("RTASK_REMOTE_CWD", "/data/work")
    monkeypatch.setenv("RTASK_SSH_PASS", "secret")
    spec = resolve_host()
    assert spec.user == "u"
    assert spec.host == "h"
    assert spec.port == 2222
    assert spec.remote_cwd == "/data/work"
    assert spec.password == "secret"


def test_config_rejects_password(tmp_path: Path):
    path = tmp_path / "host.json"
    path.write_text(json.dumps({"host": "u@h", "password": "no"}), encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_host(config=path)


def test_can_use_local_tools_bool():
    assert isinstance(can_use_local_tools(), bool)
