# Obsidian Vault 未摄入文档发现设计

日期：2026-07-11

状态：评审后已修订，待用户复审

仓库：`obsidian-llm-wiki`

Flow ID：`obsidian-ingest-inventory`

## 背景

当前 Doctor 只遍历 `00-知识库中控/wiki/` 内的 Markdown，并检查
`ingest/index.md` 中已经登记的记录。Maintain 只消费 Doctor finding 并应用已确认修复。
因此，两者都无法发现“已经放进 Obsidian Vault、但从未进入 ingest 记录”的新文档。

本设计增加一个共享的文件发现层，使 Doctor 能只读地回答：

> Vault 中是否存在尚未 ingest 的新文档，或者 ingest 后又发生变化的文档？

## 已确认决策

- 默认扫描整个 Vault，但支持 include/exclude。
- 默认排除系统目录、控制中心机器状态与 Wiki 投影、依赖目录、缓存、构建产物和
  `00-知识库中控/raw/`；`raw/` 是 Phase 3.1 起由 Core 管理的不可变归档保留区。
- 敏感目录只报告目录级汇总，不展示文件名，不读取正文。
- 使用持久化扫描基线；目录级 ingest 只覆盖确认时的文件快照，后续新增文件仍会被发现。
- Doctor 严格只读；所有 Inventory 写入复用 v0.2 的锁、operation、原子替换和 change log 协议。
- 首版检测新增文件和已摄入后变更，不检测删除与重命名。
- 默认扫描 `.md`、`.markdown`、`.txt`、`.csv`、`.pdf`、`.docx`、`.xlsx`、`.xls`。
- 没有基线时不静默接受现状，而是报告 `missing-ingest-inventory`。
- `discovered` 不等于 `processed`；只有摄入证据或明确忽略才能消除未摄入告警。
- `.meta/sources.json` 是摄入状态唯一事实源；Inventory 不保存独立的 `processed` 状态。
- 使用元数据签名，不读取正文计算哈希。
- 本能力是 v0.3 `inventory` 的正式设计，在 v0.2 状态层和 `ingest apply` 事务落地后实施。

## 目标

1. 发现 Vault 中新增但尚未 ingest 的支持文档。
2. 发现已经 ingest、此后又发生变化的文档。
3. 保持 Doctor 的只读边界。
4. 让 Doctor、Ingest、Maintain 使用同一套范围、扫描和比较规则，同时遵守 v0.2 单一事实源。
5. 对大批量结果进行汇总，对敏感范围进行脱敏。

## 非目标

- 不识别删除和重命名。
- 不读取 Markdown、PDF、Word、Excel 或其他候选文档正文。
- 不计算内容哈希。
- 不自动 ingest、移动、删除或整理原文档。
- 不扫描 Vault 外部路径。
- 不默认扫描图片、压缩包、可执行文件或代码仓库全部源码。
- 不修改 WikiLink 解析行为；WikiLink 修复保持独立交付。
- 不引入 SQLite 或其他数据库。
- 不在 Inventory 中复制 `.meta/sources.json` 的 processed、fingerprint、checksum 或 proxy 状态。

## 总体架构

新增共享的 `Inventory Core`：

```text
Vault 文件元数据
    -> InventoryScopePolicy
    -> InventoryScanner
    -> 当前文件观察结果
    -> InventoryComparator <- .meta/inventory.json
                           <- .meta/sources.json
                           <- .meta/pages.json
    -> Doctor Findings
```

### InventoryScopePolicy

负责扫描边界和文件类型：

- 默认 include：Vault 内全部相对路径。
- 默认 exclude：`.git/`、`.obsidian/`、`.trash/`、`.agents/`、`.codex/`、
  `node_modules/`、常见缓存和构建目录、`00-知识库中控/.meta/`、
  `00-知识库中控/ingest/`、`00-知识库中控/wiki/` 和 `00-知识库中控/raw/`。
- `00-知识库中控/raw/` 不接受 include/force-include 覆盖。已登记文件由 archive registry/Doctor 检查；未登记普通文件报告 `unregistered-archive`，不报告 `uningested-source`。
- 支持用户确认的 include/exclude 覆盖。
- 支持用户确认的敏感范围及其报告代号。
- 只接受已配置的支持扩展名。

解析后的策略和内置默认策略版本写入基线。`inspect` 默认严格使用基线策略；只有用户显式传入
不同策略，或 runtime 声明基线的默认策略版本不再兼容时，才报告 `inventory-scope-changed`。
策略变化后不得静默沿用旧基线。

### InventoryScanner

只读取：

- Vault 相对路径；
- 扩展名；
- 文件大小；
- 纳秒级修改时间。

扫描器不得打开文件读取正文，不得跟随目录 symlink 或 junction，不得返回 Vault 外路径。

### InventoryRepository

读取并验证：

```text
00-知识库中控/.meta/inventory.json
```

Doctor 只获得读取接口。写入接口只能由显式带 `--confirm` 的 Inventory 命令调用，供
Maintain 在已确认流程中使用。所有写入必须通过 v0.2 state writer，不允许 Inventory
另建锁、临时文件或审计实现。

### InventoryComparator

比较当前观察结果、基线记录、`.meta/sources.json` 和 `.meta/pages.json`：

- 当前普通文件没有匹配的 processed source，且未被忽略：`uningested-source`；
- processed source 的 fingerprint 与当前元数据不同：`stale-ingested-source`；
- 基线 disposition 为 `ignored`：不报告未摄入；
- 基线缺失：`missing-ingest-inventory`；
- 基线不可解析或不安全：`invalid-ingest-inventory`。

摄入证据只来自 source/page registry。`ingest/index.md`、source proxy frontmatter 和
`wiki/log.md` 都是投影或镜像，只用于 Doctor 漂移检查，不用于推导 processed。

比较优先级固定为：

1. 先验证基线、范围和 casefold 路径唯一性；错误记录不继续自动关联；
2. 再匹配 processed source；fingerprint 不同则报告 stale，即使旧 Inventory disposition 为 ignored；
3. 没有 processed source 时，`ignored` 才抑制 `uningested-source`；
4. 其余普通候选均报告 `uningested-source`。

目录 source 按 registry 中已确认的逐文件快照匹配；目录路径本身不能覆盖快照之外的后代。

### 技能边界

- Doctor：扫描、比较、评分、报告，绝不写入。
- Ingest：通过 `ingest apply` 事务更新 source/page registry；成功后 Comparator 自然推导为 processed。
- Maintain：经确认初始化基线、调整范围、标记 `ignored` 或解除忽略。
- Query：不直接依赖 Inventory Core。

## 基线数据模型

Schema v1：

```json
{
  "schema_version": 1,
  "scope": {
    "defaults_version": 1,
    "include": ["**/*"],
    "exclude": [
      ".git/**",
      ".obsidian/**",
      ".trash/**",
      ".agents/**",
      ".codex/**",
      "00-知识库中控/.meta/**",
      "00-知识库中控/ingest/**",
      "00-知识库中控/wiki/**",
      "00-知识库中控/raw/**"
    ],
    "force_include": [],
    "extensions": [
      ".md",
      ".markdown",
      ".txt",
      ".csv",
      ".pdf",
      ".docx",
      ".xlsx",
      ".xls"
    ],
    "sensitive": [
      {
        "alias": "sensitive-1",
        "pattern": "approved-sensitive-folder/**"
      }
    ]
  },
  "documents": {
    "AI/example.md": {
      "disposition": "discovered",
      "observed_signature": {
        "size": 1234,
        "mtime_ns": 1780000000000000000
      },
      "ignore_reason": null
    }
  },
  "sensitive_scopes": {
    "sensitive-1": {
      "document_count": 12,
      "latest_mtime_ns": 1780000000000000000
    }
  }
}
```

规则：

- 所有普通文档键都是规范化的 Vault 相对路径，统一使用 `/`。
- Windows 比较不区分大小写，但不改写用户原始文件名。
- 不在 JSON 中保存正文、摘要、内容片段或绝对工作站路径。
- 敏感范围配置只允许 Vault 相对 glob 和报告代号；报告只使用代号，不回显 glob。
- 敏感范围的逐文件路径不进入 `documents`；只保存批准的报告代号和汇总。
- `documents` 只保存发现观察和忽略决策，不保存 processed、source ID 或 proxy ID。
- `observed_signature` 是基线观察，不是摄入完成证明。
- `ignored` 必须带简短的 `ignore_reason`，且原因不得包含敏感值。
- 敏感 glob 会以明文相对路径保存在 `.meta/inventory.json`，可能暴露目录命名；这是已知残余风险。
  不应把包含此状态文件的 Vault 发布到公共仓库。

## 状态模型

Inventory 持久 disposition 只有：

- `discovered`：已发现但没有摄入证据；
- `ignored`：用户明确决定不摄入。

Doctor 运行时从 registry 和当前扫描推导：

- `processed`：匹配的 source 状态为 processed，且关联 page/proxy 证据有效；
- `stale`：processed source 的 fingerprint 与当前元数据不同；
- `uningested`：没有 processed source 且未被忽略。

这些诊断状态都不写回 Inventory。

```text
新文件
  -> discovered
  -> processed（ingest apply 更新 sources.json 后由 Doctor 推导）
  -> stale（当前 fingerprint 与 sources.json 不同）
  -> processed（重新 ingest apply 后由 Doctor 推导）

discovered
  -> ignored（用户明确确认）
  -> discovered（unignore，重新进入候选）
```

目录级 ingest 的语义：

- `ingest apply` 只把该次已确认扫描中实际存在的支持文件登记进 source registry；
- 目录来源可以在 source registry 中保存排序后的文件清单和每项 fingerprint；
- 后续新增文件不在该 source 快照中，仍报告 `uningested-source`；
- 初始化旧 Vault 时，不因存在一个目录级旧 ingest 行就推断当前全部后代都已处理；
- 旧投影在完成 v0.3 `migrate` 并生成 registry 之前不能作为 processed 证据。

旧记录的“可靠匹配”必须同时满足：

1. `.meta/sources.json` 中存在规范化后匹配当前文件的 source；
2. source 状态为 `processed`；
3. `proxy_page_id` 能在 `.meta/pages.json` 中解析；
4. 对应托管 proxy 页面实际存在且 registry/投影无阻塞漂移。

旧 `ingest/index.md` 行不满足上述规则。若用户希望接受旧资料，必须先通过 v0.3 migration
预览和确认生成 registry，不允许 Inventory 自行升级投影。

## Findings 与严重级别

| Finding | 级别 | 含义 |
|---|---|---|
| `missing-ingest-inventory` | WARN | 尚未建立基线，无法完成未摄入判断 |
| `invalid-ingest-inventory` | ERROR | JSON 损坏、schema 不支持或记录路径越界 |
| `inventory-path-collision` | ERROR | 两个普通路径在平台比较规则下映射为同一 casefold 键 |
| `inventory-scope-changed` | WARN | 当前扫描策略与基线策略不同，需要重新确认基线 |
| `uningested-source` | WARN | 新文件或 `discovered` 文件尚未摄入 |
| `stale-ingested-source` | WARN | 已摄入文件之后发生变化 |
| `inventory-scan-incomplete` | WARN | 权限或文件系统错误导致扫描不完整 |
| `sensitive-scope-change` | WARN | 敏感范围的数量或最新修改时间发生变化 |

现有 `missing-source-proxy` 等检查继续保留。processed source 指向的代理不存在时，继续按现有错误规则处理。

路径查找必须构建独立 casefold 索引，同时保留磁盘原始大小写。若多个原始路径映射为同一个键，
Comparator 不得任选其一，必须报告 `inventory-path-collision` 并停止这些记录的自动关联。

## 报告与降噪

文本报告：

- 按一级目录和 Finding 类型汇总；
- 每组最多展示 20 个普通文件示例；
- 明确显示剩余未展开数量；
- 敏感范围只显示代号、数量和变化时间；
- 扫描不完整时不得输出“未发现未摄入文档”之类的完整性结论。

JSON 报告：

- 保留全部非敏感文档 finding；
- 敏感范围仍只输出汇总；
- 保留确定性的 check、severity、相对路径、计数和消息字段；
- 不输出秘密值或候选正文。

## 评分

“Ingest traceability”维度调整为：

- 基线有效且无问题：20/20；
- 存在未摄入或过期文档：10/20；
- 缺少基线、范围变化或扫描不完整：5/20，并说明结论不完整；
- 基线损坏、路径冲突或已处理 source 缺少代理：0/20；
- 尚未开始 ingest 且候选扫描结果为空的新 Vault：`not-applicable`，不因空库扣分。

分数只用于方向性诊断，不应成为自动批量 ingest 的触发器。

## CLI 与协作流程

### 只读检查

```text
python scripts/llm_wiki.py inventory inspect --root <vault> --format text|json
python scripts/llm_wiki.py inventory inspect --root <vault> --verify-content --format text|json
```

目标 runtime 布局落地后，根目录 `scripts/llm_wiki.py` 必须只是兼容 shim，实际转发到
installable runtime 的权威 CLI；当前设计分支不把这一目标描述成已实现事实。
扫描、验证和比较不写入，Doctor 调用相同核心逻辑。

默认模式只比较 `size + mtime_ns`。若 fingerprint 变化，报告 `stale-ingested-source`。
只有用户显式指定 `--verify-content`，且 source registry 已有 checksum 时，才允许读取该文件计算
checksum：相同则本次检查消除 stale，不同则确认 stale。Doctor 默认健康检查不得隐式启用正文读取。

### 初始化基线

```text
python scripts/llm_wiki.py inventory initialize --root <vault>
python scripts/llm_wiki.py inventory initialize --root <vault> --confirm
```

无 `--confirm` 时只展示计划。写入计划必须列出范围、候选数量、registry 匹配数量、敏感汇总和目标文件。
该命令要求 v0.2 `.meta` 状态层已经存在；legacy Vault 必须先完成 v0.3 migration，Inventory 不负责创建或迁移 source/page registry。

自定义范围通过可重复参数传入：

```text
--include <vault-relative-glob>
--exclude <vault-relative-glob>
--sensitive-scope <alias>=<vault-relative-glob>
```

未提供参数时使用内置默认策略。glob 必须是 Vault 相对模式；绝对路径和 `..` 直接拒绝。

### 更新扫描范围

```text
python scripts/llm_wiki.py inventory configure --root <vault> [scope options]
python scripts/llm_wiki.py inventory configure --root <vault> [scope options] --confirm
```

默认只展示范围变化及新增、退出、进入敏感汇总模式的文档数量。确认后：

- 原范围内未变化的记录保持原状态；
- 新进入普通范围的文档以 `discovered` 加入；
- 离开范围的记录不再参与检查；
- 进入敏感范围的逐文件记录从普通清单移除，只保留汇总；
- 离开敏感范围并进入普通范围的文档以 `discovered` 加入，不继承推测状态。

Inventory 不提供 `mark-processed`。正式摄入路径必须通过 v0.2 `ingest apply` 在同一事务内更新
source/page registry、代理页、投影和审计。事务成功后，下一次比较自然推导为 processed。

### 明确忽略

```text
python scripts/llm_wiki.py inventory ignore \
  --root <vault> \
  --path <vault-relative-file-or-approved-folder> \
  --reason <short-reason> \
  --confirm
```

批量目录忽略必须在计划中显示影响数量，并再次确认。

### 解除忽略

```text
python scripts/llm_wiki.py inventory unignore \
  --root <vault> \
  --path <vault-relative-file-or-approved-folder> \
  --confirm
```

默认先展示将重新进入候选的文件数量。确认后 disposition 恢复为 `discovered`；若 source registry
已经存在有效 processed 证据，Doctor 仍按 registry 推导为 processed。

### Inventory 写入事务

`initialize`、`configure`、`ignore` 和 `unignore` 的确认写入都必须：

1. 获取 `.meta/lock.json` 独占锁；
2. 在锁内复核输入基线 checksum；
3. 在 `.meta/operations.json` 创建具有 idempotency key 的 operation；
4. 在同目录写临时文件并 flush/fsync（平台允许时）；
5. 原子替换 `.meta/inventory.json`；
6. 向 `.meta/change-log.jsonl` 追加完成或失败事件；
7. 更新/清理 operation 并释放自己的锁。

失败时不得把未完成结果表示为成功；Doctor 根据 operation、临时文件和 registry 报告恢复建议。

### 完整流程

```text
Doctor 发现未摄入/过期文档
  -> 用户选择范围
  -> Ingest 生成计划并确认
  -> ingest apply 在一个 operation 内更新 source/page registry 与代理页
  -> 从 registry/change log 重建 ingest/index.md、wiki/index.md 和 wiki/log.md 托管区
  -> Doctor 复查
```

“手动把文件放进 `raw/` 等待 Inventory/Ingest 发现”的旧工作流自 Phase 3.1 起废止。替代入口是直接把外部文件绝对路径交给 Ingest 生成 `archive-import` payload，由 Core 在确认后归档到 `raw/<source-id>/` 并登记 registry。`raw/` 中的未登记文件属于一致性异常，不是普通 ingest candidate。

如果 ingest 中途失败，source 不得进入 processed；Inventory 观察记录不承担事务回滚状态。

## 错误处理与安全

- JSON 损坏时不自动重建或覆盖，交给 Maintain 经确认处理。
- schema 版本高于当前支持版本时停止比较并报告错误。
- `.meta/sources.json` 或 `.meta/pages.json` 缺失时按 legacy/未完成状态层报告，不回退读取 Markdown 投影猜测 processed。
- 单个文件消失、被占用或权限不足时继续其余扫描，并报告扫描不完整。
- symlink/junction 默认跳过；不得通过路径规范化逃出 Vault。
- include/exclude 或支持扩展名变化后，先展示影响，再经确认更新基线。
- 普通路径使用 casefold 索引比较；冲突时停止关联并报告 `inventory-path-collision`。
- Doctor、`inventory inspect` 和所有无 `--confirm` 命令必须保持零写入。
- 敏感范围的文件名不得进入文本、JSON、日志或异常消息。
- 敏感范围首版不维护逐文件 disposition；如需处理具体文件，必须先由用户明确批准其离开汇总模式。
- checksum 复核只允许由显式 `--verify-content` 启用，不改变 Doctor 默认不读正文的安全承诺。

## 验收场景

1. 无基线时 Doctor 报告 `missing-ingest-inventory`，运行前后 Vault 文件状态不变。
2. `inventory initialize` 默认只显示计划，`--confirm` 才创建文件。
3. 没有 registry 摄入证据的初始文件保存为 `discovered` observation。
4. 基线后在普通 Vault 内容区新增支持文档报告 `uningested-source`；`raw/` 不进入普通 candidate 扫描，未登记 raw 文件报告 `unregistered-archive`。
5. registry 推导为 processed 且 fingerprint 未变化时不告警。
6. registry 推导为 processed 且 fingerprint 变化后报告 `stale-ingested-source`。
7. `ignored` 文件不再报告未摄入。
8. 敏感范围变化只报告汇总，所有输出均无文件名。
9. 默认排除目录和不支持扩展名不会成为候选。
10. 损坏或版本不支持的 JSON 报告 `invalid-ingest-inventory`，且不被覆盖。
11. 扫描不完整时报告原因，且不输出完整性结论。
12. Inventory 不提供 `mark-processed`；只有成功的 `ingest apply` 能使 Doctor 推导 processed。
13. 目录级 ingest 后新增文件仍会被发现。
14. 文本报告按目录汇总并限制示例，JSON 保留全部非敏感 finding。
15. 范围配置默认 dry-run；绝对路径、路径穿越或未确认的范围变更不得写入。
16. `unignore` 默认 dry-run，确认后文件重新进入候选；存在有效 registry 证据时仍推导为 processed。
17. 所有 Inventory 确认写入均产生 lock、operation 和 change-log 证据，并使用原子替换。
18. casefold 路径冲突产生 ERROR，不能自动选择记录。
19. 默认 fingerprint 变化产生 stale；显式 checksum 复核相同可在本次检查消除 stale。

## 测试计划

- 单元测试：路径规范化、casefold 索引与冲突、扩展名过滤、include/exclude、不可覆盖的 `raw/` 排除、
  `unregistered-archive` 分类、签名比较、registry 证据推导、disposition 流转。
- 安全测试：目录穿越、symlink/junction、敏感范围脱敏、损坏 JSON、未知 schema。
- CLI 测试：dry-run、`--confirm`、`unignore`、`--verify-content`、退出码、文本和 JSON 输出。
- Doctor 集成测试：Finding、评分和报告聚合。
- Registry 集成测试：只有完整 source/page 证据才能推导 processed；Markdown 投影不能替代 registry。
- 写入协议测试：锁冲突、原子替换失败、operation 恢复、change-log 审计和幂等重试。
- 临时 Vault 端到端测试：初始化、新增、修改、忽略、目录级 ingest 后新增、再次检查。
- 真实 Vault 只读验证：先运行 Doctor；未经用户确认不得初始化基线。

## 预计代码与文档范围

新增：

- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/inventory.py`
- Inventory Core 单元测试和 CLI 测试。

修改：

- `skills/obsidian-wiki-runtime/scripts/llm_wiki.py`
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor.py`
- runtime state writer、schema 和 operation 类型
- 根目录 `scripts/llm_wiki.py` 与 `scripts/obsidian_wiki_doctor.py` 仅保留兼容转发，不复制实现
- `tests/test_obsidian_wiki_doctor.py`
- `skills/obsidian-wiki-doctor/` 的检查与报告说明
- `skills/obsidian-wiki-ingest/` 的完成后状态更新说明
- `skills/obsidian-wiki-maintain/` 的基线初始化和忽略策略
- `docs/architecture.md`
- `docs/workflow.md`
- 相关中文 README 或手工验证指南

## 实施边界

本设计是 v0.3 `inventory` 命令的正式规格，同时覆盖 init/ingest 候选盘点和 Doctor 未摄入检查。

实施采用依赖方案 A：

1. v0.2 Phase 2 的 `.meta` schema、source/page registry、锁、operation、原子写和 change log 已合入；
2. v0.2 Phase 3 的 `ingest apply` 已成为 processed 的唯一正式写入路径；
3. installable runtime 的权威源码布局已经提交到本仓库，根目录脚本只作为 shim；
4. 上述前置满足后，才为本规格编写并执行实施计划。

本设计分支创建时的仓库基线尚未包含第 3 项所述 runtime 源码目录；本机已安装 skill 缓存不是
仓库事实，实施不得直接修改或反向复制缓存。若项目最终决定保留根目录 Core，必须先做一次明确的
架构决策并同步本规格，不能维护两份权威实现。

本规格只批准设计修订，不批准立即修改生产代码。实施前还需锁定测试顺序、活动文件范围和与
现有 WikiLink 分支的隔离方式。
