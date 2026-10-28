"""Read/write the remote JobStore over SSH."""

from __future__ import annotations

import shlex
import tempfile
from pathlib import Path

from remote_task.jobs import JOBS_DIR, JOBS_FILE, JOBS_REL, Job, JobStore
from remote_task.ssh.backend import SshBackend


def jobs_path(remote_cwd: str) -> str:
    return f"{remote_cwd.rstrip('/')}/{JOBS_REL}"


def load_jobs(backend: SshBackend, remote_cwd: str) -> JobStore:
    path = jobs_path(remote_cwd)
    code, out, _err = backend.run(
        f"if test -f {shlex.quote(path)}; then cat {shlex.quote(path)}; fi",
        check=False,
    )
    if code != 0:
        return JobStore()
    try:
        return JobStore.loads(out)
    except Exception:
        return JobStore()


def save_jobs(backend: SshBackend, remote_cwd: str, store: JobStore) -> None:
    remote_dir = f"{remote_cwd.rstrip('/')}/{JOBS_DIR}"
    remote_file = f"{remote_dir}/{JOBS_FILE}"
    remote_tmp = f"{remote_file}.tmp"
    backend.mkdir(remote_dir)
    text = store.dumps()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as fh:
        fh.write(text)
        local_tmp = Path(fh.name)
    try:
        backend.put(local_tmp, remote_tmp)
        backend.run(
            f"mv {shlex.quote(remote_tmp)} {shlex.quote(remote_file)}"
        )
    finally:
        local_tmp.unlink(missing_ok=True)


def register_job(
    backend: SshBackend,
    remote_cwd: str,
    job: Job,
    *,
    force: bool = False,
) -> JobStore:
    store = load_jobs(backend, remote_cwd)
    store.upsert(job, force=force)
    save_jobs(backend, remote_cwd, store)
    return store


def get_job(backend: SshBackend, remote_cwd: str, job_id: str) -> Job:
    store = load_jobs(backend, remote_cwd)
    job = store.find(job_id)
    if job is None:
        raise KeyError(f"job not found on remote: {job_id}")
    return job
