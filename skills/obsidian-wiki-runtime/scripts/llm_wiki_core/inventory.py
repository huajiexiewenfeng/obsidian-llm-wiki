from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping


INVENTORY_SCHEMA_VERSION = 1
INVENTORY_DEFAULTS_VERSION = 1
SUPPORTED_EXTENSIONS = (
    ".csv",
    ".docx",
    ".md",
    ".markdown",
    ".pdf",
    ".txt",
    ".xls",
    ".xlsx",
)


class InventoryValidationError(ValueError):
    pass


class InventoryLoadError(InventoryValidationError):
    pass


def _normalized_pattern(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryValidationError(f"{field} must be a non-empty Vault-relative glob")
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or ".." in path.parts
    ):
        raise InventoryValidationError(f"{field} must be a Vault-relative glob")
    return normalized


def _normalized_relative_path(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryValidationError(f"{field} must be a non-empty Vault-relative path")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or re.match(r"^[A-Za-z]:/", normalized) or ".." in path.parts:
        raise InventoryValidationError(f"{field} must be a safe Vault-relative path")
    return path.as_posix()


@dataclass(frozen=True)
class ObservedSignature:
    size: int
    mtime_ns: int

    def __post_init__(self) -> None:
        if self.size < 0 or self.mtime_ns < 0:
            raise InventoryValidationError("observed signature values must be non-negative")


@dataclass(frozen=True)
class SensitiveScope:
    alias: str
    pattern: str

    def __post_init__(self) -> None:
        if not isinstance(self.alias, str) or not self.alias.strip():
            raise InventoryValidationError("sensitive alias must be a non-empty string")
        if any(character in self.alias for character in ("/", "\\", ":")):
            raise InventoryValidationError("sensitive alias must not contain path characters")
        object.__setattr__(self, "pattern", _normalized_pattern(self.pattern, "sensitive pattern"))


@dataclass(frozen=True)
class SensitiveSummary:
    document_count: int
    latest_mtime_ns: int

    def __post_init__(self) -> None:
        if self.document_count < 0 or self.latest_mtime_ns < 0:
            raise InventoryValidationError("sensitive summary values must be non-negative")


@dataclass(frozen=True)
class InventoryScope:
    defaults_version: int
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    force_include: tuple[str, ...]
    extensions: tuple[str, ...]
    sensitive: tuple[SensitiveScope, ...]

    def __post_init__(self) -> None:
        if self.defaults_version < 1:
            raise InventoryValidationError("defaults_version must be positive")
        for field in ("include", "exclude", "force_include"):
            normalized = tuple(
                _normalized_pattern(value, field)
                for value in getattr(self, field)
            )
            object.__setattr__(self, field, normalized)
        normalized_extensions: list[str] = []
        for extension in self.extensions:
            if not isinstance(extension, str) or not re.fullmatch(r"\.[A-Za-z0-9]+", extension):
                raise InventoryValidationError("extensions must contain dot-prefixed suffixes")
            normalized_extensions.append(extension.casefold())
        if not normalized_extensions:
            raise InventoryValidationError("extensions must not be empty")
        object.__setattr__(self, "extensions", tuple(sorted(set(normalized_extensions))))
        aliases = [item.alias.casefold() for item in self.sensitive]
        if len(aliases) != len(set(aliases)):
            raise InventoryValidationError("sensitive aliases must be unique")


@dataclass(frozen=True)
class InventoryDocument:
    disposition: str
    observed_signature: ObservedSignature
    ignore_reason: str | None

    def __post_init__(self) -> None:
        if self.disposition not in {"discovered", "ignored"}:
            raise InventoryValidationError("inventory disposition is invalid")
        if self.disposition == "ignored":
            if not isinstance(self.ignore_reason, str) or not self.ignore_reason.strip():
                raise InventoryValidationError("ignored document requires ignore_reason")
        elif self.ignore_reason is not None:
            raise InventoryValidationError("discovered document must not have ignore_reason")


@dataclass(frozen=True)
class InventoryBaseline:
    schema_version: int
    scope: InventoryScope
    documents: Mapping[str, InventoryDocument]
    sensitive_scopes: Mapping[str, SensitiveSummary]


@dataclass(frozen=True)
class InventoryScanError:
    path: str
    message: str


@dataclass(frozen=True)
class InventoryObservation:
    documents: Mapping[str, ObservedSignature]
    sensitive_scopes: Mapping[str, SensitiveSummary]
    errors: tuple[InventoryScanError, ...]
    collisions: tuple[tuple[str, ...], ...]


def default_inventory_scope(control_center_name: str) -> InventoryScope:
    center = _normalized_relative_path(control_center_name, "control center name")
    return InventoryScope(
        defaults_version=INVENTORY_DEFAULTS_VERSION,
        include=("**/*",),
        exclude=(
            ".git/**",
            ".obsidian/**",
            ".trash/**",
            ".agents/**",
            ".codex/**",
            "node_modules/**",
            "__pycache__/**",
            ".cache/**",
            ".pytest_cache/**",
            "build/**",
            "dist/**",
            f"{center}/.meta/**",
            f"{center}/ingest/**",
            f"{center}/wiki/**",
            f"{center}/raw/**",
        ),
        force_include=(),
        extensions=SUPPORTED_EXTENSIONS,
        sensitive=(),
    )


def _matches(path: str, pattern: str) -> bool:
    candidate = path.replace("\\", "/").strip("/")
    normalized = pattern.replace("\\", "/").strip("/")
    if os.name == "nt":
        candidate = candidate.casefold()
        normalized = normalized.casefold()
    if normalized in {"**", "**/*"}:
        return True
    if normalized.endswith("/**"):
        prefix = normalized[:-3].rstrip("/")
        if candidate == prefix or candidate.startswith(prefix + "/"):
            return True
    return fnmatch.fnmatchcase(candidate, normalized)


def _hard_raw_pattern(control_center: Path, vault_root: Path) -> str:
    return control_center.resolve().relative_to(vault_root.resolve()).as_posix() + "/raw/**"


def _sensitive_alias(path: str, scope: InventoryScope) -> str | None:
    for item in scope.sensitive:
        if _matches(path, item.pattern):
            return item.alias
    return None


def _is_included(path: str, scope: InventoryScope, hard_raw_pattern: str) -> bool:
    if _matches(path, hard_raw_pattern):
        return False
    forced = any(_matches(path, pattern) for pattern in scope.force_include)
    if not forced and not any(_matches(path, pattern) for pattern in scope.include):
        return False
    if not forced and any(_matches(path, pattern) for pattern in scope.exclude):
        return False
    return True


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def scan_inventory(
    vault_root: Path,
    control_center: Path,
    scope: InventoryScope,
) -> InventoryObservation:
    vault = vault_root.expanduser().resolve()
    control = control_center.expanduser().resolve()
    try:
        control.relative_to(vault)
    except ValueError as error:
        raise InventoryValidationError("control center must be inside Vault") from error
    if not vault.is_dir():
        raise InventoryValidationError("Vault root must be an existing directory")

    documents: dict[str, ObservedSignature] = {}
    sensitive_counts: dict[str, list[int]] = {
        item.alias: [0, 0] for item in scope.sensitive
    }
    errors: list[InventoryScanError] = []
    hard_raw = _hard_raw_pattern(control, vault)

    def onerror(error: OSError) -> None:
        filename = Path(error.filename) if error.filename else vault
        try:
            relative = filename.resolve().relative_to(vault).as_posix()
        except (OSError, ValueError):
            relative = "<vault>"
        alias = _sensitive_alias(relative, scope)
        errors.append(InventoryScanError(alias or relative, error.__class__.__name__))

    for directory, dirnames, filenames in os.walk(vault, topdown=True, followlinks=False, onerror=onerror):
        directory_path = Path(directory)
        kept: list[str] = []
        for name in dirnames:
            child = directory_path / name
            relative = child.relative_to(vault).as_posix()
            if _is_link_or_junction(child):
                continue
            if _matches(relative, hard_raw):
                continue
            forced_descendant = any(
                pattern.casefold().startswith(relative.casefold().rstrip("/") + "/")
                for pattern in scope.force_include
            )
            if (
                any(_matches(relative, pattern) for pattern in scope.exclude)
                and not forced_descendant
            ):
                continue
            kept.append(name)
        dirnames[:] = kept

        for name in filenames:
            path = directory_path / name
            relative = path.relative_to(vault).as_posix()
            if path.suffix.casefold() not in scope.extensions:
                continue
            if not _is_included(relative, scope, hard_raw):
                continue
            alias = _sensitive_alias(relative, scope)
            try:
                stat = path.stat()
            except OSError as error:
                errors.append(InventoryScanError(alias or relative, error.__class__.__name__))
                continue
            if alias is not None:
                summary = sensitive_counts[alias]
                summary[0] += 1
                summary[1] = max(summary[1], stat.st_mtime_ns)
                continue
            documents[relative] = ObservedSignature(stat.st_size, stat.st_mtime_ns)

    casefold_index: dict[str, list[str]] = {}
    for path in documents:
        key = path.casefold() if os.name == "nt" else path
        casefold_index.setdefault(key, []).append(path)
    collisions = tuple(
        tuple(sorted(paths))
        for _, paths in sorted(casefold_index.items())
        if len(paths) > 1
    )
    sensitive = {
        alias: SensitiveSummary(values[0], values[1])
        for alias, values in sorted(sensitive_counts.items())
    }
    return InventoryObservation(
        documents=dict(sorted(documents.items())),
        sensitive_scopes=sensitive,
        errors=tuple(sorted(errors, key=lambda item: (item.path, item.message))),
        collisions=collisions,
    )


def _scope_payload(scope: InventoryScope) -> dict[str, object]:
    return {
        "defaults_version": scope.defaults_version,
        "include": list(scope.include),
        "exclude": list(scope.exclude),
        "force_include": list(scope.force_include),
        "extensions": list(scope.extensions),
        "sensitive": [
            {"alias": item.alias, "pattern": item.pattern}
            for item in scope.sensitive
        ],
    }


def inventory_payload(baseline: InventoryBaseline) -> dict[str, object]:
    if baseline.schema_version != INVENTORY_SCHEMA_VERSION:
        raise InventoryValidationError("inventory schema_version must be 1")
    documents: dict[str, object] = {}
    seen: set[str] = set()
    for raw_path, document in sorted(baseline.documents.items()):
        path = _normalized_relative_path(raw_path, "inventory document path")
        key = path.casefold() if os.name == "nt" else path
        if key in seen:
            raise InventoryValidationError("inventory document paths collide")
        seen.add(key)
        document.__post_init__()
        documents[path] = {
            "disposition": document.disposition,
            "observed_signature": {
                "size": document.observed_signature.size,
                "mtime_ns": document.observed_signature.mtime_ns,
            },
            "ignore_reason": document.ignore_reason,
        }
    sensitive_scopes = {
        alias: {
            "document_count": summary.document_count,
            "latest_mtime_ns": summary.latest_mtime_ns,
        }
        for alias, summary in sorted(baseline.sensitive_scopes.items())
    }
    return {
        "schema_version": baseline.schema_version,
        "scope": _scope_payload(baseline.scope),
        "documents": documents,
        "sensitive_scopes": sensitive_scopes,
    }


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise InventoryValidationError(f"{field} must be an object")
    return value


def _decode_scope(value: object) -> InventoryScope:
    payload = _require_mapping(value, "scope")
    sensitive_raw = payload.get("sensitive", [])
    if not isinstance(sensitive_raw, list):
        raise InventoryValidationError("scope.sensitive must be an array")
    sensitive: list[SensitiveScope] = []
    for raw in sensitive_raw:
        item = _require_mapping(raw, "sensitive scope")
        sensitive.append(SensitiveScope(item.get("alias"), item.get("pattern")))

    def string_tuple(field: str) -> tuple[str, ...]:
        raw = payload.get(field)
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise InventoryValidationError(f"scope.{field} must be a string array")
        return tuple(raw)

    version = payload.get("defaults_version")
    if not isinstance(version, int):
        raise InventoryValidationError("scope.defaults_version must be an integer")
    return InventoryScope(
        defaults_version=version,
        include=string_tuple("include"),
        exclude=string_tuple("exclude"),
        force_include=string_tuple("force_include"),
        extensions=string_tuple("extensions"),
        sensitive=tuple(sensitive),
    )


def _decode_inventory(payload: Mapping[str, object]) -> InventoryBaseline:
    if payload.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise InventoryValidationError("inventory schema_version must be 1")
    scope = _decode_scope(payload.get("scope"))
    documents_raw = _require_mapping(payload.get("documents"), "documents")
    documents: dict[str, InventoryDocument] = {}
    for raw_path, raw in documents_raw.items():
        path = _normalized_relative_path(raw_path, "inventory document path")
        item = _require_mapping(raw, "inventory document")
        signature_raw = _require_mapping(item.get("observed_signature"), "observed_signature")
        size = signature_raw.get("size")
        mtime_ns = signature_raw.get("mtime_ns")
        if not isinstance(size, int) or not isinstance(mtime_ns, int):
            raise InventoryValidationError("observed signature values must be integers")
        documents[path] = InventoryDocument(
            disposition=item.get("disposition"),
            observed_signature=ObservedSignature(size, mtime_ns),
            ignore_reason=item.get("ignore_reason"),
        )
    sensitive_raw = _require_mapping(payload.get("sensitive_scopes"), "sensitive_scopes")
    sensitive_scopes: dict[str, SensitiveSummary] = {}
    for alias, raw in sensitive_raw.items():
        item = _require_mapping(raw, "sensitive summary")
        count = item.get("document_count")
        latest = item.get("latest_mtime_ns")
        if not isinstance(count, int) or not isinstance(latest, int):
            raise InventoryValidationError("sensitive summary values must be integers")
        sensitive_scopes[alias] = SensitiveSummary(count, latest)
    baseline = InventoryBaseline(1, scope, documents, sensitive_scopes)
    inventory_payload(baseline)
    return baseline


def load_inventory(path: Path) -> InventoryBaseline:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return _decode_inventory(_require_mapping(payload, "inventory"))
    except (OSError, UnicodeError, json.JSONDecodeError, InventoryValidationError) as error:
        raise InventoryLoadError(f"invalid inventory: {error}") from error
