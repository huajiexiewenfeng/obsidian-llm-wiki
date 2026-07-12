# Obsidian LLM Wiki v0.2 Phase 3.1 Archive Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `ingest apply` 中交付单来源、不可变、可恢复的 `archive-import`，使外部文件经锁外流式 staging 后安全发布到 `raw/<source-id>/`，并与 registry、页面、投影、operation 和 Doctor 一致性检查协同工作。

**Architecture:** canonical runtime 新增聚焦二进制归档的 `llm_wiki_core/archive.py`；`state.py` 保存可选 archive path 并统一解析权威来源，`ingest.py` 继续拥有业务 transaction，但 archive 全文读取只发生在锁外。Doctor 在 Phase 3.1 record 启用后受控扫描 `raw/`，CLI 和 Skills 仍复用现有 `ingest apply`、一次 dry-run、一次 plan checksum 确认协议。

**Tech Stack:** Python 3.12 标准库、`dataclasses`、`pathlib`、`hashlib`、`os.link`、`shutil.disk_usage`、JSON/JSONL、`unittest`、`unittest.mock`、PowerShell 测试命令。

## Global Constraints

- 实施分支基线为 `codex/v02-phase31-archive-import@1a2cad4`；Inventory 对齐证据为独立设计提交 `56f064a`。
- 执行测试前把环境实际的 Python 3.12 executable 绝对路径赋给 PowerShell 变量 `$python`；使用运行环境 dependency loader 或已激活虚拟环境解析，不把工作站路径写进仓库。
- 生产实现只进入 `skills/obsidian-wiki-runtime/scripts/`；根目录脚本保持 compatibility launcher。
- `source.mode` 合法值为 `path-index`、`summary-ingest`、`archive-import`；旧两种模式的行为、ID 和退出码不得变化。
- 一个 payload 仍只表示一个 source、一个 source proxy 和零到多个 derived pages。
- dry-run 严格零写入，不创建 `raw/`、source 目录、temp、lock 或 operation。
- archive target 只能由 Core 推导为 `raw/<source-id>/<safe-original-filename>`；payload 不增加 target、overwrite 或 takeover 字段。
- archive 字节不可变：checksum 相同才能复用，不同 checksum 绝不覆盖或自动改名。
- 外部来源和既有 archive 的完整 checksum 读取只能在 Vault 锁外发生；锁内只允许 stat/fingerprint CAS、小型状态读取和写入。
- archive source ID 首次分配使用 origin+checksum seed；registry 精确查找是身份权威，碰撞使用最小可用 deterministic collision ordinal。
- SourceRecord schema version 保持 1；旧记录无 `archive_relative_path` 时必须继续加载。
- no-replace 发布只使用安全的同目录 primitive；文件系统不支持时返回 `atomic-publish-unsupported`，不降级为覆盖或非原子复制。
- `raw/` 是 Core 管理区；未来 Inventory 排除它，Doctor 把未登记普通文件报告为 `unregistered-archive`。
- Doctor 保持零写入、Finding 六字段、score version 1、五维权重和退出码兼容。
- 所有生产改动遵循 TDD；每个任务结束时独立提交。

---

## 文件结构与职责

- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/archive.py`：新增 archive identity、safe filename、target evidence、流式 staging、锁内 stat 验证、no-replace publication 和 cleanup primitives。
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/state.py`：扩展 SourceRecord codec，提供 `is_archive_managed_path()` 和 `resolve_authoritative_source_path()`。
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py`：接受 archive payload，规划 archive action，并把锁外 preparation 接入现有 transaction。
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py`：检查 archive record、target、checksum、operation/temp 和未登记 raw 文件。
- `skills/obsidian-wiki-runtime/scripts/llm_wiki.py`：保持 CLI 形状，透传 archive 结构化 check/hint。
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/__init__.py`：导出稳定 archive/state 接口。
- `tests/test_llm_wiki_archive.py`：archive 纯逻辑、流式 I/O 和发布 primitive 单元测试。
- `tests/test_llm_wiki_state.py`、`tests/test_llm_wiki_ingest.py`：codec、planner、transaction、failure injection 和恢复测试。
- `tests/test_llm_wiki_doctor_state.py`、`tests/test_obsidian_wiki_doctor.py`：archive consistency、只读、Finding 和 score 兼容测试。
- `tests/test_llm_wiki_cli.py`、`tests/test_llm_wiki_phase3_e2e.py`：CLI/file/stdin、Unicode binary 和幂等 E2E。
- `tests/test_skill_runtime_packaging.py`：确保 `archive.py` 进入 installable runtime。
- Ingest/Doctor/Maintain Skills、README、architecture/workflow：同步用户入口、文件系统限制、Doctor vocabulary 与修复边界。

### Task 1：扩展 SourceRecord，并固定权威 archive path

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/state.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/__init__.py`
- Modify: `tests/test_llm_wiki_state.py`

**Interfaces:**
- Consumes: `validate_relative_path()`、`ensure_within()`、现有 `SourceRecord.from_dict()/to_dict()`。
- Produces: `SourceRecord.archive_relative_path: str | None`、`is_archive_managed_path(relative_path: str) -> bool`、`resolve_authoritative_source_path(control_center: Path, record: SourceRecord) -> Path`。

- [ ] **Step 1: 写旧 record 兼容、archive codec 和权威路径失败测试**

  在 `tests/test_llm_wiki_state.py` 增加：

  ```python
  def test_source_record_archive_path_is_optional_and_old_shape_round_trips(self):
      old = SOURCE.to_dict()
      old.pop("archive_relative_path", None)
      decoded = SourceRecord.from_dict(old)
      self.assertIsNone(decoded.archive_relative_path)
      self.assertNotIn("archive_relative_path", decoded.to_dict())

  def test_archive_authority_uses_raw_copy_and_rejects_escape(self):
      with tempfile.TemporaryDirectory() as tmp:
          control = Path(tmp).resolve()
          record = SourceRecord(
              **{**SOURCE.to_dict(), "mode": "archive-import",
                 "archive_relative_path": "raw/src-1/file.pdf"}
          )
          self.assertEqual(
              resolve_authoritative_source_path(control, record),
              (control / "raw/src-1/file.pdf").resolve(),
          )
          unsafe = SourceRecord(
              **{**record.to_dict(), "archive_relative_path": "../outside.pdf"}
          )
          with self.assertRaisesRegex(StateValidationError, "archive"):
              resolve_authoritative_source_path(control, unsafe)
  ```

- [ ] **Step 2: 运行 state 测试确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_state -v`

  Expected: FAIL，`archive_relative_path` 或权威路径 helper 不存在。

- [ ] **Step 3: 实现向后兼容 codec 和共享 raw classifier**

  在 `SourceRecord` 末尾增加默认字段，并保持旧序列化形状：

  ```python
  archive_relative_path: str | None = None

  def to_dict(self) -> dict[str, object]:
      payload = asdict(self)
      if self.archive_relative_path is None:
          payload.pop("archive_relative_path")
      return payload
  ```

  `from_dict()` 对非 null 值只要求非空字符串并统一 `/`；具体 `raw/<source-id>/` 规则由 authority helper/Doctor 判断，使损坏记录能产生精确 archive finding，而不是整份 registry 失效。

  ```python
  def is_archive_managed_path(relative_path: str) -> bool:
      path = PurePosixPath(relative_path.replace("\\", "/"))
      return (
          not path.is_absolute()
          and ".." not in path.parts
          and len(path.parts) >= 3
          and path.parts[0] == "raw"
      )

  def resolve_authoritative_source_path(control_center: Path, record: SourceRecord) -> Path:
      if record.mode != "archive-import":
          return Path(record.canonical_path).expanduser().resolve()
      relative = record.archive_relative_path
      if relative is None or not is_archive_managed_path(relative):
          raise StateValidationError("archive_relative_path is not a safe raw path")
      parts = PurePosixPath(relative).parts
      if parts[1] != record.source_id:
          raise StateValidationError("archive_relative_path source ID does not match")
      return ensure_within(control_center / Path(*parts), control_center)
  ```

- [ ] **Step 4: 导出 helper，运行 state 回归并提交**

  Run: `& $python -m unittest tests.test_llm_wiki_state -v`

  Expected: PASS；现有 state schema、registry、path-index 测试不回归。

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/state.py skills/obsidian-wiki-runtime/scripts/llm_wiki_core/__init__.py tests/test_llm_wiki_state.py
  git commit -m "feat: model archived source authority"
  ```

### Task 2：实现 archive identity、安全文件名和 target planner

**Files:**
- Create: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/archive.py`
- Create: `tests/test_llm_wiki_archive.py`
- Modify: `tests/test_skill_runtime_packaging.py`

**Interfaces:**
- Consumes: `SourceRecord`、`stable_record_id()`、`casefold_path_key()`、`file_checksum()`、`file_fingerprint()`。
- Produces: `ArchiveError`、`ArchiveConflict`、`ArchiveWriteError`、`ArchiveTargetEvidence`、`archive_source_id()`、`safe_archive_filename()`、`archive_relative_path()`、`inspect_archive_target()`。

- [ ] **Step 1: 写 source ID、rebind collision 和 safe filename 失败测试**

  ```python
  def test_archive_id_uses_first_free_deterministic_collision_ordinal(self):
      origin = "C:/materials/a.pdf"
      checksum = "sha256:" + "a" * 64
      occupied = archive_source_id(origin, checksum, {})
      records = {occupied: source_record(occupied, canonical_path="C:/moved/b.pdf")}
      allocated = archive_source_id(origin, checksum, records)
      self.assertNotEqual(allocated, occupied)
      self.assertEqual(allocated, archive_source_id(origin, checksum, records))

  def test_safe_archive_filename_normalizes_reserved_windows_names(self):
      self.assertEqual(safe_archive_filename("CON?.pdf"), "CON_.pdf")
      self.assertEqual(safe_archive_filename("报告  .PDF"), "报告.PDF")
  ```

- [ ] **Step 2: 写 target create/reuse/conflict 失败测试**

  使用临时 control center 固定三分支：不存在返回 `archive-create/staging_required=True`；内容相同返回 `archive-reuse/staging_required=False` 和稳定 fingerprint；不同内容返回 action/check 均为 `archive-target-conflict` 且不可 staging。目标在 checksum 读取期间变化仍抛 `ArchiveConflict(check="archive-target-changed")`。同时断言 target 永远为 `raw/<source-id>/<safe-name>`。

- [ ] **Step 3: 运行 archive/packaging 测试确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_archive tests.test_skill_runtime_packaging -v`

  Expected: FAIL，`llm_wiki_core.archive` 和 runtime 文件不存在。

- [ ] **Step 4: 实现 deterministic allocator 和 filename normalizer**

  ```python
  class ArchiveError(RuntimeError):
      def __init__(self, check: str, message: str, *, hint: str | None = None) -> None:
          super().__init__(message)
          self.check = check
          self.hint = hint

  class ArchiveConflict(ArchiveError):
      pass

  class ArchiveWriteError(ArchiveError):
      pass

  def archive_source_id(
      origin_canonical_path: str,
      checksum: str,
      records: Mapping[str, SourceRecord],
  ) -> str:
      base = f"archive\0{casefold_path_key(origin_canonical_path, windows=True)}\0{checksum}"
      for ordinal in itertools.count(0):
          seed = base if ordinal == 0 else f"{base}\0collision\0{ordinal}"
          candidate = stable_record_id("src", seed)
          if candidate not in records:
              return candidate

  WINDOWS_RESERVED = {
      "CON", "PRN", "AUX", "NUL",
      *(f"COM{index}" for index in range(1, 10)),
      *(f"LPT{index}" for index in range(1, 10)),
  }

  def safe_archive_filename(name: str) -> str:
      normalized = unicodedata.normalize("NFC", Path(name).name)
      cleaned = "".join(
          "_" if ord(char) < 32 or char in '<>:"/\\|?*' else char
          for char in normalized
      )
      suffix = Path(cleaned).suffix
      stem = cleaned[:-len(suffix)] if suffix else cleaned
      stem = stem.rstrip(" .") or "source"
      if stem.upper() in WINDOWS_RESERVED:
          stem += "_"
      return f"{stem}{suffix}"

  def archive_relative_path(source_id: str, source_name: str) -> str:
      return PurePosixPath("raw", source_id, safe_archive_filename(source_name)).as_posix()
  ```

- [ ] **Step 5: 实现 target evidence，确保 checksum 只在调用方锁外读取**

  ```python
  @dataclass(frozen=True)
  class ArchiveTargetEvidence:
      action: str
      relative_path: str
      checksum: str
      size: int
      fingerprint: Mapping[str, int] | None
      staging_required: bool
      conflict: Mapping[str, object] | None = None

      def to_public_dict(self) -> dict[str, object]:
          payload: dict[str, object] = {
              "action": self.action,
              "target": self.relative_path,
              "size": self.size,
              "checksum": self.checksum,
              "staging_required": self.staging_required,
          }
          if self.conflict is not None:
              payload.update(self.conflict)
          return payload

  def inspect_archive_target(control_center: Path, source_id: str, source_name: str,
                             expected_checksum: str, expected_size: int) -> ArchiveTargetEvidence:
      relative = archive_relative_path(source_id, source_name)
      target = ensure_within(control_center / Path(*PurePosixPath(relative).parts), control_center)
      if not target.exists():
          return ArchiveTargetEvidence(
              "archive-create", relative, expected_checksum, expected_size, None, True
          )
      before = file_fingerprint(target)
      actual = file_checksum(target)
      after = file_fingerprint(target)
      if before != after:
          raise ArchiveConflict("archive-target-changed", "archive target changed during verification")
      if actual != expected_checksum:
          return ArchiveTargetEvidence(
              "archive-target-conflict",
              relative,
              expected_checksum,
              expected_size,
              after,
              False,
              {"check": "archive-target-conflict"},
          )
      return ArchiveTargetEvidence(
          "archive-reuse", relative, actual, after["size"], after, False
      )
  ```

- [ ] **Step 6: 登记 packaging，运行测试并提交**

  在 `REQUIRED_RUNTIME_FILES` 加入 `scripts/llm_wiki_core/archive.py`。

  Run: `& $python -m unittest tests.test_llm_wiki_archive tests.test_skill_runtime_packaging -v`

  Expected: PASS。

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/archive.py tests/test_llm_wiki_archive.py tests/test_skill_runtime_packaging.py
  git commit -m "feat: plan immutable archive targets"
  ```

### Task 3：实现锁外流式 staging 与 no-replace 发布

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/archive.py`
- Modify: `tests/test_llm_wiki_archive.py`

**Interfaces:**
- Consumes: Task 2 的 `ArchiveTargetEvidence` 和目标路径规则。
- Produces: `PreparedArchive`、`prepare_archive()`、`validate_prepared_archive()`、`publish_archive_noreplace()`、`cleanup_prepared_archive()`。

- [ ] **Step 1: 写多 chunk、source drift、checksum 和空间失败测试**

  以 `chunk_size=4` 复制 17 bytes，包装 source stream 记录 `read(size)` 调用，断言没有 `read(-1)`；分别固定复制前后 fingerprint 变化、checksum mismatch 和 injected `disk_usage.free < source size`，断言 check 为 `source-changed`、`source-checksum-conflict`、`insufficient-space`。

- [ ] **Step 2: 写 no-replace、unsupported FS 和 unlink 残留测试**

  ```python
  def test_publish_never_overwrites_existing_target(self):
      prepared = make_prepared(b"new")
      prepared.target_path.write_bytes(b"old")
      with self.assertRaises(ArchiveError) as raised:
          publish_archive_noreplace(prepared)
      self.assertEqual(raised.exception.check, "archive-target-changed")
      self.assertEqual(prepared.target_path.read_bytes(), b"old")
  ```

  Mock `os.link` 抛 `OSError(errno.EPERM)`，断言 `atomic-publish-unsupported` 和 NTFS/ext4 hint；另让 `os.unlink(staging)` 失败，断言 publish result 为已发布且 `temp_cleanup_pending=True`。

- [ ] **Step 3: 运行测试确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_archive -v`

  Expected: FAIL，preparation/publication 接口不存在。

- [ ] **Step 4: 实现锁外 preparation**

  ```python
  @dataclass(frozen=True)
  class PreparedArchive:
      action: str
      target_relative_path: str
      target_path: Path
      checksum: str
      verified_fingerprint: Mapping[str, int] | None
      origin_fingerprint: Mapping[str, int]
      staging_path: Path | None

      def to_target_evidence(self) -> ArchiveTargetEvidence:
          target_fingerprint = self.verified_fingerprint if self.action == "archive-reuse" else None
          return ArchiveTargetEvidence(
              self.action,
              self.target_relative_path,
              self.checksum,
              self.origin_fingerprint["size"],
              target_fingerprint,
              self.staging_path is not None,
          )

  @dataclass(frozen=True)
  class ArchivePublishResult:
      published: bool
      reused: bool
      temp_cleanup_pending: bool

  def fingerprint_from_stat(stat: os.stat_result) -> dict[str, int]:
      return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

  def prepare_archive(source: Path, control_center: Path, evidence: ArchiveTargetEvidence,
                      expected_origin: Mapping[str, int], *, chunk_size: int = 1024 * 1024,
                      disk_usage: Callable[[Path], object] = shutil.disk_usage) -> PreparedArchive:
      target = ensure_within(
          control_center / Path(*PurePosixPath(evidence.relative_path).parts),
          control_center,
      )
      if evidence.conflict is not None:
          raise ArchiveConflict(
              str(evidence.conflict["check"]), "archive plan contains an unresolved conflict"
          )
      if evidence.action == "archive-reuse":
          return PreparedArchive(evidence.action, evidence.relative_path, target,
                                 evidence.checksum, evidence.fingerprint,
                                 dict(expected_origin), None)
      if source.is_symlink() or not source.is_file():
          raise ArchiveConflict("invalid-archive-source", "archive source must be a regular file")
      origin_before = file_fingerprint(source)
      if origin_before != dict(expected_origin):
          raise ArchiveConflict("source-changed", "archive source fingerprint changed")
      target.parent.mkdir(parents=True, exist_ok=True)
      target = ensure_within(target, control_center)
      if disk_usage(target.parent).free < expected_origin["size"]:
          raise ArchiveWriteError("insufficient-space", "not enough space for archive staging")
      fd, raw_name = tempfile.mkstemp(
          prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
      )
      staging = Path(raw_name)
      digest = hashlib.sha256()
      try:
          with source.open("rb") as input_stream, os.fdopen(fd, "wb") as output_stream:
              opened_before = fingerprint_from_stat(os.fstat(input_stream.fileno()))
              if opened_before != origin_before:
                  raise ArchiveConflict("source-changed", "archive source changed before copying")
              while True:
                  chunk = input_stream.read(chunk_size)
                  if not chunk:
                      break
                  output_stream.write(chunk)
                  digest.update(chunk)
              opened_after = fingerprint_from_stat(os.fstat(input_stream.fileno()))
              if opened_after != opened_before:
                  raise ArchiveConflict("source-changed", "archive source changed while copying")
              output_stream.flush()
              os.fsync(output_stream.fileno())
          if file_fingerprint(source) != origin_before:
              raise ArchiveConflict("source-changed", "archive source path changed while copying")
          actual = f"sha256:{digest.hexdigest()}"
          if actual != evidence.checksum:
              raise ArchiveConflict("source-checksum-conflict", "archive source checksum changed")
          staged_fingerprint = file_fingerprint(staging)
          return PreparedArchive(
              evidence.action,
              evidence.relative_path,
              target,
              actual,
              staged_fingerprint,
              origin_before,
              staging,
          )
      except BaseException:
          try:
              os.close(fd)
          except OSError:
              pass
          try:
              staging.unlink()
          except OSError:
              pass
          raise
  ```

  `fingerprint_from_stat()` 精确返回 `{"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}`；测试覆盖 fd 已由 `os.fdopen()` 关闭后 cleanup 的 harmless `EBADF` 分支。

- [ ] **Step 5: 实现锁内 stat-only 验证和 hard-link promotion**

  ```python
  def validate_prepared_archive(prepared: PreparedArchive) -> None:
      if prepared.staging_path is not None and prepared.target_path.exists():
          raise ArchiveConflict("archive-target-changed", "archive target appeared after preview")
      path = prepared.staging_path or prepared.target_path
      if path is None or file_fingerprint(path) != dict(prepared.verified_fingerprint or {}):
          raise ArchiveConflict("archive-target-changed", "prepared archive fingerprint changed")

  def publish_archive_noreplace(prepared: PreparedArchive) -> ArchivePublishResult:
      if prepared.staging_path is None:
          return ArchivePublishResult(published=False, reused=True, temp_cleanup_pending=False)
      try:
          os.link(prepared.staging_path, prepared.target_path)
      except FileExistsError as error:
          raise ArchiveConflict("archive-target-changed", "archive target appeared after preview") from error
      except OSError as error:
          raise ArchiveWriteError("atomic-publish-unsupported", "safe archive publication is unsupported",
                                  hint="Move the Vault to NTFS, ext4, or another filesystem with hard-link support.") from error
      cleanup_pending = False
      try:
          prepared.staging_path.unlink()
      except OSError:
          cleanup_pending = True
      fsync_directory(prepared.target_path.parent)
      return ArchivePublishResult(True, False, cleanup_pending)

  def fsync_directory(path: Path) -> None:
      if os.name == "nt":
          return
      descriptor = os.open(path, os.O_RDONLY)
      try:
          os.fsync(descriptor)
      finally:
          os.close(descriptor)

  def cleanup_prepared_archive(prepared: PreparedArchive | None) -> None:
      if prepared is None or prepared.staging_path is None:
          return
      try:
          prepared.staging_path.unlink()
      except OSError:
          pass
  ```

- [ ] **Step 6: 运行 archive 测试并提交**

  Run: `& $python -m unittest tests.test_llm_wiki_archive -v`

  Expected: PASS；流式读取、失败 cleanup、no-overwrite 和残留 temp 全覆盖。

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/archive.py tests/test_llm_wiki_archive.py
  git commit -m "feat: stage and publish archives safely"
  ```

### Task 4：把 archive identity/target 接入 dry-run planner

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/__init__.py`
- Modify: `tests/test_llm_wiki_ingest.py`

**Interfaces:**
- Consumes: Tasks 1–3 的 state/archive 接口、现有 `_resolve_source()`、page/projection planners。
- Produces: `INGEST_MODES` 包含 archive、`IngestPlan.archive: ArchiveTargetEvidence | None`、archive-aware `_resolve_source()` 和 dry-run public plan。

- [ ] **Step 1: 把 unsupported-mode 测试改为 archive payload 合法，并写 dry-run 零写入测试**

  `test_archive_import_is_a_structured_unsupported_mode` 改为断言 payload 成功解析；新增真实 binary source fixture，运行 `plan_ingest()` 前后比较 control center 全树 path/bytes/size/mtime_ns，断言完全相同且 public plan 包含：

  ```python
  self.assertEqual(plan.archive.action, "archive-create")
  self.assertTrue(plan.archive.staging_required)
  self.assertEqual(
      plan.to_public_dict()["archive"]["target"],
      f"raw/{plan.source.source_id}/example.bin",
  )
  ```

- [ ] **Step 2: 写 archive same-origin/change/rebind collision planner 测试**

  覆盖：同 origin+checksum 复用；同 origin 新 checksum 未 resolution 返回 `archive-content-changed`；显式 new-source 创建新 ID；rebind A+X 到 B 后 A+X new-source 使用 collision ordinal；不同 origin 相同 checksum 仍走 move candidate。

- [ ] **Step 3: 写 target reuse/conflict 和 recovery-stable plan checksum 测试**

  目标相同 checksum 时 `archive-reuse`；不同 checksum 时 `archive-target-conflict` 且 `confirmable=False`。相同 desired target path+checksum 在“目标不存在/create”和“目标已发布/reuse”两种状态下产生相同 plan checksum，使 publication 后失败可用原确认重试；registry、payload、目标 checksum 或页面改变时 plan checksum 改变。错误/public plan 不包含 managed body 或二进制内容。

- [ ] **Step 4: 运行 ingest planner 测试确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_ingest.PayloadContractTests tests.test_llm_wiki_ingest.IngestPlannerTests -v`

  Expected: FAIL，archive 仍被拒绝且 IngestPlan 无 archive 字段。

- [ ] **Step 5: 实现 archive-aware resolver 和 public plan**

  ```python
  INGEST_MODES = frozenset({"path-index", "summary-ingest", "archive-import"})

  @dataclass(frozen=True)
  class IngestPlan:
      control_center: Path
      source: SourcePlan
      pages: tuple["PagePlan", ...]
      projections: tuple["ProjectionPlan", ...]
      expected_checksums: Mapping[str, str | None]
      idempotency_key: str
      plan_checksum: str
      confirmable: bool
      confirmation_required: bool
      archive: ArchiveTargetEvidence | None = None
  ```

  `_resolve_source()` 对 archive 先按 registry 的 `(canonical_path casefold, checksum)` 精确查找；同 path 不同 checksum 必须 resolution；没有精确记录时才调用 `archive_source_id()`。非 archive 分支保持现有代码和 ID seed 不变。

  `confirmable` 在现有 source/page/projection 条件之外增加 `archive is None or archive.conflict is None`；target checksum 不同因此返回可展示但不可确认的 plan，而不是 write failure。

- [ ] **Step 6: 把 archive desired state 纳入 confirmability/idempotency/plan checksum**

  `plan_ingest()` 在锁外调用 `inspect_archive_target()`；public archive 只包含 action、control-center-relative target、size、checksum、staging_required 和可公开 conflict，不包含外部绝对路径或 target fingerprint 的 mtime 细节。plan checksum 的 archive 部分只包含 desired target path+checksum，不包含 create/reuse、staging_required 或 fingerprint；后者只作为本次执行的锁内 CAS evidence。idempotency key 增加 archive target 和 source checksum。

- [ ] **Step 7: 运行 planner 与旧模式回归并提交**

  Run: `& $python -m unittest tests.test_llm_wiki_ingest -v`

  Expected: PASS；path-index/summary-ingest 原测试逐项通过。

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py skills/obsidian-wiki-runtime/scripts/llm_wiki_core/__init__.py tests/test_llm_wiki_ingest.py
  git commit -m "feat: plan archive ingest operations"
  ```

### Task 5：把锁外 preparation 接入 ingest transaction

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py`
- Modify: `tests/test_llm_wiki_ingest.py`

**Interfaces:**
- Consumes: Task 4 的 archive plan、Task 3 的 `PreparedArchive`、现有 `VaultLock`/operation/page/projection transaction。
- Produces: `_plan_ingest_with_archive_evidence()`、`_completed_ingest_result()`、`IngestResult.archive_relative_path`、archive-aware `apply_ingest()`、operation step `publish-archive`。

- [ ] **Step 1: 写错误 plan checksum 零 staging 和锁外读取测试**

  错误 confirmed checksum 必须在创建 source 目录/temp 前返回。用 mock lock 设置 `inside_lock=True`，包装 origin/target checksum reader：若在锁内被调用就抛 AssertionError；confirmed archive apply 必须完成且 spy 只在入锁前被调用。

  ```python
  def guarded_checksum(path):
      if lock_state["inside"]:
          raise AssertionError("full checksum read occurred under Vault lock")
      checksum_calls.append(path)
      return real_checksum(path)
  ```

- [ ] **Step 2: 写 create/reuse 完整 transaction 失败测试**

  create 断言 archive bytes、processed SourceRecord.archive_relative_path、页面、投影、operation、change event 同时完成；第二次 apply 返回相同 operation、`idempotent=True`、不创建 temp、不追加 event。reuse fixture 预先放置相同 archive，断言不调用 `os.link`。

- [ ] **Step 3: 写 publication 前后 failure injection 和恢复测试**

  覆盖 `write-source-pending`、`publish-archive`、`write-pages`、`write-page-registry`、`write-projections`、`write-source-processed`、`append-change-log`：

  - publish 前失败：无正式 target，temp 已清理，source/operation 按现有失败语义可诊断；
  - publish 后失败：正式 target 保留且 checksum 正确，source pending/failed operation 可见；
  - 相同 payload 重跑：复用 target，最终 processed，只产生一个 completed event。

- [ ] **Step 4: 运行 transaction 测试确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_ingest.IngestTransactionTests -v`

  Expected: FAIL，archive preparation/publication 尚未由 coordinator 调用。

- [ ] **Step 5: 拆分纯 planner 与锁内 evidence replan**

  保持公开 `plan_ingest(control_center, payload)` 负责锁外完整验证；新增内部入口：

  ```python
  def _plan_ingest_with_archive_evidence(
      control_center: Path,
      payload: IngestPayload,
      evidence: PreparedArchive,
  ) -> IngestPlan:
      validate_prepared_archive(evidence)
      return _plan_ingest_from_current_state(
          control_center,
          payload,
          archive_evidence=evidence.to_target_evidence(),
      )
  ```

  `_plan_ingest_from_current_state()` 只读取 `.meta`、page/projection 小文件和 stat evidence；archive 分支不得调用 `file_checksum(origin)` 或 `file_checksum(target)`。非 archive 的既有路径不在本任务重构。

- [ ] **Step 6: 在入锁前验证 plan 并 preparation**

  ```python
  if payload.source.mode != "archive-import":
      return _apply_non_archive_ingest(
          control_center, payload, confirmed_plan_checksum,
          fail_after_step=fail_after_step,
      )

  outside_plan = plan_ingest(control_center, payload)
  outside_events = read_change_events(control_center / ".meta/change-log.jsonl")
  completed = _completed_event(outside_events, outside_plan.idempotency_key)
  if completed is None:
      if outside_plan.plan_checksum != confirmed_plan_checksum:
          raise IngestPlanConflict(
              "confirmed plan checksum no longer matches", check="plan-conflict"
          )
      if not outside_plan.confirmable:
          raise IngestPlanConflict(
              "ingest plan contains unresolved conflicts", check="plan-not-confirmable"
          )
      assert outside_plan.archive is not None
      prepared = prepare_archive(
          payload.source.path,
          control_center,
          outside_plan.archive,
          payload.source.fingerprint,
      )
  else:
      prepared = None
  ```

  `_apply_non_archive_ingest()` 是当前 `apply_ingest()` 主体的窄重命名，保持旧模式逐行语义。Archive 随后进入 `with VaultLock`，再次读取 completed event：存在则调用 `_completed_ingest_result()` 返回，不要求 preparation；不存在则要求 `prepared` 非空并使用 evidence replan。`PreparedArchive` 的随机 staging path 不进入 plan checksum。Registry/page 或 prepared fingerprint 变化使 replan/验证失败并清理未发布 staging。

- [ ] **Step 7: 在 pending source 后发布 archive**

  `_planned_source_record()` 为 archive 写入 `archive_relative_path`；`IngestResult` 增加 `archive_relative_path: str | None = None`，普通模式保持 null。`_completed_ingest_result()` 从 completed event summary 恢复该值。transaction 顺序固定：operation running → source pending → `publish-archive` → pages → page registry → projections → source processed → event → complete。change event summary：

  ```python
  summary = {
      "source_action": source_plan.action,
      "archive_action": refreshed.archive.action,
      "archive_target": refreshed.archive.relative_path,
      "archive_checksum": payload.source.checksum,
  }
  ```

  summary 不写外部绝对路径。`completed_targets` 在 publish 成功后加入 archive relative path；unlink staging 失败不回滚 target，operation 继续完成并由 Doctor 报 temp。

- [ ] **Step 8: 运行 ingest 全套并提交**

  Run: `& $python -m unittest tests.test_llm_wiki_ingest -v`

  Expected: PASS；archive create/reuse/retry 和旧模式 transaction 全通过。

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py tests/test_llm_wiki_ingest.py
  git commit -m "feat: transact archive ingest safely"
  ```

### Task 6：实现 Archive Doctor consistency 和 raw temp 诊断

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py`
- Modify: `skills/obsidian-wiki-doctor/references/doctor-checks.md`
- Modify: `tests/test_llm_wiki_doctor_state.py`
- Modify: `tests/test_obsidian_wiki_doctor.py`

**Interfaces:**
- Consumes: `resolve_authoritative_source_path()`、`is_archive_managed_path()`、SourceRecord registry、operation completed targets、archive temp 命名。
- Produces: `_check_archives()`、条件性 raw scan、公开 archive checks；现有 `finding_from_consistency_issue()` 无字段变化。

- [ ] **Step 1: 写 archive record/target/checksum 失败测试**

  每个 check 使用独立 fixture并断言 severity/path/hint：

  ```python
  expected = {
      "archive-record-missing-path",
      "unsafe-archive-path",
      "archive-file-missing",
      "archive-checksum-drift",
      "unexpected-archive-path",
      "archive-operation-target-drift",
  }
  self.assertTrue(expected.issubset({issue.check for issue in issues}))
  ```

  健康 archive record/target 无 finding；旧 Wiki、非 archive source 和 `.meta` absent 行为不变。

- [ ] **Step 2: 写 bounded raw、unregistered 和 hard-link temp 测试**

  `raw/` 外同名文件不扫描；registry 未登记普通文件产生 `unregistered-archive`；已登记 target 不产生；target 与 temp `os.path.samefile()` 时只产生 `orphan-temp-file`，不产生 checksum drift。Doctor 运行前后对 `.meta/`、`wiki/`、`ingest/`、`raw/` 做 path/size/mtime/checksum 快照并断言完全相同。

- [ ] **Step 3: 写 Finding/score/脱敏兼容测试**

  validate JSON 中 archive Finding 字段集合仍为 `check/severity/path/message/line/hint`；`--fail-on error` 语义不变；score version、五维值和权重逐项等于既有 fixture。错误文本不包含外部 origin path 或文件正文。

- [ ] **Step 4: 运行 Doctor 测试确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_doctor_state tests.test_obsidian_wiki_doctor -v`

  Expected: FAIL，archive checks 和 raw temp 扫描尚未实现。

- [ ] **Step 5: 实现 record 驱动的 archive 检查**

  ```python
  def _check_archives(control_center: Path, snapshot: DoctorStateSnapshot) -> list[ConsistencyIssue]:
      if snapshot.sources is None:
          return []
      issues: list[ConsistencyIssue] = []
      for source_id, record in sorted(snapshot.sources.items()):
          if record.mode != "archive-import":
              if record.archive_relative_path is not None:
                  issues.append(_issue(
                      "unexpected-archive-path", "ERROR", ".meta/sources.json",
                      f"Non-archive source {source_id} declares an archive path.",
                      hint="Remove the archive field or correct the source mode through Maintain.",
                  ))
              continue
          relative = record.archive_relative_path
          if relative is None:
              issues.append(_issue(
                  "archive-record-missing-path", "ERROR", ".meta/sources.json",
                  f"Archive source {source_id} has no archive path.",
                  hint="Review the failed ingest operation before repairing the source record.",
              ))
              continue
          try:
              target = resolve_authoritative_source_path(control_center, record)
          except StateValidationError:
              issues.append(_issue(
                  "unsafe-archive-path", "ERROR", ".meta/sources.json",
                  f"Archive source {source_id} has an unsafe archive path.",
                  hint="Repair the archive path without reading outside the control center.",
              ))
              continue
          if not target.is_file():
              issues.append(_issue(
                  "archive-file-missing", "ERROR", relative,
                  f"Archive file for {source_id} is missing.",
                  hint="Review the source and operation before retrying archive import.",
              ))
              continue
          if record.checksum is None or file_checksum(target) != record.checksum:
              issues.append(_issue(
                  "archive-checksum-drift", "ERROR", relative,
                  f"Archive checksum for {source_id} differs from the registry.",
                  hint="Do not overwrite the archive; inspect the file and operation history.",
              ))
          if snapshot.events is not None:
              event = next((
                  item for item in reversed(snapshot.events)
                  if item.get("kind") == "ingest-apply"
                  and item.get("result") == "completed"
                  and source_id in item.get("record_ids", [])
              ), None)
              summary = event.get("summary") if isinstance(event, dict) else None
              if isinstance(summary, dict) and summary.get("archive_target") not in (None, relative):
                  issues.append(_issue(
                      "archive-operation-target-drift", "ERROR", relative,
                      f"Archive event target for {source_id} differs from the registry.",
                      hint="Review the completed event before repairing either path.",
                  ))
      return issues
  ```

  Archive checksum 读取发生在 Doctor 的只读流程中，不获取 Vault 写锁；所有 message/hint 使用 source ID 和 control-relative path，不使用 origin canonical path。

- [ ] **Step 6: 扩展 temp scanner 和未登记分类**

  `_check_temp_files()` 在存在 archive records 或 `raw/` 时增加 `raw`，仍 `followlinks=False`。构造所有 registry archive relative paths 的 casefold set；raw 普通文件既不是 registered target、也不是认可 temp 时报告 `unregistered-archive`。同 inode target/temp 只报可清理 temp。

- [ ] **Step 7: 同步公开 check vocabulary，运行测试并提交**

  `doctor-checks.md` 增加上述 ERROR/WARN，说明不影响 score v1；`orphan-temp-file` 范围加入条件性 `raw/`。

  Run: `& $python -m unittest tests.test_llm_wiki_doctor_state tests.test_obsidian_wiki_doctor -v`

  Expected: PASS，完整树只读快照通过。

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py skills/obsidian-wiki-doctor/references/doctor-checks.md tests/test_llm_wiki_doctor_state.py tests/test_obsidian_wiki_doctor.py
  git commit -m "feat: diagnose archived source consistency"
  ```

### Task 7：接入 CLI、E2E、Skills 和用户文档

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki.py`
- Modify: `tests/test_llm_wiki_cli.py`
- Modify: `tests/test_llm_wiki_phase3_e2e.py`
- Modify: `skills/obsidian-wiki-ingest/SKILL.md`
- Modify: `skills/obsidian-wiki-ingest/references/ingest-workflow.md`
- Modify: `skills/obsidian-wiki-ingest/references/safety-rules.md`
- Modify: `skills/obsidian-wiki-doctor/SKILL.md`
- Modify: `skills/obsidian-wiki-maintain/SKILL.md`
- Modify: `skills/obsidian-wiki-maintain/references/repair-policy.md`
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflow.md`

**Interfaces:**
- Consumes: archive-aware planner/coordinator 和 Doctor checks。
- Produces: 原 CLI 下的 archive plan/result/error JSON、file/stdin E2E、三个 Skills 的一致工作流。

- [ ] **Step 1: 写 CLI check/hint 和 file/stdin 失败测试**

  dry-run 返回 `confirmation-required`、archive target 和 plan checksum；confirm 返回 operation/source/archive target；`atomic-publish-unsupported`、`archive-target-conflict`、`archive-target-changed` 保留各自 check，并在支持限制时带不含绝对路径的 hint。file/stdin 规范化 payload 产生相同 plan checksum。

- [ ] **Step 2: 写 Unicode binary E2E 和 launcher 等价测试**

  使用文件名 `批准资料-合同 01.PDF`、含 NUL/非 UTF-8 bytes 的内容；根 launcher 与 canonical runtime 分别 dry-run/confirm，断言 JSON 关键字段等价、archive bytes 逐字节相同、第二次 confirm 幂等、Doctor 无 archive ERROR/WARN。

- [ ] **Step 3: 运行 CLI/E2E 确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_cli tests.test_llm_wiki_phase3_e2e -v`

  Expected: FAIL，CLI 仍把 archive write failure 折叠为 generic check，Skills 仍声明 unsupported。

- [ ] **Step 4: 透传结构化 archive conflict/write error**

  `ArchiveConflict` 表示可预期计划/来源/目标漂移并返回 2；`ArchiveWriteError` 表示空间、I/O 或原子发布能力问题并返回 3。两者都暴露 `check`/`hint`；`run_ingest_apply()` 使用：

  ```python
  except (IngestValidationError, IngestPlanConflict, ArchiveConflict,
          StateValidationError, SnapshotConflict) as error:
      payload = {"error": {
          "check": getattr(error, "check", "ingest-conflict"),
          "message": str(error),
      }}
      hint = getattr(error, "hint", None)
      if hint:
          payload["error"]["hint"] = hint
      code = 2
  except (IngestWriteError, ArchiveWriteError, LockTimeout, WriterError, OSError) as error:
      payload = {"error": {
          "check": getattr(error, "check", "ingest-write-failed"),
          "message": str(error),
      }}
      hint = getattr(error, "hint", None)
      if hint:
          payload["error"]["hint"] = hint
      code = 3
  ```

  保持 validation/conflict=2、write=3、internal=4；confirmation-required 仍为 1。

  Confirm success payload 在 `result.archive_relative_path` 非 null 时增加 `archive_target`；普通模式不增加该键，保持既有 JSON 形状。

- [ ] **Step 5: 更新 Ingest Skill 和 workflow**

  删除“Phase 3.1 deferred/unsupported”和“process raw files”手工投递表述；明确：外部路径 → payload mode archive-import → dry-run → 用户确认相同 plan checksum → Core 归档 → Doctor。写明 `raw/` 不作为候选入口、原文件不删除、文件系统需要安全 hard-link/no-replace、一次 payload 只归档一个来源。

- [ ] **Step 6: 更新 Doctor/Maintain 和项目文档**

  Doctor Skill 引用 archive checks；Maintain repair policy 规定 orphan staging/unregistered archive 只生成候选计划，删除、移出、登记或重归档都需确认。README/architecture/workflow 同步 SourceRecord archive field、锁外 staging、no-replace、`raw/` 保留区及错误 hint。

- [ ] **Step 7: 运行 CLI/E2E/Skill 契约并提交**

  Run: `& $python -m unittest tests.test_llm_wiki_cli tests.test_llm_wiki_phase3_e2e tests.test_skill_runtime_packaging -v`

  Expected: PASS；测试中不再出现 `archive-import is deferred`，所有公开文档行为一致。

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki.py tests/test_llm_wiki_cli.py tests/test_llm_wiki_phase3_e2e.py skills/obsidian-wiki-ingest skills/obsidian-wiki-doctor/SKILL.md skills/obsidian-wiki-maintain README.md README.zh.md docs/architecture.md docs/workflow.md
  git commit -m "docs: publish archive import workflow"
  ```

### Task 8：完整验证、测试完整性和 Flow handoff

**Files:**
- Create: `.llm-wiki/verification/obsidian-v02-phase31-archive-import.md`
- Create: `.llm-wiki/handoff/obsidian-v02-phase31-archive-import-handoff.md`
- Modify: `.llm-wiki/requirements/obsidian-v02-phase31-archive-import.md`
- Modify: `.llm-wiki/artifacts/index.md`
- Modify: `.llm-wiki/index.md`
- Modify: `.llm-wiki/log.md`

**Interfaces:**
- Consumes: Tasks 1–7 的实现和全部测试。
- Produces: agent-local verification evidence、Test Integrity 结论、实施 handoff 和保守 Flow 状态。

- [ ] **Step 1: 运行 archive/state/ingest/Doctor 定向套件**

  Run:

  ```powershell
  & $python -m unittest tests.test_llm_wiki_archive tests.test_llm_wiki_state tests.test_llm_wiki_ingest tests.test_llm_wiki_doctor_state tests.test_obsidian_wiki_doctor -v
  ```

  Expected: PASS；0 failures，只有测试文件中明确标注的平台 symlink/hard-link capability skip 可接受。

- [ ] **Step 2: 运行 CLI/E2E/packaging 套件**

  Run:

  ```powershell
  & $python -m unittest tests.test_llm_wiki_cli tests.test_llm_wiki_phase3_e2e tests.test_skill_runtime_packaging -v
  ```

  Expected: PASS；canonical/root launcher 等价，archive.py 被 packaging 覆盖。

- [ ] **Step 3: 运行完整回归**

  Run: `& $python -m unittest discover -s tests -v`

  Expected: PASS；记录 tests run、passed、skipped、exit code、executor、Python 版本和平台。不得把 agent-local 结果写成 CI 或独立评审。

- [ ] **Step 4: 执行静态锁边界和写入安全检查**

  Run:

  ```powershell
  rg -n "with lock|with VaultLock|file_checksum|read_bytes|\.open\(\"rb\"" skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py skills/obsidian-wiki-runtime/scripts/llm_wiki_core/archive.py
  git diff --check
  git status --short
  ```

  Expected: 人工逐项确认 archive 的完整读取只位于 preparation/planner，锁内路径只调用 fingerprint/stat；`git diff --check` 为 0；status 只包含本 Flow 已知文件。

- [ ] **Step 5: 记录 Test Integrity Gate**

  verification 文档明确列出：真实临时目录与真实 bytes I/O 覆盖、mock 只用于锁状态/磁盘空间/失败注入、没有删除旧模式断言、没有放宽 expected values、failure injection 覆盖 publication 前后、测试风险评级和剩余平台限制。

- [ ] **Step 6: 更新 Flow Record 与 handoff**

  Change Brief 仅在证据存在时把 development 标为 done、testing 标为 `passed-agent-local`、archive 标为 done；handoff 记录 commits、命令、原始计数、两个既有 skips、文件系统限制和 CI/独立评审未运行。Artifact registry 加入 plan/verification/handoff；index next route 指向 review/integration，不宣称 merged/pushed。

- [ ] **Step 7: 提交验证与 handoff**

  ```powershell
  git add .llm-wiki/verification/obsidian-v02-phase31-archive-import.md .llm-wiki/handoff/obsidian-v02-phase31-archive-import-handoff.md .llm-wiki/requirements/obsidian-v02-phase31-archive-import.md .llm-wiki/artifacts/index.md .llm-wiki/index.md .llm-wiki/log.md
  git commit -m "docs: hand off Phase 3.1 archive import"
  ```

## Plan Self-Review Checklist

- [x] 每条 Phase 3.1 验收标准至少映射到一个任务和一个真实行为测试。
- [x] rebind collision、origin lock drift、reuse target lock read、Inventory raw 冲突和 Phase 4 raw scope 五项评审问题均有任务覆盖。
- [x] 没有 production step 留下占位标记、盲目 overwrite、全局 takeover 或非原子 fallback。
- [x] `ArchiveTargetEvidence`、`PreparedArchive`、`ArchivePublishResult` 和 error check 在前后任务中名称一致。
- [x] path-index/summary-ingest 的 ID、planner、transaction、CLI 和投影回归均保留。
- [x] Doctor check vocabulary、score v1、Finding 六字段和只读快照均有测试。
- [x] 计划不包含 Inventory 命令实现、多来源批处理、migration、自动删除或模型调用。
