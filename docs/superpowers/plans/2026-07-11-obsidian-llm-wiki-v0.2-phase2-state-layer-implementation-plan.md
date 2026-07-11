# Obsidian LLM Wiki v0.2 Phase 2 状态层实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Obsidian LLM Wiki 增加 `.meta` 状态契约、幂等 `state init`、独占锁、原子快照写入、operation/change-log 审计、来源指纹以及安全的 Markdown 托管区基础函数。

**Architecture:** `llm_wiki_core.state` 只拥有 schema、record、registry、稳定 ID 和 fingerprint/checksum；`llm_wiki_core.writer` 只拥有锁、原子替换、operation 与 change log；`llm_wiki_core.managed` 只拥有 frontmatter、managed body 和 projection marker 的纯文本变换。`scripts/llm_wiki.py state init` 组合这些组件，但 Phase 3 的 `ingest apply` 和 Phase 4 的 Doctor 迁移不在本计划中实现。

**Tech Stack:** Python 3.10+ 标准库（`argparse`、`dataclasses`、`hashlib`、`json`、`os`、`pathlib`、`socket`、`tempfile`、`time`、`uuid`、`unittest`），PowerShell，Git。

---

## 范围

本计划只实现 v0.2 Phase 2：

- `.meta/schema.json`、`sources.json`、`pages.json`、`operations.json`、`change-log.jsonl`。
- source/page/operation record 的 schema v1 与唯一键校验。
- `state init` dry-run、确认写入和幂等补全。
- `.meta/lock.json` 的独占创建、超时、所有者释放和 stale 分类基础函数。
- snapshot checksum 复核、同目录临时文件、flush/fsync 和原子替换。
- operation snapshot 与 append-only change log。
- canonical path、casefold key、稳定 ID、fingerprint 和 SHA-256。
- frontmatter、managed body、projection marker 的确定性纯函数。

本计划不实现：

- `ingest apply`、`page apply` 或 `projection rebuild` 公开命令。
- source proxy 或索引投影的业务内容生成。
- Doctor 迁移、stale-lock finding 或自动清锁。
- v0.3 Inventory、Context Pack 或 migration。
- WikiLink resolver 修改。
- installable runtime 重新打包。

## 前置与绿色基线

实施必须从包含本计划的提交创建独立 worktree，建议分支：

```text
codex/v02-phase2-state-layer
```

当前工作站无全局 `python` 命令，使用 bundled Python：

```powershell
$python = 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $python --version
& $python -m unittest discover tests -v
```

预期：

```text
Python 3.12.13
Ran 50 tests
OK
```

任何任务开始前都运行：

```powershell
git status --short --branch
git rev-parse --short HEAD
```

预期：worktree 干净，HEAD 包含本计划和 Change Brief。

## 文件地图

### 新增

- `scripts/llm_wiki_core/state.py`：schema v1、record 模型、registry 编解码、路径身份、fingerprint/checksum 和 state-init 计划模型。
- `scripts/llm_wiki_core/writer.py`：Vault lock、checksum 冲突、原子替换、operation snapshot 和 change log。
- `scripts/llm_wiki_core/managed.py`：frontmatter、managed body、projection marker 与 managed checksum。
- `tests/test_llm_wiki_state.py`：状态模型、registry、身份和 fingerprint 测试。
- `tests/test_llm_wiki_writer.py`：锁、原子写、operation 和 change log 测试。
- `tests/test_llm_wiki_managed.py`：托管 marker、用户区保留和 conflict 测试。

### 修改

- `scripts/llm_wiki_core/__init__.py`：导出 Phase 2 的稳定公共接口。
- `scripts/llm_wiki.py`：增加 `state init` 解析、JSON/text 输出和退出码。
- `tests/test_llm_wiki_cli.py`：增加 state-init dry-run、confirm、幂等和错误退出码测试。
- `skills/obsidian-wiki-init/SKILL.md`：Init 在写页面前先调用 `state init`。
- `docs/architecture.md`：记录 `.meta` 单一事实源和写入边界。
- `docs/workflow.md`：记录 state-init 与后续 Phase 3 的边界。
- `docs/development-plan.md`：标记 Phase 2 交付与剩余 Phase 3/4。
- `README.md`、`README.zh.md`：增加状态初始化命令和安全说明。
- `.llm-wiki/requirements/obsidian-v02-phase2-state-layer.md`：执行完成后由 `project-finish` 更新，不在普通实现任务中提前标记完成。

## 公共数据契约

### Snapshot registry

```json
{
  "schema_version": 1,
  "records": {}
}
```

### Source record

```json
{
  "source_id": "src-0123456789abcdef",
  "display_path": "D:\\materials\\example.md",
  "canonical_path": "D:/materials/example.md",
  "source_type": "markdown",
  "mode": "path-index",
  "status": "pending",
  "fingerprint": {"size": 1024, "mtime_ns": 1783658400000000000},
  "checksum": null,
  "proxy_page_id": null,
  "sensitivity": "normal",
  "last_verified_at": "2026-07-11T00:00:00+00:00",
  "revision": 1
}
```

### Page record

```json
{
  "page_id": "page-0123456789abcdef",
  "relative_path": "wiki/sources/example.md",
  "page_type": "source",
  "source_ids": ["src-0123456789abcdef"],
  "managed_checksum": "sha256:...",
  "revision": 1
}
```

### Operation record

```json
{
  "operation_id": "op-0123456789abcdef",
  "idempotency_key": "sha256:...",
  "kind": "state-init",
  "record_ids": [],
  "current_step": "write-schema",
  "status": "running",
  "started_at": "2026-07-11T00:00:00+00:00",
  "updated_at": "2026-07-11T00:00:00+00:00",
  "error": null
}
```

### `state init` JSON

Dry-run：

```json
{
  "control_center": "<resolved-control-center>",
  "meta_root": "<resolved-control-center>/.meta",
  "confirmation_required": true,
  "initialized": false,
  "create": ["schema.json", "sources.json", "pages.json", "operations.json", "change-log.jsonl"],
  "unchanged": []
}
```

确认或幂等重跑时退出码为 `0`；等待确认返回 `1`；无效 schema/path 返回 `2`；锁或 IO 失败返回 `3`。

## Task 1：定义 schema、record 与 registry 编解码

**Files:**
- Create: `scripts/llm_wiki_core/state.py`
- Create: `tests/test_llm_wiki_state.py`
- Modify: `scripts/llm_wiki_core/__init__.py`

- [ ] **Step 1：写失败的 registry 与 record 测试**

创建 `tests/test_llm_wiki_state.py`：

```python
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
```

- [ ] **Step 2：运行测试并确认失败**

```powershell
& $python -m unittest tests.test_llm_wiki_state.RegistryCodecTests -v
```

预期：`ModuleNotFoundError: No module named 'llm_wiki_core.state'`。

- [ ] **Step 3：实现最小 schema 与 record 模型**

在 `scripts/llm_wiki_core/state.py` 中实现这些接口：

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

SCHEMA_VERSION = 1
SOURCE_STATUSES = frozenset({"pending", "processed", "failed"})
SOURCE_MODES = frozenset({"path-index", "summary-ingest", "archive-import"})
PAGE_TYPES = frozenset({"source", "topic", "project", "entity", "sop", "index", "log"})


class StateValidationError(ValueError):
    pass


def require_string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise StateValidationError(f"{field} must be a non-empty string")
    return value


def validate_relative_path(value: str, field: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise StateValidationError(f"{field} must be a control-center-relative path")
    return path.as_posix()


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    display_path: str
    canonical_path: str
    source_type: str
    mode: str
    status: str
    fingerprint: dict[str, int]
    checksum: str | None
    proxy_page_id: str | None
    sensitivity: str
    last_verified_at: str
    revision: int = 1

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SourceRecord":
        fingerprint = payload.get("fingerprint")
        if not isinstance(fingerprint, dict) or set(fingerprint) != {"size", "mtime_ns"}:
            raise StateValidationError("fingerprint must contain size and mtime_ns")
        if any(not isinstance(value, int) or value < 0 for value in fingerprint.values()):
            raise StateValidationError("fingerprint values must be non-negative integers")
        status = require_string(payload.get("status"), "status")
        mode = require_string(payload.get("mode"), "mode")
        checksum = payload.get("checksum")
        proxy_page_id = payload.get("proxy_page_id")
        revision = payload.get("revision", 1)
        if checksum is not None and not isinstance(checksum, str):
            raise StateValidationError("checksum must be a string or null")
        if proxy_page_id is not None and not isinstance(proxy_page_id, str):
            raise StateValidationError("proxy_page_id must be a string or null")
        if not isinstance(revision, int) or revision < 1:
            raise StateValidationError("revision must be positive")
        if status not in SOURCE_STATUSES:
            raise StateValidationError("source status is invalid")
        if mode not in SOURCE_MODES:
            raise StateValidationError("source mode is invalid")
        return cls(
            source_id=require_string(payload.get("source_id"), "source_id"),
            display_path=require_string(payload.get("display_path"), "display_path"),
            canonical_path=require_string(payload.get("canonical_path"), "canonical_path"),
            source_type=require_string(payload.get("source_type"), "source_type"),
            mode=mode,
            status=status,
            fingerprint={"size": fingerprint["size"], "mtime_ns": fingerprint["mtime_ns"]},
            checksum=checksum,
            proxy_page_id=proxy_page_id,
            sensitivity=require_string(payload.get("sensitivity"), "sensitivity"),
            last_verified_at=require_string(payload.get("last_verified_at"), "last_verified_at"),
            revision=revision,
        )


@dataclass(frozen=True)
class PageRecord:
    page_id: str
    relative_path: str
    page_type: str
    source_ids: tuple[str, ...]
    managed_checksum: str
    revision: int = 1

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["source_ids"] = list(self.source_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PageRecord":
        source_ids = payload.get("source_ids")
        if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
            raise StateValidationError("source_ids must be a string array")
        revision = payload.get("revision", 1)
        if not isinstance(revision, int) or revision < 1:
            raise StateValidationError("revision must be positive")
        record = cls(
            page_id=require_string(payload.get("page_id"), "page_id"),
            relative_path=validate_relative_path(require_string(payload.get("relative_path"), "relative_path"), "relative_path"),
            page_type=require_string(payload.get("page_type"), "page_type"),
            source_ids=tuple(source_ids),
            managed_checksum=require_string(payload.get("managed_checksum"), "managed_checksum"),
            revision=revision,
        )
        if record.page_type not in PAGE_TYPES:
            raise StateValidationError("page_type is invalid")
        return record


def empty_registry() -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "records": {}}


def registry_records(payload: Mapping[str, object]) -> Mapping[str, object]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StateValidationError("schema_version must be 1")
    records = payload.get("records")
    if not isinstance(records, dict):
        raise StateValidationError("records must be an object")
    return records


def decode_source_registry(payload: Mapping[str, object]) -> dict[str, SourceRecord]:
    result: dict[str, SourceRecord] = {}
    for key, raw in registry_records(payload).items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            raise StateValidationError("source registry entries must be objects")
        record = SourceRecord.from_dict(raw)
        if record.source_id != key:
            raise StateValidationError("source_id does not match registry key")
        result[key] = record
    return result


def decode_page_registry(payload: Mapping[str, object]) -> dict[str, PageRecord]:
    result: dict[str, PageRecord] = {}
    for key, raw in registry_records(payload).items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            raise StateValidationError("page registry entries must be objects")
        record = PageRecord.from_dict(raw)
        if record.page_id != key:
            raise StateValidationError("page_id does not match registry key")
        result[key] = record
    return result


def encode_registry(records: Mapping[str, Mapping[str, object]]) -> str:
    return json.dumps(
        {"schema_version": SCHEMA_VERSION, "records": dict(sorted(records.items()))},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
```

在 `scripts/llm_wiki_core/__init__.py` 导出 `SourceRecord`、`PageRecord` 和 `StateValidationError`。

- [ ] **Step 4：运行测试并确认通过**

```powershell
& $python -m unittest tests.test_llm_wiki_state.RegistryCodecTests -v
```

预期：`Ran 5 tests`，`OK`。

- [ ] **Step 5：提交 Task 1**

```powershell
git add scripts/llm_wiki_core/state.py scripts/llm_wiki_core/__init__.py tests/test_llm_wiki_state.py
git commit -m "feat: define LLM Wiki state registries"
```

## Task 2：实现来源身份、canonical path 与 fingerprint/checksum

**Files:**
- Modify: `scripts/llm_wiki_core/state.py`
- Modify: `tests/test_llm_wiki_state.py`

- [ ] **Step 1：追加失败测试**

在 `tests/test_llm_wiki_state.py` 追加：

```python
import tempfile

from llm_wiki_core.state import (
    canonical_path,
    casefold_path_key,
    ensure_within,
    file_checksum,
    file_fingerprint,
    stable_record_id,
)


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
```

- [ ] **Step 2：运行测试并确认失败**

```powershell
& $python -m unittest tests.test_llm_wiki_state.SourceIdentityTests -v
```

预期：导入失败，提示 identity/fingerprint 函数尚不存在。

- [ ] **Step 3：实现纯函数**

在 `state.py` 增加：

```python
import hashlib
import os
from pathlib import Path


def stable_record_id(prefix: str, seed: str) -> str:
    if prefix not in {"src", "page", "op"}:
        raise StateValidationError("record id prefix is invalid")
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def canonical_path(path: Path) -> str:
    return path.expanduser().resolve().as_posix()


def ensure_within(path: Path, allowed_root: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = allowed_root.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise StateValidationError(f"unsafe_path: {resolved} is outside allowed root {root}") from error
    return resolved


def casefold_path_key(value: str, *, windows: bool | None = None) -> str:
    normalized = value.replace("\\", "/")
    use_windows = os.name == "nt" if windows is None else windows
    return normalized.casefold() if use_windows else normalized


def file_fingerprint(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def file_checksum(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
```

- [ ] **Step 4：运行 Task 1–2 测试**

```powershell
& $python -m unittest tests.test_llm_wiki_state -v
```

预期：`Ran 12 tests`，`OK`（无 symlink 权限的平台允许 1 个 skip）。

- [ ] **Step 5：提交 Task 2**

```powershell
git add scripts/llm_wiki_core/state.py tests/test_llm_wiki_state.py
git commit -m "feat: add source identity and fingerprints"
```

## Task 3：实现独占 Vault lock

**Files:**
- Create: `scripts/llm_wiki_core/writer.py`
- Create: `tests/test_llm_wiki_writer.py`
- Modify: `scripts/llm_wiki_core/__init__.py`

- [ ] **Step 1：写失败的锁测试**

创建 `tests/test_llm_wiki_writer.py`：

```python
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
            first = VaultLock(lock_path, allowed_root=Path(tmp), command="state init", target=Path(tmp), wait_seconds=0)
            second = VaultLock(lock_path, allowed_root=Path(tmp), command="state init", target=Path(tmp), wait_seconds=0)
            with first:
                with self.assertRaises(LockTimeout):
                    second.acquire()
            self.assertFalse(lock_path.exists())

    def test_release_does_not_remove_another_owner_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / ".meta" / "lock.json"
            lock = VaultLock(lock_path, allowed_root=Path(tmp), command="state init", target=Path(tmp), wait_seconds=0)
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
```

- [ ] **Step 2：运行测试并确认失败**

```powershell
& $python -m unittest tests.test_llm_wiki_writer.VaultLockTests -v
```

预期：`ModuleNotFoundError: No module named 'llm_wiki_core.writer'`。

- [ ] **Step 3：实现锁模型**

创建 `scripts/llm_wiki_core/writer.py`，先加入：

```python
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from llm_wiki_core.state import ensure_within


class WriterError(RuntimeError):
    exit_code = 3


class LockTimeout(WriterError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def classify_lock(
    payload: Mapping[str, object],
    *,
    now: datetime | None = None,
    ttl_seconds: int = 600,
    pid_exists: Callable[[int], bool] = default_pid_exists,
) -> str:
    host = payload.get("host")
    pid = payload.get("pid")
    acquired_at = payload.get("acquired_at")
    if host != socket.gethostname():
        return "cross-host"
    if not isinstance(pid, int) or not isinstance(acquired_at, str):
        return "invalid"
    acquired = datetime.fromisoformat(acquired_at)
    current = now or datetime.now(timezone.utc)
    if (current - acquired).total_seconds() > ttl_seconds and not pid_exists(pid):
        return "stale"
    return "active"


class VaultLock:
    def __init__(
        self,
        path: Path,
        *,
        allowed_root: Path,
        command: str,
        target: Path,
        wait_seconds: float = 30.0,
    ):
        self.path = ensure_within(path, allowed_root)
        self.command = command
        self.target = target
        self.wait_seconds = wait_seconds
        self.lock_id = str(uuid.uuid4())
        self.acquired = False

    def payload(self) -> dict[str, object]:
        return {
            "lock_id": self.lock_id,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "command": self.command,
            "acquired_at": utc_now(),
            "target": str(self.target.resolve()),
        }

    def acquire(self) -> "VaultLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_seconds
        encoded = (json.dumps(self.payload(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"lock_timeout: {self.path}")
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
                continue
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                self.path.unlink(missing_ok=True)
                raise
            self.acquired = True
            return self

    def release(self) -> None:
        if not self.acquired or not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("lock_id") == self.lock_id:
            self.path.unlink()
            self.acquired = False

    def __enter__(self) -> "VaultLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
```

导出 `VaultLock`、`LockTimeout` 和 `classify_lock`。

- [ ] **Step 4：运行锁测试**

```powershell
& $python -m unittest tests.test_llm_wiki_writer.VaultLockTests -v
```

预期：`Ran 4 tests`，`OK`。

- [ ] **Step 5：提交 Task 3**

```powershell
git add scripts/llm_wiki_core/writer.py scripts/llm_wiki_core/__init__.py tests/test_llm_wiki_writer.py
git commit -m "feat: add exclusive Vault write lock"
```

## Task 4：实现原子 snapshot、operation 与 change log

**Files:**
- Modify: `scripts/llm_wiki_core/state.py`
- Modify: `scripts/llm_wiki_core/writer.py`
- Modify: `tests/test_llm_wiki_writer.py`

- [ ] **Step 1：追加失败测试**

在 `tests/test_llm_wiki_writer.py` 追加：

```python
from unittest.mock import patch

from llm_wiki_core.state import empty_registry
from llm_wiki_core.writer import (
    SnapshotConflict,
    append_change_event,
    atomic_write_json,
    begin_operation,
    file_text_checksum,
    update_operation,
)


class SnapshotWriterTests(unittest.TestCase):
    def test_atomic_json_is_deterministic_and_replaces_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".meta" / "sources.json"
            atomic_write_json(target, empty_registry(), allowed_root=Path(tmp))
            first = target.read_text(encoding="utf-8")
            atomic_write_json(target, empty_registry(), allowed_root=Path(tmp), expected_checksum=file_text_checksum(target))
            self.assertEqual(target.read_text(encoding="utf-8"), first)

    def test_expected_checksum_conflict_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sources.json"
            target.write_text('{"original": true}\n', encoding="utf-8")
            with self.assertRaises(SnapshotConflict):
                atomic_write_json(target, empty_registry(), allowed_root=Path(tmp), expected_checksum="sha256:wrong")
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
            operation = begin_operation(path, allowed_root=Path(tmp), kind="state-init", idempotency_key="sha256:key", record_ids=[])
            failed = update_operation(path, operation.operation_id, allowed_root=Path(tmp), status="failed", current_step="write-schema", error="boom")
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.error, "boom")
```

- [ ] **Step 2：运行测试并确认失败**

```powershell
& $python -m unittest tests.test_llm_wiki_writer.SnapshotWriterTests -v
```

预期：导入失败，提示 snapshot/operation 函数尚不存在。

- [ ] **Step 3：增加 OperationRecord**

在 `state.py` 增加：

```python
@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    idempotency_key: str
    kind: str
    record_ids: tuple[str, ...]
    current_step: str
    status: str
    started_at: str
    updated_at: str
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["record_ids"] = list(self.record_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "OperationRecord":
        record_ids = payload.get("record_ids")
        if not isinstance(record_ids, list) or not all(isinstance(item, str) for item in record_ids):
            raise StateValidationError("record_ids must be a string array")
        status = require_string(payload.get("status"), "status")
        if status not in {"running", "completed", "failed"}:
            raise StateValidationError("operation status is invalid")
        return cls(
            operation_id=require_string(payload.get("operation_id"), "operation_id"),
            idempotency_key=require_string(payload.get("idempotency_key"), "idempotency_key"),
            kind=require_string(payload.get("kind"), "kind"),
            record_ids=tuple(record_ids),
            current_step=require_string(payload.get("current_step"), "current_step"),
            status=status,
            started_at=require_string(payload.get("started_at"), "started_at"),
            updated_at=require_string(payload.get("updated_at"), "updated_at"),
            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
        )
```

- [ ] **Step 4：实现 snapshot、change log 与 operation 函数**

在 `writer.py` 增加以下公共接口；所有调用都假设上层已经持有对应 Vault lock。将 Task 3 的
`from llm_wiki_core.state import ensure_within` 替换为下面包含全部状态依赖的 import：

```python
import hashlib
import tempfile
from dataclasses import replace

from llm_wiki_core.state import OperationRecord, StateValidationError, empty_registry, ensure_within, stable_record_id


class SnapshotConflict(WriterError):
    exit_code = 2


def deterministic_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def file_text_checksum(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def atomic_write_text(
    path: Path,
    text: str,
    *,
    allowed_root: Path,
    expected_checksum: str | None = None,
) -> None:
    safe_path = ensure_within(path, allowed_root)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    current_checksum = file_text_checksum(safe_path)
    if current_checksum is not None and expected_checksum is None:
        raise SnapshotConflict(f"expected checksum is required for existing target: {safe_path}")
    if expected_checksum is not None and current_checksum != expected_checksum:
        raise SnapshotConflict(f"snapshot_conflict: {safe_path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{safe_path.name}.", suffix=".tmp", dir=safe_path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, safe_path)
    except BaseException:
        if temp_path.exists():
            temp_path.unlink()
        raise


def atomic_write_json(
    path: Path,
    payload: Mapping[str, object],
    *,
    allowed_root: Path,
    expected_checksum: str | None = None,
) -> None:
    atomic_write_text(path, deterministic_json(payload), allowed_root=allowed_root, expected_checksum=expected_checksum)


def read_json_object(path: Path, default: Mapping[str, object] | None = None) -> dict[str, object]:
    if not path.is_file() and default is not None:
        return dict(default)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise WriterError(f"JSON root must be an object: {path}")
    return payload


def append_change_event(
    path: Path,
    *,
    allowed_root: Path,
    operation_id: str,
    kind: str,
    record_ids: list[str],
    old_checksums: Mapping[str, str | None],
    new_checksums: Mapping[str, str | None],
    result: str,
) -> dict[str, object]:
    path = ensure_within(path, allowed_root)
    sequence = 1
    if path.is_file():
        lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        if lines:
            last = json.loads(lines[-1])
            sequence = int(last["sequence"]) + 1
    event = {
        "sequence": sequence,
        "operation_id": operation_id,
        "kind": kind,
        "record_ids": record_ids,
        "old_checksums": dict(sorted(old_checksums.items())),
        "new_checksums": dict(sorted(new_checksums.items())),
        "result": result,
        "timestamp": utc_now(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return event


def load_operations(path: Path) -> dict[str, OperationRecord]:
    payload = read_json_object(path, empty_registry())
    records = payload.get("records")
    if payload.get("schema_version") != 1 or not isinstance(records, dict):
        raise WriterError("invalid operations registry")
    result: dict[str, OperationRecord] = {}
    for key, value in records.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise StateValidationError("operation registry entries must be objects")
        record = OperationRecord.from_dict(value)
        if record.operation_id != key:
            raise StateValidationError("operation_id does not match registry key")
        result[key] = record
    return result


def save_operations(path: Path, records: Mapping[str, OperationRecord], *, allowed_root: Path) -> None:
    expected_checksum = file_text_checksum(path)
    atomic_write_json(
        path,
        {"schema_version": 1, "records": {key: value.to_dict() for key, value in sorted(records.items())}},
        allowed_root=allowed_root,
        expected_checksum=expected_checksum,
    )


def begin_operation(
    path: Path,
    *,
    allowed_root: Path,
    kind: str,
    idempotency_key: str,
    record_ids: list[str],
    reuse_completed: bool = True,
) -> OperationRecord:
    records = load_operations(path)
    for record in records.values():
        if reuse_completed and record.idempotency_key == idempotency_key and record.status == "completed":
            return record
    now = utc_now()
    operation_id = stable_record_id("op", f"{kind}:{idempotency_key}:{now}")
    record = OperationRecord(operation_id, idempotency_key, kind, tuple(record_ids), "start", "running", now, now)
    records[operation_id] = record
    save_operations(path, records, allowed_root=allowed_root)
    return record


def update_operation(
    path: Path,
    operation_id: str,
    *,
    allowed_root: Path,
    status: str,
    current_step: str,
    error: str | None = None,
) -> OperationRecord:
    records = load_operations(path)
    current = records[operation_id]
    updated = replace(current, status=status, current_step=current_step, updated_at=utc_now(), error=error)
    records[operation_id] = updated
    save_operations(path, records, allowed_root=allowed_root)
    return updated
```

- [ ] **Step 5：运行 writer 全部测试**

```powershell
& $python -m unittest tests.test_llm_wiki_writer -v
```

预期：`Ran 10 tests`，`OK`。

- [ ] **Step 6：提交 Task 4**

```powershell
git add scripts/llm_wiki_core/state.py scripts/llm_wiki_core/writer.py tests/test_llm_wiki_writer.py
git commit -m "feat: add atomic state snapshots and journal"
```

## Task 5：实现幂等 `state init` 和 CLI

**Files:**
- Modify: `scripts/llm_wiki_core/state.py`
- Modify: `scripts/llm_wiki_core/writer.py`
- Modify: `scripts/llm_wiki.py`
- Modify: `tests/test_llm_wiki_state.py`
- Modify: `tests/test_llm_wiki_cli.py`

- [ ] **Step 1：写失败的 state-init 直接测试**

在 `tests/test_llm_wiki_state.py` 追加：

```python
from llm_wiki_core.state import plan_state_init


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
```

- [ ] **Step 2：写失败的 CLI 测试**

在 `tests/test_llm_wiki_cli.py` 追加：

```python
class StateInitCliTests(unittest.TestCase):
    def test_preview_writes_nothing_and_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            result = run_cli("state", "init", "--root", str(vault), "--format", "json")
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["confirmation_required"])
            self.assertFalse(payload["initialized"])
            self.assertFalse((vault / "00-知识库中控" / ".meta").exists())

    def test_confirm_creates_state_and_second_run_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            first = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            second = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            meta = vault / "00-知识库中控" / ".meta"
            self.assertTrue((meta / "schema.json").is_file())
            self.assertEqual(json.loads(second.stdout)["create"], [])

    def test_invalid_existing_schema_returns_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            meta = vault / "00-知识库中控" / ".meta"
            meta.mkdir()
            (meta / "schema.json").write_text('{"schema_version": 99}', encoding="utf-8")
            result = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["error"]["check"], "invalid-state")
```

- [ ] **Step 3：运行测试并确认失败**

```powershell
& $python -m unittest tests.test_llm_wiki_state.StateInitPlanTests tests.test_llm_wiki_cli.StateInitCliTests -v
```

预期：缺少 `plan_state_init`，CLI 不认识 `state` group。

- [ ] **Step 4：实现 state-init 计划与执行模型**

在 `state.py` 增加：

```python
from dataclasses import dataclass

STATE_FILES = ("schema.json", "sources.json", "pages.json", "operations.json", "change-log.jsonl")


@dataclass(frozen=True)
class StateInitPlan:
    control_center: Path
    meta_root: Path
    create: tuple[str, ...]
    unchanged: tuple[str, ...]


def schema_payload() -> dict[str, object]:
    return {"schema_version": 1, "state_format": "obsidian-llm-wiki"}


def validate_state_file(path: Path) -> None:
    if path.name == "change-log.jsonl":
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                json.loads(line)
        return
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise StateValidationError(f"{path.name} has invalid schema")
    if path.name == "sources.json":
        decode_source_registry(payload)
    elif path.name == "pages.json":
        decode_page_registry(payload)
    elif path.name == "operations.json":
        for key, raw in registry_records(payload).items():
            if not isinstance(key, str) or not isinstance(raw, dict):
                raise StateValidationError("operations.json entries must be objects")
            record = OperationRecord.from_dict(raw)
            if record.operation_id != key:
                raise StateValidationError("operation_id does not match registry key")


def plan_state_init(control_center: Path) -> StateInitPlan:
    control_center = control_center.resolve()
    meta_root = ensure_within(control_center / ".meta", control_center)
    create: list[str] = []
    unchanged: list[str] = []
    for name in STATE_FILES:
        path = meta_root / name
        if not path.exists():
            create.append(name)
            continue
        try:
            validate_state_file(path)
        except (OSError, json.JSONDecodeError, StateValidationError) as error:
            raise StateValidationError(f"{name}: {error}") from error
        unchanged.append(name)
    return StateInitPlan(control_center, meta_root, tuple(create), tuple(unchanged))
```

在 `writer.py` 增加组合函数：

```python
from llm_wiki_core.state import StateInitPlan, empty_registry, plan_state_init, schema_payload


def apply_state_init(plan: StateInitPlan) -> StateInitPlan:
    plan.meta_root.mkdir(parents=True, exist_ok=True)
    lock = VaultLock(
        plan.meta_root / "lock.json",
        allowed_root=plan.control_center,
        command="state init",
        target=plan.control_center,
    )
    with lock:
        refreshed = plan_state_init(plan.control_center)
        if not refreshed.create:
            return refreshed
        operations_path = refreshed.meta_root / "operations.json"
        if "operations.json" in refreshed.create:
            atomic_write_json(operations_path, empty_registry(), allowed_root=plan.control_center)
        operation = begin_operation(
            operations_path,
            allowed_root=plan.control_center,
            kind="state-init",
            idempotency_key="sha256:" + hashlib.sha256(b"state-init-v1").hexdigest(),
            record_ids=[],
            reuse_completed=False,
        )
        try:
            payloads = {
                "schema.json": schema_payload(),
                "sources.json": empty_registry(),
                "pages.json": empty_registry(),
            }
            for name in refreshed.create:
                if name in payloads:
                    update_operation(
                        operations_path,
                        operation.operation_id,
                        allowed_root=plan.control_center,
                        status="running",
                        current_step=f"write-{name}",
                    )
                    atomic_write_json(refreshed.meta_root / name, payloads[name], allowed_root=plan.control_center)
                elif name == "change-log.jsonl":
                    atomic_write_text(refreshed.meta_root / name, "", allowed_root=plan.control_center)
            append_change_event(
                refreshed.meta_root / "change-log.jsonl",
                allowed_root=plan.control_center,
                operation_id=operation.operation_id,
                kind="state-init",
                record_ids=[],
                old_checksums={},
                new_checksums={},
                result="completed",
            )
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=plan.control_center,
                status="completed",
                current_step="complete",
            )
            return plan_state_init(plan.control_center)
        except BaseException as error:
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=plan.control_center,
                status="failed",
                current_step="failed",
                error=str(error),
            )
            raise
```

`state.py` 只提供计划和验证；`writer.py` 单向导入 `state.py` 并执行写入，`state.py` 不反向导入 writer。

- [ ] **Step 5：增加 CLI handler 与 parser**

在 `scripts/llm_wiki.py` 导入：

```python
from llm_wiki_core.state import StateValidationError, plan_state_init
from llm_wiki_core.writer import LockTimeout, WriterError, apply_state_init
```

增加：

```python
def state_plan_to_dict(plan, *, confirmation_required: bool, initialized: bool) -> dict[str, object]:
    return {
        "control_center": str(plan.control_center),
        "meta_root": str(plan.meta_root),
        "confirmation_required": confirmation_required,
        "initialized": initialized,
        "create": list(plan.create),
        "unchanged": list(plan.unchanged),
    }


def run_state_init(args: argparse.Namespace) -> int:
    root = resolve_root(root_arg=args.root, cwd=args.cwd, user_config_path=args.user_config)
    if root.error is not None or root.control_center is None:
        print(json.dumps(root_to_dict(root), ensure_ascii=False, indent=2))
        return root_exit_code(root)
    try:
        plan = plan_state_init(root.control_center)
        if plan.create and not args.confirm:
            payload = state_plan_to_dict(plan, confirmation_required=True, initialized=False)
            code = 1
        else:
            result = apply_state_init(plan) if plan.create else plan
            payload = state_plan_to_dict(result, confirmation_required=False, initialized=True)
            code = 0
    except StateValidationError as error:
        payload = {"error": {"check": "invalid-state", "message": str(error)}}
        code = 2
    except (LockTimeout, WriterError, OSError) as error:
        payload = {"error": {"check": "state-write-failed", "message": str(error)}}
        code = 3
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"initialized: {payload.get('initialized', False)}")
        print(f"create: {', '.join(payload.get('create', []))}")
    return code
```

在 `build_parser()` 中增加：

```python
    state = groups.add_parser("state")
    state_commands = state.add_subparsers(dest="command", required=True)
    state_init = state_commands.add_parser("init")
    state_init.add_argument("--root")
    state_init.add_argument("--cwd", default=str(Path.cwd()))
    state_init.add_argument("--user-config")
    state_init.add_argument("--confirm", action="store_true")
    state_init.add_argument("--format", choices=("text", "json"), default="json")
    state_init.set_defaults(handler=run_state_init)
```

- [ ] **Step 6：运行 state 与 CLI 测试**

```powershell
& $python -m unittest tests.test_llm_wiki_state tests.test_llm_wiki_writer tests.test_llm_wiki_cli.StateInitCliTests -v
```

预期：新增测试全部通过；第二次 `state init --confirm` 不追加重复 init 事件。

- [ ] **Step 7：提交 Task 5**

```powershell
git add scripts/llm_wiki_core/state.py scripts/llm_wiki_core/writer.py scripts/llm_wiki.py tests/test_llm_wiki_state.py tests/test_llm_wiki_cli.py
git commit -m "feat: add idempotent state initialization"
```

## Task 6：实现 frontmatter、managed body 与 projection marker

**Files:**
- Create: `scripts/llm_wiki_core/managed.py`
- Create: `tests/test_llm_wiki_managed.py`
- Modify: `scripts/llm_wiki_core/__init__.py`

- [ ] **Step 1：写失败的 managed-region 测试**

创建 `tests/test_llm_wiki_managed.py`：

```python
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from llm_wiki_core.managed import (
    ManagedConflict,
    PROJECTION_END,
    PROJECTION_START,
    managed_checksum,
    replace_frontmatter_region,
    replace_managed_body,
    replace_projection_region,
)


class ManagedRegionTests(unittest.TestCase):
    def test_projection_replace_preserves_user_text(self):
        original = "Before\n<!-- llm-wiki:projection:start -->\nold\n<!-- llm-wiki:projection:end -->\nAfter\n"
        updated = replace_projection_region(original, "new\n")
        self.assertEqual(updated, "Before\n<!-- llm-wiki:projection:start -->\nnew\n<!-- llm-wiki:projection:end -->\nAfter\n")

    def test_missing_projection_requires_takeover(self):
        with self.assertRaisesRegex(ManagedConflict, "projection markers are missing"):
            replace_projection_region("User text\n", "managed\n")

    def test_duplicate_markers_are_conflict(self):
        text = "<!-- llm-wiki:managed:start -->\na\n<!-- llm-wiki:managed:start -->\nb\n<!-- llm-wiki:managed:end -->\n"
        with self.assertRaisesRegex(ManagedConflict, "managed markers"):
            replace_managed_body(text, "new\n")

    def test_out_of_order_markers_are_conflict(self):
        text = f"{PROJECTION_END}\nuser\n{PROJECTION_START}\n"
        with self.assertRaisesRegex(ManagedConflict, "out of order"):
            replace_projection_region(text, "new\n")

    def test_frontmatter_replace_preserves_user_fields(self):
        original = "---\ntags:\n  - user\n# llm-wiki:frontmatter:start\nllm_wiki_schema: 1\n# llm-wiki:frontmatter:end\naliases:\n  - Mine\n---\nBody\n"
        updated = replace_frontmatter_region(original, {"llm_wiki_schema": 1, "llm_wiki_page_id": "page-1"})
        self.assertIn("tags:\n  - user\n", updated)
        self.assertIn("aliases:\n  - Mine\n", updated)
        self.assertIn('llm_wiki_page_id: "page-1"', updated)

    def test_managed_checksum_is_stable_and_excludes_checksum_field(self):
        fields = {"llm_wiki_page_id": "page-1", "llm_wiki_managed_checksum": "sha256:old"}
        self.assertEqual(managed_checksum(fields, "body\n"), managed_checksum({"llm_wiki_page_id": "page-1"}, "body\n"))
```

- [ ] **Step 2：运行测试并确认失败**

```powershell
& $python -m unittest tests.test_llm_wiki_managed.ManagedRegionTests -v
```

预期：`ModuleNotFoundError: No module named 'llm_wiki_core.managed'`。

- [ ] **Step 3：实现通用 marker 替换与 checksum**

创建 `scripts/llm_wiki_core/managed.py`：

```python
from __future__ import annotations

import hashlib
import json
from typing import Mapping

PROJECTION_START = "<!-- llm-wiki:projection:start -->"
PROJECTION_END = "<!-- llm-wiki:projection:end -->"
MANAGED_START = "<!-- llm-wiki:managed:start -->"
MANAGED_END = "<!-- llm-wiki:managed:end -->"
FRONTMATTER_START = "# llm-wiki:frontmatter:start"
FRONTMATTER_END = "# llm-wiki:frontmatter:end"


class ManagedConflict(ValueError):
    pass


def replace_region(text: str, content: str, start: str, end: str, label: str, *, takeover: bool = False) -> str:
    start_count = text.count(start)
    end_count = text.count(end)
    if start_count != end_count or start_count > 1:
        raise ManagedConflict(f"{label} markers are duplicate or unbalanced")
    if start_count == 0:
        if not takeover:
            raise ManagedConflict(f"{label} markers are missing")
        separator = "" if not text or text.endswith("\n") else "\n"
        return f"{text}{separator}{start}\n{content.rstrip()}\n{end}\n"
    start_index = text.index(start)
    end_index = text.index(end)
    if end_index < start_index:
        raise ManagedConflict(f"{label} markers are out of order")
    prefix = text[: start_index + len(start)]
    suffix = text[end_index:]
    return f"{prefix}\n{content.rstrip()}\n{suffix}"


def replace_projection_region(text: str, content: str, *, takeover: bool = False) -> str:
    return replace_region(text, content, PROJECTION_START, PROJECTION_END, "projection", takeover=takeover)


def replace_managed_body(text: str, content: str, *, takeover: bool = False) -> str:
    return replace_region(text, content, MANAGED_START, MANAGED_END, "managed", takeover=takeover)


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise ManagedConflict("YAML frontmatter is missing")
    closing = text.find("\n---\n", 4)
    if closing < 0:
        raise ManagedConflict("YAML frontmatter is unclosed")
    return text[4:closing], text[closing + 5 :]


def encode_frontmatter_fields(fields: Mapping[str, object]) -> str:
    lines: list[str] = []
    for key, value in sorted(fields.items()):
        if not key.startswith("llm_wiki_"):
            raise ManagedConflict("managed frontmatter keys must start with llm_wiki_")
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) + "\n"


def replace_frontmatter_region(text: str, fields: Mapping[str, object], *, takeover: bool = False) -> str:
    frontmatter, body = split_frontmatter(text)
    updated = replace_region(frontmatter + "\n", encode_frontmatter_fields(fields), FRONTMATTER_START, FRONTMATTER_END, "frontmatter", takeover=takeover)
    if not updated.endswith("\n"):
        updated += "\n"
    return f"---\n{updated}---\n{body}"


def managed_checksum(fields: Mapping[str, object], managed_body: str) -> str:
    filtered = {key: value for key, value in fields.items() if key != "llm_wiki_managed_checksum"}
    payload = json.dumps(filtered, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" + managed_body
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4：增加 marker 嵌套、takeover 和 JSON 值测试**

在测试文件追加三个具体测试：

```python
    def test_takeover_appends_projection_once(self):
        updated = replace_projection_region("User\n", "managed\n", takeover=True)
        self.assertEqual(updated.count("llm-wiki:projection:start"), 1)
        self.assertTrue(updated.startswith("User\n"))

    def test_frontmatter_json_array_is_single_line(self):
        original = "---\n# llm-wiki:frontmatter:start\n# llm-wiki:frontmatter:end\n---\n"
        updated = replace_frontmatter_region(original, {"llm_wiki_source_ids": ["src-1", "src-2"]})
        self.assertIn('llm_wiki_source_ids: ["src-1","src-2"]', updated)

    def test_nested_projection_markers_are_rejected(self):
        text = f"{PROJECTION_START}\n{PROJECTION_START}\nx\n{PROJECTION_END}\n{PROJECTION_END}\n"
        with self.assertRaises(ManagedConflict):
            replace_projection_region(text, "new\n")
```

- [ ] **Step 5：运行 managed 与全部 Phase 2 单元测试**

```powershell
& $python -m unittest tests.test_llm_wiki_managed tests.test_llm_wiki_state tests.test_llm_wiki_writer -v
```

预期：全部通过，用户字段和用户正文保持不变。

- [ ] **Step 6：提交 Task 6**

```powershell
git add scripts/llm_wiki_core/managed.py scripts/llm_wiki_core/__init__.py tests/test_llm_wiki_managed.py
git commit -m "feat: add managed Markdown region contracts"
```

## Task 7：同步 Phase 2 文档并完成全量验证

**Files:**
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflow.md`
- Modify: `docs/development-plan.md`
- Modify: `skills/obsidian-wiki-init/SKILL.md`
- Modify: `tests/test_llm_wiki_state.py`

- [ ] **Step 1：增加失败的仓库契约测试**

在 `tests/test_llm_wiki_state.py` 追加：

```python
class Phase2DocumentationTests(unittest.TestCase):
    def test_public_docs_name_state_init_and_meta_authority(self):
        files = [
            REPO_ROOT / "README.md",
            REPO_ROOT / "README.zh.md",
            REPO_ROOT / "docs" / "architecture.md",
            REPO_ROOT / "docs" / "workflow.md",
            REPO_ROOT / "skills" / "obsidian-wiki-init" / "SKILL.md",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("state init", text, path)
            self.assertIn(".meta", text, path)

    def test_phase3_commands_are_not_implemented_early(self):
        cli = (REPO_ROOT / "scripts" / "llm_wiki.py").read_text(encoding="utf-8-sig")
        self.assertNotIn('add_parser("ingest")', cli)
        self.assertNotIn('add_parser("inventory")', cli)
```

- [ ] **Step 2：运行契约测试并确认失败**

```powershell
& $python -m unittest tests.test_llm_wiki_state.Phase2DocumentationTests -v
```

预期：公共文档尚未同时包含 `state init` 和 `.meta`。

- [ ] **Step 3：更新 Skill 和公共文档**

在 Init Skill 中加入以下顺序：

```text
root resolve
-> state init dry-run
-> show files that will be created
-> user confirmation
-> state init --confirm
-> page generation remains Agent-managed until Phase 3 page apply exists
```

在中英文 README 增加：

```text
python scripts/llm_wiki.py state init --root <vault-or-control-center> --format json
python scripts/llm_wiki.py state init --root <vault-or-control-center> --confirm --format json
```

并明确：

- `.meta/sources.json` 和 `.meta/pages.json` 是未来 Phase 3 的权威 snapshot；
- `ingest/index.md`、`wiki/index.md` 和 `wiki/log.md` 仍是人类可读投影；
- Phase 2 只提供安全状态基础，不代表 ingest 已完成；
- Doctor 和 Query 保持只读。

在 `docs/architecture.md`、`docs/workflow.md` 和 `docs/development-plan.md` 记录相同边界，并把 Phase 2 标记为“implemented”只能留到验证通过后的实现提交，不能在计划提交中提前修改状态。

- [ ] **Step 4：运行契约测试和全量测试**

```powershell
& $python -m unittest discover tests -v
```

预期：原 50 个测试和全部 Phase 2 新测试通过。

- [ ] **Step 5：运行 CLI 手工烟测**

```powershell
$vault = Join-Path $env:TEMP 'obsidian-phase2-smoke'
$control = Join-Path $vault '00-知识库中控'
$wiki = Join-Path $control 'wiki'
New-Item -ItemType Directory -Force -Path $wiki | Out-Null
Set-Content -LiteralPath (Join-Path $wiki 'index.md') -Encoding utf8 -Value '# Index'
Set-Content -LiteralPath (Join-Path $wiki 'log.md') -Encoding utf8 -Value '# Log'
& $python scripts/llm_wiki.py state init --root $vault --format json
Test-Path -LiteralPath (Join-Path $control '.meta')
& $python scripts/llm_wiki.py state init --root $vault --confirm --format json
& $python scripts/llm_wiki.py state init --root $vault --confirm --format json
```

预期：

- 第一次命令退出 `1` 且 `.meta` 不存在；
- `Test-Path` 输出 `False`；
- 第二次命令退出 `0` 并创建五个状态文件；
- 第三次命令退出 `0`，`create` 为空。

- [ ] **Step 6：运行静态检查**

```powershell
rg -n "state init|\.meta|sources\.json|pages\.json|operations\.json|change-log\.jsonl" README.md README.zh.md docs skills scripts tests
rg -n "add_parser\(\"(ingest|inventory)\"" scripts
git diff --check
git status --short
```

预期：

- 第一条显示 Phase 2 契约分布；
- 第二条无匹配；
- `git diff --check` 无输出；
- Git 状态只包含 Phase 2 预期文件。

- [ ] **Step 7：提交 Task 7**

```powershell
git add README.md README.zh.md docs/architecture.md docs/workflow.md docs/development-plan.md skills/obsidian-wiki-init/SKILL.md tests/test_llm_wiki_state.py
git commit -m "docs: publish Phase 2 state contract"
```

## 规格覆盖自检

| Phase 2 要求 | 计划任务 |
|---|---|
| `.meta` schema 与 snapshot registry | Task 1、Task 5 |
| 稳定 ID、canonical path、casefold、fingerprint/checksum | Task 2 |
| lock、stale 分类与所有者释放 | Task 3 |
| checksum 复核、同目录临时文件、原子替换 | Task 4 |
| operation 状态与幂等键 | Task 4、Task 5 |
| append-only change log 与旧/新 checksum | Task 4 |
| 幂等 `state init` dry-run/confirm | Task 5 |
| frontmatter、managed body、projection marker | Task 6 |
| 用户区保留与 managed checksum | Task 6 |
| Skill、架构、工作流与公开命令文档 | Task 7 |
| 全量回归与手工烟测 | Task 7 |

自检未发现未覆盖的 Phase 2 要求。Phase 3 `ingest apply`、Phase 4 Doctor 迁移和 v0.3
Inventory 只作为接口消费者或明确非目标出现，没有对应生产实现步骤。

## 最终验证清单

- [ ] `state init` 未确认时零写入，返回退出码 `1`。
- [ ] `state init --confirm` 创建 schema、两个 registry、operations 和 change log。
- [ ] 重复初始化幂等，不覆盖有效文件，不重复声称创建。
- [ ] 无效或未知 schema 返回退出码 `2`，原文件保持不变。
- [ ] 锁冲突返回退出码 `3`，第二写入者不修改状态。
- [ ] 锁只由 matching `lock_id` 所有者释放。
- [ ] snapshot JSON 编码稳定，checksum 冲突停止写入。
- [ ] 临时文件与目标在同目录，写入使用 flush/fsync 和 `os.replace`。
- [ ] operation 的 running/completed/failed 可持久化和恢复读取。
- [ ] change-log sequence 单调递增且只追加。
- [ ] canonical path 保留显示大小写，Windows comparison 使用 casefold key。
- [ ] fingerprint 与 SHA-256 测试通过。
- [ ] frontmatter、managed body、projection marker 冲突不会被猜测修复。
- [ ] 用户 frontmatter、用户正文和 projection 外内容保持不变。
- [ ] CLI 没有提前实现 `ingest`、`inventory`、`migrate` 或 Doctor 迁移。
- [ ] 全量测试在 bundled Python 3.12.13 通过。

## 执行交接

计划获批并提交后，从该提交创建实现 worktree。两种执行方式：

1. **Subagent-Driven（推荐）**：使用 `superpowers:subagent-driven-development`，每个 Task 使用独立 worker，并在 Task 间做规格和代码双重审查。
2. **Inline Execution**：使用 `superpowers:executing-plans`，按小批次执行 Task，并在每批后停下来复核。

无论选择哪种方式，都不得把 Phase 3、Phase 4 或 Inventory 顺带加入 Phase 2 提交。
