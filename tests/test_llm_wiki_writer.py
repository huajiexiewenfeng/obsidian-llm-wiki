import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.state import empty_registry
from llm_wiki_core.writer import (
    LockTimeout,
    SnapshotConflict,
    VaultLock,
    append_change_event,
    atomic_write_json,
    begin_operation,
    classify_lock,
    file_text_checksum,
    update_operation,
)


class VaultLockTests(unittest.TestCase):
    def test_exclusive_lock_blocks_second_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / ".meta" / "lock.json"
            first = VaultLock(
                lock_path,
                allowed_root=Path(tmp),
                command="state init",
                target=Path(tmp),
                wait_seconds=0,
            )
            second = VaultLock(
                lock_path,
                allowed_root=Path(tmp),
                command="state init",
                target=Path(tmp),
                wait_seconds=0,
            )
            with first:
                with self.assertRaises(LockTimeout):
                    second.acquire()
            self.assertFalse(lock_path.exists())

    def test_release_does_not_remove_another_owner_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / ".meta" / "lock.json"
            lock = VaultLock(
                lock_path,
                allowed_root=Path(tmp),
                command="state init",
                target=Path(tmp),
                wait_seconds=0,
            )
            lock.acquire()
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            payload["lock_id"] = "another-owner"
            lock_path.write_text(json.dumps(payload), encoding="utf-8")
            lock.release()
            self.assertTrue(lock_path.exists())

    def test_same_host_dead_pid_old_lock_is_stale(self):
        acquired = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
        payload = {"host": socket.gethostname(), "pid": 99999999, "acquired_at": acquired}
        self.assertEqual(classify_lock(payload, pid_exists=lambda pid: False), "stale")

    def test_cross_host_lock_is_never_auto_stale(self):
        acquired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        payload = {"host": "another-host", "pid": 1, "acquired_at": acquired}
        self.assertEqual(classify_lock(payload, pid_exists=lambda pid: False), "cross-host")


class SnapshotWriterTests(unittest.TestCase):
    def test_atomic_json_is_deterministic_and_replaces_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".meta" / "sources.json"
            atomic_write_json(target, empty_registry(), allowed_root=Path(tmp))
            first = target.read_text(encoding="utf-8")
            atomic_write_json(
                target,
                empty_registry(),
                allowed_root=Path(tmp),
                expected_checksum=file_text_checksum(target),
            )
            self.assertEqual(target.read_text(encoding="utf-8"), first)

    def test_expected_checksum_conflict_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sources.json"
            target.write_text('{"original": true}\n', encoding="utf-8")
            with self.assertRaises(SnapshotConflict):
                atomic_write_json(
                    target,
                    empty_registry(),
                    allowed_root=Path(tmp),
                    expected_checksum="sha256:wrong",
                )
            self.assertEqual(target.read_text(encoding="utf-8"), '{"original": true}\n')

    def test_existing_target_requires_expected_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sources.json"
            target.write_text('{"original": true}\n', encoding="utf-8")
            with self.assertRaisesRegex(SnapshotConflict, "expected checksum is required"):
                atomic_write_json(target, empty_registry(), allowed_root=Path(tmp))
            self.assertEqual(target.read_text(encoding="utf-8"), '{"original": true}\n')

    def test_replace_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sources.json"
            target.write_text('{"original": true}\n', encoding="utf-8")
            with patch("llm_wiki_core.writer.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_write_json(
                        target,
                        empty_registry(),
                        allowed_root=Path(tmp),
                        expected_checksum=file_text_checksum(target),
                    )
            self.assertEqual(target.read_text(encoding="utf-8"), '{"original": true}\n')

    def test_change_log_sequence_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "change-log.jsonl"
            first = append_change_event(
                path,
                allowed_root=Path(tmp),
                operation_id="op-1",
                kind="state-init",
                record_ids=[],
                old_checksums={},
                new_checksums={},
                result="completed",
            )
            second = append_change_event(
                path,
                allowed_root=Path(tmp),
                operation_id="op-2",
                kind="state-init",
                record_ids=[],
                old_checksums={},
                new_checksums={},
                result="completed",
            )
            self.assertEqual((first["sequence"], second["sequence"]), (1, 2))
            self.assertEqual(first["old_checksums"], {})
            self.assertEqual(first["new_checksums"], {})

    def test_operation_moves_from_running_to_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operations.json"
            operation = begin_operation(
                path,
                allowed_root=Path(tmp),
                kind="state-init",
                idempotency_key="sha256:key",
                record_ids=[],
            )
            failed = update_operation(
                path,
                operation.operation_id,
                allowed_root=Path(tmp),
                status="failed",
                current_step="write-schema",
                error="boom",
            )
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.error, "boom")
