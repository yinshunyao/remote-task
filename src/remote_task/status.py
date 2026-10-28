"""Query remote job status (running / queued / done)."""

from __future__ import annotations

import json
import shlex
import tempfile
from pathlib import Path

from remote_task.ssh.backend import SshBackend

_PROBE_PY = r'''#!/usr/bin/env python3
import json, os, re, subprocess, time
from pathlib import Path

cwd = Path(os.environ["RTASK_STATUS_CWD"]).expanduser().resolve()
days = float(os.environ.get("RTASK_STATUS_DAYS", "7") or "7")
limit = int(os.environ.get("RTASK_STATUS_LIMIT", "20") or "20")
WAIT_RE = re.compile(r"queue-remote-wait\.py\s+(\S+)")
KNOWN = re.compile(
    r"(fill_[\w.-]+\.py|compare\.py|queue-remote-wait\.py|train_[\w.-]+\.py|"
    r"reeval_[\w.-]+\.py|dump_aug\.py|split_aug\.py|pyfernet)"
)

def ps_rows():
    out = subprocess.check_output(["ps", "-eo", "pid,args"], text=True, errors="replace")
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            rows.append((int(parts[0]), parts[1]))
        except ValueError:
            pass
    return rows

def load_env(path):
    data = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v
    return data

def tail(path, n=40):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])

def short(s, n=120):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"

now = time.time()
days_s = None if days <= 0 else days
ps = ps_rows()
wait_by_id = {}
run_procs = []
for pid, args in ps:
    m = WAIT_RE.search(args)
    if m:
        wait_by_id.setdefault(m.group(1), []).append(pid)
        continue
    hit = KNOWN.search(args)
    if hit and "queue-remote-wait.py" not in args:
        run_procs.append((pid, hit.group(1), args))

rows = []
by_name = {}
for pid, name, args in run_procs:
    by_name.setdefault(name, []).append((pid, args))
for name, group in by_name.items():
    group_sorted = sorted(group, key=lambda t: (0 if " -u " in t[1] else 1, len(t[1]), t[0]))
    main_pid, main_args = group_sorted[0]
    rows.append({
        "status": "running", "name": name, "kind": "process",
        "pid": main_pid, "mtime": now, "detail": short(main_args),
    })

qdir = cwd / ".queue-wait"
if qdir.is_dir():
    for env_path in sorted(qdir.glob("*.env")):
        wait_id = env_path.stem
        try:
            mtime = env_path.stat().st_mtime
        except OSError:
            continue
        if days_s is not None and (now - mtime) > days_s * 86400:
            continue
        cfg = load_env(env_path)
        run = cfg.get("QUEUE_RUN", "").strip()
        block = cfg.get("QUEUE_BLOCK", "").strip()
        pids = wait_by_id.get(wait_id, [])
        log_guess = cwd / f"queue-{wait_id}.log"
        t = tail(log_guess) if log_guess.is_file() else ""
        if pids:
            if "idle; starting" in t and "finished" not in "\n".join(t.splitlines()[-3:]):
                status = "running"
                detail = f"waiter launched run; block={short(block, 80)}"
            elif any("waiting " in line for line in t.splitlines()[-5:]):
                status = "queued"
                detail = f"waiting; block={short(block, 80)}"
            else:
                status = "queued"
                detail = f"waiter alive pid={pids[0]}; block={short(block, 80)}"
            rows.append({
                "status": status, "name": wait_id, "kind": "waiter", "pid": pids[0],
                "mtime": mtime,
                "detail": detail + (f" | run={short(run, 80)}" if run else ""),
            })
        else:
            if f"queue {wait_id} finished" in t or "finished" in t[-200:]:
                status = "done"
                detail = f"waiter exited; run={short(run, 80)}"
            elif log_guess.is_file() and (
                days_s is None or (now - log_guess.stat().st_mtime) <= days_s * 86400
            ):
                status = "done"
                detail = f"no waiter; last log={short(t.splitlines()[-1] if t else '', 100)}"
            else:
                continue
            rows.append({
                "status": status, "name": wait_id, "kind": "waiter", "pid": None,
                "mtime": mtime, "detail": detail,
            })

rank = {"running": 0, "queued": 1, "unknown": 2, "done": 3}
rows.sort(key=lambda r: (rank.get(r["status"], 9), -(r.get("mtime") or 0)))
if limit > 0 and len(rows) > limit:
    keep = [r for r in rows if r["status"] in ("running", "queued")]
    rest = [r for r in rows if r["status"] not in ("running", "queued")]
    rows = keep + rest[: max(0, limit - len(keep))]

print(json.dumps(
    {"cwd": str(cwd), "days": days_s, "limit": limit, "jobs": rows},
    ensure_ascii=False,
))
'''


def fetch_status(
    backend: SshBackend,
    *,
    remote_cwd: str,
    python: str = "python3",
    days: float = 7.0,
    limit: int = 20,
) -> dict:
    """Upload a tiny probe script, run it, return parsed JSON."""
    qdir = f"{remote_cwd.rstrip('/')}/.queue-wait"
    remote_probe = f"{qdir}/rtask-status-probe.py"
    backend.mkdir(qdir)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", delete=False) as fh:
        fh.write(_PROBE_PY)
        local = Path(fh.name)
    try:
        backend.put(local, remote_probe)
    finally:
        local.unlink(missing_ok=True)

    cmd = (
        f"RTASK_STATUS_CWD={shlex.quote(remote_cwd)} "
        f"RTASK_STATUS_DAYS={shlex.quote(str(days))} "
        f"RTASK_STATUS_LIMIT={shlex.quote(str(limit))} "
        f"{shlex.quote(python)} -u {shlex.quote(remote_probe)}"
    )
    _code, out, err = backend.run(cmd, check=True)
    text = (out or "").strip()
    if not text:
        raise RuntimeError(f"status probe returned empty output: {err}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Take the last JSON object line
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise


def format_status_table(payload: dict) -> str:
    rows = payload.get("jobs") or []
    lines = [
        f"cwd={payload.get('cwd')}",
        f"count={len(rows)}  (running/queued always kept; done/unknown capped)",
        "",
        f"{'STATUS':<10} {'KIND':<8} {'PID':>8} NAME",
        "-" * 72,
    ]
    for r in rows:
        pid = str(r.get("pid")) if r.get("pid") is not None else "-"
        lines.append(
            f"{r.get('status', '?'):<10} {r.get('kind', '?'):<8} {pid:>8} {r.get('name', '')}"
        )
        if r.get("detail"):
            detail = " ".join(str(r["detail"]).split())
            if len(detail) > 100:
                detail = detail[:99] + "…"
            lines.append(f"{'':10} {detail}")
    by = {"running": 0, "queued": 0, "done": 0, "unknown": 0}
    for r in rows:
        st = r.get("status") or "unknown"
        by[st] = by.get(st, 0) + 1
    lines.append("")
    lines.append(
        f"summary: running={by.get('running', 0)} queued={by.get('queued', 0)} "
        f"done={by.get('done', 0)} unknown={by.get('unknown', 0)}"
    )
    return "\n".join(lines)
