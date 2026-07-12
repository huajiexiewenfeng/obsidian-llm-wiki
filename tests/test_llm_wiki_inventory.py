import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.inventory import (
    InventoryBaseline,
    InventoryDocument,
    InventoryLoadError,
    InventoryValidationError,
    ObservedSignature,
    SensitiveScope,
    default_inventory_scope,
    inventory_payload,
    load_inventory,
    scan_inventory,
)


CONTROL_CENTER_NAME = "00-知识库中控"


def write_file(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class InventoryScannerTests(unittest.TestCase):
    def test_scans_supported_vault_document_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            write_file(vault / "notes/new.md", b"hello")

            observation = scan_inventory(
                vault,
                control,
                default_inventory_scope(CONTROL_CENTER_NAME),
            )

        signature = observation.documents["notes/new.md"]
        self.assertEqual(signature.size, 5)
        self.assertGreater(signature.mtime_ns, 0)
        self.assertEqual(observation.errors, ())

    def test_excludes_system_dependency_control_center_and_unsupported_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            included = vault / "notes/keep.markdown"
            write_file(included)
            for relative in (
                ".git/hidden.md",
                ".obsidian/hidden.md",
                ".agents/hidden.md",
                "node_modules/pkg/hidden.md",
                f"{CONTROL_CENTER_NAME}/.meta/hidden.md",
                f"{CONTROL_CENTER_NAME}/ingest/hidden.md",
                f"{CONTROL_CENTER_NAME}/wiki/hidden.md",
                f"{CONTROL_CENTER_NAME}/raw/src-1/hidden.md",
                "notes/image.png",
            ):
                write_file(vault / relative)

            observation = scan_inventory(
                vault,
                control,
                default_inventory_scope(CONTROL_CENTER_NAME),
            )

        self.assertEqual(set(observation.documents), {"notes/keep.markdown"})

    def test_raw_exclusion_cannot_be_force_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            write_file(control / "raw/src-1/hidden.md")
            scope = replace(
                default_inventory_scope(CONTROL_CENTER_NAME),
                force_include=(f"{CONTROL_CENTER_NAME}/raw/**",),
            )

            observation = scan_inventory(vault, control, scope)

        self.assertEqual(observation.documents, {})

    def test_sensitive_scope_returns_only_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            write_file(vault / "private/secret-name.md", b"secret")
            scope = replace(
                default_inventory_scope(CONTROL_CENTER_NAME),
                sensitive=(SensitiveScope("sensitive-1", "private/**"),),
            )

            observation = scan_inventory(vault, control, scope)

        self.assertEqual(observation.documents, {})
        summary = observation.sensitive_scopes["sensitive-1"]
        self.assertEqual(summary.document_count, 1)
        self.assertGreater(summary.latest_mtime_ns, 0)
        self.assertNotIn("secret-name", repr(observation))

    def test_rejects_unsafe_scope_patterns(self):
        scope = default_inventory_scope(CONTROL_CENTER_NAME)
        for pattern in ("../outside/**", "/absolute/**", "C:/absolute/**"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(InventoryValidationError):
                    replace(scope, include=(pattern,))

    def test_does_not_follow_directory_symlink(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            outside = Path(outside_tmp)
            write_file(outside / "escaped.md")
            link = vault / "linked"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlink unavailable: {error}")

            observation = scan_inventory(
                vault,
                control,
                default_inventory_scope(CONTROL_CENTER_NAME),
            )

        self.assertEqual(observation.documents, {})


class InventoryCodecTests(unittest.TestCase):
    def test_baseline_round_trips_deterministically(self):
        scope = default_inventory_scope(CONTROL_CENTER_NAME)
        baseline = InventoryBaseline(
            schema_version=1,
            scope=scope,
            documents={
                "notes/a.md": InventoryDocument(
                    disposition="discovered",
                    observed_signature=ObservedSignature(size=3, mtime_ns=4),
                    ignore_reason=None,
                )
            },
            sensitive_scopes={},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inventory.json"
            first = json.dumps(
                inventory_payload(baseline),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
            path.write_text(first, encoding="utf-8")
            loaded = load_inventory(path)
            second = json.dumps(
                inventory_payload(loaded),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"

        self.assertEqual(loaded, baseline)
        self.assertEqual(second, first)

    def test_rejects_unknown_schema_and_unsafe_document_path(self):
        scope = inventory_payload(
            InventoryBaseline(1, default_inventory_scope(CONTROL_CENTER_NAME), {}, {})
        )["scope"]
        cases = (
            {"schema_version": 2, "scope": scope, "documents": {}, "sensitive_scopes": {}},
            {
                "schema_version": 1,
                "scope": scope,
                "documents": {
                    "../outside.md": {
                        "disposition": "discovered",
                        "observed_signature": {"size": 1, "mtime_ns": 1},
                        "ignore_reason": None,
                    }
                },
                "sensitive_scopes": {},
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "inventory.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(InventoryLoadError):
                        load_inventory(path)

    def test_rejects_malformed_json_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inventory.json"
            original = b'{"schema_version": 1'
            path.write_bytes(original)

            with self.assertRaises(InventoryLoadError):
                load_inventory(path)

            self.assertEqual(path.read_bytes(), original)

    def test_ignored_document_requires_reason(self):
        with self.assertRaises(InventoryValidationError):
            InventoryDocument(
                    "ignored",
                    ObservedSignature(size=1, mtime_ns=1),
                    None,
                )


if __name__ == "__main__":
    unittest.main()
