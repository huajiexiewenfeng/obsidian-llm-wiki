import json
import sys
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
