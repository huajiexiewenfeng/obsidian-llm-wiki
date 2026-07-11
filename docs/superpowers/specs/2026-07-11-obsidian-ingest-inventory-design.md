# Obsidian Vault 未摄入文档发现设计

日期：2026-07-11

状态：已批准，待用户审阅书面规格

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
- 默认排除系统目录、控制中心、依赖目录、缓存和构建产物。
- 敏感目录只报告目录级汇总，不展示文件名，不读取正文。
- 使用持久化扫描基线；目录级 ingest 只覆盖确认时的文件快照，后续新增文件仍会被发现。
- Doctor 严格只读；Ingest/Maintain 仅在用户确认后写入基线。
- 首版检测新增文件和已摄入后变更，不检测删除与重命名。
- 默认扫描 `.md`、`.markdown`、`.txt`、`.csv`、`.pdf`、`.docx`、`.xlsx`、`.xls`。
- 没有基线时不静默接受现状，而是报告 `missing-ingest-inventory`。
- `discovered` 不等于 `processed`；只有摄入证据或明确忽略才能消除未摄入告警。
- 使用元数据签名，不读取正文计算哈希。

## 目标

1. 发现 Vault 中新增但尚未 ingest 的支持文档。
2. 发现已经 ingest、此后又发生变化的文档。
3. 保持 Doctor 的只读边界。
4. 让 Doctor、Ingest、Maintain 使用同一套范围、扫描和比较规则。
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

## 总体架构

新增共享的 `Inventory Core`：

```text
Vault 文件元数据
    -> InventoryScopePolicy
    -> InventoryScanner
    -> 当前文件观察结果
    -> InventoryComparator <- ingest/inventory.json
    -> Doctor Findings
```

### InventoryScopePolicy

负责扫描边界和文件类型：

- 默认 include：Vault 内全部相对路径。
- 默认 exclude：`.git/`、`.obsidian/`、`.agents/`、`.codex/`、
  `node_modules/`、常见缓存和构建目录、`00-知识库中控/`。
- 支持用户确认的 include/exclude 覆盖。
- 支持用户确认的敏感范围及其报告代号。
- 只接受已配置的支持扩展名。

策略本身写入基线。Doctor 比较当前策略与基线策略；策略变化后不得静默沿用旧基线。

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
00-知识库中控/ingest/inventory.json
```

Doctor 只获得读取接口。写入接口只能由显式带 `--confirm` 的 Inventory 命令调用，供
Ingest/Maintain 在已确认流程中使用。

### InventoryComparator

比较当前观察结果、基线记录和摄入证据：

- 当前存在、基线无记录：`uningested-source`；
- 基线状态为 `discovered`：`uningested-source`；
- 基线状态为 `processed` 且元数据签名变化：`stale-ingested-source`；
- 基线状态为 `ignored`：不报告未摄入；
- 基线缺失：`missing-ingest-inventory`；
- 基线不可解析或不安全：`invalid-ingest-inventory`。

### 技能边界

- Doctor：扫描、比较、评分、报告，绝不写入。
- Ingest：完成已确认的 ingest 后，将对应快照标记为 `processed`。
- Maintain：经确认初始化基线、调整范围或标记 `ignored`。
- Query：不直接依赖 Inventory Core。

## 基线数据模型

Schema v1：

```json
{
  "schema_version": 1,
  "scope": {
    "include": ["**/*"],
    "exclude": [
      ".git/**",
      ".obsidian/**",
      ".agents/**",
      ".codex/**",
      "00-知识库中控/**"
    ],
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
      "state": "discovered",
      "size": 1234,
      "mtime_ns": 1780000000000,
      "processed_signature": null,
      "ingest_entry": null,
      "ignore_reason": null
    }
  },
  "sensitive_scopes": {
    "sensitive-1": {
      "document_count": 12,
      "latest_mtime_ns": 1780000000000
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
- `processed_signature` 为对象或 `null`；对象保存 ingest 成功时的 `size` 与 `mtime_ns`。
- `ingest_entry` 使用控制中心相对的 Wiki 代理路径，不使用绝对路径。
- `ignored` 必须带简短的 `ignore_reason`，且原因不得包含敏感值。

## 状态模型

持久状态只有：

- `discovered`：已发现但没有摄入证据；
- `processed`：已完成摄入并记录当时签名；
- `ignored`：用户明确决定不摄入。

`stale` 是 Doctor 根据当前元数据与 `processed_signature` 计算出的诊断状态，不写回 JSON。

```text
新文件
  -> discovered
  -> processed（ingest 成功）
  -> stale（Doctor 计算）
  -> processed（重新 ingest 后刷新签名）

discovered
  -> ignored（用户明确确认）
```

目录级 ingest 的语义：

- 只把该次已确认扫描中实际存在的支持文件快照标记为 `processed`；
- 这些记录可以共享同一个目录级 source proxy；
- 后续新增文件没有基线记录，仍报告 `uningested-source`；
- 初始化旧 Vault 时，不因存在一个目录级旧 ingest 行就推断当前全部后代都已处理；
- 旧记录只有在文件路径和 Wiki 入口都能可靠匹配时才自动标记 `processed`，否则保持 `discovered`。

旧记录的“可靠匹配”必须同时满足：

1. ingest 文档级记录能规范化为当前 Vault 中的同一个文件；
2. 记录包含明确的 Wiki 入口；
3. Wiki 入口能解析为实际存在的 source proxy；
4. 记录状态明确表示已完成，而不是待确认、仅计划或未深读。

目录级记录不满足逐文件可靠匹配。若用户希望接受一个旧目录批次，Maintain 必须先展示
将被标记的当前文件快照和数量，再通过单独确认写入。

## Findings 与严重级别

| Finding | 级别 | 含义 |
|---|---|---|
| `missing-ingest-inventory` | WARN | 尚未建立基线，无法完成未摄入判断 |
| `invalid-ingest-inventory` | ERROR | JSON 损坏、schema 不支持或记录路径越界 |
| `inventory-scope-changed` | WARN | 当前扫描策略与基线策略不同，需要重新确认基线 |
| `uningested-source` | WARN | 新文件或 `discovered` 文件尚未摄入 |
| `stale-ingested-source` | WARN | 已摄入文件之后发生变化 |
| `inventory-scan-incomplete` | WARN | 权限或文件系统错误导致扫描不完整 |
| `sensitive-scope-change` | WARN | 敏感范围的数量或最新修改时间发生变化 |

现有 `missing-source-proxy` 等检查继续保留。`processed` 记录指向的代理不存在时，继续按现有错误规则处理。

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
- 基线损坏或已处理记录缺少代理：0/20；
- 尚未开始 ingest 且候选扫描结果为空的新 Vault：`not-applicable`，不因空库扣分。

分数只用于方向性诊断，不应成为自动批量 ingest 的触发器。

## CLI 与协作流程

### 只读检查

```text
python scripts/llm_wiki.py inventory inspect --root <vault> --format text|json
```

扫描、验证和比较，不写入。Doctor 调用相同核心逻辑。

### 初始化基线

```text
python scripts/llm_wiki.py inventory initialize --root <vault>
python scripts/llm_wiki.py inventory initialize --root <vault> --confirm
```

无 `--confirm` 时只展示计划。写入计划必须列出范围、候选数量、可靠匹配数量、敏感汇总和目标文件。

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

### 标记已处理

```text
python scripts/llm_wiki.py inventory mark-processed \
  --root <vault> \
  --path <vault-relative-file-or-approved-folder> \
  --ingest-entry <control-center-relative-proxy> \
  --confirm
```

文件模式只更新指定文件。目录模式必须额外显式指定递归，并且只更新当前已确认 ingest 批次中的文件快照。
尚未出现在基线中的新文件可以在成功 ingest 后由该命令直接创建为 `processed` 记录。

写入前验证：

- 源文件仍存在且位于 Vault；
- ingest 记录存在；
- Wiki 代理页存在；
- 路径未越界；
- 目录批次的文件清单与已确认计划一致。

任一验证失败都不写入 `processed`。

### 明确忽略

```text
python scripts/llm_wiki.py inventory ignore \
  --root <vault> \
  --path <vault-relative-file-or-approved-folder> \
  --reason <short-reason> \
  --confirm
```

批量目录忽略必须在计划中显示影响数量，并再次确认。

### 完整流程

```text
Doctor 发现未摄入/过期文档
  -> 用户选择范围
  -> Ingest 生成计划并确认
  -> 创建或更新 source proxy
  -> 更新 ingest/index.md、wiki/index.md、相关页面和 wiki/log.md
  -> mark-processed
  -> Doctor 复查
```

如果 ingest 中途失败，Inventory 状态保持 `discovered` 或原来的过期状态。

## 错误处理与安全

- JSON 损坏时不自动重建或覆盖，交给 Maintain 经确认处理。
- schema 版本高于当前支持版本时停止比较并报告错误。
- 单个文件消失、被占用或权限不足时继续其余扫描，并报告扫描不完整。
- symlink/junction 默认跳过；不得通过路径规范化逃出 Vault。
- include/exclude 或支持扩展名变化后，先展示影响，再经确认更新基线。
- Doctor、`inventory inspect` 和所有无 `--confirm` 命令必须保持零写入。
- 敏感范围的文件名不得进入文本、JSON、日志或异常消息。
- 敏感范围首版不维护逐文件 `processed` 状态；如需处理具体文件，必须先由用户明确批准其离开汇总模式。

## 验收场景

1. 无基线时 Doctor 报告 `missing-ingest-inventory`，运行前后 Vault 文件状态不变。
2. `inventory initialize` 默认只显示计划，`--confirm` 才创建文件。
3. 没有可靠摄入证据的初始文件保存为 `discovered`。
4. 基线后新增支持文档报告 `uningested-source`。
5. `processed` 文件未变化时不告警。
6. `processed` 文件元数据变化后报告 `stale-ingested-source`。
7. `ignored` 文件不再报告未摄入。
8. 敏感范围变化只报告汇总，所有输出均无文件名。
9. 默认排除目录和不支持扩展名不会成为候选。
10. 损坏或版本不支持的 JSON 报告 `invalid-ingest-inventory`，且不被覆盖。
11. 扫描不完整时报告原因，且不输出完整性结论。
12. `mark-processed` 缺少 ingest 行、代理或确认参数时拒绝写入。
13. 目录级 ingest 后新增文件仍会被发现。
14. 文本报告按目录汇总并限制示例，JSON 保留全部非敏感 finding。
15. 范围配置默认 dry-run；绝对路径、路径穿越或未确认的范围变更不得写入。

## 测试计划

- 单元测试：路径规范化、扩展名过滤、include/exclude、签名比较、状态流转。
- 安全测试：目录穿越、symlink/junction、敏感范围脱敏、损坏 JSON、未知 schema。
- CLI 测试：dry-run、`--confirm`、退出码、文本和 JSON 输出。
- Doctor 集成测试：Finding、评分和报告聚合。
- Ingest/Maintain 集成测试：只有完整摄入证据才能进入 `processed`。
- 临时 Vault 端到端测试：初始化、新增、修改、忽略、目录级 ingest 后新增、再次检查。
- 真实 Vault 只读验证：先运行 Doctor；未经用户确认不得初始化基线。

## 预计代码与文档范围

新增：

- `scripts/llm_wiki_core/inventory.py`
- Inventory Core 单元测试和 CLI 测试。

修改：

- `scripts/llm_wiki.py`
- `scripts/obsidian_wiki_doctor.py`
- `tests/test_obsidian_wiki_doctor.py`
- `skills/obsidian-wiki-doctor/` 的检查与报告说明
- `skills/obsidian-wiki-ingest/` 的完成后状态更新说明
- `skills/obsidian-wiki-maintain/` 的基线初始化和忽略策略
- `docs/architecture.md`
- `docs/workflow.md`
- 相关中文 README 或手工验证指南

## 实施边界

本规格只批准设计，不批准立即修改生产代码。下一步必须先形成独立实施计划，并在实施前锁定测试顺序、活动文件范围和与现有 WikiLink 分支的隔离方式。
