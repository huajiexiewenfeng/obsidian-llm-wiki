import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.ingest import (
    IngestPlanConflict,
    IngestWriteError,
    IngestValidationError,
    apply_ingest,
    load_payload_file,
    load_payload_text,
    normalized_payload_dict,
    plan_ingest,
)
from llm_wiki_core.projection import read_change_events
from llm_wiki_core.state import (
    SourceRecord,
    decode_page_registry,
    decode_source_registry,
    file_checksum,
    file_fingerprint,
)
from llm_wiki_core.writer import load_operations
import llm_wiki_core


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {
            "path": str((Path(tempfile.gettempdir()) / "materials" / "example.md").resolve()),
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
        self.assertIsNotNone(llm_wiki_core.ArchiveTargetEvidence)
        self.assertEqual(llm_wiki_core.prepare_archive.__module__, "llm_wiki_core.archive")

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

    def test_archive_import_is_an_allowed_mode(self):
        payload = valid_payload()
        payload["source"]["mode"] = "archive-import"

        parsed = load_payload_text(json.dumps(payload))

        self.assertEqual(parsed.source.mode, "archive-import")

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


def write_registry(path: Path, records: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "records": records}, ensure_ascii=False),
        encoding="utf-8",
    )


def planner_fixture(base: Path, name: str = "source.md") -> tuple[Path, Path, dict[str, object]]:
    control = base / "control"
    meta = control / ".meta"
    source_path = base / name
    source_path.write_bytes(b"source-v1")
    write_registry(meta / "sources.json", {})
    write_registry(meta / "pages.json", {})
    (meta / "change-log.jsonl").write_bytes(b"")
    payload = valid_payload()
    payload["source"]["path"] = str(source_path.resolve())
    payload["source"]["fingerprint"] = file_fingerprint(source_path)
    payload["source"]["checksum"] = file_checksum(source_path)
    payload["pages"] = [payload["pages"][0]]
    return control, source_path, payload


def source_record(source_id: str, path: Path, checksum: str, *, revision: int = 1) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        display_path=str(path),
        canonical_path=path.resolve().as_posix(),
        source_type="markdown",
        mode="summary-ingest",
        status="processed",
        fingerprint=file_fingerprint(path) if path.exists() else {"size": 9, "mtime_ns": 1},
        checksum=checksum,
        proxy_page_id=None,
        sensitivity="normal",
        last_verified_at="2026-07-11T00:00:00+00:00",
        revision=revision,
    )


def archive_record(
    source_id: str,
    path: Path,
    checksum: str,
    *,
    revision: int = 1,
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        display_path=str(path),
        canonical_path=path.resolve().as_posix(),
        source_type="binary",
        mode="archive-import",
        status="processed",
        fingerprint=file_fingerprint(path) if path.exists() else {"size": 9, "mtime_ns": 1},
        checksum=checksum,
        proxy_page_id=None,
        sensitivity="normal",
        last_verified_at="2026-07-12T00:00:00+00:00",
        revision=revision,
        archive_relative_path=f"raw/{source_id}/{path.name}",
    )


def archive_planner_fixture(
    base: Path,
    name: str = "example.bin",
) -> tuple[Path, Path, dict[str, object]]:
    control, source_path, payload = planner_fixture(base, name)
    source_path.write_bytes(b"archive-binary-v1\x00\xff")
    payload["source"].update(
        {
            "source_type": "binary",
            "mode": "archive-import",
            "fingerprint": file_fingerprint(source_path),
            "checksum": file_checksum(source_path),
        }
    )
    return control, source_path, payload


def tree_snapshot(root: Path) -> dict[str, tuple[bool, int, int, bytes | None]]:
    return {
        path.relative_to(root).as_posix(): (
            path.is_dir(),
            path.stat().st_size,
            path.stat().st_mtime_ns,
            None if path.is_dir() else path.read_bytes(),
        )
        for path in root.rglob("*")
    }


class IngestPlannerTests(unittest.TestCase):
    def test_archive_dry_run_plans_target_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, _, raw = archive_planner_fixture(Path(tmp))
            before = tree_snapshot(control)

            plan = plan_ingest(control, load_payload_text(json.dumps(raw)))
            after = tree_snapshot(control)

        self.assertEqual(before, after)
        self.assertEqual(plan.archive.action, "archive-create")
        self.assertTrue(plan.archive.staging_required)
        self.assertEqual(
            plan.to_public_dict()["archive"]["target"],
            f"raw/{plan.source.source_id}/example.bin",
        )
        self.assertNotIn("archive-binary-v1", str(plan.to_public_dict()))

    def test_archive_same_origin_reuses_and_changed_content_requires_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, source_path, raw = archive_planner_fixture(Path(tmp))
            initial = plan_ingest(control, load_payload_text(json.dumps(raw)))
            existing = archive_record(
                initial.source.source_id,
                source_path,
                raw["source"]["checksum"],
            )
            write_registry(control / ".meta/sources.json", {existing.source_id: existing.to_dict()})

            same = plan_ingest(control, load_payload_text(json.dumps(raw)))
            source_path.write_bytes(b"archive-binary-v2")
            raw["source"]["fingerprint"] = file_fingerprint(source_path)
            raw["source"]["checksum"] = file_checksum(source_path)
            conflict = plan_ingest(control, load_payload_text(json.dumps(raw)))
            raw["source"]["move_resolution"] = {"action": "new-source"}
            distinct = plan_ingest(control, load_payload_text(json.dumps(raw)))

        self.assertEqual(same.source.action, "unchanged")
        self.assertEqual(same.source.source_id, existing.source_id)
        self.assertEqual(conflict.source.action, "archive-content-changed")
        self.assertEqual(conflict.source.conflict["check"], "archive-content-changed")
        self.assertFalse(conflict.confirmable)
        self.assertEqual(distinct.source.action, "create")
        self.assertNotEqual(distinct.source.source_id, existing.source_id)

    def test_archive_rebind_then_new_source_uses_collision_ordinal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            control, path_a, raw_a = archive_planner_fixture(base, "a.bin")
            first = plan_ingest(control, load_payload_text(json.dumps(raw_a)))
            existing = archive_record(
                first.source.source_id,
                path_a,
                raw_a["source"]["checksum"],
            )
            write_registry(control / ".meta/sources.json", {existing.source_id: existing.to_dict()})

            path_b = base / "b.bin"
            path_b.write_bytes(path_a.read_bytes())
            raw_b = json.loads(json.dumps(raw_a))
            raw_b["source"]["path"] = str(path_b.resolve())
            raw_b["source"]["fingerprint"] = file_fingerprint(path_b)
            raw_b["source"]["move_resolution"] = {
                "action": "rebind",
                "source_id": existing.source_id,
            }
            path_a.unlink()
            rebound = plan_ingest(control, load_payload_text(json.dumps(raw_b)))

            rebound_record = archive_record(
                existing.source_id,
                path_b,
                raw_b["source"]["checksum"],
                revision=2,
            )
            write_registry(
                control / ".meta/sources.json",
                {rebound_record.source_id: rebound_record.to_dict()},
            )
            path_a.write_bytes(path_b.read_bytes())
            raw_a["source"]["fingerprint"] = file_fingerprint(path_a)
            raw_a["source"]["move_resolution"] = {"action": "new-source"}
            collision = plan_ingest(control, load_payload_text(json.dumps(raw_a)))

        self.assertEqual(rebound.source.action, "rebind")
        self.assertEqual(rebound.source.source_id, existing.source_id)
        self.assertEqual(collision.source.action, "create")
        self.assertNotEqual(collision.source.source_id, existing.source_id)

    def test_archive_target_recovery_keeps_plan_checksum_and_conflict_blocks_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, source_path, raw = archive_planner_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            create = plan_ingest(control, payload)
            target = control / Path(*create.archive.relative_path.split("/"))
            target.parent.mkdir(parents=True)
            target.write_bytes(source_path.read_bytes())

            reuse = plan_ingest(control, payload)
            target.write_bytes(b"conflicting-target")
            conflict = plan_ingest(control, payload)

        self.assertEqual(reuse.archive.action, "archive-reuse")
        self.assertEqual(create.plan_checksum, reuse.plan_checksum)
        self.assertEqual(conflict.archive.action, "archive-target-conflict")
        self.assertFalse(conflict.confirmable)
        self.assertEqual(conflict.archive.conflict["check"], "archive-target-conflict")

    def test_new_source_plan_is_deterministic_and_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, _, raw = planner_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            before = {path.relative_to(control): path.read_bytes() for path in control.rglob("*") if path.is_file()}

            first = plan_ingest(control, payload)
            second = plan_ingest(control, payload)
            after = {path.relative_to(control): path.read_bytes() for path in control.rglob("*") if path.is_file()}

        self.assertEqual(first.plan_checksum, second.plan_checksum)
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(first.source.action, "create")
        self.assertTrue(first.confirmable)
        self.assertEqual(before, after)

    def test_same_path_reuses_source_and_changed_checksum_increments_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, source_path, raw = planner_fixture(Path(tmp))
            existing = source_record("src-existing", source_path, raw["source"]["checksum"])
            write_registry(control / ".meta/sources.json", {existing.source_id: existing.to_dict()})

            same = plan_ingest(control, load_payload_text(json.dumps(raw)))
            source_path.write_bytes(b"source-v2")
            raw["source"]["fingerprint"] = file_fingerprint(source_path)
            raw["source"]["checksum"] = file_checksum(source_path)
            changed = plan_ingest(control, load_payload_text(json.dumps(raw)))

        self.assertEqual(same.source.source_id, "src-existing")
        self.assertEqual(same.source.action, "unchanged")
        self.assertEqual(changed.source.source_id, "src-existing")
        self.assertEqual(changed.source.action, "update")
        self.assertEqual(changed.source.revision, 2)

    def test_move_candidate_requires_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            control, new_path, raw = planner_fixture(base, "new.md")
            old_path = base / "old.md"
            old_path.write_bytes(new_path.read_bytes())
            existing = source_record("src-existing", old_path, raw["source"]["checksum"])
            write_registry(control / ".meta/sources.json", {existing.source_id: existing.to_dict()})

            plan = plan_ingest(control, load_payload_text(json.dumps(raw)))

        self.assertEqual(plan.source.action, "move-conflict")
        self.assertFalse(plan.confirmable)
        self.assertEqual(plan.source.candidate_source_ids, ("src-existing",))

    def test_rebind_requires_missing_old_path_and_new_source_stays_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            control, new_path, raw = planner_fixture(base, "new.md")
            old_path = base / "old.md"
            old_path.write_bytes(new_path.read_bytes())
            existing = source_record("src-existing", old_path, raw["source"]["checksum"])
            write_registry(control / ".meta/sources.json", {existing.source_id: existing.to_dict()})
            raw["source"]["move_resolution"] = {"action": "rebind", "source_id": "src-existing"}

            copy_plan = plan_ingest(control, load_payload_text(json.dumps(raw)))
            old_path.unlink()
            rebind = plan_ingest(control, load_payload_text(json.dumps(raw)))
            raw["source"]["move_resolution"] = {"action": "new-source"}
            distinct = plan_ingest(control, load_payload_text(json.dumps(raw)))

        self.assertEqual(copy_plan.source.action, "source-copy-not-move")
        self.assertFalse(copy_plan.confirmable)
        self.assertEqual(rebind.source.action, "rebind")
        self.assertEqual(rebind.source.source_id, "src-existing")
        self.assertNotEqual(distinct.source.source_id, "src-existing")

    def test_source_fingerprint_or_checksum_drift_is_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, source_path, raw = planner_fixture(Path(tmp))
            raw["source"]["fingerprint"]["size"] += 1
            with self.assertRaises(IngestPlanConflict) as fingerprint_error:
                plan_ingest(control, load_payload_text(json.dumps(raw)))
            self.assertEqual(fingerprint_error.exception.check, "source-fingerprint-conflict")

            raw["source"]["fingerprint"] = file_fingerprint(source_path)
            raw["source"]["checksum"] = "sha256:" + "b" * 64
            with self.assertRaises(IngestPlanConflict) as checksum_error:
                plan_ingest(control, load_payload_text(json.dumps(raw)))
            self.assertEqual(checksum_error.exception.check, "source-checksum-conflict")

    def test_payload_registry_and_target_drift_change_plan_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, source_path, raw = planner_fixture(Path(tmp))
            initial = plan_ingest(control, load_payload_text(json.dumps(raw)))
            self.assertNotIn("# Example", str(initial.to_public_dict()))

            changed_payload = json.loads(json.dumps(raw))
            changed_payload["pages"][0]["managed_body"] = "SECRET-CHANGED-BODY"
            payload_plan = plan_ingest(control, load_payload_text(json.dumps(changed_payload)))

            unrelated = source_record(
                "src-unrelated",
                source_path,
                "sha256:" + "c" * 64,
            )
            unrelated = SourceRecord(
                **{
                    **unrelated.to_dict(),
                    "canonical_path": "Z:/unrelated.md",
                    "display_path": "Z:/unrelated.md",
                }
            )
            write_registry(
                control / ".meta/sources.json",
                {unrelated.source_id: unrelated.to_dict()},
            )
            registry_plan = plan_ingest(control, load_payload_text(json.dumps(raw)))

            (control / "wiki").mkdir(parents=True, exist_ok=True)
            (control / "wiki/index.md").write_bytes(b"User projection\n")
            target_plan = plan_ingest(control, load_payload_text(json.dumps(raw)))

        self.assertNotEqual(initial.plan_checksum, payload_plan.plan_checksum)
        self.assertNotEqual(initial.plan_checksum, registry_plan.plan_checksum)
        self.assertNotEqual(registry_plan.plan_checksum, target_plan.plan_checksum)
        self.assertNotIn("SECRET-CHANGED-BODY", str(payload_plan.to_public_dict()))


def transaction_fixture(base: Path) -> tuple[Path, dict[str, object]]:
    control, _, raw = planner_fixture(base)
    write_registry(control / ".meta/operations.json", {})
    return control, raw


def archive_transaction_fixture(base: Path) -> tuple[Path, Path, dict[str, object]]:
    control, source, raw = archive_planner_fixture(base)
    write_registry(control / ".meta/operations.json", {})
    return control, source, raw


class IngestTransactionTests(unittest.TestCase):
    def test_archive_wrong_confirmation_creates_no_raw_or_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, _, raw = archive_transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))

            with self.assertRaises(IngestPlanConflict) as raised:
                apply_ingest(control, payload, "sha256:" + "0" * 64)

            self.assertEqual(raised.exception.check, "plan-conflict")
            self.assertFalse((control / "raw").exists())

    def test_archive_create_is_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, source, raw = archive_transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            plan = plan_ingest(control, payload)

            result = apply_ingest(control, payload, plan.plan_checksum)
            sources = decode_source_registry(
                json.loads((control / ".meta/sources.json").read_text(encoding="utf-8"))
            )
            record = sources[result.source_id]
            target = control / Path(*record.archive_relative_path.split("/"))
            events = read_change_events(control / ".meta/change-log.jsonl")
            operation = load_operations(control / ".meta/operations.json")[result.operation_id]
            repeated = apply_ingest(control, payload, plan.plan_checksum)
            repeated_events = read_change_events(control / ".meta/change-log.jsonl")
            target_bytes = target.read_bytes()
            source_bytes = source.read_bytes()
            temp_files = list((control / "raw").rglob("*.tmp"))

        self.assertEqual(target_bytes, source_bytes)
        self.assertEqual(record.status, "processed")
        self.assertEqual(result.archive_relative_path, record.archive_relative_path)
        self.assertEqual(events[0]["summary"]["archive_target"], record.archive_relative_path)
        self.assertEqual(operation.status, "completed")
        self.assertTrue(repeated.idempotent)
        self.assertEqual(repeated.operation_id, result.operation_id)
        self.assertEqual(repeated.archive_relative_path, record.archive_relative_path)
        self.assertEqual(len(repeated_events), 1)
        self.assertEqual(temp_files, [])

    def test_archive_reuse_does_not_publish_a_new_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, source, raw = archive_transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            initial = plan_ingest(control, payload)
            target = control / Path(*initial.archive.relative_path.split("/"))
            target.parent.mkdir(parents=True)
            target.write_bytes(source.read_bytes())
            reuse = plan_ingest(control, payload)

            with patch(
                "llm_wiki_core.archive.os.link",
                side_effect=AssertionError("reuse attempted publication"),
            ):
                result = apply_ingest(control, payload, reuse.plan_checksum)
            target_bytes = target.read_bytes()
            source_bytes = source.read_bytes()

        self.assertEqual(result.archive_relative_path, reuse.archive.relative_path)
        self.assertEqual(target_bytes, source_bytes)

    def test_archive_full_checksum_reads_stay_outside_vault_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, _, raw = archive_transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            plan = plan_ingest(control, payload)
            real_checksum = file_checksum
            calls: list[Path] = []

            def guarded_checksum(path: Path, *args, **kwargs):
                if (control / ".meta/lock.json").exists():
                    raise AssertionError("full checksum read occurred under Vault lock")
                calls.append(Path(path))
                return real_checksum(Path(path), *args, **kwargs)

            with patch("llm_wiki_core.ingest.file_checksum", side_effect=guarded_checksum), patch(
                "llm_wiki_core.archive.file_checksum", side_effect=guarded_checksum
            ):
                result = apply_ingest(control, payload, plan.plan_checksum)

        self.assertEqual(result.status, "completed")
        self.assertGreaterEqual(len(calls), 1)

    def test_archive_failure_before_publish_cleans_temp_and_fresh_plan_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, _, raw = archive_transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            plan = plan_ingest(control, payload)

            with self.assertRaises(IngestWriteError) as raised:
                apply_ingest(
                    control,
                    payload,
                    plan.plan_checksum,
                    fail_after_step="write-source-pending",
                )

            target = control / Path(*plan.archive.relative_path.split("/"))
            self.assertFalse(target.exists())
            self.assertEqual(list((control / "raw").rglob("*.tmp")), [])
            retry_plan = plan_ingest(control, payload)
            recovered = apply_ingest(control, payload, retry_plan.plan_checksum)
            recovered_target_exists = target.is_file()

        self.assertEqual(raised.exception.current_step, "write-source-pending")
        self.assertEqual(recovered.status, "completed")
        self.assertTrue(recovered_target_exists)

    def test_archive_failure_after_publish_keeps_target_and_retry_reuses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, source, raw = archive_transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            plan = plan_ingest(control, payload)

            with self.assertRaises(IngestWriteError) as raised:
                apply_ingest(
                    control,
                    payload,
                    plan.plan_checksum,
                    fail_after_step="publish-archive",
                )

            target = control / Path(*plan.archive.relative_path.split("/"))
            self.assertEqual(target.read_bytes(), source.read_bytes())
            retry_plan = plan_ingest(control, payload)
            self.assertEqual(retry_plan.archive.action, "archive-reuse")
            recovered = apply_ingest(control, payload, retry_plan.plan_checksum)
            events = read_change_events(control / ".meta/change-log.jsonl")

        self.assertEqual(raised.exception.current_step, "publish-archive")
        self.assertEqual(recovered.status, "completed")
        self.assertEqual(len(events), 1)

    def test_archive_transaction_steps_record_precise_failure_position(self):
        steps = (
            "write-source-pending",
            "publish-archive",
            "write-pages",
            "write-page-registry",
            "write-projections",
            "write-source-processed",
            "append-change-log",
        )
        for step in steps:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                control, _, raw = archive_transaction_fixture(Path(tmp))
                payload = load_payload_text(json.dumps(raw))
                plan = plan_ingest(control, payload)

                with self.assertRaises(IngestWriteError):
                    apply_ingest(
                        control,
                        payload,
                        plan.plan_checksum,
                        fail_after_step=step,
                    )

                operations = load_operations(control / ".meta/operations.json")
                failed = next(iter(operations.values()))
                self.assertEqual(failed.status, "failed")
                self.assertEqual(failed.current_step, step)

    def test_confirmed_transaction_writes_processed_state_pages_projections_and_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, raw = transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            plan = plan_ingest(control, payload)

            result = apply_ingest(control, payload, plan.plan_checksum)

            sources = decode_source_registry(
                json.loads((control / ".meta/sources.json").read_text(encoding="utf-8"))
            )
            pages = decode_page_registry(
                json.loads((control / ".meta/pages.json").read_text(encoding="utf-8"))
            )
            events = read_change_events(control / ".meta/change-log.jsonl")
            operation = load_operations(control / ".meta/operations.json")[result.operation_id]
            projection_files = {
                relative: (control / relative).is_file()
                for relative in ("wiki/index.md", "ingest/index.md", "wiki/log.md")
            }
            ingest_index = (control / "ingest/index.md").read_text(encoding="utf-8")
            repeated = apply_ingest(control, payload, plan.plan_checksum)
            repeated_events = read_change_events(control / ".meta/change-log.jsonl")

        self.assertEqual(result.status, "completed")
        self.assertFalse(result.idempotent)
        self.assertEqual(sources[plan.source.source_id].status, "processed")
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["idempotency_key"], plan.idempotency_key)
        self.assertEqual(operation.status, "completed")
        self.assertTrue(all(projection_files.values()))
        self.assertIn("processed", ingest_index)
        self.assertTrue(repeated.idempotent)
        self.assertEqual(repeated.operation_id, result.operation_id)
        self.assertEqual(len(repeated_events), 1)

    def test_wrong_confirmed_checksum_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, raw = transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            before = {path.relative_to(control): path.read_bytes() for path in control.rglob("*") if path.is_file()}

            with self.assertRaises(IngestPlanConflict) as raised:
                apply_ingest(control, payload, "sha256:" + "0" * 64)
            after = {path.relative_to(control): path.read_bytes() for path in control.rglob("*") if path.is_file()}

        self.assertEqual(raised.exception.check, "plan-conflict")
        self.assertEqual(before, after)

    def test_failure_after_pages_leaves_pending_source_and_failed_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, raw = transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            plan = plan_ingest(control, payload)

            with self.assertRaises(IngestWriteError) as raised:
                apply_ingest(control, payload, plan.plan_checksum, fail_after_step="write-pages")

            sources = decode_source_registry(
                json.loads((control / ".meta/sources.json").read_text(encoding="utf-8"))
            )
            operations = load_operations(control / ".meta/operations.json")
            failed = next(iter(operations.values()))

        self.assertEqual(sources[plan.source.source_id].status, "pending")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.current_step, "write-pages")
        self.assertIn("wiki/sources/example.md", raised.exception.completed_targets)

    def test_retry_after_appended_event_repairs_operation_without_duplicate_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            control, raw = transaction_fixture(Path(tmp))
            payload = load_payload_text(json.dumps(raw))
            plan = plan_ingest(control, payload)
            with self.assertRaises(IngestWriteError):
                apply_ingest(
                    control,
                    payload,
                    plan.plan_checksum,
                    fail_after_step="append-change-log",
                )
            first_events = read_change_events(control / ".meta/change-log.jsonl")

            result = apply_ingest(control, payload, plan.plan_checksum)
            second_events = read_change_events(control / ".meta/change-log.jsonl")
            operation = load_operations(control / ".meta/operations.json")[result.operation_id]

        self.assertTrue(result.idempotent)
        self.assertEqual(len(first_events), 1)
        self.assertEqual(len(second_events), 1)
        self.assertEqual(operation.status, "completed")

    def test_each_transaction_step_records_precise_failure_position(self):
        steps = (
            "write-source-pending",
            "write-pages",
            "write-page-registry",
            "write-projections",
            "write-source-processed",
            "append-change-log",
            "complete",
        )
        for step in steps:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                control, raw = transaction_fixture(Path(tmp))
                payload = load_payload_text(json.dumps(raw))
                plan = plan_ingest(control, payload)

                with self.assertRaises(IngestWriteError):
                    apply_ingest(
                        control,
                        payload,
                        plan.plan_checksum,
                        fail_after_step=step,
                    )

                operations = load_operations(control / ".meta/operations.json")
                failed = next(iter(operations.values()))
                self.assertEqual(failed.status, "failed")
                self.assertEqual(failed.current_step, step)


if __name__ == "__main__":
    unittest.main()
