from __future__ import annotations

import pytest

from remote_task.encrypt_flow import pyfernet_run_command


def test_pyfernet_run_command():
    cmd = pyfernet_run_command("train.enc", python="/usr/bin/python3")
    assert cmd.startswith("/usr/bin/python3 -m pyfernet run train.enc")
    assert "--password-env PYFERNET_PASSWORD" in cmd


def test_require_pyfernet_message():
    from remote_task import encrypt_flow

    # If pyfernet is installed in this env, skip; else assert message.
    try:
        encrypt_flow.require_pyfernet()
    except RuntimeError as exc:
        assert "remote-task[encrypt]" in str(exc)
    else:
        pytest.skip("pyfernet-payload already installed")
