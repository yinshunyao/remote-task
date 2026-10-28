from __future__ import annotations

from remote_task.queue import WAITER_REMOTE_NAME, _waiter_bytes


def test_waiter_asset_packaged():
    data = _waiter_bytes()
    assert b"QUEUE_BLOCK" in data
    assert b"waiting" in data
    assert WAITER_REMOTE_NAME == "queue-remote-wait.py"
