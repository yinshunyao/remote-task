"""SSH via paramiko when local ssh/rsync/scp are unavailable."""

from __future__ import annotations

import posixpath
import stat
from pathlib import Path
from typing import Sequence

from remote_task.config import DEFAULT_EXCLUDES, HostSpec
from remote_task.ssh.backend import SshBackend
from remote_task.ssh.local_tools import _excluded


class ParamikoBackend(SshBackend):
    def __init__(self, spec: HostSpec) -> None:
        super().__init__(spec)
        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "paramiko is required for the fallback SSH backend; "
                "pip install paramiko"
            ) from exc
        self._paramiko = paramiko
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kw: dict = {
            "hostname": spec.host,
            "port": spec.port,
            "username": spec.user,
            "allow_agent": True,
            "look_for_keys": True,
        }
        if spec.password:
            connect_kw["password"] = spec.password
            connect_kw["look_for_keys"] = False
            connect_kw["allow_agent"] = False
        self._client.connect(**connect_kw)
        self._sftp = self._client.open_sftp()

    def close(self) -> None:
        try:
            self._sftp.close()
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass

    def run(self, command: str, *, check: bool = True) -> tuple[int, str, str]:
        _stdin, stdout, stderr = self._client.exec_command(command)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if check and code != 0:
            raise RuntimeError(f"remote command failed ({code}): {command}\n{err}")
        return code, out, err

    def mkdir(self, remote_path: str) -> None:
        parts = []
        cur = remote_path.rstrip("/")
        if not cur:
            return
        # Build parents from root or relative
        while cur and cur not in (".", "/"):
            parts.append(cur)
            parent = posixpath.dirname(cur)
            if parent == cur:
                break
            cur = parent
        for path in reversed(parts):
            try:
                self._sftp.stat(path)
            except OSError:
                try:
                    self._sftp.mkdir(path)
                except OSError:
                    # race or already exists
                    pass

    def put(self, local_path: Path | str, remote_path: str) -> None:
        local = Path(local_path)
        if not local.is_file():
            raise FileNotFoundError(local)
        parent = posixpath.dirname(remote_path)
        if parent and parent not in (".", "/"):
            self.mkdir(parent)
        self._sftp.put(str(local), remote_path)

    def get(self, remote_path: str, local_path: Path | str) -> None:
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        self._sftp.get(remote_path, str(local))

    def sync_dir(
        self,
        local_dir: Path | str,
        remote_dir: str,
        *,
        excludes: Sequence[str] | None = None,
        delete: bool = False,
    ) -> None:
        local = Path(local_dir)
        if not local.is_dir():
            raise NotADirectoryError(local)
        pats = list(excludes) if excludes is not None else list(DEFAULT_EXCLUDES)
        self.mkdir(remote_dir)
        for path in local.rglob("*"):
            rel = path.relative_to(local).as_posix()
            if path.is_dir():
                if _excluded(rel, pats):
                    continue
                self.mkdir(posixpath.join(remote_dir, rel))
                continue
            if not path.is_file():
                continue
            if _excluded(rel, pats):
                continue
            dest = posixpath.join(remote_dir, rel)
            self.put(path, dest)
        if delete:
            self._delete_extra(local, remote_dir, pats)

    def _delete_extra(self, local: Path, remote_dir: str, pats: Sequence[str]) -> None:
        local_files = set()
        for path in local.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(local).as_posix()
            if not _excluded(rel, pats):
                local_files.add(rel)
        for rel in self._list_remote_files(remote_dir):
            if rel not in local_files and not _excluded(rel, pats):
                try:
                    self._sftp.remove(posixpath.join(remote_dir, rel))
                except OSError:
                    pass

    def _list_remote_files(self, remote_dir: str, prefix: str = "") -> list[str]:
        out: list[str] = []
        try:
            entries = self._sftp.listdir_attr(remote_dir)
        except OSError:
            return out
        for entry in entries:
            name = entry.filename
            if name in (".", ".."):
                continue
            rel = f"{prefix}/{name}".lstrip("/") if prefix else name
            remote = posixpath.join(remote_dir, name)
            if stat.S_ISDIR(entry.st_mode):
                out.extend(self._list_remote_files(remote, rel))
            else:
                out.append(rel)
        return out
