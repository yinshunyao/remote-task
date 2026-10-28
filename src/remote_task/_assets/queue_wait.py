#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wait until named processes exit, then run one shell command.

Uploaded by remote-task to ``<cwd>/.queue-wait/`` on the job host.
This file only reads a local env file. It does not open a network connection
and does not stop other processes.

Usage:
    python3 queue_wait.py <wait-id>

Config file (next to this script): ``<wait-id>.env``
    QUEUE_BLOCK          process cmdline substrings, joined by ``|``
    QUEUE_RUN            command to run when none of those substrings remain
    QUEUE_POLL_SECONDS   optional, default 60
    QUEUE_CWD            optional working directory for QUEUE_RUN
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value
    return data


def _blocking(needles: list[str], own_pid: int) -> list[tuple[int, str]]:
    out = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
    found: list[tuple[int, str]] = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_s, args = parts
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        if pid == own_pid:
            continue
        hit = next((name for name in needles if name and name in args), None)
        if hit is None:
            continue
        found.append((pid, hit))
    return found


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: queue_wait.py <wait-id>", file=sys.stderr)
        sys.exit(2)
    wait_id = sys.argv[1]
    if not wait_id or any(ch in wait_id for ch in "/\\ \n"):
        print("wait-id must be a single path token", file=sys.stderr)
        sys.exit(2)

    env_path = Path(__file__).resolve().parent / f"{wait_id}.env"
    if not env_path.is_file():
        print(f"missing config: {env_path}", file=sys.stderr)
        sys.exit(2)
    cfg = _load_env(env_path)
    block_raw = cfg.get("QUEUE_BLOCK", "").strip()
    run = cfg.get("QUEUE_RUN", "").strip()
    if not block_raw or not run:
        print("QUEUE_BLOCK and QUEUE_RUN are required", file=sys.stderr)
        sys.exit(2)
    needles = [part.strip() for part in block_raw.split("|") if part.strip()]
    if not needles:
        print("QUEUE_BLOCK is empty", file=sys.stderr)
        sys.exit(2)
    try:
        poll = int(cfg.get("QUEUE_POLL_SECONDS", "60") or "60")
    except ValueError:
        poll = 60
    poll = min(3600, max(5, poll))
    cwd = cfg.get("QUEUE_CWD", "").strip() or None
    own_pid = os.getpid()

    while True:
        busy = _blocking(needles, own_pid)
        if not busy:
            print(f"idle; starting: {run}", flush=True)
            break
        shown = ", ".join(f"{pid}:{name}" for pid, name in busy[:12])
        print(f"waiting {wait_id}: {shown}", flush=True)
        time.sleep(poll)

    subprocess.check_call(run, shell=True, cwd=cwd)
    print(f"queue {wait_id} finished", flush=True)


if __name__ == "__main__":
    main()
