# remote-task

Upload code to an Ubuntu host, register jobs in a remote ledger, then queue or run them over SSH. Does not kill processes already running on the host.

- **PyPI name**: `remote-task`
- **CLI**: `rtask`
- **Import**: `remote_task`
- SSH prefers local `ssh` / `rsync` / `scp` (password via `sshpass` + `RTASK_SSH_PASS`); falls back to **paramiko**
- Optional encryption: `pip install 'remote-task[encrypt]'` (uses [pyfernet-payload](https://pypi.org/project/pyfernet-payload/))

## Install

```bash
pip install remote-task

# with pyfernet encrypt/run helpers
pip install 'remote-task[encrypt]'
```

From a local clone:

```bash
python3 -m pip install .
# or editable
python3 -m pip install -e '.[dev]'
```

## Host settings

Passwords stay in environment variables. Never put them in config files.

| Variable | Meaning |
|:---|:---|
| `RTASK_SSH` | `user@host` |
| `RTASK_SSH_PORT` | SSH port (default 22) |
| `RTASK_SSH_PASS` | password (optional if you use keys) |
| `RTASK_REMOTE_CWD` | remote working directory |
| `RTASK_PYTHON` | remote interpreter (default `python3`) |
| `PYFERNET_PASSWORD` | passphrase for encrypt/run (optional extra) |

JSON config (`--config`) may contain only `host`, `port`, `remote_cwd` / `cwd`, `python`.

```json
{
  "host": "user@example.com",
  "port": 22,
  "remote_cwd": "/home/user/work",
  "python": "/usr/bin/python3"
}
```

## Remote job ledger

Jobs live on the remote host at:

```text
<remote_cwd>/.remote-task/jobs.json
```

Example entry:

```json
{
  "version": 1,
  "jobs": [
    {
      "id": "next",
      "block": ["queue-remote-wait.py prev", "train_foo.py"],
      "run": "/usr/bin/python3 -u train_bar.py",
      "note": "",
      "created_at": "2026-10-28T07:00:00Z",
      "encrypt": false,
      "payload": null
    }
  ]
}
```

`block` uses `|` on the CLI. Include the previous waiter as `queue-remote-wait.py <prev-id>` plus the script name the previous job will launch, so the hand-off gap does not start the next job early.

## CLI

```bash
export RTASK_SSH=user@host
export RTASK_SSH_PASS='…'          # optional with keys
export RTASK_REMOTE_CWD=/path/work

# register
rtask register --id next \
  --block 'queue-remote-wait.py prev|train_foo.py' \
  --run '/usr/bin/python3 -u train_bar.py'

rtask list

# upload code (default excludes .git .venv runs models *.pt …; no --delete)
rtask upload ./my_train

# queue after current work
rtask queue --job next

# or start immediately
rtask run --job next

# status
rtask status
rtask status --json --days 3 --limit 15
```

Force local tools or paramiko:

```bash
rtask status --backend local
rtask status --backend paramiko
```

### Optional encrypt flow

```bash
export PYFERNET_PASSWORD='…'

rtask encrypt ./my_train -o dist/train.enc -e train.py \
  --upload \
  --register-id enc1 \
  --block 'queue-remote-wait.py prev|train.py'

rtask queue --job enc1
```

The registered `run` is roughly:

```text
python3 -m pyfernet run train.enc --password-env PYFERNET_PASSWORD
```

The remote host must already have `pyfernet-payload` installed. The passphrase is **not** stored in `jobs.json`; set `PYFERNET_PASSWORD` in the remote environment for the waiter / process (for example via your login env or a wrapper).

## Library sketch

```python
from remote_task.config import resolve_host
from remote_task.ssh import open_backend
from remote_task.jobs import Job
from remote_task.remote_jobs import register_job
from remote_task.upload import upload_dir
from remote_task.queue import start_queue

spec = resolve_host()
with open_backend(spec) as backend:
    cwd = spec.require_cwd()
    upload_dir(backend, "./my_train", cwd)
    register_job(
        backend,
        cwd,
        Job(id="next", block=["queue-remote-wait.py prev", "train_foo.py"],
            run="/usr/bin/python3 -u train_bar.py"),
        force=True,
    )
    print(start_queue(
        backend,
        remote_cwd=cwd,
        wait_id="next",
        block="queue-remote-wait.py prev|train_foo.py",
        run="/usr/bin/python3 -u train_bar.py",
        python=spec.python,
    ))
```

## Build

```bash
python3 -m pip install build
python3 -m build
# artifacts in dist/
```

## Safety

- Does not kill remote processes
- Same wait id already running → will not start a second waiter
- Default upload does **not** use `--delete`
- Passwords only via env (`RTASK_SSH_PASS`, `PYFERNET_PASSWORD`)
