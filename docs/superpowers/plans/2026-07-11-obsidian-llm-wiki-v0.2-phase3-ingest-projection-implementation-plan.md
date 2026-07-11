# Obsidian LLM Wiki v0.2 Phase 3 Ingest 与投影实施计划

> **Required sub-skill:** 使用 `executing-plans` 按任务顺序执行；每个生产改动先遵循 `test-driven-development` 写失败测试，完成前使用 `verification-before-completion`。

**Goal:** 实现一个来源、一个 source proxy、零到多个派生页的可预览、可确认、可幂等恢复的 `ingest apply`，并提供共用的 `page apply` 与 `projection rebuild`。

**Architecture:** canonical runtime 新增 `ingest.py`、`page.py`、`projection.py` 三个专用 coordinator。纯 planner 在锁外读取并规范化 payload、registry 和托管 Markdown，生成确定性 plan；确认执行在单把 `VaultLock` 内重新计划并核对 `plan_checksum`，再用 Phase 2 writer primitives 写 registry、页面、三个投影、change log 和 operation。CLI 只负责 root resolution、payload I/O、确认参数、退出码和脱敏输出。

**Tech Stack:** Python 3.12 标准库、`dataclasses`、SHA-256、JSON/JSONL、`unittest`、Obsidian Markdown 托管 marker、PowerShell 测试命令。

## 实施边界

- 基线：本分支从本地 `main@01509a6` 创建，包含 Phase 2 merge `e30f59f` 和两轮 Phase 3 设计修订。
- canonical 实现只进入 `skills/obsidian-wiki-runtime/scripts/`；根目录 `scripts/llm_wiki.py` 保持 launcher。
- 本次接受 `path-index`、`summary-ingest`；`archive-import` 返回 `unsupported-mode`，二进制复制属于 v0.2 Phase 3.1。
- 不实现 Inventory、自动扫描、页面移动/删除、模型调用、通用事务 DSL。
- 所有命令默认 dry-run；可确认计划返回退出码 1，写入必须同时提供 `--confirm` 和匹配的 `--plan-checksum`。

## Task 1：锁定 payload loader、schema 和规范化契约

**Files:**
- Create: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py`
- Create: `tests/test_llm_wiki_ingest.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/__init__.py`

1. 在 `tests/test_llm_wiki_ingest.py` 写失败测试，覆盖：文件/stdin 共用 `load_payload_text()`；未知字段和 schema 拒绝；必须且只能有一个 source proxy；派生页可为空；重复及 case-fold 冲突路径拒绝；合法 mode 只有 `path-index`/`summary-ingest`；`archive-import` 抛出 check 为 `unsupported-mode` 的 `IngestValidationError`；`move_resolution` 只允许 `rebind + source_id` 或 `new-source`；异常文本不包含 `managed_body`。
2. 运行：

   ```powershell
   & $python -m unittest tests.test_llm_wiki_ingest.PayloadContractTests -v
   ```

   预期：因 `llm_wiki_core.ingest` 不存在而失败。
3. 实现不可变模型：

   ```python
   @dataclass(frozen=True)
   class SourceInput:
       path: Path
       source_type: str
       mode: str
       fingerprint: Mapping[str, int]
       checksum: str
       sensitivity: str
       move_resolution: MoveResolution | None

   @dataclass(frozen=True)
   class PageMutation:
       role: str
       page_type: str
       relative_path: str
       managed_body: str
       expected_managed_checksum: str | None
       takeover: bool

   @dataclass(frozen=True)
   class IngestPayload:
       schema_version: int
       source: SourceInput
       pages: tuple[PageMutation, ...]
       projection_takeovers: tuple[str, ...]

   def load_payload_text(text: str) -> IngestPayload: ...
   def load_payload_file(path: str, stdin: TextIO) -> IngestPayload: ...
   def normalized_payload_dict(payload: IngestPayload) -> dict[str, object]: ...
   ```
4. `normalized_payload_dict()` 使用稳定字段顺序语义、POSIX 相对路径和排序后的 takeover；不输出原始来源正文，也不写文件。
5. 重跑 Task 1 测试，预期全部通过；运行 `git diff --check`。
6. 提交：`git commit -m "feat: validate Phase 3 ingest payloads"`。

## Task 2：实现纯页面 mutation planner

**Files:**
- Create: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/page.py`
- Create: `tests/test_llm_wiki_page.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/managed.py`

1. 写失败测试，覆盖 create/update/unchanged/conflict；既有页缺 `expected_managed_checksum` 或不匹配时返回 `current_managed_checksum`、`registry_managed_checksum`、`resolution_hint` 且不返回正文；缺 marker 需要该 mutation 的 `takeover`; LF/CRLF、用户 frontmatter、用户正文均保留；路径不能逃逸 control center。
2. 运行：

   ```powershell
   & $python -m unittest tests.test_llm_wiki_page -v
   ```

   预期：因 `llm_wiki_core.page` 不存在而失败。
3. 实现：

   ```python
   @dataclass(frozen=True)
   class PagePlan:
       page_id: str
       relative_path: str
       action: str
       expected_file_checksum: str | None
       old_managed_checksum: str | None
       new_managed_checksum: str | None
       rendered_text: str | None
       conflict: Mapping[str, object] | None

   def plan_page_mutation(
       control_center: Path,
       mutation: PageMutation,
       pages: Mapping[str, PageRecord],
       source_ids: tuple[str, ...],
   ) -> PagePlan: ...
   ```
4. 新页面生成带托管 frontmatter/body marker 的最小 Markdown；既有页面只经 `managed.py` 更新托管区。`rendered_text` 仅供内部 apply，`PagePlan.to_public_dict()` 必须移除正文。
5. 运行 `tests.test_llm_wiki_page tests.test_llm_wiki_managed`，预期全部通过。
6. 提交：`git commit -m "feat: plan managed page mutations"`。

## Task 3：实现三类确定性投影

**Files:**
- Create: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/projection.py`
- Create: `tests/test_llm_wiki_projection.py`

1. 写失败测试，覆盖 `wiki/index.md` 按 page type/path 排序、`ingest/index.md` 按 source canonical path/source_id 排序、`wiki/log.md` 按 sequence 排序；prospective event 当次可见；重复渲染字节相同；marker 外文本和 CRLF 保持；每个缺 marker 目标必须单独 takeover。
2. 运行 `& $python -m unittest tests.test_llm_wiki_projection -v`，预期模块不存在。
3. 实现：

   ```python
   PROJECTION_PATHS = ("wiki/index.md", "ingest/index.md", "wiki/log.md")

   @dataclass(frozen=True)
   class ProjectionPlan:
       relative_path: str
       action: str
       expected_file_checksum: str | None
       rendered_text: str | None
       conflict: Mapping[str, object] | None

   def read_change_events(path: Path) -> tuple[dict[str, object], ...]: ...
   def render_wiki_index(pages: Mapping[str, PageRecord]) -> str: ...
   def render_ingest_index(sources: Mapping[str, SourceRecord], pages: Mapping[str, PageRecord]) -> str: ...
   def render_wiki_log(events: Sequence[Mapping[str, object]]) -> str: ...
   def plan_projections(
       control_center: Path,
       sources: Mapping[str, SourceRecord],
       pages: Mapping[str, PageRecord],
       events: Sequence[Mapping[str, object]],
       takeovers: Sequence[str],
       prospective_event: Mapping[str, object] | None = None,
   ) -> tuple[ProjectionPlan, ...]: ...
   ```
4. 所有 renderer 显式 `sorted()`；公共 plan 输出不携带 `rendered_text`。
5. 运行投影和 managed 测试，预期全部通过。
6. 提交：`git commit -m "feat: add deterministic wiki projections"`。

## Task 4：实现来源身份、move resolution 与确定性 IngestPlan

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py`
- Modify: `tests/test_llm_wiki_ingest.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/state.py`

1. 写失败测试：同路径同 checksum 复用；同路径新 checksum 增 revision；新路径同 checksum 返回候选；`rebind` 只接受候选且旧路径不存在；旧路径仍存在返回 `source-copy-not-move`；`new-source` 生成不同稳定 ID；source fingerprint/checksum 漂移冲突；相同输入 plan/idempotency checksum 稳定；任一 registry/目标文件/payload 变化导致 plan checksum 变化；dry-run 不创建 `.meta`、operation 或临时文件。
2. 运行 `& $python -m unittest tests.test_llm_wiki_ingest.IngestPlannerTests -v`，预期新测试失败。
3. 实现：

   ```python
   @dataclass(frozen=True)
   class IngestPlan:
       control_center: Path
       source: SourcePlan
       pages: tuple[PagePlan, ...]
       projections: tuple[ProjectionPlan, ...]
       expected_checksums: Mapping[str, str | None]
       idempotency_key: str
       plan_checksum: str
       confirmable: bool
       confirmation_required: bool

   def plan_ingest(control_center: Path, payload: IngestPayload) -> IngestPlan: ...
   ```
4. planner 只读加载 `.meta/sources.json`、`pages.json`、`change-log.jsonl` 和明确目标文件；先验证来源当前 fingerprint/checksum，再解析 source/page ID；构造 prospective completed event 后规划三投影；plan checksum 基于公共规范化计划和 expected checksums，不含时间或 operation ID。
5. `SourceRecord` schema 不新增模糊字段；rebind 更新既有 record 的路径/指纹/checksum/revision，new-source 使用稳定 seed 加显式 resolution 上下文。
6. 运行 ingest/page/projection/state 测试，预期全部通过。
7. 提交：`git commit -m "feat: plan idempotent source ingestion"`。

## Task 5：实现锁内 ingest transaction 与失败恢复事实

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/ingest.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/writer.py`
- Modify: `tests/test_llm_wiki_ingest.py`
- Modify: `tests/test_llm_wiki_writer.py`

1. 写失败测试，覆盖：锁内重新计划与 checksum 不符零写入；completed idempotency key 直接返回原结果且不创建 operation；source 先 pending、最后 processed；页面后 page registry；三个投影后 change log；每个步骤注入失败时 operation 为 failed/current_step 精确、source 不为 processed、成功文件不伪装回滚；change log 已追加但 operation completion 失败时重试修复 operation 且不重复 event。
2. 为 writer 增加只做 primitive 的 helpers：`read_change_events()`/`find_completed_event()` 或等价读取函数，以及允许 change event 保存 `idempotency_key` 和 `summary` 的向后兼容字段；不把业务编排放入 writer。
3. 实现：

   ```python
   def apply_ingest(
       control_center: Path,
       payload: IngestPayload,
       confirmed_plan_checksum: str,
       *,
       fail_after_step: str | None = None,
   ) -> IngestResult: ...
   ```
4. 严格执行设计中的步骤序列；每次 atomic replace 都带 planner 记录的 expected checksum；异常时尽力 `update_operation(... status="failed", current_step=step)`，然后抛出 `IngestWriteError`，公共错误包含已完成目标但不含正文。
5. 运行 `tests.test_llm_wiki_ingest tests.test_llm_wiki_writer`，预期全部通过。
6. 提交：`git commit -m "feat: apply recoverable ingest transactions"`。

## Task 6：复用 planner 实现 page apply 与 projection rebuild

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/page.py`
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/projection.py`
- Create: `tests/test_llm_wiki_page_apply.py`
- Modify: `tests/test_llm_wiki_projection.py`

1. 写失败测试：`PageApplyPayload` 不接受 source 字段且可多页；dry-run/confirm checksum 防漂移；一个 operation 下更新 pages registry 和 wiki/index；`ProjectionRebuildPayload` 只接受 schema/takeover；三投影从权威状态重建；重复 rebuild unchanged；失败有 operation 诊断。
2. 实现公共入口：

   ```python
   def load_page_apply_payload(text: str) -> PageApplyPayload: ...
   def plan_page_apply(control_center: Path, payload: PageApplyPayload) -> PageApplyPlan: ...
   def apply_pages(control_center: Path, payload: PageApplyPayload, confirmed_plan_checksum: str) -> PageApplyResult: ...
   def load_projection_rebuild_payload(text: str) -> ProjectionRebuildPayload: ...
   def plan_projection_rebuild(control_center: Path, payload: ProjectionRebuildPayload) -> ProjectionRebuildPlan: ...
   def apply_projection_rebuild(
       control_center: Path,
       payload: ProjectionRebuildPayload,
       confirmed_plan_checksum: str,
   ) -> ProjectionRebuildResult: ...
   ```
3. 与 ingest 共用 checksum/公共 plan 编码 helper，禁止复制出第二套并发语义。
4. 运行 page/projection/ingest 测试，预期全部通过。
5. 提交：`git commit -m "feat: apply pages and rebuild projections"`。

## Task 7：接入 canonical CLI、stdin 和退出码

**Files:**
- Modify: `skills/obsidian-wiki-runtime/scripts/llm_wiki.py`
- Modify: `tests/test_llm_wiki_cli.py`
- Modify: `tests/test_skill_runtime_packaging.py`

1. 写 subprocess 失败测试，覆盖三条命令的 parser；文件和 stdin 计划等价；dry-run 返回 1、`status=confirmation-required`、`confirmable=true` 且零写；缺 `--plan-checksum`、plan drift、payload/marker/checksum conflict 返回 2；锁/IO/部分失败返回 3；确认成功/unchanged/idempotent 返回 0；stdout/stderr 不出现 managed body；根 launcher 和 canonical CLI 等价。
2. 在 CLI 增加共用参数与 handler：

   ```python
   def add_apply_arguments(parser):
       parser.add_argument("--root")
       parser.add_argument("--cwd", default=str(Path.cwd()))
       parser.add_argument("--user-config")
       parser.add_argument("--payload", required=True)
       parser.add_argument("--confirm", action="store_true")
       parser.add_argument("--plan-checksum")
       parser.add_argument("--format", choices=("text", "json"), default="json")
   ```

   增加 `ingest apply`、`page apply`、`projection rebuild`；所有 handler 先 root resolve，再读 payload，共用异常到退出码映射。
3. 删除 Phase 2 的“Phase 3 commands 尚不存在”测试，替换为“`inventory` 仍不存在”。
4. 运行 CLI、runtime packaging 和三个 coordinator 测试，预期全部通过。
5. 提交：`git commit -m "feat: expose transactional wiki apply commands"`。

## Task 8：更新 Ingest Skill、公共文档并完成端到端验证

**Files:**
- Modify: `skills/obsidian-wiki-ingest/SKILL.md`
- Modify: `skills/obsidian-wiki-ingest/references/ingest-workflow.md`
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflow.md`
- Modify: `docs/development-plan.md`
- Modify: `.llm-wiki/requirements/obsidian-v02-phase3-ingest-projection.md`
- Create: `tests/test_llm_wiki_phase3_e2e.py`

1. 写契约测试：Skill 必须按 `root resolve -> payload -> dry-run -> 用户确认 -> confirm + plan checksum -> doctor`；不得指示 Agent 直接写 registry/投影；文档列出三个命令、退出码 1 语义、合法 mode、Phase 3.1 边界、Inventory 非目标。
2. 写临时 Vault E2E：先 `state init --confirm`，从文件 dry-run/confirm 摄入一个 source proxy + topic，验证两个 registry、三个投影、change event 和 completed operation；相同 payload 重跑不重复；stdin 再摄入第二来源；用户 marker 外文本保持。
3. 更新 Skill 和文档；把 Change Brief 的 development/testing evidence 指向实际提交与测试，只有全部验证后才改为 done。
4. 运行定向回归：

   ```powershell
   & $python -m unittest tests.test_llm_wiki_ingest tests.test_llm_wiki_page tests.test_llm_wiki_page_apply tests.test_llm_wiki_projection tests.test_llm_wiki_cli tests.test_llm_wiki_phase3_e2e -v
   ```

   预期：全部通过。
5. 运行全量：

   ```powershell
   & $python -m unittest discover -s tests -v
   git diff --check
   git status --short
   ```

   预期：全套通过，仅 Windows symlink 权限和 opt-in Skills CLI integration 可按既有理由跳过；diff check 无输出；状态仅有 Phase 3 预期文件。
6. 手工检查 JSON 不泄露：用唯一哨兵作为 `managed_body`，分别触发 validation、checksum、marker、plan conflict，`rg` 不得在输出中找到哨兵。
7. 提交：`git commit -m "docs: publish Phase 3 ingest workflow"`。

## 规格覆盖自检

| 设计要求 | 计划任务 |
|---|---|
| 单 source、单 proxy、多派生页 payload | Task 1 |
| file/stdin 同解析器、未知字段拒绝 | Task 1、7 |
| 页面 checksum/takeover/用户区保留 | Task 2 |
| 三投影确定性、prospective event | Task 3 |
| source identity、move rebind/new-source | Task 4 |
| plan checksum、dry-run 零写入 | Task 4、7 |
| 单锁 operation、pending 到 processed | Task 5 |
| 失败诊断、幂等补全、不伪造回滚 | Task 5 |
| page apply / projection rebuild | Task 6、7 |
| 稳定退出码与脱敏 JSON | Task 7 |
| Skill 只生成 payload、不直接写状态 | Task 8 |
| archive-import Phase 3.1、Inventory 非目标 | Task 1、8 |

## 计划自检

- 计划覆盖设计的 12 项验收标准；每项均有失败测试、实现步骤和验证命令。
- 没有 `TODO`、`TBD`、占位函数或未决定枚举；Phase 3 mode 固定为 `path-index`、`summary-ingest`。
- planner 的内部 `rendered_text` 与公共脱敏输出明确分离；Skill、CLI、coordinator、writer 的职责没有交叉。
- 所有路径均为仓库相对路径，命令从本 worktree 根目录运行；不依赖未推送的 `origin/main`。
- Phase 3.1 archive binary copy 不在生产实现任务中，仅验证结构化 `unsupported-mode`。
