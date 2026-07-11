from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, TextIO

from .state import (
    PAGE_TYPES,
    StateValidationError,
    casefold_path_key,
    validate_relative_path,
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
