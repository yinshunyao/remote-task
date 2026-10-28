"""SSH backends: prefer local ssh/rsync/sshpass, else paramiko."""

from __future__ import annotations

from remote_task.config import HostSpec
from remote_task.ssh.backend import SshBackend, can_use_local_tools, open_backend

__all__ = ["SshBackend", "can_use_local_tools", "open_backend", "HostSpec"]
