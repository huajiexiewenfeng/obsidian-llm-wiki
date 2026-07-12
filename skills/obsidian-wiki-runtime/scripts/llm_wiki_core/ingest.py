from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, TextIO

from .state import (
    PAGE_TYPES,
    PageRecord,
    SourceRecord,
    StateValidationError,
    canonical_path,
    casefold_path_key,
    decode_page_registry,
    decode_source_registry,
    file_checksum,
    file_fingerprint,
    stable_record_id,
    validate_relative_path,
)
from .writer import (
    VaultLock,
    append_change_event,
    atomic_write_json,
    atomic_write_text,
    begin_operation,
    file_text_checksum,
    read_json_object,
    update_operation,
    utc_now,
)

PAYLOAD_SCHEMA_VERSION = 1
INGEST_MODES = frozenset({"path-index", "summary-ingest"})
SENSITIVITIES = frozenset({"normal", "sensitive"})
PAGE_ROLES = frozenset({"source-proxy", "derived"})
DERIVED_PAGE_TYPES = frozenset({"topic", "project", "entity", "sop"})
PROJECTION_PATHS = frozenset({"wiki/index.md", "ingest/index.md", "wiki/log.md"})
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


class IngestValidationError(ValueError):
    def __init__(self, message: str, *, check: str = "invalid-payload") -> None:
        super().__init__(message)
        self.check = check


class IngestPlanConflict(ValueError):
    def __init__(self, message: str, *, check: str) -> None:
        super().__init__(message)
        self.check = check


class IngestWriteError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        current_step: str,
        completed_targets: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.current_step = current_step
        self.completed_targets = completed_targets


@dataclass(frozen=True)
class MoveResolution:
    action: str
    source_id: str | None = None


@dataclass(frozen=True)
class SourceInput:
    path: Path
    source_type: str
    mode: str
    fingerprint: Mapping[str, int]
    checksum: str
    sensitivity: str
    move_resolution: MoveResolution | None


@dataclass(frozen=True)
class PageMutation:
    role: str
    page_type: str
    relative_path: str
    managed_body: str
    expected_managed_checksum: str | None
    takeover: bool


@dataclass(frozen=True)
class IngestPayload:
    schema_version: int
    source: SourceInput
    pages: tuple[PageMutation, ...]
    projection_takeovers: tuple[str, ...]


@dataclass(frozen=True)
class SourcePlan:
    source_id: str
    action: str
    revision: int
    candidate_source_ids: tuple[str, ...] = ()
    conflict: Mapping[str, object] | None = None

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_id": self.source_id,
            "action": self.action,
            "revision": self.revision,
            "candidate_source_ids": list(self.candidate_source_ids),
        }
        if self.conflict:
            payload.update(self.conflict)
        return payload


@dataclass(frozen=True)
class IngestPlan:
    control_center: Path
    source: SourcePlan
    pages: tuple["PagePlan", ...]
    projections: tuple["ProjectionPlan", ...]
    expected_checksums: Mapping[str, str | None]
    idempotency_key: str
    plan_checksum: str
    confirmable: bool
    confirmation_required: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "control_center": str(self.control_center),
            "source": self.source.to_public_dict(),
            "pages": [page.to_public_dict() for page in self.pages],
            "projections": [projection.to_public_dict() for projection in self.projections],
            "expected_checksums": dict(sorted(self.expected_checksums.items())),
            "idempotency_key": self.idempotency_key,
            "plan_checksum": self.plan_checksum,
            "confirmable": self.confirmable,
            "confirmation_required": self.confirmation_required,
        }


@dataclass(frozen=True)
class IngestResult:
    status: str
    operation_id: str
    idempotency_key: str
    source_id: str
    record_ids: tuple[str, ...]
    idempotent: bool = False


def _object(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise IngestValidationError(f"{field} must be an object")
    return value


def _strict_fields(
    payload: Mapping[str, object],
    field: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    unknown = sorted(set(payload) - allowed)
    missing = sorted(required - set(payload))
    if unknown:
        raise IngestValidationError(f"{field} has unknown fields: {', '.join(unknown)}")
    if missing:
        raise IngestValidationError(f"{field} is missing fields: {', '.join(missing)}")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestValidationError(f"{field} must be a non-empty string")
    return value


def _sha256(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    text = _string(value, field)
    if SHA256_PATTERN.fullmatch(text) is None:
        raise IngestValidationError(f"{field} must be a lowercase sha256 checksum")
    return text


def _parse_move_resolution(value: object) -> MoveResolution | None:
    if value is None:
        return None
    payload = _object(value, "source.move_resolution")
    action = payload.get("action")
    if action == "rebind":
        _strict_fields(
            payload,
            "source.move_resolution",
            required={"action", "source_id"},
        )
        return MoveResolution(
            action="rebind",
            source_id=_string(payload["source_id"], "source.move_resolution.source_id"),
        )
    if action == "new-source":
        _strict_fields(payload, "source.move_resolution", required={"action"})
        return MoveResolution(action="new-source")
    raise IngestValidationError("source.move_resolution.action is invalid")


def _parse_source(value: object) -> SourceInput:
    payload = _object(value, "source")
    _strict_fields(
        payload,
        "source",
        required={
            "path",
            "source_type",
            "mode",
            "fingerprint",
            "checksum",
            "sensitivity",
            "move_resolution",
        },
    )
    mode = _string(payload["mode"], "source.mode")
    if mode == "archive-import":
        raise IngestValidationError(
            "source.mode archive-import is deferred to Phase 3.1",
            check="unsupported-mode",
        )
    if mode not in INGEST_MODES:
        raise IngestValidationError("source.mode is invalid")
    sensitivity = _string(payload["sensitivity"], "source.sensitivity")
    if sensitivity not in SENSITIVITIES:
        raise IngestValidationError("source.sensitivity is invalid")
    fingerprint = _object(payload["fingerprint"], "source.fingerprint")
    _strict_fields(
        fingerprint,
        "source.fingerprint",
        required={"size", "mtime_ns"},
    )
    if any(
        isinstance(fingerprint[name], bool)
        or not isinstance(fingerprint[name], int)
        or fingerprint[name] < 0
        for name in ("size", "mtime_ns")
    ):
        raise IngestValidationError("source.fingerprint values must be non-negative integers")
    checksum = _sha256(payload["checksum"], "source.checksum")
    assert checksum is not None
    source_path = Path(_string(payload["path"], "source.path"))
    if not source_path.is_absolute():
        raise IngestValidationError("source.path must be absolute")
    return SourceInput(
        path=source_path,
        source_type=_string(payload["source_type"], "source.source_type"),
        mode=mode,
        fingerprint={"size": fingerprint["size"], "mtime_ns": fingerprint["mtime_ns"]},
        checksum=checksum,
        sensitivity=sensitivity,
        move_resolution=_parse_move_resolution(payload["move_resolution"]),
    )


def _parse_page(value: object, index: int) -> PageMutation:
    field = f"pages[{index}]"
    payload = _object(value, field)
    _strict_fields(
        payload,
        field,
        required={
            "role",
            "page_type",
            "path",
            "managed_body",
            "expected_managed_checksum",
            "takeover",
        },
    )
    role = _string(payload["role"], f"{field}.role")
    page_type = _string(payload["page_type"], f"{field}.page_type")
    if role not in PAGE_ROLES:
        raise IngestValidationError(f"{field}.role is invalid")
    if page_type not in PAGE_TYPES:
        raise IngestValidationError(f"{field}.page_type is invalid")
    if role == "source-proxy" and page_type != "source":
        raise IngestValidationError("source-proxy page_type must be source")
    if role == "derived" and page_type not in DERIVED_PAGE_TYPES:
        raise IngestValidationError("derived page_type is invalid")
    managed_body = payload["managed_body"]
    if not isinstance(managed_body, str):
        raise IngestValidationError(f"{field}.managed_body must be a string")
    takeover = payload["takeover"]
    if not isinstance(takeover, bool):
        raise IngestValidationError(f"{field}.takeover must be a boolean")
    expected = _sha256(
        payload["expected_managed_checksum"],
        f"{field}.expected_managed_checksum",
        nullable=True,
    )
    try:
        relative_path = validate_relative_path(
            _string(payload["path"], f"{field}.path"),
            f"{field}.path",
        )
    except StateValidationError as error:
        raise IngestValidationError(str(error)) from error
    return PageMutation(
        role=role,
        page_type=page_type,
        relative_path=relative_path,
        managed_body=managed_body,
        expected_managed_checksum=expected,
        takeover=takeover,
    )


def load_payload_text(text: str) -> IngestPayload:
    try:
        decoded = json.loads(text)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise IngestValidationError("payload must be valid UTF-8 JSON") from error
    payload = _object(decoded, "payload")
    _strict_fields(
        payload,
        "payload",
        required={"schema_version", "source", "pages", "projection_takeovers"},
    )
    if payload["schema_version"] != PAYLOAD_SCHEMA_VERSION:
        raise IngestValidationError("schema_version must be 1")
    raw_pages = payload["pages"]
    if not isinstance(raw_pages, list):
        raise IngestValidationError("pages must be an array")
    pages = tuple(_parse_page(item, index) for index, item in enumerate(raw_pages))
    if sum(page.role == "source-proxy" for page in pages) != 1:
        raise IngestValidationError("pages must contain exactly one source-proxy")
    keys = [casefold_path_key(page.relative_path, windows=True) for page in pages]
    if len(keys) != len(set(keys)):
        raise IngestValidationError("page paths conflict after case folding")
    raw_takeovers = payload["projection_takeovers"]
    if not isinstance(raw_takeovers, list) or not all(
        isinstance(item, str) for item in raw_takeovers
    ):
        raise IngestValidationError("projection_takeovers must be a string array")
    takeovers = tuple(sorted(set(raw_takeovers)))
    if any(path not in PROJECTION_PATHS for path in takeovers):
        raise IngestValidationError("projection_takeovers contains an invalid path")
    return IngestPayload(
        schema_version=PAYLOAD_SCHEMA_VERSION,
        source=_parse_source(payload["source"]),
        pages=pages,
        projection_takeovers=takeovers,
    )


def load_payload_file(path: str, stdin: TextIO) -> IngestPayload:
    if path == "-":
        return load_payload_text(stdin.read())
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise IngestValidationError("payload file could not be read") from error
    return load_payload_text(text)


def normalized_payload_dict(payload: IngestPayload) -> dict[str, object]:
    resolution = payload.source.move_resolution
    return {
        "schema_version": payload.schema_version,
        "source": {
            "path": payload.source.path.as_posix(),
            "source_type": payload.source.source_type,
            "mode": payload.source.mode,
            "fingerprint": dict(payload.source.fingerprint),
            "checksum": payload.source.checksum,
            "sensitivity": payload.source.sensitivity,
            "move_resolution": (
                None
                if resolution is None
                else {
                    "action": resolution.action,
                    **({"source_id": resolution.source_id} if resolution.source_id else {}),
                }
            ),
        },
        "pages": [
            {
                "role": page.role,
                "page_type": page.page_type,
                "path": page.relative_path,
                "managed_body": page.managed_body,
                "expected_managed_checksum": page.expected_managed_checksum,
                "takeover": page.takeover,
            }
            for page in payload.pages
        ],
        "projection_takeovers": list(payload.projection_takeovers),
    }


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _resolve_source(
    payload: IngestPayload,
    sources: Mapping[str, SourceRecord],
) -> tuple[SourcePlan, SourceRecord | None]:
    source_path = canonical_path(payload.source.path)
    path_key = casefold_path_key(source_path, windows=True)
    same_path = [
        record
        for record in sources.values()
        if casefold_path_key(record.canonical_path, windows=True) == path_key
    ]
    if len(same_path) > 1:
        raise IngestPlanConflict(
            "source registry contains duplicate canonical paths",
            check="source-registry-conflict",
        )
    if same_path:
        record = same_path[0]
        action = "unchanged" if record.checksum == payload.source.checksum else "update"
        revision = record.revision if action == "unchanged" else record.revision + 1
        return SourcePlan(record.source_id, action, revision), record

    candidates = tuple(
        sorted(
            record.source_id
            for record in sources.values()
            if record.checksum == payload.source.checksum
        )
    )
    resolution = payload.source.move_resolution
    if candidates and resolution is None:
        return (
            SourcePlan(
                "",
                "move-conflict",
                1,
                candidates,
                {
                    "check": "move-candidate",
                    "resolution_actions": ["rebind", "new-source"],
                },
            ),
            None,
        )
    if resolution and resolution.action == "rebind":
        if resolution.source_id not in candidates:
            return (
                SourcePlan(
                    resolution.source_id or "",
                    "move-conflict",
                    1,
                    candidates,
                    {"check": "invalid-move-candidate"},
                ),
                None,
            )
        record = sources[resolution.source_id]
        if Path(record.display_path).exists():
            return (
                SourcePlan(
                    record.source_id,
                    "source-copy-not-move",
                    record.revision,
                    candidates,
                    {
                        "check": "source-copy-not-move",
                        "resolution_actions": ["new-source"],
                    },
                ),
                record,
            )
        return SourcePlan(record.source_id, "rebind", record.revision + 1), record
    seed = path_key
    if resolution and resolution.action == "new-source":
        seed += "|new-source|" + payload.source.checksum
    source_id = stable_record_id("src", seed)
    return SourcePlan(source_id, "create", 1), None


def _planned_source_record(
    payload: IngestPayload,
    source: SourcePlan,
    previous: SourceRecord | None,
    proxy_page_id: str | None,
    *,
    status: str = "pending",
    verified_at: str | None = None,
) -> SourceRecord:
    return SourceRecord(
        source_id=source.source_id,
        display_path=str(payload.source.path),
        canonical_path=canonical_path(payload.source.path),
        source_type=payload.source.source_type,
        mode=payload.source.mode,
        status=status,
        fingerprint=dict(payload.source.fingerprint),
        checksum=payload.source.checksum,
        proxy_page_id=proxy_page_id,
        sensitivity=payload.source.sensitivity,
        last_verified_at=(
            verified_at
            or (previous.last_verified_at if previous else "pending-confirmation")
        ),
        revision=source.revision,
    )


def _planned_page_records(
    existing: Mapping[str, PageRecord],
    mutations: tuple[PageMutation, ...],
    page_plans: tuple["PagePlan", ...],
    source_id: str,
) -> dict[str, PageRecord]:
    records = dict(existing)
    by_path = {mutation.relative_path: mutation for mutation in mutations}
    for page in page_plans:
        if page.action == "conflict":
            continue
        mutation = by_path[page.relative_path]
        previous = records.get(page.page_id)
        revision = previous.revision if previous else 1
        if previous and page.action == "update":
            revision += 1
        records[page.page_id] = PageRecord(
            page_id=page.page_id,
            relative_path=page.relative_path,
            page_type=mutation.page_type,
            source_ids=(source_id,),
            managed_checksum=page.new_managed_checksum,
            revision=revision,
        )
    return records


def plan_ingest(control_center: Path, payload: IngestPayload) -> IngestPlan:
    from .page import plan_page_mutation
    from .projection import plan_projections, read_change_events

    control_center = control_center.resolve()
    actual_fingerprint = file_fingerprint(payload.source.path)
    if actual_fingerprint != dict(payload.source.fingerprint):
        raise IngestPlanConflict(
            "source fingerprint changed after payload creation",
            check="source-fingerprint-conflict",
        )
    if file_checksum(payload.source.path) != payload.source.checksum:
        raise IngestPlanConflict(
            "source checksum changed after payload creation",
            check="source-checksum-conflict",
        )
    meta = control_center / ".meta"
    sources_path = meta / "sources.json"
    pages_path = meta / "pages.json"
    change_log_path = meta / "change-log.jsonl"
    try:
        sources = decode_source_registry(read_json_object(sources_path))
        pages = decode_page_registry(read_json_object(pages_path))
        events = read_change_events(change_log_path)
    except (OSError, ValueError, StateValidationError) as error:
        raise IngestPlanConflict(str(error), check="invalid-state") from error

    source_plan, previous_source = _resolve_source(payload, sources)
    if source_plan.action in {"move-conflict", "source-copy-not-move"}:
        page_plans: tuple["PagePlan", ...] = ()
        projection_plans: tuple["ProjectionPlan", ...] = ()
    else:
        page_plans = tuple(
            plan_page_mutation(
                control_center,
                mutation,
                pages,
                (source_plan.source_id,),
            )
            for mutation in payload.pages
        )
        planned_pages = _planned_page_records(
            pages, payload.pages, page_plans, source_plan.source_id
        )
        proxy_path = next(
            mutation.relative_path
            for mutation in payload.pages
            if mutation.role == "source-proxy"
        )
        proxy_page_id = next(
            page.page_id for page in page_plans if page.relative_path == proxy_path
        )
        planned_sources = dict(sources)
        planned_sources[source_plan.source_id] = _planned_source_record(
            payload,
            source_plan,
            previous_source,
            proxy_page_id,
            status="processed",
        )
        next_sequence = max(
            (
                event.get("sequence", 0)
                for event in events
                if isinstance(event.get("sequence"), int)
            ),
            default=0,
        ) + 1
        prospective_event = {
            "sequence": next_sequence,
            "operation_id": "pending-confirmation",
            "kind": "ingest-apply",
            "record_ids": [source_plan.source_id]
            + sorted(page.page_id for page in page_plans),
            "result": "completed",
        }
        projection_plans = plan_projections(
            control_center,
            planned_sources,
            planned_pages,
            events,
            payload.projection_takeovers,
            prospective_event=prospective_event,
        )

    expected: dict[str, str | None] = {
        ".meta/sources.json": file_text_checksum(sources_path),
        ".meta/pages.json": file_text_checksum(pages_path),
        ".meta/change-log.jsonl": file_text_checksum(change_log_path),
    }
    for page in page_plans:
        expected[page.relative_path] = page.expected_file_checksum
    for projection in projection_plans:
        expected[projection.relative_path] = projection.expected_file_checksum
    idempotency_key = _digest(
        {
            "control_center": canonical_path(control_center),
            "source_id": source_plan.source_id,
            "source_checksum": payload.source.checksum,
            "payload": normalized_payload_dict(payload),
            "projection_targets": sorted(PROJECTION_PATHS),
        }
    )
    confirmable = (
        source_plan.action not in {"move-conflict", "source-copy-not-move"}
        and all(page.action != "conflict" for page in page_plans)
        and all(projection.action != "conflict" for projection in projection_plans)
    )
    unsigned = {
        "control_center": canonical_path(control_center),
        "source": source_plan.to_public_dict(),
        "pages": [page.to_public_dict() for page in page_plans],
        "projections": [projection.to_public_dict() for projection in projection_plans],
        "expected_checksums": dict(sorted(expected.items())),
        "idempotency_key": idempotency_key,
        "confirmable": confirmable,
    }
    plan_checksum = _digest(unsigned)
    return IngestPlan(
        control_center=control_center,
        source=source_plan,
        pages=page_plans,
        projections=projection_plans,
        expected_checksums=expected,
        idempotency_key=idempotency_key,
        plan_checksum=plan_checksum,
        confirmable=confirmable,
        confirmation_required=confirmable,
    )


def _registry_payload(records: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "records": {
            key: value.to_dict()
            for key, value in sorted(records.items())
        },
    }


def _completed_event(
    events: tuple[dict[str, object], ...], idempotency_key: str
) -> dict[str, object] | None:
    for event in reversed(events):
        if (
            event.get("idempotency_key") == idempotency_key
            and event.get("result") == "completed"
        ):
            return event
    return None


def apply_ingest(
    control_center: Path,
    payload: IngestPayload,
    confirmed_plan_checksum: str,
    *,
    fail_after_step: str | None = None,
) -> IngestResult:
    from .projection import plan_projections, read_change_events

    control_center = control_center.resolve()
    meta = control_center / ".meta"
    operations_path = meta / "operations.json"
    lock = VaultLock(
        meta / "lock.json",
        allowed_root=control_center,
        command="ingest apply",
        target=control_center,
    )
    with lock:
        refreshed = plan_ingest(control_center, payload)
        events = read_change_events(meta / "change-log.jsonl")
        completed = _completed_event(events, refreshed.idempotency_key)
        if completed is not None:
            operation_id = str(completed.get("operation_id", ""))
            try:
                update_operation(
                    operations_path,
                    operation_id,
                    allowed_root=control_center,
                    status="completed",
                    current_step="complete",
                )
            except (KeyError, OSError, ValueError):
                pass
            record_ids = tuple(
                item
                for item in completed.get("record_ids", [])
                if isinstance(item, str)
            )
            return IngestResult(
                status="completed",
                operation_id=operation_id,
                idempotency_key=refreshed.idempotency_key,
                source_id=refreshed.source.source_id,
                record_ids=record_ids,
                idempotent=True,
            )
        if refreshed.plan_checksum != confirmed_plan_checksum:
            raise IngestPlanConflict(
                "confirmed plan checksum no longer matches current state",
                check="plan-conflict",
            )
        if not refreshed.confirmable:
            check = refreshed.source.conflict.get("check") if refreshed.source.conflict else None
            raise IngestPlanConflict(
                "ingest plan contains unresolved conflicts",
                check=str(check or "plan-not-confirmable"),
            )

        sources_path = meta / "sources.json"
        pages_path = meta / "pages.json"
        change_log_path = meta / "change-log.jsonl"
        sources = decode_source_registry(read_json_object(sources_path))
        pages = decode_page_registry(read_json_object(pages_path))
        source_plan, previous_source = _resolve_source(payload, sources)
        planned_pages = _planned_page_records(
            pages, payload.pages, refreshed.pages, source_plan.source_id
        )
        proxy_path = next(
            mutation.relative_path
            for mutation in payload.pages
            if mutation.role == "source-proxy"
        )
        proxy_page_id = next(
            page.page_id for page in refreshed.pages if page.relative_path == proxy_path
        )
        verified_at = utc_now()
        pending_source = _planned_source_record(
            payload,
            source_plan,
            previous_source,
            proxy_page_id,
            status="pending",
            verified_at=verified_at,
        )
        processed_source = _planned_source_record(
            payload,
            source_plan,
            previous_source,
            proxy_page_id,
            status="processed",
            verified_at=verified_at,
        )
        pending_sources = dict(sources)
        pending_sources[source_plan.source_id] = pending_source
        processed_sources = dict(sources)
        processed_sources[source_plan.source_id] = processed_source
        record_ids = (source_plan.source_id,) + tuple(
            sorted(page.page_id for page in refreshed.pages)
        )
        operation = begin_operation(
            operations_path,
            allowed_root=control_center,
            kind="ingest-apply",
            idempotency_key=refreshed.idempotency_key,
            record_ids=list(record_ids),
            reuse_completed=False,
        )
        completed_targets: list[str] = []
        current_step = "start"

        def enter(step: str) -> None:
            nonlocal current_step
            current_step = step
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=control_center,
                status="running",
                current_step=step,
            )

        def inject() -> None:
            if fail_after_step == current_step:
                raise RuntimeError(f"injected failure after {current_step}")

        try:
            enter("write-source-pending")
            atomic_write_json(
                sources_path,
                _registry_payload(pending_sources),
                allowed_root=control_center,
                expected_checksum=refreshed.expected_checksums[".meta/sources.json"],
            )
            completed_targets.append(".meta/sources.json")
            inject()

            enter("write-pages")
            for page in refreshed.pages:
                if page.action == "unchanged":
                    continue
                atomic_write_text(
                    control_center / page.relative_path,
                    page.rendered_text,
                    allowed_root=control_center,
                    expected_checksum=page.expected_file_checksum,
                )
                completed_targets.append(page.relative_path)
            inject()

            enter("write-page-registry")
            atomic_write_json(
                pages_path,
                _registry_payload(planned_pages),
                allowed_root=control_center,
                expected_checksum=refreshed.expected_checksums[".meta/pages.json"],
            )
            completed_targets.append(".meta/pages.json")
            inject()

            next_sequence = max(
                (
                    event.get("sequence", 0)
                    for event in events
                    if isinstance(event.get("sequence"), int)
                ),
                default=0,
            ) + 1
            prospective = {
                "sequence": next_sequence,
                "operation_id": operation.operation_id,
                "kind": "ingest-apply",
                "record_ids": list(record_ids),
                "result": "completed",
            }
            projections = plan_projections(
                control_center,
                processed_sources,
                planned_pages,
                events,
                payload.projection_takeovers,
                prospective_event=prospective,
            )
            if any(projection.action == "conflict" for projection in projections):
                raise IngestPlanConflict(
                    "projection changed after confirmation",
                    check="plan-conflict",
                )
            enter("write-projections")
            for projection in projections:
                if projection.action == "unchanged":
                    continue
                atomic_write_text(
                    control_center / projection.relative_path,
                    projection.rendered_text,
                    allowed_root=control_center,
                    expected_checksum=projection.expected_file_checksum,
                )
                completed_targets.append(projection.relative_path)
            inject()

            enter("write-source-processed")
            atomic_write_json(
                sources_path,
                _registry_payload(processed_sources),
                allowed_root=control_center,
                expected_checksum=file_text_checksum(sources_path),
            )
            inject()

            enter("append-change-log")
            append_change_event(
                change_log_path,
                allowed_root=control_center,
                operation_id=operation.operation_id,
                kind="ingest-apply",
                record_ids=list(record_ids),
                old_checksums={},
                new_checksums={
                    "sources.json": file_text_checksum(sources_path),
                    "pages.json": file_text_checksum(pages_path),
                },
                result="completed",
                idempotency_key=refreshed.idempotency_key,
                summary={"source_action": source_plan.action},
            )
            completed_targets.append(".meta/change-log.jsonl")
            inject()

            enter("complete")
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=control_center,
                status="completed",
                current_step="complete",
            )
            inject()
            return IngestResult(
                status="completed",
                operation_id=operation.operation_id,
                idempotency_key=refreshed.idempotency_key,
                source_id=source_plan.source_id,
                record_ids=record_ids,
            )
        except BaseException as error:
            try:
                update_operation(
                    operations_path,
                    operation.operation_id,
                    allowed_root=control_center,
                    status="failed",
                    current_step=current_step,
                    error=str(error),
                )
            except BaseException:
                pass
            if isinstance(error, IngestPlanConflict):
                raise
            raise IngestWriteError(
                str(error),
                current_step=current_step,
                completed_targets=tuple(completed_targets),
            ) from error
