"""Remote jobs registry stored at ``<cwd>/.remote-task/jobs.json``."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

JOBS_DIR = ".remote-task"
JOBS_FILE = "jobs.json"
JOBS_REL = f"{JOBS_DIR}/{JOBS_FILE}"

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class Job:
    id: str
    block: list[str]
    run: str
    note: str = ""
    created_at: str = ""
    encrypt: bool = False
    payload: str | None = None

    def block_joined(self) -> str:
        return "|".join(part.strip() for part in self.block if part.strip())

    def validate(self) -> None:
        if not _ID_RE.match(self.id):
            raise ValueError("job id must match [A-Za-z0-9._-]+")
        if not self.run or "\n" in self.run:
            raise ValueError("run must be a non-empty single line")
        needles = [p.strip() for p in self.block if p.strip()]
        if not needles:
            raise ValueError("block must contain at least one process substring")
        for part in needles:
            if "\n" in part:
                raise ValueError("block parts must be single-line")


@dataclass
class JobStore:
    version: int = 1
    jobs: list[Job] = field(default_factory=list)

    def find(self, job_id: str) -> Job | None:
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    def upsert(self, job: Job, *, force: bool = False) -> None:
        job.validate()
        existing = self.find(job.id)
        if existing is not None and not force:
            raise ValueError(f"job already registered: {job.id} (use --force to replace)")
        if existing is not None:
            self.jobs = [j for j in self.jobs if j.id != job.id]
        if not job.created_at:
            job.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.jobs.append(job)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "jobs": [asdict(j) for j in self.jobs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> JobStore:
        if not data:
            return cls()
        jobs: list[Job] = []
        for raw in data.get("jobs") or []:
            if not isinstance(raw, dict):
                continue
            block = raw.get("block") or []
            if isinstance(block, str):
                block = [p.strip() for p in block.split("|") if p.strip()]
            jobs.append(
                Job(
                    id=str(raw["id"]),
                    block=[str(x) for x in block],
                    run=str(raw.get("run") or ""),
                    note=str(raw.get("note") or ""),
                    created_at=str(raw.get("created_at") or ""),
                    encrypt=bool(raw.get("encrypt") or False),
                    payload=raw.get("payload"),
                )
            )
        return cls(version=int(data.get("version") or 1), jobs=jobs)

    @classmethod
    def loads(cls, text: str) -> JobStore:
        text = (text or "").strip()
        if not text:
            return cls()
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("jobs.json must be an object")
        return cls.from_dict(data)

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


def parse_block(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [part.strip() for part in str(value).split("|") if part.strip()]
