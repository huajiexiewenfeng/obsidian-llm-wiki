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
    inspect_inventory,
    load_inventory,
    scan_inventory,
)
from llm_wiki_core.state import PageRecord, SourceRecord, encode_registry, file_fingerprint


CONTROL_CENTER_NAME = "00-知识库中控"


def write_file(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def write_registry(path: Path, records: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode_registry(records), encoding="utf-8")


def write_baseline(
    control: Path,
    scope,
    documents: dict[str, InventoryDocument],
    sensitive_scopes=None,
) -> None:
    path = control / ".meta/inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = inventory_payload(
        InventoryBaseline(1, scope, documents, sensitive_scopes or {})
    )
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def processed_records(control: Path, source_path: Path):
    source_id = "src-0123456789abcdef"
    page_id = "page-0123456789abcdef"
    page_path = "wiki/sources/source.md"
    write_file(control / page_path, b"managed proxy")
    source = SourceRecord(
        source_id=source_id,
        display_path=source_path.as_posix(),
        canonical_path=source_path.resolve().as_posix(),
        source_type="markdown",
        mode="path-index",
        status="processed",
        fingerprint=file_fingerprint(source_path),
        checksum=None,
        proxy_page_id=page_id,
        sensitivity="normal",
        last_verified_at="2026-07-12T00:00:00+00:00",
    )
    page = PageRecord(
        page_id=page_id,
        relative_path=page_path,
        page_type="source",
        source_ids=(source_id,),
        managed_checksum="sha256:abc",
    )
    return source, page


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


class InventoryInspectionTests(unittest.TestCase):
    def test_missing_baseline_reports_only_incomplete_inventory_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            write_file(vault / "notes/new.md")

            result = inspect_inventory(vault, control)

        self.assertEqual([item.check for item in result.findings], ["missing-ingest-inventory"])
        self.assertIn("known-existing", result.findings[0].hint)
        self.assertIn("do not require ingest", result.findings[0].hint)
        self.assertIn("unverified", result.findings[0].hint)
        self.assertIn("not auto-ingested", result.findings[0].hint)
        self.assertIn("post-baseline", result.findings[0].hint)
        self.assertFalse(result.complete)

    def test_reports_uningested_document_after_baseline_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source = vault / "notes/new.md"
            write_file(source)
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            signature = ObservedSignature(**file_fingerprint(source))
            write_baseline(
                control,
                scope,
                {"notes/new.md": InventoryDocument("discovered", signature, None)},
            )
            write_registry(control / ".meta/sources.json", {})
            write_registry(control / ".meta/pages.json", {})

            result = inspect_inventory(vault, control)

        self.assertEqual([item.check for item in result.findings], ["uningested-source"])
        self.assertEqual(result.findings[0].path, "notes/new.md")
        self.assertTrue(result.complete)

    def test_unverified_historical_document_is_source_island_not_uningested(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source = vault / "notes/island.md"
            write_file(source)
            write_file(control / "wiki/index.md", b"# Index")
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            write_baseline(
                control,
                scope,
                {
                    "notes/island.md": InventoryDocument(
                        "unverified",
                        ObservedSignature(**file_fingerprint(source)),
                        None,
                    )
                },
            )
            write_registry(control / ".meta/sources.json", {})
            write_registry(control / ".meta/pages.json", {})

            result = inspect_inventory(vault, control)

        self.assertEqual([item.check for item in result.findings], ["source-island"])
        self.assertEqual(result.findings[0].path, "notes/island.md")

    def test_known_existing_document_with_removed_edge_reports_coverage_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source = vault / "notes/covered.md"
            write_file(source)
            write_file(control / "wiki/index.md", b"# Index")
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            write_baseline(
                control,
                scope,
                {
                    "notes/covered.md": InventoryDocument(
                        "known-existing",
                        ObservedSignature(**file_fingerprint(source)),
                        None,
                    )
                },
            )
            write_registry(control / ".meta/sources.json", {})
            write_registry(control / ".meta/pages.json", {})

            result = inspect_inventory(vault, control)

        self.assertEqual(
            [item.check for item in result.findings],
            ["source-coverage-lost"],
        )
        self.assertEqual(result.findings[0].path, "notes/covered.md")

    def test_complete_registry_evidence_marks_document_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source_path = vault / "notes/processed.md"
            write_file(source_path)
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            signature = ObservedSignature(**file_fingerprint(source_path))
            write_baseline(
                control,
                scope,
                {"notes/processed.md": InventoryDocument("discovered", signature, None)},
            )
            source, page = processed_records(control, source_path)
            write_registry(control / ".meta/sources.json", {source.source_id: source.to_dict()})
            write_registry(control / ".meta/pages.json", {page.page_id: page.to_dict()})

            result = inspect_inventory(vault, control)

        self.assertEqual(result.findings, ())
        self.assertTrue(result.complete)

    def test_missing_proxy_page_does_not_count_as_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source_path = vault / "notes/no-proxy.md"
            write_file(source_path)
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            signature = ObservedSignature(**file_fingerprint(source_path))
            write_baseline(
                control,
                scope,
                {"notes/no-proxy.md": InventoryDocument("discovered", signature, None)},
            )
            source, page = processed_records(control, source_path)
            (control / page.relative_path).unlink()
            write_registry(control / ".meta/sources.json", {source.source_id: source.to_dict()})
            write_registry(control / ".meta/pages.json", {page.page_id: page.to_dict()})

            result = inspect_inventory(vault, control)

        self.assertIn("uningested-source", {item.check for item in result.findings})

    def test_multiple_processed_sources_for_same_path_are_never_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source_path = vault / "notes/ambiguous.md"
            write_file(source_path)
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            write_baseline(
                control,
                scope,
                {
                    "notes/ambiguous.md": InventoryDocument(
                        "discovered",
                        ObservedSignature(**file_fingerprint(source_path)),
                        None,
                    )
                },
            )
            original_source, original_page = processed_records(control, source_path)
            sources = {}
            pages = {}
            for index in range(3):
                source_id = f"src-{index:016d}"
                page_id = f"page-{index:016d}"
                page_path = f"wiki/sources/source-{index}.md"
                write_file(control / page_path, b"managed proxy")
                source = replace(
                    original_source,
                    source_id=source_id,
                    proxy_page_id=page_id,
                )
                page = replace(
                    original_page,
                    page_id=page_id,
                    relative_path=page_path,
                    source_ids=(source_id,),
                )
                sources[source_id] = source.to_dict()
                pages[page_id] = page.to_dict()
            write_registry(control / ".meta/sources.json", sources)
            write_registry(control / ".meta/pages.json", pages)

            result = inspect_inventory(vault, control)

        self.assertIn("uningested-source", {item.check for item in result.findings})

    def test_processed_fingerprint_change_beats_ignored_disposition(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source_path = vault / "notes/stale.md"
            write_file(source_path, b"before")
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            source, page = processed_records(control, source_path)
            write_baseline(
                control,
                scope,
                {
                    "notes/stale.md": InventoryDocument(
                        "ignored",
                        ObservedSignature(**source.fingerprint),
                        "user-approved",
                    )
                },
            )
            write_registry(control / ".meta/sources.json", {source.source_id: source.to_dict()})
            write_registry(control / ".meta/pages.json", {page.page_id: page.to_dict()})
            write_file(source_path, b"after-and-larger")

            result = inspect_inventory(vault, control)

        self.assertEqual([item.check for item in result.findings], ["stale-ingested-source"])

    def test_ignored_document_without_processed_source_is_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source_path = vault / "notes/ignored.md"
            write_file(source_path)
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            write_baseline(
                control,
                scope,
                {
                    "notes/ignored.md": InventoryDocument(
                        "ignored",
                        ObservedSignature(**file_fingerprint(source_path)),
                        "user-approved",
                    )
                },
            )
            write_registry(control / ".meta/sources.json", {})
            write_registry(control / ".meta/pages.json", {})

            result = inspect_inventory(vault, control)

        self.assertEqual(result.findings, ())

    def test_inspection_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = vault / CONTROL_CENTER_NAME
            source_path = vault / "notes/new.md"
            write_file(source_path)
            scope = default_inventory_scope(CONTROL_CENTER_NAME)
            write_baseline(
                control,
                scope,
                {
                    "notes/new.md": InventoryDocument(
                        "discovered",
                        ObservedSignature(**file_fingerprint(source_path)),
                        None,
                    )
                },
            )
            write_registry(control / ".meta/sources.json", {})
            write_registry(control / ".meta/pages.json", {})
            before = {
                path.relative_to(vault).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in vault.rglob("*")
                if path.is_file()
            }

            inspect_inventory(vault, control)

            after = {
                path.relative_to(vault).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in vault.rglob("*")
                if path.is_file()
            }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
