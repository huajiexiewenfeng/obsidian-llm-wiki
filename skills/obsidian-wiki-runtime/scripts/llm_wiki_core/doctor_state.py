from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from .state import (
    OperationRecord,
    PageRecord,
    SourceRecord,
    StateValidationError,
    decode_page_registry,
    decode_source_registry,
    registry_records,
)
from .writer import default_pid_exists


STATE_FILE_NAMES = (
    "schema.json",
    "sources.json",
    "pages.json",
    "operations.json",
    "change-log.jsonl",
)
SEVERITY_RANK = {"ERROR": 0, "WARN": 1, "INFO": 2}


@dataclass(frozen=True)
class ConsistencyIssue:
    check: str
    severity: str
    relative_path: str
    message: str
    line: int | None = None
    recovery_hint: str | None = None


@dataclass(frozen=True)
class DoctorStateSnapshot:
    meta_enabled: bool
    schema: Mapping[str, object] | None
    sources: Mapping[str, SourceRecord] | None
    pages: Mapping[str, PageRecord] | None
    operations: Mapping[str, OperationRecord] | None
    events: tuple[dict[str, object], ...] | None


class ChangeLogError(ValueError):
    def __init__(self, message: str, line: int):
        super().__init__(message)
        self.line = line


def _issue(
    check: str,
    severity: str,
    relative_path: str,
    message: str,
    *,
    line: int | None = None,
    hint: str | None = None,
) -> ConsistencyIssue:
    return ConsistencyIssue(
        check=check,
        severity=severity,
        relative_path=relative_path,
        message=message,
        line=line,
        recovery_hint=hint,
    )


def _sort_issues(issues: list[ConsistencyIssue]) -> tuple[ConsistencyIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda issue: (
                SEVERITY_RANK[issue.severity],
                issue.check,
                issue.relative_path,
                issue.line or 0,
            ),
        )
    )


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise StateValidationError("JSON root must be an object")
    return payload


def _load_schema(path: Path) -> dict[str, object]:
    payload = _read_json_object(path)
    if payload.get("schema_version") != 1:
        raise StateValidationError("schema_version must be 1")
    if payload.get("state_format") != "obsidian-llm-wiki":
        raise StateValidationError("state_format is invalid")
    return payload


def _load_operations(path: Path) -> dict[str, OperationRecord]:
    payload = _read_json_object(path)
    operations: dict[str, OperationRecord] = {}
    for key, raw in registry_records(payload).items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            raise StateValidationError("operation registry entries must be objects")
        record = OperationRecord.from_dict(raw)
        if record.operation_id != key:
            raise StateValidationError("operation_id does not match registry key")
        operations[key] = record
    return operations


def _has_line_ending(raw_line: bytes) -> bool:
    return raw_line.endswith((b"\n", b"\r"))


def _read_change_log(
    path: Path,
) -> tuple[tuple[dict[str, object], ...], ConsistencyIssue | None]:
    raw_lines = path.read_bytes().splitlines(keepends=True)
    nonempty_indexes = [
        index for index, raw_line in enumerate(raw_lines) if raw_line.strip()
    ]
    last_nonempty = nonempty_indexes[-1] if nonempty_indexes else None
    events: list[dict[str, object]] = []

    for index, raw_line in enumerate(raw_lines):
        line_number = index + 1
        if not raw_line.strip():
            continue
        try:
            encoding = "utf-8-sig" if index == 0 else "utf-8"
            text = raw_line.decode(encoding).rstrip("\r\n")
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise StateValidationError("change-log entry must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, StateValidationError) as error:
            if index == last_nonempty and not _has_line_ending(raw_line):
                return (
                    tuple(events),
                    _issue(
                        "torn-change-log-tail",
                        "WARN",
                        ".meta/change-log.jsonl",
                        "change-log.jsonl has an incomplete final line; the valid prefix remains usable.",
                        line=line_number,
                        hint=(
                            "Review the related operation, then have Maintain truncate the "
                            "incomplete tail only after user confirmation."
                        ),
                    ),
                )
            raise ChangeLogError(error.__class__.__name__, line_number) from error
        events.append(payload)
    return tuple(events), None


def _invalid_state_issue(name: str, error: BaseException) -> ConsistencyIssue:
    line = error.line if isinstance(error, ChangeLogError) else None
    return _issue(
        "invalid-state-file",
        "ERROR",
        f".meta/{name}",
        f"{name} is invalid ({error.__class__.__name__}).",
        line=line,
        hint=f"Repair or restore .meta/{name} before relying on dependent checks.",
    )


def load_doctor_state(
    control_center: Path,
) -> tuple[DoctorStateSnapshot, tuple[ConsistencyIssue, ...]]:
    control_center = control_center.resolve()
    meta = control_center / ".meta"
    empty = DoctorStateSnapshot(False, None, None, None, None, None)
    if not meta.exists():
        return empty, ()

    issues: list[ConsistencyIssue] = []
    missing: set[str] = set()
    for name in STATE_FILE_NAMES:
        if not (meta / name).is_file():
            missing.add(name)
            issues.append(
                _issue(
                    "missing-state-file",
                    "ERROR",
                    f".meta/{name}",
                    f"Required state file is missing: {name}.",
                    hint=f"Restore or initialize .meta/{name} before retrying Doctor.",
                )
            )

    schema: dict[str, object] | None = None
    if "schema.json" not in missing:
        try:
            schema = _load_schema(meta / "schema.json")
        except (OSError, UnicodeError, json.JSONDecodeError, StateValidationError) as error:
            issues.append(_invalid_state_issue("schema.json", error))

    snapshot = DoctorStateSnapshot(True, schema, None, None, None, None)
    if schema is None:
        return snapshot, _sort_issues(issues)

    sources: dict[str, SourceRecord] | None = None
    if "sources.json" not in missing:
        try:
            sources = decode_source_registry(_read_json_object(meta / "sources.json"))
        except (OSError, UnicodeError, json.JSONDecodeError, StateValidationError) as error:
            issues.append(_invalid_state_issue("sources.json", error))

    pages: dict[str, PageRecord] | None = None
    if "pages.json" not in missing:
        try:
            pages = decode_page_registry(_read_json_object(meta / "pages.json"))
        except (OSError, UnicodeError, json.JSONDecodeError, StateValidationError) as error:
            issues.append(_invalid_state_issue("pages.json", error))

    operations: dict[str, OperationRecord] | None = None
    if "operations.json" not in missing:
        try:
            operations = _load_operations(meta / "operations.json")
        except (OSError, UnicodeError, json.JSONDecodeError, StateValidationError) as error:
            issues.append(_invalid_state_issue("operations.json", error))

    events: tuple[dict[str, object], ...] | None = None
    if "change-log.jsonl" not in missing:
        try:
            events, tail_issue = _read_change_log(meta / "change-log.jsonl")
            if tail_issue is not None:
                issues.append(tail_issue)
        except (OSError, ChangeLogError) as error:
            issues.append(_invalid_state_issue("change-log.jsonl", error))

    return (
        DoctorStateSnapshot(
            True,
            schema,
            sources,
            pages,
            operations,
            events,
        ),
        _sort_issues(issues),
    )


def inspect_state_consistency(
    control_center: Path,
    *,
    now: datetime | None = None,
    pid_exists: Callable[[int], bool] = default_pid_exists,
) -> tuple[ConsistencyIssue, ...]:
    del now, pid_exists
    _, issues = load_doctor_state(control_center)
    return issues
