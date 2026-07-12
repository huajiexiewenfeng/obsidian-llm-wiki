from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from .managed import (
    MANAGED_END,
    MANAGED_START,
    ManagedConflict,
    canonical_managed_body,
    inspect_managed_page,
    inspect_projection_region,
)
from .projection import render_ingest_index, render_wiki_index, render_wiki_log
from .state import (
    OperationRecord,
    PageRecord,
    SourceRecord,
    StateValidationError,
    decode_page_registry,
    decode_source_registry,
    file_checksum,
    registry_records,
    resolve_authoritative_source_path,
)
from .writer import classify_lock, default_pid_exists, is_atomic_temp_name


STATE_FILE_NAMES = (
    "schema.json",
    "sources.json",
    "pages.json",
    "operations.json",
    "change-log.jsonl",
)
SEVERITY_RANK = {"ERROR": 0, "WARN": 1, "INFO": 2}
AUDITED_OPERATION_KINDS = frozenset(
    {"state-init", "ingest-apply", "page-apply", "inventory-initialize"}
)


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


def _read_text_preserving_newlines(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def _safe_registered_path(
    control_center: Path,
    record: PageRecord,
) -> tuple[Path | None, ConsistencyIssue | None]:
    candidate = control_center / record.relative_path
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(control_center)
    except (OSError, ValueError):
        return (
            None,
            _issue(
                "unsafe-registered-path",
                "ERROR",
                record.relative_path,
                f"Registered page {record.page_id} resolves outside the control center.",
                hint="Repair the page registry path before reading or updating this page.",
            ),
        )
    return resolved, None


def _check_sources(
    control_center: Path,
    snapshot: DoctorStateSnapshot,
) -> list[ConsistencyIssue]:
    if snapshot.sources is None:
        return []
    issues: list[ConsistencyIssue] = []
    for source_id, source in sorted(snapshot.sources.items()):
        if source.status == "failed":
            issues.append(
                _issue(
                    "failed-source",
                    "WARN",
                    ".meta/sources.json",
                    f"Source {source_id} is marked failed.",
                    hint="Review the failed source and its latest ingest operation before retrying.",
                )
            )
        if source.status != "processed":
            continue
        if not source.proxy_page_id:
            issues.append(
                _issue(
                    "processed-source-missing-proxy",
                    "ERROR",
                    ".meta/sources.json",
                    f"Processed source {source_id} has no proxy page ID.",
                    hint="Repair the source-to-proxy registry relationship before continuing.",
                )
            )
            continue
        if snapshot.pages is None:
            continue
        page = snapshot.pages.get(source.proxy_page_id)
        if page is None:
            issues.append(
                _issue(
                    "processed-source-missing-proxy",
                    "ERROR",
                    ".meta/sources.json",
                    f"Processed source {source_id} references an unknown proxy page.",
                    hint="Restore the proxy page record or repair the source registry reference.",
                )
            )
            continue
        target, unsafe = _safe_registered_path(control_center, page)
        if unsafe is None and target is not None and not target.is_file():
            issues.append(
                _issue(
                    "source-proxy-file-missing",
                    "ERROR",
                    page.relative_path,
                    f"Source proxy file for {source_id} is missing.",
                    hint="Restore the registered proxy Markdown file before retrying ingest.",
                )
            )
    return issues


def _check_archives(
    control_center: Path,
    snapshot: DoctorStateSnapshot,
) -> list[ConsistencyIssue]:
    if snapshot.sources is None:
        return []
    issues: list[ConsistencyIssue] = []
    for source_id, record in sorted(snapshot.sources.items()):
        if record.mode != "archive-import":
            if record.archive_relative_path is not None:
                issues.append(
                    _issue(
                        "unexpected-archive-path",
                        "ERROR",
                        ".meta/sources.json",
                        f"Non-archive source {source_id} declares an archive path.",
                        hint=(
                            "Remove the archive field or correct the source mode "
                            "through Maintain."
                        ),
                    )
                )
            continue
        relative = record.archive_relative_path
        if relative is None:
            issues.append(
                _issue(
                    "archive-record-missing-path",
                    "ERROR",
                    ".meta/sources.json",
                    f"Archive source {source_id} has no archive path.",
                    hint=(
                        "Review the failed ingest operation before repairing the "
                        "source record."
                    ),
                )
            )
            continue
        try:
            target = resolve_authoritative_source_path(control_center, record)
        except (OSError, StateValidationError):
            issues.append(
                _issue(
                    "unsafe-archive-path",
                    "ERROR",
                    ".meta/sources.json",
                    f"Archive source {source_id} has an unsafe archive path.",
                    hint=(
                        "Repair the archive path without reading outside the "
                        "control center."
                    ),
                )
            )
            continue
        if not target.is_file():
            issues.append(
                _issue(
                    "archive-file-missing",
                    "ERROR",
                    relative,
                    f"Archive file for {source_id} is missing.",
                    hint=(
                        "Review the source and operation before retrying archive import."
                    ),
                )
            )
            continue
        try:
            actual_checksum = file_checksum(target)
        except OSError:
            actual_checksum = None
        if actual_checksum != record.checksum:
            issues.append(
                _issue(
                    "archive-checksum-drift",
                    "ERROR",
                    relative,
                    f"Archive checksum for {source_id} differs from the registry.",
                    hint=(
                        "Do not overwrite the archive; inspect the file and operation "
                        "history."
                    ),
                )
            )
        if snapshot.events is None:
            continue
        event = next(
            (
                item
                for item in reversed(snapshot.events)
                if item.get("kind") == "ingest-apply"
                and item.get("result") == "completed"
                and isinstance(item.get("record_ids"), list)
                and source_id in item["record_ids"]
            ),
            None,
        )
        summary = event.get("summary") if isinstance(event, dict) else None
        if (
            isinstance(summary, dict)
            and summary.get("archive_target") not in (None, relative)
        ):
            issues.append(
                _issue(
                    "archive-operation-target-drift",
                    "ERROR",
                    relative,
                    f"Archive event target for {source_id} differs from the registry.",
                    hint=(
                        "Review the completed event before repairing either path."
                    ),
                )
            )
    return issues


def _frontmatter_matches(record: PageRecord, fields: Mapping[str, object]) -> bool:
    source_ids = fields.get("llm_wiki_source_ids")
    return (
        fields.get("llm_wiki_page_id") == record.page_id
        and fields.get("llm_wiki_page_type") == record.page_type
        and isinstance(source_ids, list)
        and all(isinstance(item, str) for item in source_ids)
        and tuple(sorted(source_ids)) == tuple(sorted(record.source_ids))
    )


def _check_pages(
    control_center: Path,
    snapshot: DoctorStateSnapshot,
) -> list[ConsistencyIssue]:
    if snapshot.pages is None:
        return []
    issues: list[ConsistencyIssue] = []
    registered_paths: set[str] = set()

    for _, record in sorted(snapshot.pages.items()):
        registered_paths.add(record.relative_path.casefold())
        target, unsafe = _safe_registered_path(control_center, record)
        if unsafe is not None:
            issues.append(unsafe)
            continue
        if target is None or not target.is_file():
            issues.append(
                _issue(
                    "registered-page-missing",
                    "ERROR",
                    record.relative_path,
                    f"Registered page {record.page_id} is missing.",
                    hint="Restore the page file or repair the page registry entry.",
                )
            )
            continue
        try:
            page = inspect_managed_page(_read_text_preserving_newlines(target))
        except (OSError, UnicodeError, ManagedConflict) as error:
            issues.append(
                _issue(
                    "managed-marker-conflict",
                    "ERROR",
                    record.relative_path,
                    f"Registered page {record.page_id} cannot be safely parsed ({error.__class__.__name__}).",
                    hint="Review the managed/frontmatter markers before applying any page repair.",
                )
            )
            continue
        if not _frontmatter_matches(record, page.fields):
            issues.append(
                _issue(
                    "page-frontmatter-drift",
                    "ERROR",
                    record.relative_path,
                    f"Managed frontmatter for {record.page_id} differs from the page registry.",
                    hint="Reconcile page identity, type, and source IDs before applying content.",
                )
            )
        mirror = page.fields.get("llm_wiki_managed_checksum")
        if (
            mirror != page.computed_checksum
            or record.managed_checksum != page.computed_checksum
        ):
            issues.append(
                _issue(
                    "managed-checksum-drift",
                    "ERROR",
                    record.relative_path,
                    f"Managed checksum evidence for {record.page_id} is inconsistent.",
                    hint="Review the current managed region and registry checksum before page apply.",
                )
            )

    wiki_root = control_center / "wiki"
    if not wiki_root.is_dir():
        return issues
    for path in sorted(wiki_root.rglob("*.md")):
        try:
            relative_path = path.relative_to(control_center).as_posix()
        except ValueError:
            continue
        if relative_path.casefold() in registered_paths or not path.is_file():
            continue
        try:
            text = _read_text_preserving_newlines(path)
        except (OSError, UnicodeError):
            continue
        if MANAGED_START not in text and MANAGED_END not in text:
            continue
        issues.append(
            _issue(
                "orphan-managed-page",
                "WARN",
                relative_path,
                "Managed Markdown page has no page registry record.",
                hint="Ask the user whether to register the page or remove its managed identity.",
            )
        )
        try:
            inspect_managed_page(text)
        except ManagedConflict as error:
            issues.append(
                _issue(
                    "managed-marker-conflict",
                    "ERROR",
                    relative_path,
                    f"Orphan managed page markers are invalid ({error.__class__.__name__}).",
                    hint="Review marker structure before registering or changing this page.",
                )
            )
    return issues


def _check_projection(
    control_center: Path,
    relative_path: str,
    expected_body: str,
) -> list[ConsistencyIssue]:
    target = control_center / relative_path
    if not target.is_file():
        return []
    try:
        projection = inspect_projection_region(_read_text_preserving_newlines(target))
    except (OSError, UnicodeError, ManagedConflict) as error:
        return [
            _issue(
                "projection-marker-conflict",
                "ERROR",
                relative_path,
                f"Projection markers cannot be safely parsed ({error.__class__.__name__}).",
                hint="Review projection markers before running projection rebuild.",
            )
        ]
    if projection.managed_body == canonical_managed_body(expected_body):
        return []
    return [
        _issue(
            "projection-drift",
            "WARN",
            relative_path,
            "Projection content differs from the authoritative state renderer.",
            hint="Run projection rebuild dry-run and review the plan before confirmation.",
        )
    ]


def _check_projections(
    control_center: Path,
    snapshot: DoctorStateSnapshot,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    if snapshot.pages is not None:
        issues.extend(
            _check_projection(
                control_center,
                "wiki/index.md",
                render_wiki_index(snapshot.pages),
            )
        )
    if snapshot.sources is not None and snapshot.pages is not None:
        issues.extend(
            _check_projection(
                control_center,
                "ingest/index.md",
                render_ingest_index(snapshot.sources, snapshot.pages),
            )
        )
    if snapshot.events is not None:
        issues.extend(
            _check_projection(
                control_center,
                "wiki/log.md",
                render_wiki_log(snapshot.events),
            )
        )
    return issues


def _normalize_command(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").split())


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _lock_matches_operation(
    payload: Mapping[str, object],
    operation: OperationRecord,
    control_center: Path,
) -> bool:
    command = payload.get("command")
    target = payload.get("target")
    acquired_at = payload.get("acquired_at")
    if not isinstance(command, str) or not isinstance(target, str):
        return False
    if not isinstance(acquired_at, str):
        return False
    if _normalize_command(command) != _normalize_command(operation.kind):
        return False
    try:
        if Path(target).resolve() != control_center:
            return False
    except OSError:
        return False
    acquired = _parse_time(acquired_at)
    started = _parse_time(operation.started_at)
    return acquired is not None and started is not None and acquired <= started


def _load_lock(
    control_center: Path,
    *,
    now: datetime | None,
    pid_exists: Callable[[int], bool],
) -> tuple[str, Mapping[str, object] | None, list[ConsistencyIssue]]:
    path = control_center / ".meta/lock.json"
    if not path.exists():
        return "absent", None, []
    invalid = _issue(
        "invalid-lock",
        "ERROR",
        ".meta/lock.json",
        "Lock file is invalid and cannot prove writer ownership.",
        hint="Review the lock file and related operations before any Maintain action.",
    )
    try:
        payload = _read_json_object(path)
    except (OSError, UnicodeError, json.JSONDecodeError, StateValidationError):
        return "invalid", None, [invalid]
    command = payload.get("command")
    target = payload.get("target")
    if not isinstance(command, str) or not command.strip() or not isinstance(target, str):
        return "invalid", payload, [invalid]
    try:
        if Path(target).resolve() != control_center:
            return "invalid", payload, [invalid]
    except OSError:
        return "invalid", payload, [invalid]
    classification = classify_lock(payload, now=now, pid_exists=pid_exists)
    if classification == "invalid":
        return classification, payload, [invalid]
    if classification == "stale":
        return classification, payload, [
            _issue(
                "stale-lock",
                "WARN",
                ".meta/lock.json",
                "Same-host lock is older than the writer TTL and its PID is absent.",
                hint="Have Maintain isolate the stale lock only after user confirmation.",
            )
        ]
    if classification == "cross-host":
        return classification, payload, [
            _issue(
                "cross-host-lock",
                "WARN",
                ".meta/lock.json",
                "Lock belongs to another host and cannot be proven stale locally.",
                hint="Verify the remote writer before taking any recovery action.",
            )
        ]
    return classification, payload, []


def _check_operations(
    control_center: Path,
    snapshot: DoctorStateSnapshot,
    *,
    now: datetime | None,
    pid_exists: Callable[[int], bool],
) -> list[ConsistencyIssue]:
    classification, lock_payload, issues = _load_lock(
        control_center,
        now=now,
        pid_exists=pid_exists,
    )
    if snapshot.operations is None:
        return issues

    operations = snapshot.operations
    running = [item for item in operations.values() if item.status == "running"]
    matching = (
        [
            item
            for item in running
            if lock_payload is not None
            and _lock_matches_operation(lock_payload, item, control_center)
        ]
        if classification in {"active", "stale", "cross-host"}
        else []
    )
    newest_match = max(matching, key=lambda item: (item.updated_at, item.operation_id), default=None)

    for operation in sorted(operations.values(), key=lambda item: item.operation_id):
        if operation.status == "failed":
            related = ", ".join(operation.record_ids)
            suffix = f" Related records: {related}." if related else ""
            issues.append(
                _issue(
                    "failed-operation",
                    "WARN",
                    ".meta/operations.json",
                    f"Operation {operation.operation_id} is failed.{suffix}",
                    hint=(
                        "Review the operation step, payload, change event, and related records"
                        f" before retrying.{suffix}"
                    ),
                )
            )
        if operation.status != "running":
            continue
        if classification == "active" and operation is newest_match:
            issues.append(
                _issue(
                    "active-operation",
                    "INFO",
                    ".meta/operations.json",
                    f"Operation {operation.operation_id} matches the active writer lock.",
                    hint="Allow the writer to finish before running recovery actions.",
                )
            )
        elif classification == "stale" and operation in matching:
            issues.append(
                _issue(
                    "running-operation-with-stale-lock",
                    "ERROR",
                    ".meta/operations.json",
                    f"Running operation {operation.operation_id} only has a stale lock.",
                    hint="Review operation progress before isolating the stale lock.",
                )
            )
        elif classification == "cross-host" and operation in matching:
            continue
        else:
            issues.append(
                _issue(
                    "orphan-running-operation",
                    "ERROR",
                    ".meta/operations.json",
                    f"Running operation {operation.operation_id} has no matching active lock.",
                    hint="Review the operation and lock evidence before retry or rollback.",
                )
            )

    if snapshot.events is None:
        return issues
    completed_events = {
        str(item.get("operation_id"))
        for item in snapshot.events
        if item.get("result") == "completed" and isinstance(item.get("operation_id"), str)
    }
    for operation_id in sorted(completed_events):
        operation = operations.get(operation_id)
        if operation is not None and operation.status != "completed":
            issues.append(
                _issue(
                    "operation-event-status-drift",
                    "WARN",
                    ".meta/operations.json",
                    f"Operation {operation_id} has a completion event but is not completed.",
                    hint="Reconcile the operation status from the authoritative change event.",
                )
            )
    for operation in sorted(operations.values(), key=lambda item: item.operation_id):
        if (
            operation.status == "completed"
            and operation.kind in AUDITED_OPERATION_KINDS
            and operation.operation_id not in completed_events
        ):
            issues.append(
                _issue(
                    "missing-completion-event",
                    "ERROR",
                    ".meta/change-log.jsonl",
                    f"Completed operation {operation.operation_id} has no completion event.",
                    hint="Review the operation and change log before retrying the original payload.",
                )
            )
    return issues


def _check_pending_sources(snapshot: DoctorStateSnapshot) -> list[ConsistencyIssue]:
    if snapshot.sources is None or snapshot.operations is None:
        return []
    issues: list[ConsistencyIssue] = []
    for source_id, source in sorted(snapshot.sources.items()):
        if source.status != "pending":
            continue
        related = [
            operation
            for operation in snapshot.operations.values()
            if operation.kind == "ingest-apply" and source_id in operation.record_ids
        ]
        latest = max(
            related,
            key=lambda operation: (operation.updated_at, operation.operation_id),
            default=None,
        )
        if latest is not None and latest.status in {"running", "failed"}:
            continue
        issues.append(
            _issue(
                "pending-source-without-active-operation",
                "WARN",
                ".meta/sources.json",
                f"Pending source {source_id} has no active ingest operation.",
                hint="Review source state and related operations before retrying ingest.",
            )
        )
    return issues


def _check_temp_files(
    control_center: Path,
    snapshot: DoctorStateSnapshot,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    archive_paths = {
        record.archive_relative_path.casefold()
        for record in (snapshot.sources or {}).values()
        if record.mode == "archive-import"
        and record.archive_relative_path is not None
    }
    roots = [".meta", "wiki", "ingest"]
    if archive_paths or (control_center / "raw").is_dir():
        roots.append("raw")
    for relative_root in roots:
        root = control_center / relative_root
        if not root.is_dir():
            continue
        for directory, _, filenames in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            for name in filenames:
                if not is_atomic_temp_name(name):
                    if relative_root != "raw":
                        continue
                    path = directory_path / name
                    relative_path = path.relative_to(control_center).as_posix()
                    if relative_path.casefold() in archive_paths:
                        continue
                    issues.append(
                        _issue(
                            "unregistered-archive",
                            "WARN",
                            relative_path,
                            "File in raw/ has no archive source record.",
                            hint=(
                                "Review its origin before asking Maintain to register, "
                                "move, or remove it."
                            ),
                        )
                    )
                    continue
                path = directory_path / name
                relative_path = path.relative_to(control_center).as_posix()
                issues.append(
                    _issue(
                        "orphan-temp-file",
                        "WARN",
                        relative_path,
                        "Writer-style temporary file remains in the control center.",
                        hint="Confirm there is no active writer before asking Maintain to remove it.",
                    )
                )
    return issues


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
    snapshot, load_issues = load_doctor_state(control_center)
    if not snapshot.meta_enabled or snapshot.schema is None:
        return load_issues
    issues = list(load_issues)
    resolved = control_center.resolve()
    issues.extend(_check_sources(resolved, snapshot))
    issues.extend(_check_archives(resolved, snapshot))
    issues.extend(_check_pages(resolved, snapshot))
    issues.extend(_check_projections(resolved, snapshot))
    issues.extend(
        _check_operations(
            resolved,
            snapshot,
            now=now,
            pid_exists=pid_exists,
        )
    )
    issues.extend(_check_pending_sources(snapshot))
    issues.extend(_check_temp_files(resolved, snapshot))
    return _sort_issues(issues)
