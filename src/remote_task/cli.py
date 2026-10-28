"""Command-line entry: ``rtask``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from remote_task import __version__
from remote_task.config import resolve_host
from remote_task.encrypt_flow import encrypt_source, pyfernet_run_command
from remote_task.jobs import Job, parse_block
from remote_task.queue import run_now, start_queue
from remote_task.remote_jobs import get_job, load_jobs, register_job
from remote_task.ssh import can_use_local_tools, open_backend
from remote_task.status import fetch_status, format_status_table
from remote_task.upload import upload_dir, upload_file


def _add_host_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", help="user@hostname (or RTASK_SSH)")
    p.add_argument("--port", type=int, default=None, help="SSH port (default 22)")
    p.add_argument("--cwd", dest="remote_cwd", help="remote working directory")
    p.add_argument("--python", default=None, help="remote Python interpreter")
    p.add_argument(
        "--config",
        help="JSON host file (host/port/remote_cwd/python only; no passwords)",
    )
    p.add_argument(
        "--backend",
        choices=("auto", "local", "paramiko"),
        default="auto",
        help="SSH backend (default: auto = local tools if present else paramiko)",
    )


def _host_from_args(args: argparse.Namespace):
    return resolve_host(
        host=getattr(args, "host", None),
        port=getattr(args, "port", None),
        remote_cwd=getattr(args, "remote_cwd", None),
        python=getattr(args, "python", None),
        config=getattr(args, "config", None),
    )


def _backend_from_args(args: argparse.Namespace):
    spec = _host_from_args(args)
    prefer_local = True
    mode = getattr(args, "backend", "auto")
    if mode == "paramiko":
        prefer_local = False
    elif mode == "local":
        if not can_use_local_tools():
            raise SystemExit("local ssh/rsync|scp not available")
        prefer_local = True
    return open_backend(spec, prefer_local=prefer_local), spec


def cmd_register(args: argparse.Namespace) -> int:
    backend, spec = _backend_from_args(args)
    cwd = spec.require_cwd()
    block = parse_block(args.block)
    job = Job(
        id=args.id,
        block=block,
        run=args.run,
        note=args.note or "",
        encrypt=bool(args.encrypt),
        payload=args.payload,
    )
    with backend:
        store = register_job(backend, cwd, job, force=args.force)
    print(f"registered {job.id} on {spec.user_host}:{cwd} (jobs={len(store.jobs)})")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    backend, spec = _backend_from_args(args)
    cwd = spec.require_cwd()
    with backend:
        store = load_jobs(backend, cwd)
    if args.json:
        print(json.dumps(store.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if not store.jobs:
        print(f"(no jobs) {spec.user_host}:{cwd}/.remote-task/jobs.json")
        return 0
    print(f"{'ID':<24} {'ENCRYPT':<8} RUN")
    print("-" * 80)
    for job in store.jobs:
        enc = "yes" if job.encrypt else "no"
        print(f"{job.id:<24} {enc:<8} {job.run}")
        if job.block:
            print(f"{'':24} block={'|'.join(job.block)}")
        if job.note:
            print(f"{'':24} note={job.note}")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    backend, spec = _backend_from_args(args)
    cwd = spec.require_cwd()
    local = Path(args.local_dir)
    with backend:
        if args.file:
            dest = args.remote_path or f"{cwd.rstrip('/')}/{Path(args.file).name}"
            upload_file(backend, args.file, dest)
            print(f"uploaded file → {spec.user_host}:{dest}")
        else:
            upload_dir(backend, local, cwd, delete=bool(args.delete))
            print(f"uploaded {local} → {spec.user_host}:{cwd}")
    return 0


def _resolve_job_fields(args: argparse.Namespace, backend, cwd: str):
    if args.job:
        job = get_job(backend, cwd, args.job)
        wait_id = args.id or job.id
        block = job.block_joined()
        run = job.run
        return wait_id, block, run, job
    if not args.block or not args.run:
        raise SystemExit("provide --job ID, or both --block and --run")
    wait_id = args.id
    if not wait_id:
        raise SystemExit("--id is required when not using --job")
    return wait_id, args.block, args.run, None


def cmd_queue(args: argparse.Namespace) -> int:
    backend, spec = _backend_from_args(args)
    cwd = spec.require_cwd()
    with backend:
        wait_id, block, run, _job = _resolve_job_fields(args, backend, cwd)
        out = start_queue(
            backend,
            remote_cwd=cwd,
            wait_id=wait_id,
            block=block,
            run=run,
            python=spec.python,
            poll_seconds=args.poll,
        )
    print(out.rstrip())
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    backend, spec = _backend_from_args(args)
    cwd = spec.require_cwd()
    with backend:
        if args.job:
            job = get_job(backend, cwd, args.job)
            wait_id = args.id or job.id
            run = job.run
        else:
            if not args.run:
                raise SystemExit("provide --job ID or --run")
            wait_id = args.id or "run"
            run = args.run
        out = run_now(
            backend,
            remote_cwd=cwd,
            run=run,
            python=spec.python,
            wait_id=wait_id,
        )
    print(out.rstrip())
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    backend, spec = _backend_from_args(args)
    cwd = spec.require_cwd()
    with backend:
        payload = fetch_status(
            backend,
            remote_cwd=cwd,
            python=spec.python,
            days=args.days,
            limit=args.limit,
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_status_table(payload))
    return 0


def cmd_encrypt(args: argparse.Namespace) -> int:
    out = encrypt_source(
        args.source,
        args.output,
        args.entry,
        password_env=args.password_env,
    )
    print(f"encrypted → {out}")
    if not args.upload and not args.register_id:
        return 0
    backend, spec = _backend_from_args(args)
    cwd = spec.require_cwd()
    dest = args.remote_path or f"{cwd.rstrip('/')}/{out.name}"
    payload_name = Path(dest).name
    with backend:
        if args.upload:
            upload_file(backend, out, dest)
            print(f"uploaded → {spec.user_host}:{dest}")
        if args.register_id:
            if not args.block:
                raise SystemExit("--block is required with --register-id")
            run = pyfernet_run_command(
                payload_name,
                python=spec.python,
                password_env=args.password_env,
                entry=args.entry if args.override_entry else None,
            )
            job = Job(
                id=args.register_id,
                block=parse_block(args.block),
                run=run,
                note=args.note or "pyfernet payload",
                encrypt=True,
                payload=payload_name,
            )
            register_job(backend, cwd, job, force=args.force)
            print(f"registered encrypt job {job.id}")
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtask",
        description="Upload, register, queue and run jobs on a remote Ubuntu host.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("register", help="append/update a job in remote jobs.json")
    _add_host_args(p)
    p.add_argument("--id", required=True, help="job id / wait id")
    p.add_argument(
        "--block",
        required=True,
        help="process substrings joined by | (include queue-remote-wait.py <prev>)",
    )
    p.add_argument("--run", required=True, help="remote command to run when idle")
    p.add_argument("--note", default="")
    p.add_argument("--encrypt", action="store_true", help="mark job as encrypted payload")
    p.add_argument("--payload", default=None, help="remote .enc filename if encrypt")
    p.add_argument("--force", action="store_true", help="replace existing id")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("list", help="list remote registered jobs")
    _add_host_args(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("upload", help="rsync/sync a local directory to remote cwd")
    _add_host_args(p)
    p.add_argument("local_dir", nargs="?", default=".", help="local directory (default .)")
    p.add_argument("--file", help="upload a single file instead of a directory")
    p.add_argument("--remote-path", help="remote destination path for --file")
    p.add_argument("--delete", action="store_true", help="pass rsync --delete (dangerous)")
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("queue", help="start a waiter for a registered or inline job")
    _add_host_args(p)
    p.add_argument("--job", help="registered job id")
    p.add_argument("--id", help="wait id (default: job id)")
    p.add_argument("--block", help="inline block list (| separated)")
    p.add_argument("--run", help="inline run command")
    p.add_argument("--poll", type=int, default=60, help="poll seconds (default 60)")
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("run", help="nohup a job immediately (no wait)")
    _add_host_args(p)
    p.add_argument("--job", help="registered job id")
    p.add_argument("--id", help="log name token")
    p.add_argument("--run", help="inline run command")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="show running / queued / done jobs")
    _add_host_args(p)
    p.add_argument("--days", type=float, default=7.0)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("encrypt", help="encrypt a source dir with pyfernet (optional extra)")
    _add_host_args(p)
    p.add_argument("source", help="local source directory")
    p.add_argument("-o", "--output", required=True, help="output .enc path")
    p.add_argument("-e", "--entry", required=True, help="entry script relative to source")
    p.add_argument("--password-env", default="PYFERNET_PASSWORD")
    p.add_argument("--upload", action="store_true", help="upload .enc after encrypt")
    p.add_argument("--remote-path", help="remote path for uploaded .enc")
    p.add_argument("--register-id", help="also register a remote job for this payload")
    p.add_argument("--block", help="required with --register-id")
    p.add_argument("--note", default="")
    p.add_argument("--force", action="store_true")
    p.add_argument("--override-entry", action="store_true")
    p.set_defaults(func=cmd_encrypt)

    p = sub.add_parser("version", help="print package version")
    p.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
