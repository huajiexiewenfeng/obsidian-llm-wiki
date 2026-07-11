import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from llm_wiki_core.writer import LockTimeout, VaultLock, classify_lock


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
