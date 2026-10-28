"""Sync a local directory to the remote working directory."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from remote_task.config import DEFAULT_EXCLUDES
from remote_task.ssh.backend import SshBackend


def upload_dir(
    backend: SshBackend,
    local_dir: Path | str,
    remote_cwd: str,
    *,
    excludes: Sequence[str] | None = None,
    delete: bool = False,
) -> None:
    local = Path(local_dir).expanduser().resolve()
    if not local.is_dir():
        raise NotADirectoryError(local)
    pats = list(DEFAULT_EXCLUDES if excludes is None else excludes)
    backend.sync_dir(local, remote_cwd, excludes=pats, delete=delete)


def upload_file(
    backend: SshBackend,
    local_file: Path | str,
    remote_path: str,
) -> None:
    local = Path(local_file).expanduser().resolve()
    if not local.is_file():
        raise FileNotFoundError(local)
    backend.put(local, remote_path)
