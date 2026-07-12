import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.archive import (
    ArchiveConflict,
    ArchiveError,
    ArchiveWriteError,
    cleanup_prepared_archive,
    archive_relative_path,
    archive_source_id,
    inspect_archive_target,
    prepare_archive,
    publish_archive_noreplace,
    safe_archive_filename,
    validate_prepared_archive,
)
from llm_wiki_core.state import SourceRecord, file_checksum, file_fingerprint


def source_record(source_id: str, canonical_path: str) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        display_path=canonical_path,
        canonical_path=canonical_path,
        source_type="pdf",
        mode="archive-import",
        status="processed",
        fingerprint={"size": 1, "mtime_ns": 1},
        checksum="sha256:" + "a" * 64,
        proxy_page_id=None,
        sensitivity="normal",
        last_verified_at="2026-07-12T00:00:00+00:00",
        archive_relative_path=f"raw/{source_id}/a.pdf",
    )


class ArchiveIdentityTests(unittest.TestCase):
    def test_source_id_is_stable_for_first_allocation(self):
        origin = "C:/Materials/Approved.pdf"
        checksum = "sha256:" + "a" * 64

        first = archive_source_id(origin, checksum, {})
        second = archive_source_id(origin, checksum, {})

        self.assertEqual(first, second)
        self.assertRegex(first, r"^src-[0-9a-f]{16}$")

    def test_source_id_uses_first_free_collision_ordinal(self):
        origin = "C:/Materials/Approved.pdf"
        checksum = "sha256:" + "a" * 64
        occupied = archive_source_id(origin, checksum, {})
        records = {occupied: source_record(occupied, "C:/Moved/Approved.pdf")}

        allocated = archive_source_id(origin, checksum, records)

        self.assertNotEqual(allocated, occupied)
        self.assertEqual(allocated, archive_source_id(origin, checksum, records))

    def test_safe_filename_is_unicode_stable_and_windows_safe(self):
        cases = {
            "CON.pdf": "CON_.pdf",
            "CON?.pdf": "CON_.pdf",
            "报告  .PDF": "报告.PDF",
            "bad<name>.txt": "bad_name_.txt",
            "...": "source",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(safe_archive_filename(raw), expected)

    def test_archive_relative_path_never_contains_origin_directories(self):
        self.assertEqual(
            archive_relative_path("src-0123", "D:/Downloads/report.pdf"),
            "raw/src-0123/report.pdf",
        )


class ArchiveTargetPlannerTests(unittest.TestCase):
    def test_missing_target_is_create_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp)
            evidence = inspect_archive_target(
                control,
                "src-0123",
                "example.bin",
                "sha256:" + "a" * 64,
                17,
            )

            self.assertEqual(evidence.action, "archive-create")
            self.assertEqual(evidence.relative_path, "raw/src-0123/example.bin")
            self.assertEqual(evidence.size, 17)
            self.assertTrue(evidence.staging_required)
            self.assertIsNone(evidence.conflict)
            self.assertFalse((control / "raw").exists())

    def test_matching_target_is_reuse_with_stable_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp)
            target = control / "raw/src-0123/example.bin"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"archive-bytes")
            checksum = file_checksum(target)

            evidence = inspect_archive_target(
                control, "src-0123", "example.bin", checksum, target.stat().st_size
            )

            self.assertEqual(evidence.action, "archive-reuse")
            self.assertFalse(evidence.staging_required)
            self.assertEqual(evidence.fingerprint["size"], len(b"archive-bytes"))
            self.assertIsNone(evidence.conflict)

    def test_different_target_is_nonconfirmable_conflict_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp)
            target = control / "raw/src-0123/example.bin"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"different")

            evidence = inspect_archive_target(
                control,
                "src-0123",
                "example.bin",
                "sha256:" + "a" * 64,
                17,
            )

            self.assertEqual(evidence.action, "archive-target-conflict")
            self.assertEqual(evidence.conflict, {"check": "archive-target-conflict"})
            self.assertFalse(evidence.staging_required)

    def test_target_change_while_hashing_is_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp)
            target = control / "raw/src-0123/example.bin"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"original")
            checksum = file_checksum(target)

            def hash_then_change(path: Path) -> str:
                result = file_checksum(path)
                path.write_bytes(b"changed-and-longer")
                return result

            with patch("llm_wiki_core.archive.file_checksum", side_effect=hash_then_change):
                with self.assertRaises(ArchiveConflict) as raised:
                    inspect_archive_target(
                        control, "src-0123", "example.bin", checksum, len(b"original")
                    )

            self.assertEqual(raised.exception.check, "archive-target-changed")


class RecordingReader:
    def __init__(self, path: Path) -> None:
        self.stream = path.open("rb")
        self.read_sizes: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stream.close()

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.stream.read(size)

    def fileno(self) -> int:
        return self.stream.fileno()


class ArchivePreparationTests(unittest.TestCase):
    def _fixture(self, tmp: str, content: bytes = b"0123456789abcdefg"):
        root = Path(tmp)
        source = root / "source.bin"
        control = root / "control"
        control.mkdir()
        source.write_bytes(content)
        origin = file_fingerprint(source)
        evidence = inspect_archive_target(
            control,
            "src-0123",
            source.name,
            file_checksum(source),
            origin["size"],
        )
        return source, control, origin, evidence

    def test_prepare_streams_in_fixed_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, control, origin, evidence = self._fixture(tmp)
            reader = RecordingReader(source)

            with patch("llm_wiki_core.archive.Path.open", return_value=reader):
                prepared = prepare_archive(
                    source, control, evidence, origin, chunk_size=4
                )

            self.assertEqual(reader.read_sizes, [4, 4, 4, 4, 4, 4])
            self.assertNotIn(-1, reader.read_sizes)
            self.assertEqual(prepared.staging_path.read_bytes(), source.read_bytes())
            cleanup_prepared_archive(prepared)

    def test_prepare_rejects_source_fingerprint_drift_before_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, control, origin, evidence = self._fixture(tmp)
            changed_origin = {**origin, "mtime_ns": origin["mtime_ns"] + 1}

            with self.assertRaises(ArchiveConflict) as raised:
                prepare_archive(source, control, evidence, changed_origin)

            self.assertEqual(raised.exception.check, "source-changed")

    def test_prepare_rejects_source_fingerprint_drift_during_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, control, origin, evidence = self._fixture(tmp)
            changed = {**origin, "mtime_ns": origin["mtime_ns"] + 1}

            with patch(
                "llm_wiki_core.archive.fingerprint_from_stat",
                side_effect=[origin, changed],
            ):
                with self.assertRaises(ArchiveConflict) as raised:
                    prepare_archive(source, control, evidence, origin, chunk_size=4)

            self.assertEqual(raised.exception.check, "source-changed")
            self.assertEqual(list((control / "raw").rglob("*.tmp")), [])

    def test_prepare_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, control, origin, evidence = self._fixture(tmp)
            evidence = type(evidence)(
                evidence.action,
                evidence.relative_path,
                "sha256:" + "0" * 64,
                evidence.size,
                evidence.fingerprint,
                evidence.staging_required,
                evidence.conflict,
            )

            with self.assertRaises(ArchiveConflict) as raised:
                prepare_archive(source, control, evidence, origin, chunk_size=4)

            self.assertEqual(raised.exception.check, "source-checksum-conflict")
            self.assertEqual(list((control / "raw").rglob("*.tmp")), [])

    def test_prepare_rejects_insufficient_space_before_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, control, origin, evidence = self._fixture(tmp)

            with self.assertRaises(ArchiveWriteError) as raised:
                prepare_archive(
                    source,
                    control,
                    evidence,
                    origin,
                    disk_usage=lambda _: SimpleNamespace(free=origin["size"] - 1),
                )

            self.assertEqual(raised.exception.check, "insufficient-space")
            self.assertEqual(list((control / "raw").rglob("*.tmp")), [])


class ArchivePublicationTests(unittest.TestCase):
    def _prepared(self, tmp: str, content: bytes = b"new"):
        root = Path(tmp)
        source = root / "source.bin"
        control = root / "control"
        control.mkdir()
        source.write_bytes(content)
        origin = file_fingerprint(source)
        evidence = inspect_archive_target(
            control,
            "src-0123",
            source.name,
            file_checksum(source),
            origin["size"],
        )
        return prepare_archive(source, control, evidence, origin)

    def test_validate_prepared_archive_is_stat_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = self._prepared(tmp)
            with patch(
                "llm_wiki_core.archive.file_checksum",
                side_effect=AssertionError("checksum read under lock"),
            ):
                validate_prepared_archive(prepared)
            cleanup_prepared_archive(prepared)

    def test_publish_never_overwrites_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = self._prepared(tmp)
            prepared.target_path.write_bytes(b"old")

            with self.assertRaises(ArchiveError) as raised:
                publish_archive_noreplace(prepared)

            self.assertEqual(raised.exception.check, "archive-target-changed")
            self.assertEqual(prepared.target_path.read_bytes(), b"old")
            cleanup_prepared_archive(prepared)

    def test_publish_reports_unsupported_atomic_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = self._prepared(tmp)

            with patch(
                "llm_wiki_core.archive.os.link",
                side_effect=OSError(errno.EPERM, "not supported"),
            ):
                with self.assertRaises(ArchiveWriteError) as raised:
                    publish_archive_noreplace(prepared)

            self.assertEqual(raised.exception.check, "atomic-publish-unsupported")
            self.assertIn("NTFS", raised.exception.hint)
            self.assertIn("ext4", raised.exception.hint)
            cleanup_prepared_archive(prepared)

    def test_publish_reports_residual_temp_without_rolling_back_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = self._prepared(tmp)
            real_unlink = os.unlink

            def fail_only_for_staging(path, *args, **kwargs):
                if Path(path) == prepared.staging_path:
                    raise PermissionError("busy")
                return real_unlink(path, *args, **kwargs)

            with patch("llm_wiki_core.archive.os.unlink", side_effect=fail_only_for_staging):
                result = publish_archive_noreplace(prepared)

            self.assertTrue(result.published)
            self.assertFalse(result.reused)
            self.assertTrue(result.temp_cleanup_pending)
            self.assertEqual(prepared.target_path.read_bytes(), b"new")
            self.assertTrue(prepared.staging_path.exists())
            cleanup_prepared_archive(prepared)

    def test_cleanup_only_removes_staging_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = self._prepared(tmp)
            prepared.target_path.write_bytes(b"target")

            cleanup_prepared_archive(prepared)

            self.assertFalse(prepared.staging_path.exists())
            self.assertEqual(prepared.target_path.read_bytes(), b"target")


if __name__ == "__main__":
    unittest.main()
