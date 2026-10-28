"""Host connection settings. Passwords stay in environment variables only."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HOST_RE = re.compile(r"^([^@\s]+)@([^\s:]+)$")

DEFAULT_EXCLUDES = (
    ".git",
    ".venv",
    "__pycache__",
    ".DS_Store",
    "*.log",
    "runs",
    "models",
    "*.pt",
    "*.pth",
    ".remote-task",
)


@dataclass(frozen=True)
class HostSpec:
    """SSH target and remote working directory."""

    user: str
    host: str
    port: int = 22
    remote_cwd: str = ""
    python: str = "python3"
    password: str | None = None

    @property
    def user_host(self) -> str:
        return f"{self.user}@{self.host}"

    def require_cwd(self) -> str:
        cwd = (self.remote_cwd or "").strip()
        if not cwd:
            raise ValueError("remote_cwd is required")
        if " " in cwd or "\n" in cwd:
            raise ValueError("remote_cwd must not contain spaces or newlines")
        return cwd


def parse_user_host(value: str) -> tuple[str, str]:
    m = _HOST_RE.match(value.strip())
    if not m:
        raise ValueError(f"host must look like user@hostname, got: {value!r}")
    return m.group(1), m.group(2)


def load_host_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("host config must be a JSON object")
    if "password" in data or "pass" in data or "ssh_pass" in data:
        raise ValueError("host config must not contain passwords; use RTASK_SSH_PASS")
    return data


def resolve_host(
    *,
    host: str | None = None,
    port: int | None = None,
    remote_cwd: str | None = None,
    python: str | None = None,
    config: Path | str | None = None,
    password_env: str = "RTASK_SSH_PASS",
) -> HostSpec:
    """Build HostSpec from CLI flags, optional JSON file, and env password."""
    file_data: dict[str, Any] = {}
    if config:
        file_data = load_host_file(Path(config).expanduser())

    host_s = host or file_data.get("host") or os.environ.get("RTASK_SSH")
    if not host_s:
        raise ValueError("set --host user@host, RTASK_SSH, or config host")
    user, hostname = parse_user_host(str(host_s))

    port_v = port
    if port_v is None and file_data.get("port") is not None:
        port_v = int(file_data["port"])
    if port_v is None and os.environ.get("RTASK_SSH_PORT"):
        port_v = int(os.environ["RTASK_SSH_PORT"])
    if port_v is None:
        port_v = 22

    cwd = remote_cwd or file_data.get("remote_cwd") or file_data.get("cwd") or os.environ.get(
        "RTASK_REMOTE_CWD", ""
    )
    py = (
        python
        or file_data.get("python")
        or os.environ.get("RTASK_PYTHON")
        or "python3"
    )
    password = os.environ.get(password_env) or None
    if password == "":
        password = None

    return HostSpec(
        user=user,
        host=hostname,
        port=int(port_v),
        remote_cwd=str(cwd or ""),
        python=str(py),
        password=password,
    )
