from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from llm_wiki_core.state import ensure_within


class WriterError(RuntimeError):
    exit_code = 3


class LockTimeout(WriterError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def classify_lock(
    payload: Mapping[str, object],
    *,
    now: datetime | None = None,
    ttl_seconds: int = 600,
    pid_exists: Callable[[int], bool] = default_pid_exists,
) -> str:
    host = payload.get("host")
    pid = payload.get("pid")
    acquired_at = payload.get("acquired_at")
    if not isinstance(host, str) or not isinstance(pid, int) or not isinstance(acquired_at, str):
        return "invalid"
    if host != socket.gethostname():
        return "cross-host"
    try:
        acquired = datetime.fromisoformat(acquired_at)
    except ValueError:
        return "invalid"
    if acquired.tzinfo is None:
        return "invalid"
    current = now or datetime.now(timezone.utc)
    if (current - acquired).total_seconds() > ttl_seconds and not pid_exists(pid):
        return "stale"
    return "active"


class VaultLock:
    def __init__(
        self,
        path: Path,
        *,
        allowed_root: Path,
        command: str,
        target: Path,
        wait_seconds: float = 30.0,
    ):
        self.path = ensure_within(path, allowed_root)
        self.command = command
        self.target = target
        self.wait_seconds = wait_seconds
        self.lock_id = str(uuid.uuid4())
        self.acquired = False

    def payload(self) -> dict[str, object]:
        return {
            "lock_id": self.lock_id,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "command": self.command,
            "acquired_at": utc_now(),
            "target": str(self.target.resolve()),
        }

    def acquire(self) -> "VaultLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_seconds
        encoded = (json.dumps(self.payload(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"lock_timeout: {self.path}")
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
                continue
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                self.path.unlink(missing_ok=True)
                raise
            self.acquired = True
            return self

    def release(self) -> None:
        if not self.acquired or not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("lock_id") == self.lock_id:
            self.path.unlink()
            self.acquired = False

    def __enter__(self) -> "VaultLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
