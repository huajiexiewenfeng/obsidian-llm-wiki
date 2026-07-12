import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.archive import (
    ArchiveConflict,
    archive_relative_path,
    archive_source_id,
    inspect_archive_target,
    safe_archive_filename,
)
from llm_wiki_core.state import SourceRecord, file_checksum


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


if __name__ == "__main__":
    unittest.main()
