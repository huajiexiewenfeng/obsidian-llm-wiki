from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from llm_wiki_core.state import (
    PageRecord,
    SourceRecord,
    decode_page_registry,
    decode_source_registry,
    file_checksum,
)
from llm_wiki_core.writer import (
    VaultLock,
    append_change_event,
    atomic_write_json,
    begin_operation,
    file_text_checksum,
    load_operations,
    update_operation,
)


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


class InventoryPlanConflict(InventoryValidationError):
    pass


class InventoryWriteError(RuntimeError):
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


@dataclass(frozen=True)
class InventoryFinding:
    check: str
    severity: str
    path: str | None
    message: str
    hint: str | None = None
    count: int | None = None


@dataclass(frozen=True)
class InventoryInspection:
    scope: InventoryScope
    observation: InventoryObservation
    baseline: InventoryBaseline | None
    findings: tuple[InventoryFinding, ...]
    complete: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "document_count": len(self.observation.documents),
            "sensitive_scopes": {
                alias: {
                    "document_count": summary.document_count,
                    "latest_mtime_ns": summary.latest_mtime_ns,
                }
                for alias, summary in sorted(self.observation.sensitive_scopes.items())
            },
            "findings": [
                {
                    "check": item.check,
                    "severity": item.severity,
                    "path": item.path,
                    "message": item.message,
                    **({} if item.hint is None else {"hint": item.hint}),
                    **({} if item.count is None else {"count": item.count}),
                }
                for item in self.findings
            ],
        }


@dataclass(frozen=True)
class InventoryMutationPlan:
    action: str
    baseline: InventoryBaseline
    expected_inventory_checksum: str | None
    plan_checksum: str
    idempotency_key: str
    candidate_count: int
    confirmable: bool
    affected_count: int = 0

    def to_public_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "candidate_count": self.candidate_count,
            "affected_count": self.affected_count,
            "sensitive_scopes": {
                alias: {
                    "document_count": summary.document_count,
                    "latest_mtime_ns": summary.latest_mtime_ns,
                }
                for alias, summary in sorted(self.baseline.sensitive_scopes.items())
            },
            "target": ".meta/inventory.json",
            "plan_checksum": self.plan_checksum,
            "idempotency_key": self.idempotency_key,
            "confirmable": self.confirmable,
            "confirmation_required": self.confirmable,
        }


@dataclass(frozen=True)
class InventoryMutationResult:
    status: str
    operation_id: str
    idempotency_key: str
    idempotent: bool = False


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


def _finding(
    check: str,
    severity: str,
    path: str | None,
    message: str,
    *,
    hint: str | None = None,
    count: int | None = None,
) -> InventoryFinding:
    return InventoryFinding(check, severity, path, message, hint, count)


def _read_registry(path: Path, decoder):
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InventoryLoadError(f"invalid registry: {path.name}")
    return decoder(payload)


def _path_key(path: Path) -> str:
    normalized = path.expanduser().resolve().as_posix()
    return normalized.casefold() if os.name == "nt" else normalized


def _valid_processed_sources(
    control_center: Path,
    sources: Mapping[str, SourceRecord],
    pages: Mapping[str, PageRecord],
) -> dict[str, SourceRecord]:
    result: dict[str, SourceRecord] = {}
    ambiguous: set[str] = set()
    for source_id, source in sources.items():
        if source.status != "processed" or source.proxy_page_id is None:
            continue
        page = pages.get(source.proxy_page_id)
        if page is None or source_id not in page.source_ids:
            continue
        proxy = control_center / Path(*PurePosixPath(page.relative_path).parts)
        if not proxy.is_file():
            continue
        try:
            key = _path_key(Path(source.canonical_path))
        except (OSError, RuntimeError):
            continue
        if key in result or key in ambiguous:
            # Ambiguous source evidence must never be selected automatically.
            result.pop(key, None)
            ambiguous.add(key)
            continue
        result[key] = source
    return result


def _scope_equal(left: InventoryScope, right: InventoryScope) -> bool:
    return _scope_payload(left) == _scope_payload(right)


def inspect_inventory(
    vault_root: Path,
    control_center: Path,
    *,
    scope_override: InventoryScope | None = None,
    verify_content: bool = False,
) -> InventoryInspection:
    vault = vault_root.expanduser().resolve()
    control = control_center.expanduser().resolve()
    control_relative = control.relative_to(vault).as_posix()
    inventory_path = control / ".meta/inventory.json"
    default_scope = default_inventory_scope(control_relative)

    if not inventory_path.is_file():
        scope = scope_override or default_scope
        observation = scan_inventory(vault, control, scope)
        finding = _finding(
            "missing-ingest-inventory",
            "WARN",
            f"{control_relative}/.meta/inventory.json",
            "Inventory baseline is missing; un-ingested document status is incomplete.",
            hint="Review inventory initialize dry-run before confirming a baseline.",
            count=len(observation.documents),
        )
        return InventoryInspection(scope, observation, None, (finding,), False)

    try:
        baseline = load_inventory(inventory_path)
    except InventoryLoadError as error:
        scope = scope_override or default_scope
        observation = scan_inventory(vault, control, scope)
        finding = _finding(
            "invalid-ingest-inventory",
            "ERROR",
            f"{control_relative}/.meta/inventory.json",
            str(error),
            hint="Review and repair the baseline; Doctor will not overwrite it.",
        )
        return InventoryInspection(scope, observation, None, (finding,), False)

    scope = scope_override or baseline.scope
    observation = scan_inventory(vault, control, scope)
    findings: list[InventoryFinding] = []
    complete = True

    if not _scope_equal(scope, baseline.scope):
        findings.append(
            _finding(
                "inventory-scope-changed",
                "WARN",
                f"{control_relative}/.meta/inventory.json",
                "Current Inventory scope differs from the confirmed baseline scope.",
                hint="Review inventory configure dry-run before confirming the new scope.",
            )
        )
        complete = False

    collision_paths: set[str] = set()
    for collision in observation.collisions:
        collision_paths.update(collision)
        findings.append(
            _finding(
                "inventory-path-collision",
                "ERROR",
                collision[0],
                "Multiple Vault paths collide under platform path comparison rules.",
                hint="Rename one path before Inventory can associate records safely.",
                count=len(collision),
            )
        )
        complete = False

    for error in observation.errors:
        findings.append(
            _finding(
                "inventory-scan-incomplete",
                "WARN",
                error.path,
                f"Inventory could not inspect one path ({error.message}).",
                hint="Resolve the filesystem access issue and rerun Inventory.",
            )
        )
        complete = False

    for alias, current in observation.sensitive_scopes.items():
        previous = baseline.sensitive_scopes.get(alias)
        if previous != current:
            findings.append(
                _finding(
                    "sensitive-scope-change",
                    "WARN",
                    alias,
                    "Sensitive scope metadata changed.",
                    hint="Review the sensitive scope through its approved alias.",
                    count=current.document_count,
                )
            )

    try:
        sources = _read_registry(control / ".meta/sources.json", decode_source_registry)
        pages = _read_registry(control / ".meta/pages.json", decode_page_registry)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, InventoryLoadError):
        sources = {}
        pages = {}
    processed_by_path = _valid_processed_sources(control, sources, pages)

    for relative_path, signature in observation.documents.items():
        if relative_path in collision_paths:
            continue
        absolute = vault / Path(*PurePosixPath(relative_path).parts)
        source = processed_by_path.get(_path_key(absolute))
        if source is not None:
            current_fingerprint = {"size": signature.size, "mtime_ns": signature.mtime_ns}
            if source.fingerprint != current_fingerprint:
                checksum_matches = False
                if verify_content and source.checksum is not None:
                    try:
                        checksum_matches = file_checksum(absolute) == source.checksum
                    except OSError:
                        checksum_matches = False
                if not checksum_matches:
                    findings.append(
                        _finding(
                            "stale-ingested-source",
                            "WARN",
                            relative_path,
                            "Processed source metadata changed after ingest.",
                            hint="Review the source and rerun ingest apply if the change is intended.",
                        )
                    )
            continue

        document = baseline.documents.get(relative_path)
        if document is not None and document.disposition == "ignored":
            continue
        findings.append(
            _finding(
                "uningested-source",
                "WARN",
                relative_path,
                "Vault document has no complete processed ingest evidence.",
                hint="Review the document and create an ingest plan.",
            )
        )

    severity_order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    findings.sort(
        key=lambda item: (
            severity_order.get(item.severity, 9),
            item.check,
            item.path or "",
        )
    )
    return InventoryInspection(
        scope=scope,
        observation=observation,
        baseline=baseline,
        findings=tuple(findings),
        complete=complete,
    )


def _digest_payload(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def plan_inventory_initialize(
    vault_root: Path,
    control_center: Path,
    *,
    scope: InventoryScope | None = None,
) -> InventoryMutationPlan:
    vault = vault_root.expanduser().resolve()
    control = control_center.expanduser().resolve()
    meta = control / ".meta"
    for name in ("schema.json", "sources.json", "pages.json", "operations.json", "change-log.jsonl"):
        if not (meta / name).is_file():
            raise InventoryPlanConflict(f"required state file is missing: {name}")
    target = meta / "inventory.json"
    if target.exists():
        raise InventoryPlanConflict("inventory baseline already exists")
    control_relative = control.relative_to(vault).as_posix()
    resolved_scope = scope or default_inventory_scope(control_relative)
    observation = scan_inventory(vault, control, resolved_scope)
    if observation.errors or observation.collisions:
        raise InventoryPlanConflict("inventory scan is incomplete or contains path collisions")
    documents = {
        path: InventoryDocument("discovered", signature, None)
        for path, signature in observation.documents.items()
    }
    baseline = InventoryBaseline(
        INVENTORY_SCHEMA_VERSION,
        resolved_scope,
        documents,
        observation.sensitive_scopes,
    )
    material = {
        "action": "initialize",
        "baseline": inventory_payload(baseline),
        "expected_inventory_checksum": None,
        "sources_checksum": file_text_checksum(meta / "sources.json"),
        "pages_checksum": file_text_checksum(meta / "pages.json"),
    }
    plan_checksum = _digest_payload(material)
    return InventoryMutationPlan(
        action="initialize",
        baseline=baseline,
        expected_inventory_checksum=None,
        plan_checksum=plan_checksum,
        idempotency_key=_digest_payload({"kind": "inventory-initialize", "plan": plan_checksum}),
        candidate_count=len(documents),
        confirmable=True,
    )


def apply_inventory_initialize(
    vault_root: Path,
    control_center: Path,
    confirmed_plan_checksum: str,
    *,
    scope: InventoryScope | None = None,
) -> InventoryMutationResult:
    vault = vault_root.expanduser().resolve()
    control = control_center.expanduser().resolve()
    meta = control / ".meta"
    lock = VaultLock(
        meta / "lock.json",
        allowed_root=control,
        command="inventory initialize",
        target=control,
    )
    with lock:
        expected_idempotency_key = _digest_payload(
            {"kind": "inventory-initialize", "plan": confirmed_plan_checksum}
        )
        for existing in load_operations(meta / "operations.json").values():
            if (
                existing.kind == "inventory-initialize"
                and existing.idempotency_key == expected_idempotency_key
                and existing.status == "completed"
            ):
                return InventoryMutationResult(
                    "completed",
                    existing.operation_id,
                    existing.idempotency_key,
                    True,
                )
        refreshed = plan_inventory_initialize(vault, control, scope=scope)
        if refreshed.plan_checksum != confirmed_plan_checksum:
            raise InventoryPlanConflict("confirmed plan checksum no longer matches current state")
        operation = begin_operation(
            meta / "operations.json",
            allowed_root=control,
            kind="inventory-initialize",
            idempotency_key=refreshed.idempotency_key,
            record_ids=[".meta/inventory.json"],
            reuse_completed=True,
        )
        if operation.status == "completed":
            return InventoryMutationResult(
                "completed",
                operation.operation_id,
                refreshed.idempotency_key,
                True,
            )
        current_step = "write-inventory"
        try:
            update_operation(
                meta / "operations.json",
                operation.operation_id,
                allowed_root=control,
                status="running",
                current_step=current_step,
            )
            atomic_write_json(
                meta / "inventory.json",
                inventory_payload(refreshed.baseline),
                allowed_root=control,
                expected_checksum=refreshed.expected_inventory_checksum,
            )
            current_step = "append-change-log"
            update_operation(
                meta / "operations.json",
                operation.operation_id,
                allowed_root=control,
                status="running",
                current_step=current_step,
            )
            append_change_event(
                meta / "change-log.jsonl",
                allowed_root=control,
                operation_id=operation.operation_id,
                kind="inventory-initialize",
                record_ids=[".meta/inventory.json"],
                old_checksums={"inventory.json": None},
                new_checksums={"inventory.json": file_text_checksum(meta / "inventory.json")},
                result="completed",
                idempotency_key=refreshed.idempotency_key,
                summary={"candidate_count": refreshed.candidate_count},
            )
            update_operation(
                meta / "operations.json",
                operation.operation_id,
                allowed_root=control,
                status="completed",
                current_step="complete",
            )
            return InventoryMutationResult(
                "completed",
                operation.operation_id,
                refreshed.idempotency_key,
            )
        except BaseException as error:
            try:
                update_operation(
                    meta / "operations.json",
                    operation.operation_id,
                    allowed_root=control,
                    status="failed",
                    current_step=current_step,
                    error=str(error),
                )
            except BaseException:
                pass
            if isinstance(error, InventoryPlanConflict):
                raise
            raise InventoryWriteError(str(error)) from error


def _current_baseline_with_scope(
    vault: Path,
    control: Path,
    previous: InventoryBaseline,
    scope: InventoryScope,
) -> InventoryBaseline:
    observation = scan_inventory(vault, control, scope)
    if observation.errors or observation.collisions:
        raise InventoryPlanConflict("inventory scan is incomplete or contains path collisions")
    documents: dict[str, InventoryDocument] = {}
    for path, signature in observation.documents.items():
        old = previous.documents.get(path)
        disposition = old.disposition if old is not None else "discovered"
        reason = old.ignore_reason if disposition == "ignored" else None
        documents[path] = InventoryDocument(disposition, signature, reason)
    return InventoryBaseline(1, scope, documents, observation.sensitive_scopes)


def _update_plan(
    action: str,
    baseline: InventoryBaseline,
    expected_checksum: str,
    *,
    affected_count: int,
) -> InventoryMutationPlan:
    material = {
        "action": action,
        "baseline": inventory_payload(baseline),
        "expected_inventory_checksum": expected_checksum,
    }
    plan_checksum = _digest_payload(material)
    return InventoryMutationPlan(
        action=action,
        baseline=baseline,
        expected_inventory_checksum=expected_checksum,
        plan_checksum=plan_checksum,
        idempotency_key=_digest_payload({"kind": f"inventory-{action}", "plan": plan_checksum}),
        candidate_count=sum(
            document.disposition == "discovered" for document in baseline.documents.values()
        ),
        confirmable=True,
        affected_count=affected_count,
    )


def plan_inventory_configure(
    vault_root: Path,
    control_center: Path,
    scope: InventoryScope,
) -> InventoryMutationPlan:
    vault = vault_root.resolve()
    control = control_center.resolve()
    target = control / ".meta/inventory.json"
    expected = file_text_checksum(target)
    if expected is None:
        raise InventoryPlanConflict("inventory baseline is missing")
    previous = load_inventory(target)
    updated = _current_baseline_with_scope(vault, control, previous, scope)
    old_paths = set(previous.documents)
    new_paths = set(updated.documents)
    changed = len(old_paths.symmetric_difference(new_paths))
    changed += sum(
        previous.documents[path].disposition != updated.documents[path].disposition
        for path in old_paths & new_paths
    )
    return _update_plan("configure", updated, expected, affected_count=changed)


def _mutation_targets(
    baseline: InventoryBaseline,
    control_relative: str,
    requested_path: str,
) -> tuple[str, ...]:
    target = _normalized_relative_path(requested_path, "inventory mutation path")
    if target == control_relative or target.startswith(control_relative.rstrip("/") + "/"):
        raise InventoryPlanConflict("inventory mutation path must not target the control center")
    prefix = target.rstrip("/") + "/"
    matches = tuple(
        path for path in sorted(baseline.documents)
        if path == target or path.startswith(prefix)
    )
    if not matches:
        raise InventoryPlanConflict("inventory mutation path matches no ordinary documents")
    return matches


def plan_inventory_ignore(
    vault_root: Path,
    control_center: Path,
    requested_path: str,
    reason: str,
) -> InventoryMutationPlan:
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 200:
        raise InventoryPlanConflict("ignore reason must be a short non-empty string")
    vault = vault_root.resolve()
    control = control_center.resolve()
    target = control / ".meta/inventory.json"
    expected = file_text_checksum(target)
    if expected is None:
        raise InventoryPlanConflict("inventory baseline is missing")
    previous = load_inventory(target)
    current = _current_baseline_with_scope(vault, control, previous, previous.scope)
    control_relative = control.relative_to(vault).as_posix()
    matches = _mutation_targets(current, control_relative, requested_path)
    documents = dict(current.documents)
    affected = 0
    for path in matches:
        old = documents[path]
        if old.disposition != "ignored" or old.ignore_reason != reason.strip():
            affected += 1
        documents[path] = InventoryDocument("ignored", old.observed_signature, reason.strip())
    updated = InventoryBaseline(1, current.scope, documents, current.sensitive_scopes)
    return _update_plan("ignore", updated, expected, affected_count=affected)


def plan_inventory_unignore(
    vault_root: Path,
    control_center: Path,
    requested_path: str,
) -> InventoryMutationPlan:
    vault = vault_root.resolve()
    control = control_center.resolve()
    target = control / ".meta/inventory.json"
    expected = file_text_checksum(target)
    if expected is None:
        raise InventoryPlanConflict("inventory baseline is missing")
    previous = load_inventory(target)
    current = _current_baseline_with_scope(vault, control, previous, previous.scope)
    control_relative = control.relative_to(vault).as_posix()
    matches = _mutation_targets(current, control_relative, requested_path)
    documents = dict(current.documents)
    affected = 0
    for path in matches:
        old = documents[path]
        if old.disposition == "ignored":
            documents[path] = InventoryDocument("discovered", old.observed_signature, None)
            affected += 1
    updated = InventoryBaseline(1, current.scope, documents, current.sensitive_scopes)
    return _update_plan("unignore", updated, expected, affected_count=affected)


def apply_inventory_mutation(
    vault_root: Path,
    control_center: Path,
    action: str,
    confirmed_plan_checksum: str,
    *,
    scope: InventoryScope | None = None,
    requested_path: str | None = None,
    reason: str | None = None,
) -> InventoryMutationResult:
    planners = {
        "configure": lambda: plan_inventory_configure(vault_root, control_center, scope),
        "ignore": lambda: plan_inventory_ignore(vault_root, control_center, requested_path, reason),
        "unignore": lambda: plan_inventory_unignore(vault_root, control_center, requested_path),
    }
    if action not in planners:
        raise InventoryPlanConflict("unsupported inventory mutation action")
    if action == "configure" and scope is None:
        raise InventoryPlanConflict("configure requires an Inventory scope")
    control = control_center.resolve()
    meta = control / ".meta"
    kind = f"inventory-{action}"
    expected_key = _digest_payload({"kind": kind, "plan": confirmed_plan_checksum})
    lock = VaultLock(
        meta / "lock.json",
        allowed_root=control,
        command=kind.replace("-", " "),
        target=control,
    )
    with lock:
        for existing in load_operations(meta / "operations.json").values():
            if existing.kind == kind and existing.idempotency_key == expected_key and existing.status == "completed":
                return InventoryMutationResult("completed", existing.operation_id, existing.idempotency_key, True)
        refreshed = planners[action]()
        if refreshed.plan_checksum != confirmed_plan_checksum:
            raise InventoryPlanConflict("confirmed plan checksum no longer matches current state")
        operation = begin_operation(
            meta / "operations.json",
            allowed_root=control,
            kind=kind,
            idempotency_key=refreshed.idempotency_key,
            record_ids=[".meta/inventory.json"],
            reuse_completed=True,
        )
        step = "write-inventory"
        try:
            update_operation(meta / "operations.json", operation.operation_id, allowed_root=control, status="running", current_step=step)
            atomic_write_json(
                meta / "inventory.json",
                inventory_payload(refreshed.baseline),
                allowed_root=control,
                expected_checksum=refreshed.expected_inventory_checksum,
            )
            step = "append-change-log"
            update_operation(meta / "operations.json", operation.operation_id, allowed_root=control, status="running", current_step=step)
            append_change_event(
                meta / "change-log.jsonl",
                allowed_root=control,
                operation_id=operation.operation_id,
                kind=kind,
                record_ids=[".meta/inventory.json"],
                old_checksums={"inventory.json": refreshed.expected_inventory_checksum},
                new_checksums={"inventory.json": file_text_checksum(meta / "inventory.json")},
                result="completed",
                idempotency_key=refreshed.idempotency_key,
                summary={"affected_count": refreshed.affected_count},
            )
            update_operation(meta / "operations.json", operation.operation_id, allowed_root=control, status="completed", current_step="complete")
            return InventoryMutationResult("completed", operation.operation_id, refreshed.idempotency_key)
        except BaseException as error:
            try:
                update_operation(meta / "operations.json", operation.operation_id, allowed_root=control, status="failed", current_step=step, error=str(error))
            except BaseException:
                pass
            if isinstance(error, InventoryPlanConflict):
                raise
            raise InventoryWriteError(str(error)) from error
