from __future__ import annotations

import json
import hashlib
import os
import socket
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from llm_wiki_core.state import (
    OperationRecord,
    StateInitPlan,
    StateValidationError,
    empty_registry,
    ensure_within,
    plan_state_init,
    schema_payload,
    stable_record_id,
)


class WriterError(RuntimeError):
    exit_code = 3


class LockTimeout(WriterError):
    pass


class SnapshotConflict(WriterError):
    exit_code = 2


ATOMIC_TEMP_SUFFIX = ".tmp"


def atomic_temp_prefix(target: Path) -> str:
    return f".{target.name}."


def is_atomic_temp_name(name: str) -> bool:
    if not name.startswith(".") or not name.endswith(ATOMIC_TEMP_SUFFIX):
        return False
    payload = name[1 : -len(ATOMIC_TEMP_SUFFIX)]
    target, separator, random_token = payload.rpartition(".")
    return bool(separator and target and random_token)


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


def deterministic_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def file_text_checksum(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def atomic_write_text(
    path: Path,
    text: str,
    *,
    allowed_root: Path,
    expected_checksum: str | None = None,
) -> None:
    safe_path = ensure_within(path, allowed_root)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    current_checksum = file_text_checksum(safe_path)
    if current_checksum is not None and expected_checksum is None:
        raise SnapshotConflict(f"expected checksum is required for existing target: {safe_path}")
    if expected_checksum is not None and current_checksum != expected_checksum:
        raise SnapshotConflict(f"snapshot_conflict: {safe_path}")
    fd, temp_name = tempfile.mkstemp(
        prefix=atomic_temp_prefix(safe_path),
        suffix=ATOMIC_TEMP_SUFFIX,
        dir=safe_path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, safe_path)
    except BaseException:
        if temp_path.exists():
            temp_path.unlink()
        raise


def atomic_write_json(
    path: Path,
    payload: Mapping[str, object],
    *,
    allowed_root: Path,
    expected_checksum: str | None = None,
) -> None:
    atomic_write_text(
        path,
        deterministic_json(payload),
        allowed_root=allowed_root,
        expected_checksum=expected_checksum,
    )


def read_json_object(
    path: Path,
    default: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if not path.is_file() and default is not None:
        return dict(default)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise WriterError(f"JSON root must be an object: {path}")
    return payload


def append_change_event(
    path: Path,
    *,
    allowed_root: Path,
    operation_id: str,
    kind: str,
    record_ids: list[str],
    old_checksums: Mapping[str, str | None],
    new_checksums: Mapping[str, str | None],
    result: str,
    idempotency_key: str | None = None,
    summary: Mapping[str, object] | None = None,
) -> dict[str, object]:
    safe_path = ensure_within(path, allowed_root)
    sequence = 1
    if safe_path.is_file():
        lines = [
            line
            for line in safe_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        if lines:
            last = json.loads(lines[-1])
            sequence = int(last["sequence"]) + 1
    event = {
        "sequence": sequence,
        "operation_id": operation_id,
        "kind": kind,
        "record_ids": record_ids,
        "old_checksums": dict(sorted(old_checksums.items())),
        "new_checksums": dict(sorted(new_checksums.items())),
        "result": result,
        "timestamp": utc_now(),
    }
    if idempotency_key is not None:
        event["idempotency_key"] = idempotency_key
    if summary is not None:
        event["summary"] = dict(summary)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    with safe_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return event


def load_operations(path: Path) -> dict[str, OperationRecord]:
    payload = read_json_object(path, empty_registry())
    records = payload.get("records")
    if payload.get("schema_version") != 1 or not isinstance(records, dict):
        raise WriterError("invalid operations registry")
    result: dict[str, OperationRecord] = {}
    for key, value in records.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise StateValidationError("operation registry entries must be objects")
        record = OperationRecord.from_dict(value)
        if record.operation_id != key:
            raise StateValidationError("operation_id does not match registry key")
        result[key] = record
    return result


def save_operations(
    path: Path,
    records: Mapping[str, OperationRecord],
    *,
    allowed_root: Path,
) -> None:
    expected_checksum = file_text_checksum(path)
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "records": {
                key: value.to_dict()
                for key, value in sorted(records.items())
            },
        },
        allowed_root=allowed_root,
        expected_checksum=expected_checksum,
    )


def begin_operation(
    path: Path,
    *,
    allowed_root: Path,
    kind: str,
    idempotency_key: str,
    record_ids: list[str],
    reuse_completed: bool = True,
) -> OperationRecord:
    records = load_operations(path)
    for record in records.values():
        if (
            reuse_completed
            and record.idempotency_key == idempotency_key
            and record.status == "completed"
        ):
            return record
    now = utc_now()
    operation_id = stable_record_id("op", f"{kind}:{idempotency_key}:{now}")
    record = OperationRecord(
        operation_id=operation_id,
        idempotency_key=idempotency_key,
        kind=kind,
        record_ids=tuple(record_ids),
        current_step="start",
        status="running",
        started_at=now,
        updated_at=now,
    )
    records[operation_id] = record
    save_operations(path, records, allowed_root=allowed_root)
    return record


def update_operation(
    path: Path,
    operation_id: str,
    *,
    allowed_root: Path,
    status: str,
    current_step: str,
    error: str | None = None,
) -> OperationRecord:
    if status not in {"running", "completed", "failed"}:
        raise StateValidationError("operation status is invalid")
    records = load_operations(path)
    current = records[operation_id]
    updated = replace(
        current,
        status=status,
        current_step=current_step,
        updated_at=utc_now(),
        error=error,
    )
    records[operation_id] = updated
    save_operations(path, records, allowed_root=allowed_root)
    return updated


def apply_state_init(plan: StateInitPlan) -> StateInitPlan:
    plan.meta_root.mkdir(parents=True, exist_ok=True)
    lock = VaultLock(
        plan.meta_root / "lock.json",
        allowed_root=plan.control_center,
        command="state init",
        target=plan.control_center,
    )
    with lock:
        refreshed = plan_state_init(plan.control_center)
        if not refreshed.create:
            return refreshed
        operations_path = refreshed.meta_root / "operations.json"
        if "operations.json" in refreshed.create:
            atomic_write_json(
                operations_path,
                empty_registry(),
                allowed_root=plan.control_center,
            )
        operation = begin_operation(
            operations_path,
            allowed_root=plan.control_center,
            kind="state-init",
            idempotency_key="sha256:" + hashlib.sha256(b"state-init-v1").hexdigest(),
            record_ids=[],
            reuse_completed=False,
        )
        try:
            payloads = {
                "schema.json": schema_payload(),
                "sources.json": empty_registry(),
                "pages.json": empty_registry(),
            }
            for name in refreshed.create:
                if name in payloads:
                    update_operation(
                        operations_path,
                        operation.operation_id,
                        allowed_root=plan.control_center,
                        status="running",
                        current_step=f"write-{name}",
                    )
                    atomic_write_json(
                        refreshed.meta_root / name,
                        payloads[name],
                        allowed_root=plan.control_center,
                    )
                elif name == "change-log.jsonl":
                    atomic_write_text(
                        refreshed.meta_root / name,
                        "",
                        allowed_root=plan.control_center,
                    )
            append_change_event(
                refreshed.meta_root / "change-log.jsonl",
                allowed_root=plan.control_center,
                operation_id=operation.operation_id,
                kind="state-init",
                record_ids=[],
                old_checksums={},
                new_checksums={},
                result="completed",
            )
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=plan.control_center,
                status="completed",
                current_step="complete",
            )
            return plan_state_init(plan.control_center)
        except BaseException as error:
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=plan.control_center,
                status="failed",
                current_step="failed",
                error=str(error),
            )
            raise
