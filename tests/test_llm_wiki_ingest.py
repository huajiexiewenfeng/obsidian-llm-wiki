import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.ingest import (
    IngestValidationError,
    load_payload_file,
    load_payload_text,
    normalized_payload_dict,
)
import llm_wiki_core


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {
            "path": "C:/materials/example.md",
            "source_type": "markdown",
            "mode": "summary-ingest",
            "fingerprint": {"size": 5, "mtime_ns": 123456789},
            "checksum": "sha256:" + "a" * 64,
            "sensitivity": "normal",
            "move_resolution": None,
        },
        "pages": [
            {
                "role": "source-proxy",
                "page_type": "source",
                "path": "wiki/sources/example.md",
                "managed_body": "# Example\n",
                "expected_managed_checksum": None,
                "takeover": False,
            },
            {
                "role": "derived",
                "page_type": "topic",
                "path": "wiki/topics/example.md",
                "managed_body": "# Topic\n",
                "expected_managed_checksum": None,
                "takeover": False,
            },
        ],
        "projection_takeovers": ["wiki/log.md", "wiki/index.md"],
    }


class PayloadContractTests(unittest.TestCase):
    def test_payload_api_is_exported_from_runtime_package(self):
        self.assertIs(llm_wiki_core.IngestPayload, type(load_payload_text(json.dumps(valid_payload()))))
        self.assertIs(llm_wiki_core.load_payload_text, load_payload_text)

    def test_file_and_stdin_share_normalized_payload(self):
        text = json.dumps(valid_payload(), ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload.json"
            path.write_text(text, encoding="utf-8")

            from_file = load_payload_file(str(path), io.StringIO("unused"))
            from_stdin = load_payload_file("-", io.StringIO(text))

        self.assertEqual(normalized_payload_dict(from_file), normalized_payload_dict(from_stdin))
        self.assertEqual(
            normalized_payload_dict(from_file)["projection_takeovers"],
            ["wiki/index.md", "wiki/log.md"],
        )

    def test_unknown_top_level_field_is_rejected_without_body_echo(self):
        payload = valid_payload()
        payload["unexpected"] = "SECRET-MANAGED-BODY"

        with self.assertRaises(IngestValidationError) as raised:
            load_payload_text(json.dumps(payload))

        self.assertEqual(raised.exception.check, "invalid-payload")
        self.assertNotIn("SECRET-MANAGED-BODY", str(raised.exception))

    def test_payload_requires_exactly_one_source_proxy(self):
        for pages in ([], [valid_payload()["pages"][1]]):
            with self.subTest(pages=pages):
                payload = valid_payload()
                payload["pages"] = pages
                with self.assertRaisesRegex(IngestValidationError, "exactly one source-proxy"):
                    load_payload_text(json.dumps(payload))

    def test_derived_pages_may_be_empty(self):
        payload = valid_payload()
        payload["pages"] = [payload["pages"][0]]

        parsed = load_payload_text(json.dumps(payload))

        self.assertEqual(len(parsed.pages), 1)
        self.assertEqual(parsed.pages[0].role, "source-proxy")

    def test_page_paths_must_not_casefold_collide(self):
        payload = valid_payload()
        duplicate = dict(payload["pages"][1])
        duplicate["path"] = "WIKI/SOURCES/EXAMPLE.md"
        payload["pages"].append(duplicate)

        with self.assertRaisesRegex(IngestValidationError, "page paths conflict"):
            load_payload_text(json.dumps(payload))

    def test_archive_import_is_a_structured_unsupported_mode(self):
        payload = valid_payload()
        payload["source"]["mode"] = "archive-import"

        with self.assertRaises(IngestValidationError) as raised:
            load_payload_text(json.dumps(payload))

        self.assertEqual(raised.exception.check, "unsupported-mode")

    def test_unknown_schema_and_nested_fields_are_rejected(self):
        payload = valid_payload()
        payload["schema_version"] = 2
        with self.assertRaisesRegex(IngestValidationError, "schema_version"):
            load_payload_text(json.dumps(payload))

        payload = valid_payload()
        payload["source"]["unexpected"] = True
        with self.assertRaisesRegex(IngestValidationError, "unknown fields"):
            load_payload_text(json.dumps(payload))

        payload = valid_payload()
        payload["pages"][0]["unexpected"] = True
        with self.assertRaisesRegex(IngestValidationError, "unknown fields"):
            load_payload_text(json.dumps(payload))

    def test_invalid_page_type_and_sensitivity_are_rejected(self):
        payload = valid_payload()
        payload["pages"][1]["page_type"] = "checklist"
        with self.assertRaisesRegex(IngestValidationError, "page_type"):
            load_payload_text(json.dumps(payload))

        payload = valid_payload()
        payload["source"]["sensitivity"] = "unknown"
        with self.assertRaisesRegex(IngestValidationError, "sensitivity"):
            load_payload_text(json.dumps(payload))

    def test_source_path_must_be_absolute(self):
        payload = valid_payload()
        payload["source"]["path"] = "materials/example.md"

        with self.assertRaisesRegex(IngestValidationError, "absolute"):
            load_payload_text(json.dumps(payload))

    def test_page_escape_uses_ingest_validation_error(self):
        payload = valid_payload()
        payload["pages"][0]["path"] = "../outside.md"

        with self.assertRaises(IngestValidationError) as raised:
            load_payload_text(json.dumps(payload))

        self.assertEqual(raised.exception.check, "invalid-payload")

    def test_move_resolution_rebind_requires_only_source_id(self):
        payload = valid_payload()
        payload["source"]["move_resolution"] = {"action": "rebind"}
        with self.assertRaisesRegex(IngestValidationError, "source_id"):
            load_payload_text(json.dumps(payload))

        payload = valid_payload()
        payload["source"]["move_resolution"] = {
            "action": "rebind",
            "source_id": "src-0123456789abcdef",
            "extra": True,
        }
        with self.assertRaisesRegex(IngestValidationError, "unknown fields"):
            load_payload_text(json.dumps(payload))

    def test_new_source_resolution_rejects_source_id(self):
        payload = valid_payload()
        payload["source"]["move_resolution"] = {
            "action": "new-source",
            "source_id": "src-0123456789abcdef",
        }

        with self.assertRaisesRegex(IngestValidationError, "unknown fields"):
            load_payload_text(json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
