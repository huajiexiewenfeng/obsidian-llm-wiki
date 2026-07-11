import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from llm_wiki_core.state import (
    PageRecord,
    SourceRecord,
    StateValidationError,
    decode_page_registry,
    decode_source_registry,
    empty_registry,
    encode_registry,
)
from llm_wiki_core.state import (
    canonical_path,
    casefold_path_key,
    ensure_within,
    file_checksum,
    file_fingerprint,
    plan_state_init,
    stable_record_id,
)


SOURCE = SourceRecord(
    source_id="src-0123456789abcdef",
    display_path=r"D:\materials\example.md",
    canonical_path="D:/materials/example.md",
    source_type="markdown",
    mode="path-index",
    status="pending",
    fingerprint={"size": 1024, "mtime_ns": 1783658400000000000},
    checksum=None,
    proxy_page_id=None,
    sensitivity="normal",
    last_verified_at="2026-07-11T00:00:00+00:00",
    revision=1,
)


class RegistryCodecTests(unittest.TestCase):
    def test_empty_registry_has_schema_one(self):
        self.assertEqual(empty_registry(), {"schema_version": 1, "records": {}})

    def test_source_registry_round_trips_deterministically(self):
        encoded = encode_registry({SOURCE.source_id: SOURCE.to_dict()})
        self.assertTrue(encoded.endswith("\n"))
        payload = json.loads(encoded)
        decoded = decode_source_registry(payload)
        self.assertEqual(decoded[SOURCE.source_id], SOURCE)
        self.assertEqual(encoded, encode_registry(payload["records"]))

    def test_duplicate_record_identity_is_rejected(self):
        payload = empty_registry()
        payload["records"]["wrong-key"] = SOURCE.to_dict()
        with self.assertRaisesRegex(StateValidationError, "source_id does not match registry key"):
            decode_source_registry(payload)

    def test_unknown_schema_is_rejected(self):
        with self.assertRaisesRegex(StateValidationError, "schema_version must be 1"):
            decode_source_registry({"schema_version": 2, "records": {}})

    def test_page_path_must_be_control_center_relative(self):
        page = PageRecord(
            page_id="page-0123456789abcdef",
            relative_path="../outside.md",
            page_type="source",
            source_ids=(SOURCE.source_id,),
            managed_checksum="sha256:abc",
            revision=1,
        )
        with self.assertRaisesRegex(StateValidationError, "relative_path"):
            decode_page_registry({"schema_version": 1, "records": {page.page_id: page.to_dict()}})


class SourceIdentityTests(unittest.TestCase):
    def test_stable_id_is_deterministic_and_namespaced(self):
        first = stable_record_id("src", "D:/materials/example.md")
        second = stable_record_id("src", "D:/materials/example.md")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^src-[0-9a-f]{16}$")

    def test_canonical_path_uses_forward_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Folder" / "note.md"
            path.parent.mkdir()
            path.write_text("hello", encoding="utf-8")
            self.assertEqual(canonical_path(path), path.resolve().as_posix())

    def test_casefold_key_does_not_change_display_path(self):
        value = "C:/Vault/Topic.md"
        self.assertEqual(casefold_path_key(value, windows=True), "c:/vault/topic.md")
        self.assertEqual(value, "C:/Vault/Topic.md")

    def test_write_target_outside_control_center_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "control"
            root.mkdir()
            with self.assertRaisesRegex(StateValidationError, "outside allowed root"):
                ensure_within(Path(tmp) / "outside.json", root)

    def test_symlink_escape_is_rejected_when_platform_allows_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "control"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            link = root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(StateValidationError, "outside allowed root"):
                ensure_within(link / "state.json", root)

    def test_fingerprint_uses_size_and_mtime_ns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_bytes(b"hello")
            stat = path.stat()
            self.assertEqual(file_fingerprint(path), {"size": 5, "mtime_ns": stat.st_mtime_ns})

    def test_checksum_streams_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_bytes(b"hello")
            self.assertEqual(
                file_checksum(path),
                "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            )


class StateInitPlanTests(unittest.TestCase):
    def test_fresh_meta_lists_all_state_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-知识库中控"
            control.mkdir()
            plan = plan_state_init(control)
            self.assertEqual(
                plan.create,
                ("schema.json", "sources.json", "pages.json", "operations.json", "change-log.jsonl"),
            )
            self.assertEqual(plan.unchanged, ())

    def test_invalid_existing_registry_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-知识库中控"
            meta = control / ".meta"
            meta.mkdir(parents=True)
            (meta / "sources.json").write_text('{"schema_version": 99}', encoding="utf-8")
            with self.assertRaisesRegex(StateValidationError, "sources.json"):
                plan_state_init(control)
