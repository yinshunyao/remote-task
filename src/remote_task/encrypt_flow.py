"""Optional pyfernet-payload integration for encrypted upload/run."""

from __future__ import annotations

import os
from pathlib import Path


def require_pyfernet():
    try:
        from pyfernet import encrypt_directory  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pyfernet-payload is not installed. "
            "Install with: pip install 'remote-task[encrypt]'"
        ) from exc
    return encrypt_directory


def encrypt_source(
    source_dir: Path | str,
    output_enc: Path | str,
    entry: str,
    *,
    password: str | None = None,
    password_env: str = "PYFERNET_PASSWORD",
) -> Path:
    """Encrypt a source directory into one .enc file."""
    encrypt_directory = require_pyfernet()
    pwd = password or os.environ.get(password_env)
    if not pwd:
        raise ValueError(
            f"set {password_env} or pass password= for encryption "
            "(do not store the password in jobs.json)"
        )
    src = Path(source_dir).expanduser().resolve()
    out = Path(output_enc).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    encrypt_directory(str(src), str(out), entry, pwd)
    return out


def pyfernet_run_command(
    payload_rel: str,
    *,
    python: str = "python3",
    password_env: str = "PYFERNET_PASSWORD",
    entry: str | None = None,
) -> str:
    """Build a remote shell command that runs an encrypted payload."""
    parts = [
        python,
        "-m",
        "pyfernet",
        "run",
        payload_rel,
        "--password-env",
        password_env,
    ]
    if entry:
        parts.extend(["-e", entry])
    return " ".join(parts)
