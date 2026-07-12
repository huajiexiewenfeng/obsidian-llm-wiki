import json
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.doctor_state import (
    inspect_state_consistency,
    load_doctor_state,
)
from llm_wiki_core.managed import managed_checksum
from llm_wiki_core.projection import (
    render_ingest_index,
    render_wiki_index,
    render_wiki_log,
)
from llm_wiki_core.state import OperationRecord, PageRecord, SourceRecord, file_checksum


STATE_FILES = (
    "schema.json",
    "sources.json",
    "pages.json",
    "operations.json",
    "change-log.jsonl",
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_phase3_control_center(base: Path) -> Path:
    control = base / "00-知识库中控"
    meta = control / ".meta"
    write_json(
        meta / "schema.json",
        {"schema_version": 1, "state_format": "obsidian-llm-wiki"},
    )
    for name in ("sources.json", "pages.json", "operations.json"):
        write_json(meta / name, {"schema_version": 1, "records": {}})
    (meta / "change-log.jsonl").write_bytes(b"")
    return control


def event(sequence: int = 1) -> dict[str, object]:
    return {
        "sequence": sequence,
        "operation_id": f"op-{sequence}",
        "kind": "state-init",
        "record_ids": [],
        "old_checksums": {},
        "new_checksums": {},
        "result": "completed",
        "timestamp": "2026-07-12T00:00:00+00:00",
    }


def write_registry(path: Path, records: dict[str, object]) -> None:
    write_json(path, {"schema_version": 1, "records": records})


def source_record(
    source_id: str = "source-1",
    *,
    status: str = "processed",
    proxy_page_id: str | None = "page-1",
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        display_path="notes/source.md",
        canonical_path="C:/vault/notes/source.md",
        source_type="markdown",
        mode="summary-ingest",
        status=status,
        fingerprint={"size": 10, "mtime_ns": 20},
        checksum="sha256:source",
        proxy_page_id=proxy_page_id,
        sensitivity="normal",
        last_verified_at="2026-07-12T00:00:00+00:00",
    )


def archive_source_record(
    source_id: str = "archive-1",
    *,
    archive_relative_path: str | None = "raw/archive-1/source.bin",
    checksum: str = "sha256:missing",
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        display_path="C:/external/source.bin",
        canonical_path="C:/external/source.bin",
        source_type="binary",
        mode="archive-import",
        status="pending",
        fingerprint={"size": 3, "mtime_ns": 20},
        checksum=checksum,
        proxy_page_id=None,
        sensitivity="normal",
        last_verified_at="2026-07-12T00:00:00+00:00",
        archive_relative_path=archive_relative_path,
    )


def managed_page(
    page_id: str = "page-1",
    *,
    page_type: str = "source",
    source_ids: tuple[str, ...] = ("source-1",),
    body: str = "# Managed",
    checksum_mirror: str | None = None,
    newline: str = "\n",
) -> tuple[str, str]:
    base_fields: dict[str, object] = {
        "llm_wiki_page_id": page_id,
        "llm_wiki_page_type": page_type,
        "llm_wiki_schema": 1,
        "llm_wiki_source_ids": list(source_ids),
    }
    checksum = managed_checksum(base_fields, body)
    fields = dict(base_fields)
    fields["llm_wiki_managed_checksum"] = checksum_mirror or checksum
    encoded = newline.join(
        f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        for key, value in sorted(fields.items())
    )
    text = (
        f"---{newline}# llm-wiki:frontmatter:start{newline}{encoded}{newline}"
        f"# llm-wiki:frontmatter:end{newline}---{newline}"
        f"<!-- llm-wiki:managed:start -->{newline}{body}{newline}"
        f"<!-- llm-wiki:managed:end -->{newline}"
    )
    return text, checksum


def projection_page(body: str, newline: str = "\n") -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    rendered = normalized.replace("\n", newline).rstrip("\r\n")
    return (
        f"<!-- llm-wiki:projection:start -->{newline}{rendered}{newline}"
        f"<!-- llm-wiki:projection:end -->{newline}"
    )


def write_healthy_projections(control: Path, newline: str = "\n") -> None:
    (control / "wiki").mkdir(parents=True, exist_ok=True)
    (control / "ingest").mkdir(parents=True, exist_ok=True)
    pages: dict[str, PageRecord] = {}
    sources: dict[str, SourceRecord] = {}
    (control / "wiki/index.md").write_text(
        projection_page(render_wiki_index(pages), newline),
        encoding="utf-8",
        newline="",
    )
    (control / "ingest/index.md").write_text(
        projection_page(render_ingest_index(sources, pages), newline),
        encoding="utf-8",
        newline="",
    )
    (control / "wiki/log.md").write_text(
        projection_page(render_wiki_log(()), newline),
        encoding="utf-8",
        newline="",
    )


def operation_record(
    operation_id: str = "op-1",
    *,
    kind: str = "ingest-apply",
    status: str = "running",
    record_ids: tuple[str, ...] = ("source-1",),
    updated_at: str = "2026-07-12T00:01:00+00:00",
) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        idempotency_key=f"key-{operation_id}",
        kind=kind,
        record_ids=record_ids,
        current_step="write-pages" if status != "completed" else "complete",
        status=status,
        started_at="2026-07-12T00:00:45+00:00",
        updated_at=updated_at,
        error="boom" if status == "failed" else None,
    )


def write_operations(control: Path, *operations: OperationRecord) -> None:
    write_registry(
        control / ".meta/operations.json",
        {item.operation_id: item.to_dict() for item in operations},
    )


def write_lock(
    control: Path,
    *,
    host: str | None = None,
    pid: int = 123,
    acquired_at: str = "2026-07-12T00:00:30+00:00",
    command: str = "ingest apply",
    target: str | None = None,
) -> None:
    write_json(
        control / ".meta/lock.json",
        {
            "lock_id": "lock-1",
            "host": host or socket.gethostname(),
            "pid": pid,
            "acquired_at": acquired_at,
            "command": command,
            "target": target or str(control.resolve()),
        },
    )


def write_completion_event(control: Path, operation: OperationRecord) -> None:
    payload = event()
    payload["operation_id"] = operation.operation_id
    payload["kind"] = operation.kind
    (control / ".meta/change-log.jsonl").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class DoctorStateLoadingTests(unittest.TestCase):
    def test_absent_meta_disables_phase4_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            control.mkdir()

            issues = inspect_state_consistency(control)

        self.assertEqual(issues, ())

    def test_missing_state_file_is_reported_without_hiding_valid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            (control / ".meta/pages.json").unlink()

            snapshot, issues = load_doctor_state(control)

        self.assertIsNone(snapshot.pages)
        self.assertIsNotNone(snapshot.sources)
        self.assertIsNotNone(snapshot.operations)
        missing = [issue for issue in issues if issue.check == "missing-state-file"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].severity, "ERROR")
        self.assertEqual(missing[0].relative_path, ".meta/pages.json")

    def test_invalid_pages_does_not_hide_other_state_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            (control / ".meta/pages.json").write_text("{", encoding="utf-8")

            snapshot, issues = load_doctor_state(control)

        self.assertIsNone(snapshot.pages)
        self.assertIsNotNone(snapshot.sources)
        self.assertIsNotNone(snapshot.operations)
        self.assertEqual(
            [issue.check for issue in issues],
            ["invalid-state-file"],
        )

    def test_missing_files_are_stably_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            (control / ".meta").mkdir(parents=True)

            _, issues = load_doctor_state(control)

        self.assertEqual(
            [issue.relative_path for issue in issues],
            sorted(f".meta/{name}" for name in STATE_FILES),
        )


class ChangeLogLoadingTests(unittest.TestCase):
    def test_valid_event_without_final_newline_is_not_torn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            encoded = json.dumps(event(), sort_keys=True).encode("utf-8")
            (control / ".meta/change-log.jsonl").write_bytes(encoded)

            snapshot, issues = load_doctor_state(control)

        self.assertEqual(len(snapshot.events), 1)
        self.assertNotIn("torn-change-log-tail", [issue.check for issue in issues])

    def test_torn_tail_warns_and_keeps_valid_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            prefix = json.dumps(event(), sort_keys=True).encode("utf-8") + b"\n"
            (control / ".meta/change-log.jsonl").write_bytes(
                prefix + b'{"sequence": 2'
            )

            snapshot, issues = load_doctor_state(control)

        self.assertEqual(tuple(item["sequence"] for item in snapshot.events), (1,))
        torn = [issue for issue in issues if issue.check == "torn-change-log-tail"]
        self.assertEqual(len(torn), 1)
        self.assertEqual(torn[0].severity, "WARN")
        self.assertEqual(torn[0].line, 2)

    def test_invalid_middle_line_is_error_and_disables_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            first = json.dumps(event(), sort_keys=True)
            third = json.dumps(event(3), sort_keys=True)
            (control / ".meta/change-log.jsonl").write_text(
                f"{first}\nnot-json\n{third}\n",
                encoding="utf-8",
            )

            snapshot, issues = load_doctor_state(control)

        self.assertIsNone(snapshot.events)
        invalid = [issue for issue in issues if issue.check == "invalid-state-file"]
        self.assertEqual(len(invalid), 1)
        self.assertEqual(invalid[0].line, 2)

    def test_invalid_last_line_with_newline_is_error_not_torn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            first = json.dumps(event(), sort_keys=True)
            (control / ".meta/change-log.jsonl").write_text(
                f"{first}\nnot-json\n",
                encoding="utf-8",
            )

            snapshot, issues = load_doctor_state(control)

        self.assertIsNone(snapshot.events)
        self.assertEqual(
            [issue.check for issue in issues],
            ["invalid-state-file"],
        )


class OperationLockConsistencyTests(unittest.TestCase):
    NOW = datetime(2026, 7, 12, 0, 5, tzinfo=timezone.utc)

    def test_running_operation_with_live_matching_lock_is_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            operation = operation_record()
            write_operations(control, operation)
            write_lock(control)

            issues = inspect_state_consistency(
                control,
                now=self.NOW,
                pid_exists=lambda pid: True,
            )

        active = [item for item in issues if item.check == "active-operation"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].severity, "INFO")
        self.assertNotIn("orphan-running-operation", [item.check for item in issues])

    def test_running_operation_without_lock_is_orphan_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_operations(control, operation_record())

            issues = inspect_state_consistency(control, now=self.NOW)

        orphan = [item for item in issues if item.check == "orphan-running-operation"]
        self.assertEqual(len(orphan), 1)
        self.assertEqual(orphan[0].severity, "ERROR")

    def test_stale_lock_reports_lock_and_running_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_operations(control, operation_record())
            write_lock(
                control,
                acquired_at=(self.NOW - timedelta(minutes=20)).isoformat(),
            )

            issues = inspect_state_consistency(
                control,
                now=self.NOW,
                pid_exists=lambda pid: False,
            )

        checks = [item.check for item in issues]
        self.assertIn("stale-lock", checks)
        self.assertIn("running-operation-with-stale-lock", checks)

    def test_cross_host_lock_suppresses_orphan_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_operations(control, operation_record())
            write_lock(control, host="other-host")

            issues = inspect_state_consistency(
                control,
                now=self.NOW,
                pid_exists=lambda pid: False,
            )

        checks = [item.check for item in issues]
        self.assertIn("cross-host-lock", checks)
        self.assertNotIn("orphan-running-operation", checks)

    def test_invalid_lock_does_not_suppress_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_operations(control, operation_record())
            write_json(control / ".meta/lock.json", {"host": "missing-fields"})

            issues = inspect_state_consistency(control, now=self.NOW)

        checks = [item.check for item in issues]
        self.assertIn("invalid-lock", checks)
        self.assertIn("orphan-running-operation", checks)

    def test_failed_operation_is_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_operations(control, operation_record(status="failed"))

            issues = inspect_state_consistency(control, now=self.NOW)

        failed = [item for item in issues if item.check == "failed-operation"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].severity, "WARN")

    def test_completed_event_with_failed_operation_reports_status_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            operation = operation_record(status="failed")
            write_operations(control, operation)
            write_completion_event(control, operation)

            issues = inspect_state_consistency(control, now=self.NOW)

        self.assertIn("operation-event-status-drift", [item.check for item in issues])

    def test_completed_audited_operation_without_event_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_operations(
                control,
                operation_record(kind="state-init", status="completed", record_ids=()),
            )

            issues = inspect_state_consistency(control, now=self.NOW)

        missing = [item for item in issues if item.check == "missing-completion-event"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].severity, "ERROR")

    def test_projection_rebuild_does_not_require_completion_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_operations(
                control,
                operation_record(
                    kind="projection-rebuild",
                    status="completed",
                    record_ids=(),
                ),
            )

            issues = inspect_state_consistency(control, now=self.NOW)

        self.assertNotIn("missing-completion-event", [item.check for item in issues])


class PendingSourceConsistencyTests(unittest.TestCase):
    def _write_pending_source(self, control: Path) -> None:
        source = source_record(status="pending", proxy_page_id=None)
        write_registry(
            control / ".meta/sources.json",
            {source.source_id: source.to_dict()},
        )

    def test_pending_without_related_operation_is_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            self._write_pending_source(control)

            issues = inspect_state_consistency(control)

        self.assertIn(
            "pending-source-without-active-operation",
            [item.check for item in issues],
        )

    def test_latest_failed_ingest_suppresses_duplicate_pending_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            self._write_pending_source(control)
            older = operation_record(
                "op-running-old",
                status="running",
                updated_at="2026-07-12T00:01:00+00:00",
            )
            latest = operation_record(
                "op-failed-new",
                status="failed",
                updated_at="2026-07-12T00:02:00+00:00",
            )
            write_operations(control, older, latest)

            issues = inspect_state_consistency(control)

        checks = [item.check for item in issues]
        self.assertIn("failed-operation", checks)
        self.assertNotIn("pending-source-without-active-operation", checks)
        failed = next(item for item in issues if item.check == "failed-operation")
        self.assertIn("source-1", failed.recovery_hint)

    def test_latest_completed_ingest_leaves_pending_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            self._write_pending_source(control)
            write_operations(control, operation_record(status="completed"))

            issues = inspect_state_consistency(control)

        self.assertIn(
            "pending-source-without-active-operation",
            [item.check for item in issues],
        )


class ArchiveConsistencyTests(unittest.TestCase):
    ARCHIVE_CHECKS = {
        "archive-record-missing-path",
        "unsafe-archive-path",
        "archive-file-missing",
        "archive-checksum-drift",
        "unexpected-archive-path",
        "archive-operation-target-drift",
        "unregistered-archive",
    }

    def test_healthy_archive_has_no_archive_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            target = control / "raw/archive-1/source.bin"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"abc")
            source = archive_source_record(checksum=file_checksum(target))
            write_registry(control / ".meta/sources.json", {source.source_id: source.to_dict()})

            issues = inspect_state_consistency(control)

        self.assertEqual(
            [item for item in issues if item.check in self.ARCHIVE_CHECKS],
            [],
        )

    def test_archive_record_and_target_failures_are_distinct(self):
        cases = (
            (
                "archive-record-missing-path",
                archive_source_record(archive_relative_path=None),
                None,
            ),
            (
                "unsafe-archive-path",
                archive_source_record(archive_relative_path="../outside.bin"),
                None,
            ),
            ("archive-file-missing", archive_source_record(), None),
            (
                "archive-checksum-drift",
                archive_source_record(checksum="sha256:" + "0" * 64),
                b"actual",
            ),
        )
        for expected_check, source, content in cases:
            with self.subTest(check=expected_check), tempfile.TemporaryDirectory() as tmp:
                control = make_phase3_control_center(Path(tmp))
                if content is not None:
                    target = control / Path(*source.archive_relative_path.split("/"))
                    target.parent.mkdir(parents=True)
                    target.write_bytes(content)
                write_registry(
                    control / ".meta/sources.json",
                    {source.source_id: source.to_dict()},
                )

                issues = inspect_state_consistency(control)

                issue = next(item for item in issues if item.check == expected_check)
                self.assertEqual(issue.severity, "ERROR")
                self.assertIsNotNone(issue.recovery_hint)
                self.assertNotIn("C:/external", issue.message)

    def test_non_archive_path_and_event_target_drift_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            target = control / "raw/archive-1/source.bin"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"abc")
            archive = archive_source_record(checksum=file_checksum(target))
            ordinary = source_record("source-ordinary", status="pending", proxy_page_id=None)
            ordinary = SourceRecord(
                **{**ordinary.to_dict(), "archive_relative_path": "raw/source-ordinary/x.bin"}
            )
            write_registry(
                control / ".meta/sources.json",
                {archive.source_id: archive.to_dict(), ordinary.source_id: ordinary.to_dict()},
            )
            change = {
                **event(),
                "kind": "ingest-apply",
                "record_ids": [archive.source_id],
                "summary": {"archive_target": "raw/archive-1/other.bin"},
            }
            (control / ".meta/change-log.jsonl").write_text(
                json.dumps(change) + "\n", encoding="utf-8"
            )

            checks = {item.check for item in inspect_state_consistency(control)}

        self.assertIn("unexpected-archive-path", checks)
        self.assertIn("archive-operation-target-drift", checks)

    def test_raw_scan_reports_unregistered_and_temp_without_modifying_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            raw = control / "raw/archive-1"
            raw.mkdir(parents=True)
            (raw / "unregistered.bin").write_bytes(b"secret-content")
            (raw / ".source.bin.ab12.tmp").write_bytes(b"temp-content")
            before = {
                path.relative_to(control).as_posix(): (
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                    path.read_bytes(),
                )
                for path in control.rglob("*")
                if path.is_file()
            }

            issues = inspect_state_consistency(control)
            after = {
                path.relative_to(control).as_posix(): (
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                    path.read_bytes(),
                )
                for path in control.rglob("*")
                if path.is_file()
            }

        by_check = {item.check: item for item in issues}
        self.assertIn("unregistered-archive", by_check)
        self.assertIn("orphan-temp-file", by_check)
        self.assertNotIn("secret-content", str(issues))
        self.assertEqual(before, after)

    def test_hard_linked_target_and_temp_only_report_the_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            target = control / "raw/archive-1/source.bin"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"abc")
            temp = target.with_name(".source.bin.ab12.tmp")
            try:
                os.link(target, temp)
            except OSError as error:
                self.skipTest(f"hard links unavailable: {error}")
            source = archive_source_record(checksum=file_checksum(target))
            write_registry(control / ".meta/sources.json", {source.source_id: source.to_dict()})

            issues = inspect_state_consistency(control)

        checks = [item.check for item in issues]
        self.assertEqual(checks.count("orphan-temp-file"), 1)
        self.assertNotIn("archive-checksum-drift", checks)
        self.assertNotIn("unregistered-archive", checks)


class TempFileConsistencyTests(unittest.TestCase):
    def test_only_writer_temp_pattern_in_allowed_roots_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            control = make_phase3_control_center(base)
            (control / ".meta/.pages.json.ab12.tmp").write_text(
                "SECRET-TEMP",
                encoding="utf-8",
            )
            (control / "wiki").mkdir()
            (control / "wiki/.topic.md.zz99.tmp").write_text(
                "SECRET-TEMP",
                encoding="utf-8",
            )
            (control / "ingest").mkdir()
            (control / "ingest/ordinary.tmp").write_text("x", encoding="utf-8")
            (base / ".outside.json.aa.tmp").write_text("x", encoding="utf-8")

            issues = inspect_state_consistency(control)

        temps = [item for item in issues if item.check == "orphan-temp-file"]
        self.assertEqual(
            [item.relative_path for item in temps],
            [".meta/.pages.json.ab12.tmp", "wiki/.topic.md.zz99.tmp"],
        )
        self.assertNotIn("SECRET-TEMP", str(temps))


class SourceConsistencyTests(unittest.TestCase):
    def test_processed_source_without_proxy_id_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            source = source_record(proxy_page_id=None)
            write_registry(
                control / ".meta/sources.json",
                {source.source_id: source.to_dict()},
            )

            issues = inspect_state_consistency(control)

        issue = next(
            item for item in issues if item.check == "processed-source-missing-proxy"
        )
        self.assertEqual(issue.severity, "ERROR")
        self.assertEqual(issue.relative_path, ".meta/sources.json")
        self.assertIsNotNone(issue.recovery_hint)

    def test_proxy_record_with_missing_file_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            source = source_record()
            page = PageRecord(
                page_id="page-1",
                relative_path="wiki/sources/source-1.md",
                page_type="source",
                source_ids=("source-1",),
                managed_checksum="sha256:missing",
            )
            write_registry(
                control / ".meta/sources.json",
                {source.source_id: source.to_dict()},
            )
            write_registry(
                control / ".meta/pages.json",
                {page.page_id: page.to_dict()},
            )

            issues = inspect_state_consistency(control)

        checks = [item.check for item in issues]
        self.assertIn("source-proxy-file-missing", checks)
        self.assertIn("registered-page-missing", checks)

    def test_failed_source_is_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            source = source_record(status="failed", proxy_page_id=None)
            write_registry(
                control / ".meta/sources.json",
                {source.source_id: source.to_dict()},
            )

            issues = inspect_state_consistency(control)

        failed = [item for item in issues if item.check == "failed-source"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].severity, "WARN")


class PageConsistencyTests(unittest.TestCase):
    def test_registered_page_missing_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            page = PageRecord(
                page_id="page-1",
                relative_path="wiki/topics/missing.md",
                page_type="topic",
                source_ids=(),
                managed_checksum="sha256:missing",
            )
            write_registry(
                control / ".meta/pages.json",
                {page.page_id: page.to_dict()},
            )

            issues = inspect_state_consistency(control)

        missing = [item for item in issues if item.check == "registered-page-missing"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].relative_path, "wiki/topics/missing.md")

    def test_frontmatter_drift_is_distinct_from_checksum_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            text, checksum = managed_page(page_type="topic", source_ids=())
            target = control / "wiki/topics/page-1.md"
            target.parent.mkdir(parents=True)
            target.write_text(text, encoding="utf-8", newline="")
            record = PageRecord(
                page_id="page-1",
                relative_path="wiki/topics/page-1.md",
                page_type="project",
                source_ids=(),
                managed_checksum=checksum,
            )
            write_registry(
                control / ".meta/pages.json",
                {record.page_id: record.to_dict()},
            )

            issues = inspect_state_consistency(control)

        checks = [item.check for item in issues]
        self.assertIn("page-frontmatter-drift", checks)
        self.assertNotIn("managed-checksum-drift", checks)

    def test_checksum_mirror_and_registry_drift_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            text, _ = managed_page(
                page_type="topic",
                source_ids=(),
                checksum_mirror="sha256:frontmatter-old",
            )
            target = control / "wiki/topics/page-1.md"
            target.parent.mkdir(parents=True)
            target.write_text(text, encoding="utf-8", newline="")
            record = PageRecord(
                page_id="page-1",
                relative_path="wiki/topics/page-1.md",
                page_type="topic",
                source_ids=(),
                managed_checksum="sha256:registry-old",
            )
            write_registry(
                control / ".meta/pages.json",
                {record.page_id: record.to_dict()},
            )

            issues = inspect_state_consistency(control)

        drift = [item for item in issues if item.check == "managed-checksum-drift"]
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0].severity, "ERROR")

    def test_registered_marker_conflict_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            text, checksum = managed_page(page_type="topic", source_ids=())
            text = text.replace(
                "<!-- llm-wiki:managed:start -->",
                "<!-- llm-wiki:managed:start -->\n<!-- llm-wiki:managed:start -->",
            )
            target = control / "wiki/topics/page-1.md"
            target.parent.mkdir(parents=True)
            target.write_text(text, encoding="utf-8", newline="")
            record = PageRecord(
                page_id="page-1",
                relative_path="wiki/topics/page-1.md",
                page_type="topic",
                source_ids=(),
                managed_checksum=checksum,
            )
            write_registry(
                control / ".meta/pages.json",
                {record.page_id: record.to_dict()},
            )

            issues = inspect_state_consistency(control)

        self.assertIn("managed-marker-conflict", [item.check for item in issues])

    def test_unregistered_managed_page_is_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            text, _ = managed_page("orphan-1", page_type="topic", source_ids=())
            target = control / "wiki/topics/orphan.md"
            target.parent.mkdir(parents=True)
            target.write_text(text, encoding="utf-8", newline="")

            issues = inspect_state_consistency(control)

        orphan = [item for item in issues if item.check == "orphan-managed-page"]
        self.assertEqual(len(orphan), 1)
        self.assertEqual(orphan[0].severity, "WARN")
        self.assertEqual(orphan[0].relative_path, "wiki/topics/orphan.md")


class ProjectionConsistencyTests(unittest.TestCase):
    def test_healthy_crlf_projections_have_no_projection_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_healthy_projections(control, "\r\n")

            issues = inspect_state_consistency(control)

        self.assertEqual(
            [item for item in issues if item.check.startswith("projection-")],
            [],
        )

    def test_projection_content_drift_is_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_healthy_projections(control)
            (control / "wiki/index.md").write_text(
                projection_page("# Drift"),
                encoding="utf-8",
                newline="",
            )

            issues = inspect_state_consistency(control)

        drift = [item for item in issues if item.check == "projection-drift"]
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0].severity, "WARN")
        self.assertEqual(drift[0].relative_path, "wiki/index.md")

    def test_projection_marker_conflict_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_healthy_projections(control)
            (control / "wiki/log.md").write_text(
                "<!-- llm-wiki:projection:start -->\nmissing end\n",
                encoding="utf-8",
            )

            issues = inspect_state_consistency(control)

        conflict = [
            item for item in issues if item.check == "projection-marker-conflict"
        ]
        self.assertEqual(len(conflict), 1)
        self.assertEqual(conflict[0].relative_path, "wiki/log.md")


if __name__ == "__main__":
    unittest.main()
