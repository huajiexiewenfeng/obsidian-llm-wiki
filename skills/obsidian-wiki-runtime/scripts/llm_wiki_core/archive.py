from __future__ import annotations

import hashlib
import itertools
import os
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

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


@dataclass(frozen=True)
class PreparedArchive:
    action: str
    target_relative_path: str
    target_path: Path
    checksum: str
    verified_fingerprint: Mapping[str, int] | None
    origin_fingerprint: Mapping[str, int]
    staging_path: Path | None

    def to_target_evidence(self) -> ArchiveTargetEvidence:
        target_fingerprint = (
            self.verified_fingerprint if self.action == "archive-reuse" else None
        )
        return ArchiveTargetEvidence(
            action=self.action,
            relative_path=self.target_relative_path,
            checksum=self.checksum,
            size=self.origin_fingerprint["size"],
            fingerprint=target_fingerprint,
            staging_required=self.staging_path is not None,
        )


@dataclass(frozen=True)
class ArchivePublishResult:
    published: bool
    reused: bool
    temp_cleanup_pending: bool


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


def fingerprint_from_stat(stat: os.stat_result) -> dict[str, int]:
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def prepare_archive(
    source: Path,
    control_center: Path,
    evidence: ArchiveTargetEvidence,
    expected_origin: Mapping[str, int],
    *,
    chunk_size: int = 1024 * 1024,
    disk_usage: Callable[[Path], object] = shutil.disk_usage,
) -> PreparedArchive:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    try:
        target = ensure_within(
            control_center / Path(*PurePosixPath(evidence.relative_path).parts),
            control_center,
        )
    except StateValidationError as error:
        raise ArchiveConflict(
            "unsafe-archive-path",
            "archive target resolves outside the control center",
        ) from error
    if evidence.conflict is not None:
        raise ArchiveConflict(
            str(evidence.conflict["check"]),
            "archive plan contains an unresolved conflict",
        )
    origin_expected = dict(expected_origin)
    if evidence.action == "archive-reuse":
        return PreparedArchive(
            action=evidence.action,
            target_relative_path=evidence.relative_path,
            target_path=target,
            checksum=evidence.checksum,
            verified_fingerprint=evidence.fingerprint,
            origin_fingerprint=origin_expected,
            staging_path=None,
        )
    if evidence.action != "archive-create":
        raise ArchiveConflict(
            "archive-target-conflict",
            "archive plan does not describe a creatable or reusable target",
        )
    if source.is_symlink() or not source.is_file():
        raise ArchiveConflict(
            "invalid-archive-source",
            "archive source must be a regular file",
        )
    origin_before = file_fingerprint(source)
    if origin_before != origin_expected:
        raise ArchiveConflict(
            "source-changed",
            "archive source fingerprint changed",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target = ensure_within(target, control_center)
    except StateValidationError as error:
        raise ArchiveConflict(
            "unsafe-archive-path",
            "archive target resolves outside the control center",
        ) from error
    available = disk_usage(target.parent).free
    if available < origin_expected["size"]:
        raise ArchiveWriteError(
            "insufficient-space",
            "not enough space for archive staging",
        )
    descriptor, raw_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    staging = Path(raw_name)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_stream, os.fdopen(
            descriptor, "wb"
        ) as output_stream:
            opened_before = fingerprint_from_stat(os.fstat(input_stream.fileno()))
            if opened_before != origin_before:
                raise ArchiveConflict(
                    "source-changed",
                    "archive source changed before copying",
                )
            while True:
                chunk = input_stream.read(chunk_size)
                if not chunk:
                    break
                output_stream.write(chunk)
                digest.update(chunk)
            opened_after = fingerprint_from_stat(os.fstat(input_stream.fileno()))
            if opened_after != opened_before:
                raise ArchiveConflict(
                    "source-changed",
                    "archive source changed while copying",
                )
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if file_fingerprint(source) != origin_before:
            raise ArchiveConflict(
                "source-changed",
                "archive source path changed while copying",
            )
        actual_checksum = f"sha256:{digest.hexdigest()}"
        if actual_checksum != evidence.checksum:
            raise ArchiveConflict(
                "source-checksum-conflict",
                "archive source checksum changed",
            )
        return PreparedArchive(
            action=evidence.action,
            target_relative_path=evidence.relative_path,
            target_path=target,
            checksum=actual_checksum,
            verified_fingerprint=file_fingerprint(staging),
            origin_fingerprint=origin_before,
            staging_path=staging,
        )
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            staging.unlink()
        except OSError:
            pass
        raise


def validate_prepared_archive(prepared: PreparedArchive) -> None:
    if prepared.staging_path is not None and prepared.target_path.exists():
        raise ArchiveConflict(
            "archive-target-changed",
            "archive target appeared after preview",
        )
    path = prepared.staging_path or prepared.target_path
    expected = dict(prepared.verified_fingerprint or {})
    if not path.is_file() or file_fingerprint(path) != expected:
        raise ArchiveConflict(
            "archive-target-changed",
            "prepared archive fingerprint changed",
        )


def publish_archive_noreplace(prepared: PreparedArchive) -> ArchivePublishResult:
    if prepared.staging_path is None:
        return ArchivePublishResult(
            published=False,
            reused=True,
            temp_cleanup_pending=False,
        )
    try:
        os.link(prepared.staging_path, prepared.target_path)
    except FileExistsError as error:
        raise ArchiveConflict(
            "archive-target-changed",
            "archive target appeared after preview",
        ) from error
    except OSError as error:
        raise ArchiveWriteError(
            "atomic-publish-unsupported",
            "safe archive publication is unsupported",
            hint=(
                "Move the Vault to NTFS, ext4, or another filesystem "
                "with hard-link support."
            ),
        ) from error
    cleanup_pending = False
    try:
        prepared.staging_path.unlink()
    except OSError:
        cleanup_pending = True
    fsync_directory(prepared.target_path.parent)
    return ArchivePublishResult(
        published=True,
        reused=False,
        temp_cleanup_pending=cleanup_pending,
    )


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def cleanup_prepared_archive(prepared: PreparedArchive | None) -> None:
    if prepared is None or prepared.staging_path is None:
        return
    try:
        prepared.staging_path.unlink()
    except OSError:
        pass
