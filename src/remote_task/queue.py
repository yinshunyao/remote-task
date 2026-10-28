"""Start a remote waiter that runs one command after blocking processes exit."""

from __future__ import annotations

import importlib.resources as resources
import shlex
import tempfile
from pathlib import Path

from remote_task.ssh.backend import SshBackend

WAITER_REMOTE_NAME = "queue-remote-wait.py"


def _waiter_bytes() -> bytes:
    """Read packaged queue_wait.py (uploaded as queue-remote-wait.py)."""
    try:
        data = resources.files("remote_task._assets").joinpath("queue_wait.py").read_bytes()
        if data:
            return data
    except Exception:
        pass
    fallback = Path(__file__).resolve().parent / "_assets" / "queue_wait.py"
    if fallback.is_file():
        return fallback.read_bytes()
    raise FileNotFoundError("missing packaged waiter: remote_task/_assets/queue_wait.py")


def start_queue(
    backend: SshBackend,
    *,
    remote_cwd: str,
    wait_id: str,
    block: str,
    run: str,
    python: str = "python3",
    poll_seconds: int = 60,
    log_name: str | None = None,
) -> str:
    """Upload waiter + env and nohup it. Returns remote log tail text."""
    import re

    if not wait_id or any(ch in wait_id for ch in "/\\ \n"):
        raise ValueError("wait_id must be a single path token matching [A-Za-z0-9._-]+")
    if not re.match(r"^[A-Za-z0-9._-]+$", wait_id):
        raise ValueError("wait_id must match [A-Za-z0-9._-]+")
    if "\n" in block or "\n" in run:
        raise ValueError("block and run must be single-line")
    if not block.replace("|", "").strip():
        raise ValueError("block is empty")

    qdir = f"{remote_cwd.rstrip('/')}/.queue-wait"
    log = log_name or f"queue-{wait_id}.log"
    if " " in log or "\n" in log:
        raise ValueError("log name must not contain spaces")
    remote_log = log if log.startswith("/") else f"{remote_cwd.rstrip('/')}/{log}"

    backend.mkdir(qdir)

    with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as fh:
        fh.write(_waiter_bytes())
        local_waiter = Path(fh.name)
    env_text = (
        f"QUEUE_BLOCK={block}\n"
        f"QUEUE_RUN={run}\n"
        f"QUEUE_POLL_SECONDS={poll_seconds}\n"
        f"QUEUE_CWD={remote_cwd}\n"
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".env", delete=False) as fh:
        fh.write(env_text)
        local_env = Path(fh.name)
    try:
        backend.put(local_waiter, f"{qdir}/{WAITER_REMOTE_NAME}")
        backend.put(local_env, f"{qdir}/{wait_id}.env")
    finally:
        local_waiter.unlink(missing_ok=True)
        local_env.unlink(missing_ok=True)

    # Start waiter if not already running; marker matches historical tools.
    remote_script = f"""
set -euo pipefail
cwd={shlex.quote(remote_cwd)}
py={shlex.quote(python)}
wid={shlex.quote(wait_id)}
log={shlex.quote(remote_log)}
qdir={shlex.quote(qdir)}
marker="{WAITER_REMOTE_NAME} ${{wid}}"
if ps -eo args | grep -F "$marker" | grep -v grep >/dev/null; then
  echo "already running: ${{wid}}"
else
  cd "$cwd"
  nohup "$py" -u "${{qdir}}/{WAITER_REMOTE_NAME}" "$wid" > "$log" 2>&1 < /dev/null &
  echo "started pid=$! log=${{log}}"
  sleep 1
fi
echo "=== log ==="
tail -n 20 "$log" 2>/dev/null || true
echo "=== waiter ==="
ps -eo pid,etime,args | grep -F "$marker" | grep -v grep || true
"""
    _code, out, err = backend.run(f"bash -lc {shlex.quote(remote_script)}", check=True)
    return (out or "") + (err or "")


def run_now(
    backend: SshBackend,
    *,
    remote_cwd: str,
    run: str,
    python: str = "python3",
    log_name: str | None = None,
    wait_id: str = "run",
) -> str:
    """nohup a command immediately in remote_cwd (no queue wait)."""
    if "\n" in run:
        raise ValueError("run must be single-line")
    log = log_name or f"run-{wait_id}.log"
    remote_log = log if log.startswith("/") else f"{remote_cwd.rstrip('/')}/{log}"
    script = f"""
set -euo pipefail
cd {shlex.quote(remote_cwd)}
nohup bash -lc {shlex.quote(run)} > {shlex.quote(remote_log)} 2>&1 < /dev/null &
echo "started pid=$! log={remote_log}"
sleep 1
tail -n 20 {shlex.quote(remote_log)} 2>/dev/null || true
"""
    _code, out, err = backend.run(f"bash -lc {shlex.quote(script)}", check=True)
    return (out or "") + (err or "")
