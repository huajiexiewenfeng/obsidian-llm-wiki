# Obsidian LLM Wiki v0.2 Phase 3：Ingest 接入与确定性投影设计

## 状态

- 日期：2026-07-11
- flow_id：`obsidian-v02-phase3-ingest-projection`
- 状态：设计已在对话中确认，书面规格待用户复审
- 前置：v0.2 Phase 2 状态契约与安全写入已合入
- 后续：Phase 4 Doctor 状态一致性检查、v0.3 Inventory

## 目标

Phase 3 交付第一条完整、可靠的 Obsidian LLM Wiki 摄入链路：Skill 在锁外读取一个已确认来源、生成 source proxy 与派生知识页，用户确认预览后，deterministic Core 在单进程、单 Vault 锁和单 operation 中写入机器状态、托管页面、索引投影与审计事实。

完成后，一个来源可以对应一个 source proxy 和零到多个 topic、project、entity 或 SOP 页面；重复执行不会产生重复页面，中断不会把未完成来源标记为 `processed`，用户在托管区外的内容保持不变。

## 非目标

- 不自动扫描或发现 Vault 新文件；该能力属于 v0.3 Inventory。
- 不在 Core 内调用模型、生成摘要或决定知识分类。
- 不实现自动 migration、Context Pack、附件/嵌入/块引用语法。
- 不复制、移动或删除原始来源。
- 不自动接管缺少托管 marker 的既有 Markdown。
- 不建立通用事务 DSL。

## 已确认设计决策

1. 一个 `ingest apply` payload 绑定一个来源，必须包含一个 source proxy，可以同时创建或更新多个派生知识页。
2. CLI 使用 `--payload <file|->`；普通路径读取 JSON 文件，`-` 从 stdin 读取。两者共享同一解析和校验路径。
3. takeover 在 payload 中按页面 mutation 或投影相对路径逐项声明；不提供全局 takeover。
4. 所有写命令默认 dry-run，必须使用相同 payload、`--confirm` 和预览返回的 `--plan-checksum` 才能写入。
5. 使用专用 coordinator：`ingest.py`、`page.py`、`projection.py`；复用 Phase 2 primitives，不由 CLI 直接编排事务。

## 架构

canonical 实现位于：

```text
skills/obsidian-wiki-runtime/scripts/
  llm_wiki.py
  llm_wiki_core/
    state.py
    managed.py
    writer.py
    ingest.py
    page.py
    projection.py
```

职责边界：

- `ingest.py`：解析规范化 payload、生成 `IngestPlan`、执行单来源摄入事务。
- `page.py`：定义通用 page mutation 和 source-less `page apply`，供 Init 与 Maintain 使用。
- `projection.py`：从 registry 与 change log 生成三类确定性投影，并执行 `projection rebuild`。
- `state.py`：继续拥有 schema、records、registry codec 与稳定 ID；只增加 Phase 3 必需字段校验。
- `managed.py`：继续只做 frontmatter、managed body 和 projection marker 的纯文本变换。
- `writer.py`：继续只拥有锁、checksum precondition、原子替换、operation 与 change-log primitives。
- `llm_wiki.py`：只负责 root resolve、payload 输入、dry-run/confirm、退出码和结构化输出。
- `obsidian-wiki-ingest`：在锁外读取来源、调用模型、生成内容、展示预览并取得用户确认。

## Payload 契约

`IngestPayload` 为版本化 JSON：

```json
{
  "schema_version": 1,
  "source": {
    "path": "<confirmed-source-path>",
    "source_type": "markdown",
    "mode": "summary",
    "fingerprint": {
      "size": 1024,
      "mtime_ns": 1783658400000000000
    },
    "checksum": "sha256:...",
    "sensitivity": "normal"
  },
  "pages": [
    {
      "role": "source-proxy",
      "page_type": "source",
      "path": "wiki/sources/example.md",
      "managed_body": "...",
      "expected_managed_checksum": null,
      "takeover": false
    },
    {
      "role": "derived",
      "page_type": "topic",
      "path": "wiki/topics/example.md",
      "managed_body": "...",
      "expected_managed_checksum": "sha256:...",
      "takeover": false
    }
  ],
  "projection_takeovers": []
}
```

规则：

- payload 只能包含一个 source。
- `pages` 必须且只能包含一个 `role: source-proxy`；派生页可以为零到多个。
- page path 必须是 control-center-relative，规范化后仍位于 control center 内，并且不得重复或 case-fold 冲突。
- payload 不包含原始来源正文，只包含已生成的托管 Markdown；Core 不持久化原始 payload。
- source/page ID 由 Core 根据 registry 与稳定身份规则解析，Agent 不自行指定新 ID。
- 更新既有托管页面必须提供 `expected_managed_checksum`；缺失或不匹配时返回 conflict。
- 既有无 marker 页面只有在对应 mutation 中 `takeover: true` 时才能接管。
- 投影内容不由 payload 提供；`projection_takeovers` 只列出明确允许首次创建 marker 的投影相对路径。
- 未知字段、未知 schema、非法 page type、非法 sensitivity 或缺少必填字段均返回 validation error。

`PageApplyPayload` 使用相同 page mutation 数组，但不含 source；`ProjectionRebuildPayload` 只包含 schema 与逐路径 takeover 清单。三个命令共享 payload loader 和规范化规则。

## 来源身份与幂等

Core 先按 canonical path/case-fold key 查找既有 source：

- 同一路径、相同 checksum：复用 source ID，可能得到 unchanged。
- 同一路径、不同 checksum：更新同一 source revision，不创建新 source。
- 新路径、checksum 与已有 source 相同：返回 move candidate conflict，等待用户确认重新绑定，不自动合并。
- 无匹配：创建新稳定 source ID。

page ID 按现有 page registry 与规范化目标路径解析；路径已有 page 记录时复用 ID，新路径创建稳定 ID。页面移动、删除和重命名不在本阶段自动处理。

`idempotency_key` 由目标 control center 身份、source ID、source checksum、规范化 page mutation checksum 与投影目标集合确定性生成。completed change-log event 必须保存该 key、operation ID、record IDs 和结果摘要。相同 key 已完成时返回原结果，不创建新 operation、不重写页面、不追加重复完成事件。

## Dry-run 与计划防漂移

dry-run 流程：

```text
读取并规范化 payload
-> resolve Vault/control center
-> 校验 source fingerprint/checksum
-> 读取 registries、目标页面、投影和 change log
-> 计算新的内存状态与托管内容
-> 检测路径、checksum、marker、move candidate 和 takeover 冲突
-> 输出 IngestPlan 与 plan_checksum
```

dry-run 不获取写锁，不创建 operation、目录、临时文件或审计事件。计划输出至少包含：

- `plan_checksum` 与 `idempotency_key`
- source 的 create/update/unchanged/move-conflict
- 每个页面的 create/update/unchanged/conflict
- 每个投影的 create/update/unchanged/conflict
- takeover 清单
- registry 和目标文件的预期旧 checksum
- `confirmation_required` 与 `confirmable`

确认命令：

```text
python scripts/llm_wiki.py ingest apply \
  --root <vault-or-control-center> \
  --payload <file|-> \
  --confirm \
  --plan-checksum sha256:... \
  --format json
```

获取锁后 coordinator 必须重新计划，并与用户确认的 `plan_checksum` 比较。任何 registry、页面、投影、source fingerprint 或 payload 漂移都会返回 `plan-conflict`，不会以新计划继续写入。

dry-run 只返回确定性 `plan_checksum`，不分配真实 `operation_id`。真实 operation ID 仅在确认执行且计划复核通过后创建。

## 锁内事务

确认执行顺序：

```text
获取 VaultLock
-> 重新计划并核对 plan_checksum
-> 查询 completed idempotency_key
-> 创建 running operation
-> source registry 写入 pending
-> 逐个原子写入页面
-> 原子更新 page registry
-> 重建 wiki/index.md
-> 重建 ingest/index.md
-> 构造本次 prospective change event
-> 用“已有事件 + prospective event”写入 wiki/log.md 投影
-> source registry 更新为 processed
-> 追加同一 prospective event 到 change-log.jsonl
-> operation 标记 completed
-> 释放锁
```

`wiki/log.md` 使用 prospective event 渲染，保证当前 operation 在本次投影中可见。由于多文件系统不存在全局原子提交，任何步骤之间仍可能中断；operation `current_step` 和文件/registry checksum 用于区分投影超前、registry 超前或 audit 未追加等状态。

## 失败与恢复

- 锁前校验失败：零写入，不创建 operation。
- 锁超时：返回 IO/lock 错误，不修改状态。
- 锁内失败：尽力把 operation 标记 `failed`，记录 `current_step`、error、已成功目标和预期/实际 checksum。
- source 保持 `pending` 或标记 `failed`；只有所有页面、registry 与投影步骤成功后才允许写 `processed`。
- 已成功原子替换的文件不伪造回滚；失败记录必须诚实描述部分成功状态。
- retry/resume 必须重新提供相同 payload，并重新通过路径、source 和 checksum 校验。
- Maintain 只有在用户确认后才能执行 resume 或 metadata-only rollback；不得删除原始来源或用户正文。
- Phase 4 Doctor 将检查 orphan managed page、registry/frontmatter drift、projection drift、failed/running operation、遗留临时文件和 stale lock。

如果 `wiki/log.md` 已包含 prospective event 而 change log append 失败，operation 保持 failed，`projection rebuild` 会从权威 change log 移除超前投影；如果 change log 已追加而 operation completion 写入失败，相同 idempotency key 重试时从 change log 返回原结果并修复 operation 状态。

## 投影规则

- `wiki/index.md`：从 page registry 生成 source/topic/project/entity/SOP 导航。
- `ingest/index.md`：从 source registry 生成来源状态与 proxy 链接。
- `wiki/log.md`：从 change log 生成审计投影。
- renderer 输出排序稳定，不依赖文件系统枚举顺序或字典插入顺序。
- 只替换 `llm-wiki:projection` 托管区，marker 外字节保持不变。
- 缺少 marker 时必须逐路径 takeover；重复、嵌套、越界或顺序错误均返回 conflict。
- `projection rebuild` 由权威状态重新生成相同托管区，重复执行结果不变。

## CLI 与退出码

Phase 3 增加：

```text
ingest apply
page apply
projection rebuild
```

三者均支持 JSON/text 输出、dry-run 默认值、`--confirm` 和 `--plan-checksum`。稳定退出码：

```text
0  成功、幂等命中或确认后的 unchanged
1  计划可确认但尚未提供 --confirm
2  payload、路径、checksum、marker、takeover 或 plan conflict
3  IO、锁、原子写或可诊断的部分写入失败
4  未预期内部错误
```

根目录 `scripts/llm_wiki.py` 继续是 compatibility launcher；所有实现只进入 installable shared runtime。

## Skill 流程

`obsidian-wiki-ingest` 的目标流程：

```text
resolve root
-> Agent 只读读取用户确认的来源
-> 模型生成 source proxy 与派生知识页托管内容
-> 生成 payload
-> ingest apply dry-run
-> 向用户展示 create/update/unchanged/conflict/takeover
-> 用户确认
-> ingest apply --confirm --plan-checksum
-> doctor validate/report
```

Skill 不直接修改 registry、页面或投影，也不在 Core 持锁期间进行模型调用或等待用户。

## 安全

- 不扫描整个磁盘或整个 Vault；只读取 payload 指定且已确认的 source 与目标状态文件。
- source 路径是读取范围，不会被当作 Wiki root。
- 所有写目标必须位于解析后的 control center 内，并通过 symlink/junction 越界检查。
- 错误和 JSON 输出不得回显完整 `managed_body` 或敏感来源正文。
- stdin 模式允许敏感生成内容不落临时 payload 文件；Core 不保存原始 payload。
- 不提供全局 takeover、blind overwrite 或无 checksum 更新。
- 不自动复制到 `raw/`，不删除来源，不删除用户区域。

## 测试策略

### Payload 与身份

- schema、必填字段、未知字段、单 proxy 约束、重复路径、case-fold 冲突。
- file/stdin 等价。
- canonical path、路径越界、source checksum/fingerprint、move candidate。

### Planner

- 相同输入产生相同 plan 与 checksum。
- registry、文件、source 或 payload 漂移改变 plan checksum。
- dry-run 零写入。
- create/update/unchanged/conflict/takeover 分类完整。

### 页面与投影

- frontmatter、managed body、用户区与 LF/CRLF 保留。
- expected managed checksum、marker 冲突和逐目标 takeover。
- 三个投影排序稳定、幂等重建。
- `wiki/log.md` 包含 prospective event，失败后可从 change log 修复。

### 事务

- 在每个锁内步骤注入失败。
- source 不提前进入 processed。
- operation 记录精确 current step 与部分成功目标。
- completed idempotency key 不重复执行。
- change log 已追加但 operation completion 失败时可幂等恢复。

### CLI 与集成

- 三个命令的 dry-run/confirm/plan conflict 与退出码。
- root launcher 与 canonical runtime 等价。
- sample Vault 端到端流程。
- Windows、Ubuntu、runtime packaging 与完整 unittest 回归。

## 验收标准

1. 一个确认来源可在一个 operation 中安全生成一个 source proxy 和多个派生页面。
2. dry-run 严格零写入，并返回可复核 plan checksum。
3. 确认时任何状态漂移都停止写入。
4. source 只在页面、page registry 和三个投影写入成功后进入 processed；后续 audit append 失败时 operation 仍为 failed，并可用相同 payload 幂等补全。
5. 相同 idempotency key 不产生重复页面、registry 记录或完成事件。
6. 托管区外用户内容保持不变；所有 blind overwrite 和隐式 takeover 被拒绝。
7. 三个 Markdown 投影可从权威状态确定性重建。
8. 每个注入失败点都产生可诊断 operation，不假装全量回滚。
9. canonical runtime 和根 launcher 行为一致。
10. Phase 3 不包含 Inventory、自动发现或 migration。

## 后续关系

- Phase 4 Doctor 读取本阶段产生的 operation、registry、frontmatter 与 projection checksum，报告一致性和恢复建议。
- v0.3 Inventory 以 `sources.json` 的 processed 状态作为唯一摄入证据；新文件发现、stale 推导和 ignored 基线不在本阶段实现。
- 当 Page、Projection 与 Inventory 出现更多共同事务需求后，再评估是否从专用 coordinator 抽象通用 transaction engine。
