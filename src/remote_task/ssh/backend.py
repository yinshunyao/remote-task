"""Unified SSH backend interface and factory."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

from remote_task.config import HostSpec


class SshBackend(ABC):
    """Minimal remote operations used by upload / queue / jobs / status."""

    def __init__(self, spec: HostSpec) -> None:
        self.spec = spec

    @abstractmethod
    def run(self, command: str, *, check: bool = True) -> tuple[int, str, str]:
        """Run a remote shell command. Returns (exit_code, stdout, stderr)."""

    @abstractmethod
    def mkdir(self, remote_path: str) -> None:
        """Create a remote directory (parents ok)."""

    @abstractmethod
    def put(self, local_path: Path | str, remote_path: str) -> None:
        """Copy a local file to a remote path."""

    @abstractmethod
    def get(self, remote_path: str, local_path: Path | str) -> None:
        """Copy a remote file to a local path."""

    @abstractmethod
    def sync_dir(
        self,
        local_dir: Path | str,
        remote_dir: str,
        *,
        excludes: Sequence[str] | None = None,
        delete: bool = False,
    ) -> None:
        """Sync a local directory into a remote directory."""

    def close(self) -> None:
        """Release resources (optional)."""

    def __enter__(self) -> SshBackend:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def can_use_local_tools() -> bool:
    """True when local ssh and (rsync or scp) are available."""
    if not shutil.which("ssh"):
        return False
    return bool(shutil.which("rsync") or shutil.which("scp"))


def open_backend(spec: HostSpec, *, prefer_local: bool = True) -> SshBackend:
    """Open the best available backend for ``spec``."""
    if prefer_local and can_use_local_tools():
        from remote_task.ssh.local_tools import LocalToolsBackend

        return LocalToolsBackend(spec)
    from remote_task.ssh.paramiko_backend import ParamikoBackend

    return ParamikoBackend(spec)
