# Obsidian LLM Wiki v0.2 Phase 4 Doctor 状态一致性实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展现有只读 Doctor，使其能够确定性检查 Phase 2/3 registry、托管页面、投影、operation、change log、lock 和 writer 临时文件之间的一致性，同时保持评分、Finding 字段和 CLI 退出码兼容。

**Architecture:** canonical runtime 新增纯只读 `llm_wiki_core/doctor_state.py`，它独立加载每个状态文件并返回稳定排序的 `ConsistencyIssue`。`managed.py` 提供 Page planner 与 Doctor 共用的托管区 inspector，`writer.py` 只暴露 lock 分类和临时文件命名 predicate；现有 `obsidian_wiki_doctor.py` 仅负责将 issue 适配为 Finding、脱敏和渲染，不获取锁、不写文件。

**Tech Stack:** Python 3.12 标准库、`dataclasses`、JSON/JSONL、SHA-256、`pathlib`、`unittest`、Obsidian Markdown marker、PowerShell 测试命令。

## Global Constraints

- 实施基线为 `main@e1f270d`；当前设计分支包含规格修订提交 `58b3f72`。
- canonical 实现只进入 `skills/obsidian-wiki-runtime/scripts/`；根目录 Doctor 脚本继续是 compatibility launcher。
- Doctor 不获取或创建 `.meta/lock.json`，不执行 atomic write、append、删除、投影重建或 registry 修复。
- 扫描范围只允许 control center 内的 `.meta/`、`wiki/` 和 `ingest/`；注册路径解析后仍必须位于 control center。
- Finding 字段保持 `check/severity/path/message/line/hint`；INFO 是允许值，但不影响 `--fail-on error` 或 score version 1。
- 新一致性 findings 不进入五维评分扣分映射。
- `.meta/` 完全不存在时 Phase 4 检查不适用；单文件损坏只阻断依赖该文件的检查。
- change-log 中间行损坏为 ERROR；仅无换行的非法尾片段为 `torn-change-log-tail` WARN，合法前缀继续参与检查。
- 所有生产改动遵循 TDD；每个任务结束时独立提交。

---

## 文件结构与职责

- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/managed.py`：新增纯文本托管页和投影快照 inspector，继续拥有 marker/checksum 语义。
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/page.py`：删除私有重复 parser，改用 `managed.py` 公共快照。
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py`：新增只读状态加载、检查编排、issue 排序和恢复 hint。
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/writer.py`：暴露与 atomic writer 同源的临时文件命名 predicate；不加入 Doctor 业务。
- `skills/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py`：把 `ConsistencyIssue` 转为 `Finding` 并追加到现有检查结果。
- `tests/test_llm_wiki_managed.py`、`tests/test_llm_wiki_page.py`：公共 inspector 与 planner 回归。
- `tests/test_llm_wiki_doctor_state.py`：Phase 4 Core 单元测试。
- `tests/test_obsidian_wiki_doctor.py`：CLI、INFO、脱敏、评分和只读集成测试。
- `tests/test_skill_runtime_packaging.py`：确认新增 Core 文件进入共享 runtime。

### Task 1：抽取公共托管区 inspector，并让 Page planner 复用

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/managed.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/page.py`
- Modify: `tests/test_llm_wiki_managed.py`
- Modify: `tests/test_llm_wiki_page.py`

**Interfaces:**
- Consumes: `managed_checksum(fields: Mapping[str, object], managed_body: str) -> str`、现有 marker 常量和 `ManagedConflict`。
- Produces: `ManagedPageSnapshot(fields: Mapping[str, object], managed_body: str, computed_checksum: str)`、`ProjectionSnapshot(managed_body: str)`、`inspect_managed_page(text: str) -> ManagedPageSnapshot`、`inspect_projection_region(text: str) -> ProjectionSnapshot`。

- [ ] **Step 1: 写公共 inspector 的失败测试**

  在 `ManagedRegionTests` 增加完整输入样例，固定 JSON scalar/array、LF/CRLF 归一化、末尾换行移除、checksum 镜像排除，以及 marker 缺失/重复/失衡/乱序：

  ```python
  def test_inspect_managed_page_returns_canonical_snapshot(self):
      text = (
          "---\r\n# llm-wiki:frontmatter:start\r\n"
          "llm_wiki_page_id: \"page-1\"\r\n"
          "llm_wiki_page_type: \"topic\"\r\n"
          "llm_wiki_source_ids: [\"source-1\"]\r\n"
          "llm_wiki_managed_checksum: \"old\"\r\n"
          "# llm-wiki:frontmatter:end\r\n---\r\n"
          "<!-- llm-wiki:managed:start -->\r\nBody\r\n"
          "<!-- llm-wiki:managed:end -->\r\n"
      )
      snapshot = inspect_managed_page(text)
      self.assertEqual(snapshot.fields["llm_wiki_page_id"], "page-1")
      self.assertEqual(snapshot.managed_body, "Body")
      self.assertEqual(
          snapshot.computed_checksum,
          managed_checksum(snapshot.fields, "Body"),
      )
  ```

- [ ] **Step 2: 运行测试确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_managed.ManagedRegionTests -v`

  Expected: FAIL，导入 `inspect_managed_page` 或 `ManagedPageSnapshot` 失败。

- [ ] **Step 3: 在 managed.py 实现不可变快照和单一 marker parser**

  使用一个内部 `_extract_single_region(text, start, end, label)` 验证 start/end 各出现一次且顺序正确；frontmatter 每行以第一个 `:` 分隔，key 必须以 `llm_wiki_` 开头，value 必须经 `json.loads()` 成功。托管正文执行以下唯一规范化：

  ```python
  def _canonical_managed_body(value: str) -> str:
      return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
  ```

  `inspect_managed_page()` 用规范化正文调用现有 `managed_checksum()`；`inspect_projection_region()` 只返回规范化 marker 内正文。

- [ ] **Step 4: 把 page.py 的 `_read_managed_state()` 改为公共 inspector**

  删除 `page.py` 中 `_region()` 和重复 frontmatter JSON 解析；保留一个窄适配函数：

  ```python
  def _read_managed_state(text: str) -> tuple[dict[str, object], str, str]:
      snapshot = inspect_managed_page(text)
      return dict(snapshot.fields), snapshot.managed_body, snapshot.computed_checksum
  ```

- [ ] **Step 5: 运行 managed/page 回归**

  Run: `& $python -m unittest tests.test_llm_wiki_managed tests.test_llm_wiki_page -v`

  Expected: PASS；既有 create/update/takeover/checksum 和用户区保留测试不回归。

- [ ] **Step 6: 提交**

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/managed.py skills/obsidian-wiki-runtime/scripts/llm_wiki_core/page.py tests/test_llm_wiki_managed.py tests/test_llm_wiki_page.py
  git commit -m "refactor: share managed page inspection"
  ```

### Task 2：实现独立状态加载、错误隔离和 torn change-log tail

**Files:**
- Create: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py`
- Create: `tests/test_llm_wiki_doctor_state.py`
- Modify: `tests/test_skill_runtime_packaging.py`

**Interfaces:**
- Consumes: `decode_source_registry()`、`decode_page_registry()`、`OperationRecord.from_dict()`、`schema_payload()`。
- Produces: `ConsistencyIssue`、`DoctorStateSnapshot`、`load_doctor_state(control_center: Path) -> tuple[DoctorStateSnapshot, Sequence[ConsistencyIssue]]`、`inspect_state_consistency(control_center: Path, *, now: datetime | None = None, pid_exists: Callable[[int], bool] = default_pid_exists) -> Sequence[ConsistencyIssue]`；两个入口实际返回不可变 tuple。

- [ ] **Step 1: 写 `.meta` gating、缺失文件和独立损坏测试**

  使用测试 helper 创建完整 Phase 3 registry，再分别删除或破坏一个文件。核心断言：

  ```python
  def test_absent_meta_disables_phase4_checks(self):
      with tempfile.TemporaryDirectory() as tmp:
          issues = inspect_state_consistency(Path(tmp))
          self.assertEqual(issues, ())

  def test_invalid_pages_does_not_hide_other_state_files(self):
      control = make_phase3_control_center()
      (control / ".meta/pages.json").write_text("{", encoding="utf-8")
      snapshot, issues = load_doctor_state(control)
      checks = [issue.check for issue in issues]
      self.assertIn("invalid-state-file", checks)
      self.assertIsNone(snapshot.pages)
      self.assertIsNotNone(snapshot.operations)
  ```

- [ ] **Step 2: 写 change-log 三分支失败测试**

  固定三种字节输入：合法事件无末尾换行仍合法；合法前缀加无换行半行产生 WARN 并保留前缀；中间非法行或非法尾行后仍有换行产生 ERROR 并禁用 event-dependent checks。

- [ ] **Step 3: 同时登记 runtime packaging 契约并运行红灯**

  在 `REQUIRED_RUNTIME_FILES` 增加 `scripts/llm_wiki_core/doctor_state.py`，然后运行：

  Run: `& $python -m unittest tests.test_llm_wiki_doctor_state tests.test_skill_runtime_packaging -v`

  Expected: FAIL，`llm_wiki_core.doctor_state` 不存在且 runtime required-file 检查报告缺失。

- [ ] **Step 4: 实现数据模型与逐文件 loader**

  `ConsistencyIssue` 固定字段为 `check/severity/relative_path/message/line/recovery_hint`。`DoctorStateSnapshot` 使用 `None` 表示对应状态文件不可安全使用，空 dict/tuple 表示文件合法但无 records。每个文件由独立 `try/except (OSError, JSONDecodeError, StateValidationError, UnicodeError)` 包围，错误消息只使用 control-center-relative path 和异常类别，不回显 registry 正文。

- [ ] **Step 5: 实现字节感知的 change-log parser**

  读取 UTF-8 bytes 并严格 decode。按 `splitlines(keepends=True)` 解析：只有最后一个非空片段不以 `\n`/`\r` 结尾且 `json.loads()` 失败时才是 torn tail；返回之前所有合法 dict event，并记录尾行号。其他非法 JSON、非 object event 或合法事件之后的中间坏行均使 events 为 `None` 并产生 `invalid-state-file` ERROR。

- [ ] **Step 6: 实现稳定排序入口并运行测试**

  `inspect_state_consistency()` 合并 loader issues 与后续 checker issues，排序键固定为 `({"ERROR": 0, "WARN": 1, "INFO": 2}[severity], check, relative_path, line or 0)`。

  Run: `& $python -m unittest tests.test_llm_wiki_doctor_state tests.test_skill_runtime_packaging -v`

  Expected: PASS，gating、错误隔离、torn tail 和排序测试全部通过。

- [ ] **Step 7: 提交**

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py tests/test_llm_wiki_doctor_state.py tests/test_skill_runtime_packaging.py
  git commit -m "feat: load Doctor state safely"
  ```

### Task 3：实现 source、page 和三投影一致性检查

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py`
- Modify: `tests/test_llm_wiki_doctor_state.py`

**Interfaces:**
- Consumes: Task 1 的两个 inspector，Task 2 的 `DoctorStateSnapshot`，`render_wiki_index()`、`render_ingest_index()`、`render_wiki_log()`。
- Produces: `_check_sources()`、`_check_pages()`、`_check_projections()`，由 `inspect_state_consistency()` 调用。

- [ ] **Step 1: 写 source/page 失败测试**

  每个 check 至少一个独立 fixture：processed source 无 proxy ID、proxy record 缺失、proxy 文件缺失、failed source、registered page 缺失、unsafe symlink/junction、frontmatter 三字段 drift、实际/frontmatter/registry checksum drift、marker conflict、orphan managed page。pending source 与 operation 的关联测试留在 Task 4。断言 check、severity、相对路径和非空 hint；敏感绝对路径不得进入 issue。

- [ ] **Step 2: 写投影失败测试**

  对三个投影分别覆盖 healthy、内容 drift、marker conflict 和 CRLF 等价；缺少整个投影文件不生成 Phase 4 重复 finding，因为仍由现有 Doctor 报告。

- [ ] **Step 3: 运行测试确认新断言失败**

  Run: `& $python -m unittest tests.test_llm_wiki_doctor_state -v`

  Expected: FAIL，目标 check 尚未由 `inspect_state_consistency()` 返回。

- [ ] **Step 4: 实现 source 与注册路径检查**

  page path 先拼接 control center，再使用 `resolve(strict=False)`；通过 `Path.relative_to(control_center.resolve())` 验证边界。processed source 依次验证 proxy ID、page record、Markdown 文件；pending source 的 operation 抑制留给 Task 4，Task 3 只在 operations snapshot 不可用时跳过该 check。

- [ ] **Step 5: 实现 page/frontmatter/checksum 检查**

  已登记页面调用 `inspect_managed_page()`；分别比较 `llm_wiki_page_id`、`llm_wiki_page_type`、排序后的 `llm_wiki_source_ids`，然后比较 computed checksum、frontmatter `llm_wiki_managed_checksum` 和 `PageRecord.managed_checksum`。`wiki/**/*.md` 仅按 marker 身份枚举孤儿页，不解析或扫描 marker 外正文。

- [ ] **Step 6: 实现三投影比较**

  只有依赖 registry/events 均可用时调用对应 renderer。把实际 marker 内正文与 renderer 结果执行 LF 归一化和末尾换行移除后比较；marker parser 抛错映射为 `projection-marker-conflict`，内容不同映射为 `projection-drift`，hint 指向 `projection rebuild` dry-run。

- [ ] **Step 7: 运行 Core 定向回归并提交**

  Run: `& $python -m unittest tests.test_llm_wiki_doctor_state tests.test_llm_wiki_managed tests.test_llm_wiki_page tests.test_llm_wiki_projection -v`

  Expected: PASS。

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py tests/test_llm_wiki_doctor_state.py
  git commit -m "feat: check registries pages and projections"
  ```

### Task 4：实现 operation、event、lock、pending 抑制和 temp 检查

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/writer.py`
- Modify: `tests/test_llm_wiki_doctor_state.py`
- Modify: `tests/test_llm_wiki_writer.py`

**Interfaces:**
- Consumes: `classify_lock(payload, now, ttl_seconds, pid_exists)`、operation records、合法 change events。
- Produces: `atomic_temp_prefix(target: Path) -> str`、`is_atomic_temp_name(name: str) -> bool`、operation/lock/temp issues。

- [ ] **Step 1: 写 operation/event 失败测试**

  覆盖 active、orphan、stale-lock、cross-host、invalid-lock、failed operation、event status drift、缺 completion event，以及 `projection-rebuild` completed operation 不要求 event。completion event 只认相同 `operation_id`、`result == "completed"` 的 event。

- [ ] **Step 2: 写 pending source 去重测试**

  同一 source ID 的 operation 按 `(updated_at, operation_id)` 取最新：无相关 operation或最新 completed 时报告 `pending-source-without-active-operation`；最新 running 时只进入 lock 判断；最新 failed 时只报告 `failed-operation`，且 hint 包含 source ID。

- [ ] **Step 3: 写 temp 同源规则和窄扫描测试**

  writer 测试固定 `atomic_temp_prefix(Path("pages.json")) == ".pages.json."`；Doctor 只识别 `.target.random.tmp`，不识别普通 `.tmp`、空 random token 或 control center 之外的同名文件，也不读取 temp 正文。

- [ ] **Step 4: 运行测试确认失败**

  Run: `& $python -m unittest tests.test_llm_wiki_writer tests.test_llm_wiki_doctor_state -v`

  Expected: FAIL，temp helper 和 operation/lock issues 尚未实现。

- [ ] **Step 5: 在 writer.py 抽取 temp 命名 primitive**

  `atomic_write_text()` 的 `mkstemp(prefix=atomic_temp_prefix(safe_path), suffix=ATOMIC_TEMP_SUFFIX)` 与 `is_atomic_temp_name()` 共用 `ATOMIC_TEMP_SUFFIX = ".tmp"`。predicate 要求开头点号、至少一个非空 target token、一个非空 random token和固定 suffix。

- [ ] **Step 6: 实现 lock 与 operation 联合判断**

  lock JSON 必须额外验证 `command` 和 `target` 字段；规范化 command 的空格/连字符后与 operation kind 匹配，target resolve 后必须等于 control center。多个 running operation 匹配同一有效锁时只选择最新一个为 `active-operation` INFO，其余为 orphan。cross-host lock 只报 WARN 并抑制相关 orphan；invalid lock 不抑制。

- [ ] **Step 7: 实现 event、pending 与 temp 检查并运行回归**

  `AUDITED_OPERATION_KINDS = frozenset({"state-init", "ingest-apply", "page-apply"})`；`projection-rebuild` 明确不在集合。temp 枚举只遍历 `.meta/`、`wiki/`、`ingest/`，遇到 symlink directory 不跟随。

  Run: `& $python -m unittest tests.test_llm_wiki_writer tests.test_llm_wiki_doctor_state -v`

  Expected: PASS。

- [ ] **Step 8: 提交**

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/llm_wiki_core/writer.py skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py tests/test_llm_wiki_writer.py tests/test_llm_wiki_doctor_state.py
  git commit -m "feat: diagnose operations locks and temp files"
  ```

### Task 5：接入 Doctor Finding、INFO、脱敏和 CLI 兼容

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py`
- Modify: `tests/test_obsidian_wiki_doctor.py`

**Interfaces:**
- Consumes: `inspect_state_consistency(control_center) -> Sequence[ConsistencyIssue]`。
- Produces: `finding_from_consistency_issue(issue: ConsistencyIssue) -> Finding`；`run_checks()` 在旧 findings 后追加稳定排序的新 issues 块。

- [ ] **Step 1: 写 CLI 集成失败测试**

  构造健康 Phase 3 control center，断言没有新 ERROR/WARN；构造 active operation + live lock，分别运行 validate JSON/text，断言 INFO 六字段正常、`--fail-on error` 返回 0；构造一个 Phase 4 ERROR，断言返回 1；score/report 仍返回 0 且 score version、五维名称和权重不变。

- [ ] **Step 2: 写脱敏和旧 Wiki 兼容测试**

  issue 的 message/hint 中放置敏感路径哨兵，确认 JSON/text/report 均经 `safe_finding()` 清理；`.meta` 不存在时现有 Doctor 输出逐字保持既有契约。

- [ ] **Step 3: 运行测试确认失败**

  Run: `& $python -m unittest tests.test_obsidian_wiki_doctor -v`

  Expected: FAIL，Phase 4 findings 尚未接入 CLI。

- [ ] **Step 4: 实现窄适配并追加检查块**

  `finding_from_consistency_issue()` 只做六字段映射；`run_checks()` 在四组旧检查后，仅当 `root.control_center is not None` 时调用 Core。保持 `should_fail()` 只匹配 ERROR，保持 `build_score_report()` 现有 check 映射不变。

- [ ] **Step 5: 运行 Doctor 与 CLI 兼容回归**

  Run: `& $python -m unittest tests.test_obsidian_wiki_doctor tests.test_llm_wiki_cli.DoctorCompatibilityTests -v`

  Expected: PASS；JSON/text/report、退出码、评分和根 launcher 兼容。

- [ ] **Step 6: 提交**

  ```powershell
  git add skills/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py tests/test_obsidian_wiki_doctor.py
  git commit -m "feat: expose Phase 4 Doctor findings"
  ```

### Task 6：验证严格只读、runtime 打包和全量回归

**Files:**
- Modify: `tests/test_obsidian_wiki_doctor.py`
- Modify: `skills/obsidian-wiki-doctor/references/doctor-checks.md`
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/doctor-manual-test.zh.md`
- Modify: `.llm-wiki/requirements/obsidian-v02-phase4-doctor-consistency.md`
- Modify: `.llm-wiki/artifacts/index.md`
- Modify: `.llm-wiki/index.md`
- Modify: `.llm-wiki/log.md`

**Interfaces:**
- Consumes: 完整 Phase 4 Core 与 CLI。
- Produces: 只读证据、runtime 文件契约、公开 check 清单和完成态 Flow Record。

- [ ] **Step 1: 写全树只读快照测试**

  快照递归记录 control center 每个非 symlink 文件的相对路径、size、`mtime_ns` 和 SHA-256；fixture 必须包含有效 `.meta/lock.json`。依次运行 validate、score、report，再断言前后快照完全相等，并确认没有新增 lock/temp 文件。

- [ ] **Step 2: 增加根 launcher 与 canonical runtime 的 Phase 4 输出等价测试**

  对同一个包含 `projection-drift` 的 fixture 分别运行根 launcher 和 canonical runtime，解析 JSON 后断言 payload 完全相等；继续断言根脚本只有 `runpy.run_path`，没有 Core import 或检查实现。

- [ ] **Step 3: 运行只读和打包集成门禁**

  Run: `& $python -m unittest tests.test_obsidian_wiki_doctor tests.test_skill_runtime_packaging -v`

  Expected: PASS；任何隐式写锁/temp、launcher 输出漂移或 runtime 文件缺失都会阻断后续文档同步。

- [ ] **Step 4: 更新 check 文档和手工验证说明**

  `doctor-checks.md` 按 ERROR/WARN/INFO 列出所有 Phase 4 check；README 只说明 Doctor 已理解 v0.2 状态层，不承诺自动修复；手工测试包含 torn tail、cross-host lock、projection drift 和运行前后快照核对。

- [ ] **Step 5: 运行静态只读边界检查**

  Run:

  ```powershell
  rg -n "atomic_write|append_change_event|begin_operation|update_operation|VaultLock\(|\.unlink\(|os\.remove|shutil\.rmtree" skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py
  ```

  Expected: 无输出。`doctor_state.py` 只允许导入 `classify_lock`、`is_atomic_temp_name` 等只读 primitive。

- [ ] **Step 6: 运行定向和全量回归**

  Run:

  ```powershell
  & $python -m unittest tests.test_llm_wiki_managed tests.test_llm_wiki_page tests.test_llm_wiki_writer tests.test_llm_wiki_doctor_state tests.test_obsidian_wiki_doctor tests.test_skill_runtime_packaging -v
  & $python -m unittest discover -s tests -v
  git diff --check
  ```

  Expected: 全部测试通过；仅既有 Windows symlink 权限和 opt-in Skills CLI integration 可按原理由 skip；`git diff --check` 无输出。

- [ ] **Step 7: 同步生命周期证据**

  只有全量验证成功后，才把 Change Brief 的 development/testing 改为 done，并记录原始命令、exit code、executor=`agent-local`、authority=`local-worktree`、trust level=`agent-local`；不得声称 CI 或独立评审已通过。

- [ ] **Step 8: 提交**

  ```powershell
  git add tests/test_obsidian_wiki_doctor.py tests/test_skill_runtime_packaging.py skills/obsidian-wiki-doctor/references/doctor-checks.md README.md README.zh.md docs/doctor-manual-test.zh.md .llm-wiki
  git commit -m "docs: publish Phase 4 Doctor consistency checks"
  ```

## 规格覆盖自检

| 设计要求 | 计划任务 |
|---|---|
| 公共托管页/投影 inspector 与 checksum 单一语义 | Task 1 |
| `.meta` gating、必要文件、单文件错误隔离 | Task 2 |
| torn tail WARN 与合法前缀继续检查 | Task 2 |
| source proxy、failed source | Task 3 |
| pending source 与最新 operation 关联 | Task 4 |
| page/frontmatter/checksum/marker/orphan | Task 3 |
| 三投影 drift 与 marker conflict | Task 3 |
| operation/event completion 审计与 rebuild 豁免 | Task 4 |
| active/stale/cross-host/invalid lock 联合判断 | Task 4 |
| failed operation 抑制 pending 重复告警 | Task 4 |
| writer 同源 temp pattern 与窄扫描 | Task 4 |
| Finding 六字段、INFO、脱敏、退出码与评分兼容 | Task 5 |
| Doctor 严格零写入并包含 lock 快照 | Task 6 |
| runtime packaging、根 launcher 与完整回归 | Task 6 |

## 计划自检

- 六个任务分别形成可测试、可提交的边界，不引入 Maintain、Inventory、archive-import 或评分 v2。
- 所有新接口在首次使用前定义；`projection-rebuild` 拼写、operation kind 和 audited kind 集合一致。
- 没有未决定的字段、枚举或错误级别；torn tail 的字节判定和 pending source 的最新 operation 规则均明确。
- 每个生产改动都有先失败、后实现、再回归的 TDD 步骤；最后一项包含完整 unittest、静态只读检查和验证来源记录。
- 实施期间不得把 agent-local 测试升级描述为 CI、外部审计或用户验收。
