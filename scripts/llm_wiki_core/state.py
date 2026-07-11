from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

SCHEMA_VERSION = 1
SOURCE_STATUSES = frozenset({"pending", "processed", "failed"})
SOURCE_MODES = frozenset({"path-index", "summary-ingest", "archive-import"})
PAGE_TYPES = frozenset({"source", "topic", "project", "entity", "sop", "index", "log"})


class StateValidationError(ValueError):
    pass


def require_string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise StateValidationError(f"{field} must be a non-empty string")
    return value


def validate_relative_path(value: str, field: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise StateValidationError(f"{field} must be a control-center-relative path")
    return path.as_posix()


def stable_record_id(prefix: str, seed: str) -> str:
    if prefix not in {"src", "page", "op"}:
        raise StateValidationError("record id prefix is invalid")
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def canonical_path(path: Path) -> str:
    return path.expanduser().resolve().as_posix()


def ensure_within(path: Path, allowed_root: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = allowed_root.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise StateValidationError(f"unsafe_path: {resolved} is outside allowed root {root}") from error
    return resolved


def casefold_path_key(value: str, *, windows: bool | None = None) -> str:
    normalized = value.replace("\\", "/")
    use_windows = os.name == "nt" if windows is None else windows
    return normalized.casefold() if use_windows else normalized


def file_fingerprint(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def file_checksum(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    display_path: str
    canonical_path: str
    source_type: str
    mode: str
    status: str
    fingerprint: dict[str, int]
    checksum: str | None
    proxy_page_id: str | None
    sensitivity: str
    last_verified_at: str
    revision: int = 1

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SourceRecord":
        fingerprint = payload.get("fingerprint")
        if not isinstance(fingerprint, dict) or set(fingerprint) != {"size", "mtime_ns"}:
            raise StateValidationError("fingerprint must contain size and mtime_ns")
        if any(not isinstance(value, int) or value < 0 for value in fingerprint.values()):
            raise StateValidationError("fingerprint values must be non-negative integers")
        status = require_string(payload.get("status"), "status")
        mode = require_string(payload.get("mode"), "mode")
        checksum = payload.get("checksum")
        proxy_page_id = payload.get("proxy_page_id")
        revision = payload.get("revision", 1)
        if checksum is not None and not isinstance(checksum, str):
            raise StateValidationError("checksum must be a string or null")
        if proxy_page_id is not None and not isinstance(proxy_page_id, str):
            raise StateValidationError("proxy_page_id must be a string or null")
        if not isinstance(revision, int) or revision < 1:
            raise StateValidationError("revision must be positive")
        if status not in SOURCE_STATUSES:
            raise StateValidationError("source status is invalid")
        if mode not in SOURCE_MODES:
            raise StateValidationError("source mode is invalid")
        return cls(
            source_id=require_string(payload.get("source_id"), "source_id"),
            display_path=require_string(payload.get("display_path"), "display_path"),
            canonical_path=require_string(payload.get("canonical_path"), "canonical_path"),
            source_type=require_string(payload.get("source_type"), "source_type"),
            mode=mode,
            status=status,
            fingerprint={"size": fingerprint["size"], "mtime_ns": fingerprint["mtime_ns"]},
            checksum=checksum,
            proxy_page_id=proxy_page_id,
            sensitivity=require_string(payload.get("sensitivity"), "sensitivity"),
            last_verified_at=require_string(payload.get("last_verified_at"), "last_verified_at"),
            revision=revision,
        )


@dataclass(frozen=True)
class PageRecord:
    page_id: str
    relative_path: str
    page_type: str
    source_ids: tuple[str, ...]
    managed_checksum: str
    revision: int = 1

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["source_ids"] = list(self.source_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PageRecord":
        source_ids = payload.get("source_ids")
        if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
            raise StateValidationError("source_ids must be a string array")
        revision = payload.get("revision", 1)
        if not isinstance(revision, int) or revision < 1:
            raise StateValidationError("revision must be positive")
        record = cls(
            page_id=require_string(payload.get("page_id"), "page_id"),
            relative_path=validate_relative_path(
                require_string(payload.get("relative_path"), "relative_path"),
                "relative_path",
            ),
            page_type=require_string(payload.get("page_type"), "page_type"),
            source_ids=tuple(source_ids),
            managed_checksum=require_string(payload.get("managed_checksum"), "managed_checksum"),
            revision=revision,
        )
        if record.page_type not in PAGE_TYPES:
            raise StateValidationError("page_type is invalid")
        return record


def empty_registry() -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "records": {}}


def registry_records(payload: Mapping[str, object]) -> Mapping[str, object]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StateValidationError("schema_version must be 1")
    records = payload.get("records")
    if not isinstance(records, dict):
        raise StateValidationError("records must be an object")
    return records


def decode_source_registry(payload: Mapping[str, object]) -> dict[str, SourceRecord]:
    result: dict[str, SourceRecord] = {}
    for key, raw in registry_records(payload).items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            raise StateValidationError("source registry entries must be objects")
        record = SourceRecord.from_dict(raw)
        if record.source_id != key:
            raise StateValidationError("source_id does not match registry key")
        result[key] = record
    return result


def decode_page_registry(payload: Mapping[str, object]) -> dict[str, PageRecord]:
    result: dict[str, PageRecord] = {}
    for key, raw in registry_records(payload).items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            raise StateValidationError("page registry entries must be objects")
        record = PageRecord.from_dict(raw)
        if record.page_id != key:
            raise StateValidationError("page_id does not match registry key")
        result[key] = record
    return result


def encode_registry(records: Mapping[str, Mapping[str, object]]) -> str:
    return json.dumps(
        {"schema_version": SCHEMA_VERSION, "records": dict(sorted(records.items()))},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
