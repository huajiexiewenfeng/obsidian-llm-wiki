from __future__ import annotations

import itertools
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .state import (
    SourceRecord,
    StateValidationError,
    casefold_path_key,
    ensure_within,
    file_checksum,
    file_fingerprint,
    stable_record_id,
)


class ArchiveError(RuntimeError):
    def __init__(
        self,
        check: str,
        message: str,
        *,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.check = check
        self.hint = hint


class ArchiveConflict(ArchiveError):
    pass


class ArchiveWriteError(ArchiveError):
    pass


@dataclass(frozen=True)
class ArchiveTargetEvidence:
    action: str
    relative_path: str
    checksum: str
    size: int
    fingerprint: Mapping[str, int] | None
    staging_required: bool
    conflict: Mapping[str, object] | None = None

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "action": self.action,
            "target": self.relative_path,
            "size": self.size,
            "checksum": self.checksum,
            "staging_required": self.staging_required,
        }
        if self.conflict is not None:
            payload.update(self.conflict)
        return payload


WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
WINDOWS_RESERVED_CHARACTERS = frozenset('<>:"/\\|?*')


def archive_source_id(
    origin_canonical_path: str,
    checksum: str,
    records: Mapping[str, SourceRecord],
) -> str:
    origin_key = casefold_path_key(origin_canonical_path, windows=True)
    base_seed = f"archive\0{origin_key}\0{checksum}"
    for ordinal in itertools.count(0):
        seed = (
            base_seed
            if ordinal == 0
            else f"{base_seed}\0collision\0{ordinal}"
        )
        candidate = stable_record_id("src", seed)
        if candidate not in records:
            return candidate
    raise AssertionError("unreachable archive ID allocation")


def safe_archive_filename(name: str) -> str:
    basename = PurePosixPath(name.replace("\\", "/")).name
    normalized = unicodedata.normalize("NFC", basename)
    cleaned = "".join(
        "_"
        if ord(character) < 32 or character in WINDOWS_RESERVED_CHARACTERS
        else character
        for character in normalized
    )
    suffix = PurePosixPath(cleaned).suffix
    stem = cleaned[: -len(suffix)] if suffix else cleaned
    stem = stem.rstrip(" .") or "source"
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem += "_"
    return f"{stem}{suffix}"


def archive_relative_path(source_id: str, source_name: str) -> str:
    return PurePosixPath(
        "raw",
        source_id,
        safe_archive_filename(source_name),
    ).as_posix()


def inspect_archive_target(
    control_center: Path,
    source_id: str,
    source_name: str,
    expected_checksum: str,
    expected_size: int,
) -> ArchiveTargetEvidence:
    relative_path = archive_relative_path(source_id, source_name)
    try:
        target = ensure_within(
            control_center / Path(*PurePosixPath(relative_path).parts),
            control_center,
        )
    except StateValidationError as error:
        raise ArchiveConflict(
            "unsafe-archive-path",
            "archive target resolves outside the control center",
        ) from error
    if not target.exists():
        return ArchiveTargetEvidence(
            action="archive-create",
            relative_path=relative_path,
            checksum=expected_checksum,
            size=expected_size,
            fingerprint=None,
            staging_required=True,
        )
    if not target.is_file():
        return ArchiveTargetEvidence(
            action="archive-target-conflict",
            relative_path=relative_path,
            checksum=expected_checksum,
            size=expected_size,
            fingerprint=None,
            staging_required=False,
            conflict={"check": "archive-target-conflict"},
        )
    before = file_fingerprint(target)
    actual_checksum = file_checksum(target)
    after = file_fingerprint(target)
    if before != after:
        raise ArchiveConflict(
            "archive-target-changed",
            "archive target changed during checksum verification",
        )
    if actual_checksum != expected_checksum:
        return ArchiveTargetEvidence(
            action="archive-target-conflict",
            relative_path=relative_path,
            checksum=expected_checksum,
            size=expected_size,
            fingerprint=after,
            staging_required=False,
            conflict={"check": "archive-target-conflict"},
        )
    return ArchiveTargetEvidence(
        action="archive-reuse",
        relative_path=relative_path,
        checksum=actual_checksum,
        size=after["size"],
        fingerprint=after,
        staging_required=False,
    )
