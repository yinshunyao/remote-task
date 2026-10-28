"""SSH via local ssh / scp / rsync (password via sshpass when set)."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from remote_task.config import DEFAULT_EXCLUDES, HostSpec
from remote_task.ssh.backend import SshBackend


class LocalToolsBackend(SshBackend):
    def __init__(self, spec: HostSpec) -> None:
        super().__init__(spec)
        if not shutil.which("ssh"):
            raise RuntimeError("ssh not found on PATH")
        self._has_rsync = bool(shutil.which("rsync"))
        self._has_scp = bool(shutil.which("scp"))
        if not self._has_rsync and not self._has_scp:
            raise RuntimeError("need rsync or scp on PATH")
        self._sshpass = bool(spec.password and shutil.which("sshpass"))
        if spec.password and not self._sshpass and not shutil.which("expect"):
            # Key-based may still work if password unused by ssh; keep trying.
            pass

    def _ssh_base(self) -> list[str]:
        cmd: list[str] = []
        if self.spec.password and self._sshpass:
            cmd.extend(["sshpass", "-e"])
        cmd.append("ssh")
        cmd.extend(
            [
                "-o",
                "StrictHostKeyChecking=no",
                "-p",
                str(self.spec.port),
            ]
        )
        if self.spec.password and self._sshpass:
            cmd.extend(
                [
                    "-o",
                    "PreferredAuthentications=password",
                    "-o",
                    "PubkeyAuthentication=no",
                ]
            )
        cmd.append(self.spec.user_host)
        return cmd

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.spec.password and self._sshpass:
            env["SSHPASS"] = self.spec.password
        return env

    def run(self, command: str, *, check: bool = True) -> tuple[int, str, str]:
        proc = subprocess.run(
            self._ssh_base() + [command],
            capture_output=True,
            text=True,
            env=self._env(),
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"remote command failed ({proc.returncode}): {command}\n{proc.stderr}"
            )
        return proc.returncode, proc.stdout, proc.stderr

    def mkdir(self, remote_path: str) -> None:
        self.run(f"mkdir -p {shlex.quote(remote_path)}")

    def put(self, local_path: Path | str, remote_path: str) -> None:
        import base64

        local = Path(local_path)
        if not local.is_file():
            raise FileNotFoundError(local)
        parent = str(Path(remote_path).parent).replace("\\", "/")
        if parent and parent not in (".", "/"):
            self.mkdir(parent)
        if self._has_scp:
            self._scp_to(local, remote_path)
            return
        b64 = base64.b64encode(local.read_bytes()).decode("ascii")
        self.run(
            f"mkdir -p {shlex.quote(parent or '.')} && "
            f"printf %s {shlex.quote(b64)} | base64 -d > {shlex.quote(remote_path)}"
        )

    def _scp_to(self, local: Path, remote_path: str) -> None:
        cmd: list[str] = []
        if self.spec.password and self._sshpass:
            cmd.extend(["sshpass", "-e"])
        cmd.append("scp")
        cmd.extend(
            [
                "-o",
                "StrictHostKeyChecking=no",
                "-P",
                str(self.spec.port),
            ]
        )
        if self.spec.password and self._sshpass:
            cmd.extend(
                [
                    "-o",
                    "PreferredAuthentications=password",
                    "-o",
                    "PubkeyAuthentication=no",
                ]
            )
        cmd.extend([str(local), f"{self.spec.user_host}:{remote_path}"])
        proc = subprocess.run(cmd, capture_output=True, text=True, env=self._env())
        if proc.returncode != 0:
            raise RuntimeError(f"scp failed: {proc.stderr}")

    def get(self, remote_path: str, local_path: Path | str) -> None:
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        if not self._has_scp:
            code, out, err = self.run(f"base64 {shlex.quote(remote_path)}", check=True)
            local.write_bytes(__import__("base64").b64decode(out.encode("ascii")))
            return
        cmd: list[str] = []
        if self.spec.password and self._sshpass:
            cmd.extend(["sshpass", "-e"])
        cmd.append("scp")
        cmd.extend(
            [
                "-o",
                "StrictHostKeyChecking=no",
                "-P",
                str(self.spec.port),
            ]
        )
        if self.spec.password and self._sshpass:
            cmd.extend(
                [
                    "-o",
                    "PreferredAuthentications=password",
                    "-o",
                    "PubkeyAuthentication=no",
                ]
            )
        cmd.extend([f"{self.spec.user_host}:{remote_path}", str(local)])
        proc = subprocess.run(cmd, capture_output=True, text=True, env=self._env())
        if proc.returncode != 0:
            raise RuntimeError(f"scp get failed: {proc.stderr}")

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
        if self._has_rsync:
            self._rsync(local, remote_dir, excludes=pats, delete=delete)
            return
        # Fallback: walk and scp each file
        for path in local.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(local).as_posix()
            if _excluded(rel, pats):
                continue
            dest = f"{remote_dir.rstrip('/')}/{rel}"
            self.put(path, dest)

    def _rsync(
        self,
        local: Path,
        remote_dir: str,
        *,
        excludes: Sequence[str],
        delete: bool,
    ) -> None:
        ssh_parts = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-p",
            str(self.spec.port),
        ]
        if self.spec.password and self._sshpass:
            ssh_parts.extend(
                [
                    "-o",
                    "PreferredAuthentications=password",
                    "-o",
                    "PubkeyAuthentication=no",
                ]
            )
        ssh_e = " ".join(ssh_parts)
        if self.spec.password and self._sshpass:
            ssh_e = f"sshpass -e {ssh_e}"

        args: list[str] = ["rsync", "-avz"]
        if delete:
            args.append("--delete")
        for pat in excludes:
            args.extend(["--exclude", pat])
        args.extend(["-e", ssh_e, f"{local.as_posix().rstrip('/')}/", f"{self.spec.user_host}:{remote_dir}"])
        proc = subprocess.run(args, capture_output=True, text=True, env=self._env())
        if proc.returncode != 0:
            raise RuntimeError(f"rsync failed: {proc.stderr or proc.stdout}")


def _excluded(rel: str, patterns: Sequence[str]) -> bool:
    name = Path(rel).name
    parts = Path(rel).parts
    for pat in patterns:
        if pat.startswith("*") and name.endswith(pat[1:]):
            return True
        if pat in parts or name == pat:
            return True
    return False
