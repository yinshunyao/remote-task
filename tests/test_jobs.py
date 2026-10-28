from __future__ import annotations

import pytest

from remote_task.jobs import Job, JobStore, parse_block


def test_parse_block():
    assert parse_block("a|b|c") == ["a", "b", "c"]
    assert parse_block(["a", " b ", ""]) == ["a", "b"]


def test_job_validate_ok():
    job = Job(id="next", block=["queue-remote-wait.py prev", "train.py"], run="python -u train.py")
    job.validate()


def test_job_validate_bad_id():
    job = Job(id="bad id", block=["x"], run="y")
    with pytest.raises(ValueError):
        job.validate()


def test_store_upsert_and_force():
    store = JobStore()
    job = Job(id="a", block=["x"], run="echo 1")
    store.upsert(job)
    assert store.find("a") is not None
    with pytest.raises(ValueError):
        store.upsert(Job(id="a", block=["x"], run="echo 2"))
    store.upsert(Job(id="a", block=["x"], run="echo 2"), force=True)
    assert store.find("a").run == "echo 2"


def test_roundtrip_json():
    store = JobStore()
    store.upsert(Job(id="n1", block=["w"], run="python -u t.py", note="hi"))
    text = store.dumps()
    again = JobStore.loads(text)
    assert again.find("n1").note == "hi"
    assert again.find("n1").block == ["w"]
