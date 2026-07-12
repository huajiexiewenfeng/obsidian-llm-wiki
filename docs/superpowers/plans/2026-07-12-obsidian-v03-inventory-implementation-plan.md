# Obsidian v0.3 Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让共享 Inventory Core 和 Doctor 能只读发现 Vault 中新增未摄入或摄入后变化的文档，并提供需要显式确认的基线与忽略策略写入命令。

**Architecture:** 新增单一权威模块 `llm_wiki_core.inventory`，依次负责范围策略、元数据扫描、基线 codec、registry 证据比较和已确认事务写入。CLI 与 Doctor 都调用该模块；Doctor 只获得 inspect 接口，所有写入复用现有 lock、operation、原子替换和 change log 原语。

**Tech Stack:** Python 3 标准库、`argparse`、`pathlib`、`dataclasses`、现有 `llm_wiki_core.state/writer`、pytest/unittest。

## Global Constraints

- 默认支持 `.md`、`.markdown`、`.txt`、`.csv`、`.pdf`、`.docx`、`.xlsx`、`.xls`。
- 默认排除系统、依赖、缓存、构建目录和控制中心 `.meta/`、`ingest/`、`wiki/`、`raw/`。
- `raw/` 排除不可被 include 或 force-include 覆盖；未登记 raw 文件继续由 Doctor 报告 `unregistered-archive`。
- 默认扫描只读取相对路径、扩展名、大小和 `mtime_ns`，不读取正文，不跟随 symlink/junction。
- Doctor、`inventory inspect` 和所有无 `--confirm` 命令必须零写入。
- Inventory 只持久化 `discovered` 和 `ignored`；`processed`、`stale`、`uningested` 每次从 registry 和扫描结果推导。
- processed 必须同时具有 processed source、可解析 page、存在的托管 proxy 页面和无阻塞 registry 漂移。
- 敏感范围只输出 alias、数量和最新修改时间；不得输出逐文件路径。
- 首版不检测删除或重命名，不自动 ingest，不扫描 Vault 外部路径。
- dry-run 成功沿用现有 CLI 契约返回 1；确认成功返回 0；冲突返回 2；写入失败返回 3；内部错误返回 4。

---

### Task 1: Inventory 策略、扫描器与基线 codec

**Files:**
- Create: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/inventory.py`
- Create: `tests/test_llm_wiki_inventory.py`

**Interfaces:**
- Produces: `InventoryScope`, `ObservedSignature`, `InventoryDocument`, `InventoryBaseline`, `InventoryObservation`, `InventoryLoadError`。
- Produces: `default_inventory_scope(control_center_name: str) -> InventoryScope`。
- Produces: `scan_inventory(vault_root: Path, control_center: Path, scope: InventoryScope) -> InventoryObservation`。
- Produces: `load_inventory(path: Path) -> InventoryBaseline` 与 `inventory_payload(baseline: InventoryBaseline) -> dict[str, object]`。

- [x] **Step 1: 写策略和扫描失败测试**

  在 `tests/test_llm_wiki_inventory.py` 构造临时 Vault，断言普通 `notes/new.md` 被观察，`.obsidian/`、`.agents/`、`node_modules/`、控制中心 `.meta/ingest/wiki/raw`、不支持扩展名和目录 symlink 不被普通扫描返回；绝对 glob 和含 `..` 的 glob 抛出 `InventoryValidationError`。

- [x] **Step 2: 运行失败测试**

  Run: `python -m pytest tests/test_llm_wiki_inventory.py -q`

  Expected: FAIL，原因是 `llm_wiki_core.inventory` 尚不存在。

- [x] **Step 3: 实现最小策略和扫描器**

  使用冻结 dataclass 定义以下边界，并让所有普通路径保持 Vault 相对 POSIX 形式：

  ```python
  @dataclass(frozen=True)
  class ObservedSignature:
      size: int
      mtime_ns: int

  @dataclass(frozen=True)
  class InventoryScope:
      defaults_version: int
      include: tuple[str, ...]
      exclude: tuple[str, ...]
      force_include: tuple[str, ...]
      extensions: tuple[str, ...]
      sensitive: tuple[SensitiveScope, ...]

  @dataclass(frozen=True)
  class InventoryObservation:
      documents: Mapping[str, ObservedSignature]
      sensitive_scopes: Mapping[str, SensitiveSummary]
      errors: tuple[InventoryScanError, ...]
      collisions: tuple[tuple[str, ...], ...]
  ```

  以 `os.walk(..., followlinks=False)` 扫描并在进入目录前剪枝；使用 `Path.stat()` 取得元数据；casefold 索引发现重复键时记录 collision，不任选文件。

- [x] **Step 4: 写 baseline codec 安全测试并实现**

  覆盖 schema 1、未知 schema、JSON 损坏、绝对文档键、`..`、非法 disposition、ignored 缺少 reason、敏感 alias 重复和 deterministic JSON round-trip。`load_inventory` 只读，绝不在错误时重建文件。

- [x] **Step 5: 运行单元测试并提交**

  Run: `python -m pytest tests/test_llm_wiki_inventory.py -q`

  Expected: PASS。

  Commit: `feat: scan vault inventory metadata`

### Task 2: Registry 比较器与只读 inspect

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/inventory.py`
- Modify: `tests/test_llm_wiki_inventory.py`

**Interfaces:**
- Consumes: Task 1 的 scope、observation 和 baseline 类型；`SourceRecord`、`PageRecord`。
- Produces: `InventoryFinding`、`InventoryInspection`。
- Produces: `inspect_inventory(vault_root: Path, control_center: Path, *, scope_override: InventoryScope | None = None, verify_content: bool = False) -> InventoryInspection`。

- [x] **Step 1: 写比较优先级失败测试**

  覆盖 `missing-ingest-inventory`、`invalid-ingest-inventory`、`inventory-scope-changed`、`inventory-path-collision`、`uningested-source`、`stale-ingested-source`、`inventory-scan-incomplete`、`sensitive-scope-change`。断言 collision 阻断自动关联，processed 优先于 ignored，ignored 只抑制无 processed 证据的未摄入 finding。

- [x] **Step 2: 写完整 processed 证据失败测试**

  只有以下条件同时满足才不报告 `uningested-source`：source 为 `processed`、`canonical_path` 匹配当前文件、`proxy_page_id` 在 pages registry 中存在、对应托管 proxy 文件存在。仅有 `ingest/index.md` 或缺失 proxy 的记录不能作为 processed。

- [x] **Step 3: 实现确定性比较器**

  ```python
  @dataclass(frozen=True)
  class InventoryFinding:
      check: str
      severity: str
      path: str | None
      message: str
      hint: str | None = None
      count: int | None = None

  @dataclass(frozen=True)
  class InventoryInspection:
      scope: InventoryScope
      observation: InventoryObservation
      baseline: InventoryBaseline | None
      findings: tuple[InventoryFinding, ...]
      complete: bool
  ```

  source 匹配使用 canonical resolved path 与独立 casefold 键；stale 默认比较 `size + mtime_ns`。仅在 `verify_content=True` 且 source 有 checksum 时调用 `file_checksum()`，相同则本次消除 stale。

- [x] **Step 4: 验证零写入与脱敏**

  测试前后递归记录 Vault 的路径、大小、mtime；运行 inspect 后完全相同。敏感 finding 只包含 alias/count/latest_mtime，不含配置 glob 或任何文件名。

- [x] **Step 5: 运行测试并提交**

  Run: `python -m pytest tests/test_llm_wiki_inventory.py -q`

  Expected: PASS。

  Commit: `feat: compare inventory with ingest registries`

### Task 3: Inventory initialize/inspect CLI 与安全事务

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/inventory.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki.py`
- Create: `tests/test_llm_wiki_inventory_cli.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py`

**Interfaces:**
- Produces: `InventoryMutationPlan` 和 `InventoryMutationResult`。
- Produces: `plan_inventory_initialize(...)`、`apply_inventory_mutation(control_center, plan_checksum)`。
- CLI: `inventory inspect` 和 `inventory initialize [--confirm --plan-checksum]`。

- [x] **Step 1: 写 CLI dry-run 与退出码失败测试**

  断言 `inspect --format json` 返回完整非敏感 findings 且退出 0；`initialize` 返回 `confirmation_required=true`、`confirmable=true`、`plan_checksum` 且退出 1；缺少 `--plan-checksum`、计划漂移或损坏旧基线退出 2。

- [x] **Step 2: 写事务失败测试**

  断言确认写入创建 `.meta/inventory.json`，operation kind 为 `inventory-initialize`，change log 有唯一 completed 事件；重复确认幂等；锁冲突、checksum 漂移和注入失败不会伪报成功。

- [x] **Step 3: 实现计划与事务**

  计划 checksum 由规范化 scope、观察结果和输入文件 checksums 生成。确认阶段在 `VaultLock` 内重新扫描、重算计划并比较 checksum，然后调用 `begin_operation`、`atomic_write_json`、`append_change_event`、`update_operation`；错误路径尽力把 operation 标为 failed。

- [x] **Step 4: 注册 CLI**

  在 `build_parser()` 增加 `inventory` group；scope 参数是可重复的 `--include`、`--exclude`、`--sensitive-scope alias=glob`，inspect 另有 `--verify-content`。输出沿用 deterministic JSON 和现有 0/1/2/3/4 契约。

- [x] **Step 5: 让 Doctor 审计 Inventory operation**

  把 `inventory-initialize` 加入 `AUDITED_OPERATION_KINDS`，确保完成 operation 缺失 change event 会被现有一致性检查发现。

- [x] **Step 6: 运行测试并提交**

  Run: `python -m pytest tests/test_llm_wiki_inventory.py tests/test_llm_wiki_inventory_cli.py tests/test_llm_wiki_doctor_state.py -q`

  Expected: PASS。

  Commit: `feat: initialize inventory with confirmed transaction`

### Task 4: configure、ignore 与 unignore

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/inventory.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki.py`
- Modify: `tests/test_llm_wiki_inventory.py`
- Modify: `tests/test_llm_wiki_inventory_cli.py`

**Interfaces:**
- Produces: `plan_inventory_configure(...)`、`plan_inventory_ignore(...)`、`plan_inventory_unignore(...)`。
- CLI: `inventory configure`、`inventory ignore`、`inventory unignore`。

- [x] **Step 1: 写 disposition 和范围迁移失败测试**

  覆盖新增普通文档为 discovered、离开范围移除、进入敏感范围移除逐文件记录、离开敏感范围重新 discovered、ignore 必须有非敏感 reason、unignore 恢复 discovered、目录批量影响数量确定。

- [x] **Step 2: 实现三类计划**

  所有计划返回 action、affected_count、scope diff、expected inventory checksum、idempotency key 和 plan checksum；目标路径必须是 Vault 相对普通文件或批准目录，拒绝绝对路径、`..`、控制中心和敏感汇总内部路径。

- [x] **Step 3: 复用统一事务执行器**

  operation kind 分别为 `inventory-configure`、`inventory-ignore`、`inventory-unignore`；把三者加入 Doctor audited kinds。确认前在锁内重算并比较计划；重复 confirmation 不重复 change event。

- [x] **Step 4: 注册 CLI 并验证 dry-run**

  dry-run 都输出影响数量和 `plan_checksum`，退出 1；只有 `--confirm --plan-checksum` 写入。文本输出不得展开敏感文件名。

- [x] **Step 5: 运行测试并提交**

  Run: `python -m pytest tests/test_llm_wiki_inventory.py tests/test_llm_wiki_inventory_cli.py tests/test_llm_wiki_doctor_state.py -q`

  Expected: PASS。

  Commit: `feat: manage inventory scope and dispositions`

### Task 5: Doctor findings、聚合与评分

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py`
- Modify: `tests/test_obsidian_wiki_doctor.py`

**Interfaces:**
- Consumes: `inspect_inventory(...)` 和 `InventoryFinding`。
- Produces: Doctor `run_checks()` 中的 Inventory findings；更新后的 Ingest traceability 20 分维度。

- [x] **Step 1: 写 Doctor 集成失败测试**

  构造有 state 和 baseline 的临时 Vault，新增 `notes/new.md` 后运行 `doctor validate/report`，断言出现 `uningested-source`；修改已 processed 文件后出现 `stale-ingested-source`；运行前后 Vault 快照相同。

- [x] **Step 2: 写评分矩阵失败测试**

  有效且无 finding 为 20/20；uningested/stale 为 10/20；missing/scope-changed/scan-incomplete 为 5/20；invalid/collision/缺 proxy 为 0/20；未开始 ingest 且无候选为 not-applicable。

- [x] **Step 3: 接入共享 inspect**

  在 `run_checks()` 中调用 Inventory Core 并把 finding 转换为现有 `Finding`。不要在 Doctor 模块复制扫描规则。扫描不完整时输出明确 warning，不生成“未发现未摄入文档”的完整性结论。

- [x] **Step 4: 实现报告降噪**

  文本按一级目录和 check 聚合，每组最多 20 个普通示例并显示剩余数量；JSON 保留全部非敏感 finding。所有输出继续通过 `safe_finding`。

- [x] **Step 5: 运行测试并提交**

  Run: `python -m pytest tests/test_obsidian_wiki_doctor.py tests/test_llm_wiki_doctor_state.py tests/test_llm_wiki_inventory.py -q`

  Expected: PASS。

  Commit: `feat: report untracked vault documents in Doctor`

### Task 6: 兼容入口、技能说明与工作流文档

**Files:**
- Modify: `tests/test_skill_runtime_packaging.py`
- Modify: `tests/test_skills_cli_install.py`
- Modify: `skills/obsidian-wiki-doctor/SKILL.md`
- Modify: `skills/obsidian-wiki-ingest/SKILL.md`
- Modify: `skills/obsidian-wiki-maintain/SKILL.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflow.md`

**Interfaces:**
- Preserves: 根目录 shim 只转发 installable runtime，不复制 Inventory 实现。
- Documents: Doctor 发现、Ingest 处理、Maintain 初始化/配置/忽略的职责边界。

- [ ] **Step 1: 写 packaging 失败测试**

  断言安装包包含 `llm_wiki_core/inventory.py`，根 shim 的 `inventory inspect` 可用，已安装 Doctor 与权威 runtime 使用同一 Inventory Core。

- [ ] **Step 2: 更新三项技能说明**

  Doctor 明确“扫描并报告但不写”；Ingest 明确 processed 只能由成功 apply 产生；Maintain 明确 initialize/configure/ignore/unignore 必须先展示计划再确认。

- [ ] **Step 3: 更新架构和工作流**

  记录完整链路：Doctor/inspect 发现 → 用户选择 → Ingest apply → Doctor 复查；说明 `raw/` 不属于普通候选，真实 Vault 首次初始化需要用户确认。

- [ ] **Step 4: 运行 packaging 回归并提交**

  Run: `python -m pytest tests/test_skill_runtime_packaging.py tests/test_skills_cli_install.py tests/test_llm_wiki_cli.py -q`

  Expected: PASS（环境不支持 `npx` 时仅保留既有 skip）。

  Commit: `docs: publish inventory workflow`

### Task 7: 端到端验证与真实 Vault 只读试用

**Files:**
- Create: `tests/test_llm_wiki_inventory_e2e.py`
- Modify: `.llm-wiki/requirements/obsidian-ingest-inventory.md`
- Modify: `.llm-wiki/working-context/obsidian-ingest-inventory.md`
- Create: `.llm-wiki/handoff/obsidian-ingest-inventory-handoff.md`

**Interfaces:**
- Verifies: 临时 Vault 全流程和真实 Vault 零写入试用。

- [ ] **Step 1: 写临时 Vault E2E**

  流程为 state init → inventory initialize dry-run/confirm → 新增 Markdown → Doctor 报 uningested → ingest apply → Doctor 不再报 uningested → 修改原文 → Doctor 报 stale → ignore/unignore 验证。另测目录快照 ingest 后新增文件仍被发现。

- [ ] **Step 2: 运行新增与相关回归测试**

  Run: `python -m pytest tests/test_llm_wiki_inventory_e2e.py tests/test_llm_wiki_inventory.py tests/test_llm_wiki_inventory_cli.py tests/test_obsidian_wiki_doctor.py -q`

  Expected: PASS。

- [ ] **Step 3: 运行完整测试**

  Run: `python -m pytest -q`

  Expected: 所有测试通过，仅保留环境相关既有 skip。

- [ ] **Step 4: 真实 Vault 只读验证**

  在运行前后记录真实 Vault 文件清单、大小和 mtime；只运行 `inventory inspect` 与 Doctor。若真实 Vault 尚无 baseline，只报告 `missing-ingest-inventory` 并输出 initialize dry-run，未经用户确认不执行 initialize。

- [ ] **Step 5: 完成 Flow Record 与提交**

  把 development/testing 证据写入 Change Brief 和 handoff；archive 仅在 `project-finish` 阶段标记 done。

  Commit: `docs: finish inventory implementation`
