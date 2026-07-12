# Obsidian LLM Wiki v0.2 Phase 3.1 Archive Import 设计

## 状态与基线

- 状态：confirmed
- Flow ID：`obsidian-v02-phase31-archive-import`
- Parent Flow：`obsidian-v02-phase3-ingest-projection`
- 实施基线：`main@2414f68`
- 前置能力：Phase 3 ingest/page/projection transaction、Phase 4 Doctor state consistency
- 发布约束：必须在 v0.2 tag 前交付；不推迟到 v0.3 Inventory

## 背景

Phase 3 已提供单 source 的确定性 `ingest apply`，但有意对 `archive-import` 返回结构化 `unsupported-mode`。可靠归档不能退回由 Skill 直接复制文件，因为它必须同时解决二进制流式复制、来源身份、目标冲突、原子发布、中断恢复、Doctor 一致性以及未来 Inventory 去重。

本子 Flow 恢复已经公开的 `archive-import` 能力，并把它纳入 Phase 3 的预览、确认、operation、registry、page 和 projection 契约。

## 目标

用户确认一个外部普通文件后，Core 能在一次 `ingest apply` 中：

1. 把文件安全归档到 control center 的 `raw/`；
2. 使归档副本成为后续读取和一致性检查的权威来源；
3. 保留外部原路径及归档时 fingerprint 作为 provenance；
4. 更新 source/page registries、托管页面、投影、operation 和 change log；
5. 在重复执行、中断和局部失败后确定性恢复；
6. 阻止未来 Inventory 把已归档副本再次识别为新来源。

## 非目标

- 不自动发现 Vault 新文档；该能力属于 v0.3 Inventory。
- 不支持一个 payload 归档多个 source。
- 不删除、移动、重命名或修改外部原文件。
- 不覆盖已经发布的归档副本。
- 不建立多版本 archive registry 或历史二进制版本链。
- 不实现自动 migration、自动清理或无确认修复。
- 不在 Core 内调用模型、生成摘要或决定分类。
- 不改变 Phase 3 的页面 takeover、checksum CAS、projection 或退出码全局契约。

## 方案比较

### 方案 A：扩展现有 `ingest apply`（采用）

`source.mode = archive-import` 启用归档 planner 和 confirmed staging；归档发布与 source/page/projection 更新共用同一个 operation。它保持已有公开 CLI、一次预览和一次确认，同时复用 Phase 3 的失败恢复模型。

### 方案 B：新增独立 `archive apply`

归档和 ingest 分两次操作。实现边界较清楚，但用户必须确认两次，并产生“文件已复制但 registry/page 未完成”的常态中间状态，因此不采用。

### 方案 C：独立多版本 Archive 子系统

为每个 source 保存多份历史二进制和 current pointer。历史能力最完整，但需要新 registry、迁移、版本投影和更多 Doctor 规则，超出 v0.2 Phase 3.1，因此不采用。

## 已确认决策

1. 归档成功后，`raw/` 副本是权威来源，外部路径只是 provenance。
2. 目标路径由 Core 推导为 `raw/<source-id>/<safe-original-filename>`，payload 不指定目标。
3. 继续使用 `ingest apply`、相同 payload、`--confirm` 和 `--plan-checksum`。
4. 归档副本不可变：相同 checksum 幂等；不同 checksum 冲突，绝不覆盖。
5. 同一 origin 内容变化必须显式选择 `new-source`，产生新 source ID 和新目录。
6. 大文件在 Vault 锁外流式 staging；锁内重新校验后才进行禁止覆盖的原子发布和状态提交。
7. `raw/` 是 Core 管理区；Inventory 不把其中内容作为普通新来源。
8. `SourceRecord` 使用可选 archive 字段保持 schema version 1 向后兼容，不要求 migration。

## CLI 与 payload

CLI 不新增顶层命令：

```powershell
python obsidian_wiki_runtime.py ingest apply --root <vault> --payload <file|->
python obsidian_wiki_runtime.py ingest apply --root <vault> --payload <file|-> --confirm --plan-checksum <checksum>
```

Archive payload 继续使用 Phase 3 schema：

```json
{
  "schema_version": 1,
  "source": {
    "path": "D:/approved/document.pdf",
    "source_type": "pdf",
    "mode": "archive-import",
    "fingerprint": {
      "size": 1048576,
      "mtime_ns": 1783828800000000000
    },
    "checksum": "sha256:...",
    "sensitivity": "normal",
    "move_resolution": null
  },
  "pages": [
    {
      "role": "source-proxy",
      "page_type": "source",
      "path": "wiki/sources/document.md",
      "managed_body": "...",
      "expected_managed_checksum": null,
      "takeover": false
    }
  ],
  "projection_takeovers": []
}
```

约束：

- `archive-import` 要求 checksum 非空，且来源必须是单个可读普通文件。
- payload 不增加 `archive_path`、`target`、`overwrite` 或全局 takeover 字段。
- 归档目标、source ID 和安全文件名全部由 Core 推导。
- file 和 stdin payload 使用相同解析、规范化和幂等逻辑。
- dry-run 与错误 JSON 不返回文件正文或 `managed_body`。

## SourceRecord 契约

保持 state schema version 1，只增加可选字段：

```json
{
  "source_id": "src-...",
  "display_path": "D:/approved/document.pdf",
  "canonical_path": "D:/approved/document.pdf",
  "source_type": "pdf",
  "mode": "archive-import",
  "status": "processed",
  "fingerprint": {
    "size": 1048576,
    "mtime_ns": 1783828800000000000
  },
  "checksum": "sha256:...",
  "proxy_page_id": "page-...",
  "sensitivity": "normal",
  "last_verified_at": "2026-07-12T00:00:00Z",
  "revision": 1,
  "archive_relative_path": "raw/src-.../document.pdf"
}
```

字段语义：

- `display_path`、`canonical_path`、`fingerprint` 保留归档时的外部 origin 身份和快照，保证现有来源匹配逻辑可向后兼容。
- `archive_relative_path` 是 control-center-relative 路径；仅 `archive-import` 要求非空。
- 对 `archive-import`，有效权威路径为 `<control-center>/<archive_relative_path>`，而不是外部 `canonical_path`。
- `checksum` 是内容身份；提交时外部来源、staging 文件和已发布归档必须三者一致。
- 非 archive source 的 `archive_relative_path` 必须为 null 或缺失。
- 旧记录缺少该字段时仍按原 schema 正常加载。

Core 提供单一 `resolve_authoritative_source_path()`，避免 Skill、Doctor、Inventory 和 projection 各自解释 `canonical_path`。

## Source ID 与归档路径

非 archive 模式保持 Phase 3 的现有 source ID 规则。新的 archive source 使用下列稳定 seed：

```text
archive\0<normalized-origin-canonical-path>\0<sha256-checksum>
```

这使同一外部路径的不同内容成为不同不可变 source。规则如下：

- 相同 origin、相同 checksum：复用同一 source ID。
- 相同 origin、不同 checksum：返回 `archive-content-changed`；只有 `move_resolution.action = new-source` 才创建新 source。
- 新 origin、checksum 与已有 source 相同：沿用 Phase 3 move candidate；用户选择 `rebind` 或 `new-source`。
- `rebind` 只更新 provenance 身份，归档字节和 archive path 不变，并在 change log 保留旧身份摘要。
- 对完全相同的 origin 和 checksum 使用 `new-source` 无意义，返回 validation error。

目标路径固定为：

```text
raw/<source-id>/<safe-original-filename>
```

文件名规则：

- 首选原始 basename，并执行 Unicode NFC 规范化。
- 路径分隔符、控制字符、Windows 保留字符、尾随点/空格和保留设备名使用确定性替换。
- 扩展名尽量保留；安全化后为空时使用 `source<original-extension>`。
- 规范化结果参与 plan checksum，并执行 case-fold 冲突检查。
- 外部目录结构和盘符绝不复制进 `raw/`，避免长路径和敏感路径泄露。

## Dry-run

未带 `--confirm` 时严格零写入，包括不创建 `raw/`、source 目录、staging 文件或 operation。

Planner 执行：

1. 解析 root 和 control center。
2. 校验来源存在、可读并且解析后是普通文件。
3. 校验 payload fingerprint 和流式 checksum。
4. 解析 registry 身份、move candidate 和显式 resolution。
5. 推导 source ID、安全文件名和 archive target。
6. 验证 `raw/` 目标保持在 control center 内，并拒绝 symlink/junction 越界。
7. 检查目标不存在、相同 checksum 可复用，或不同 checksum 冲突。
8. 检查当前可用空间并返回估算；确认执行仍会再次检查。
9. 规划 source/page/projection 变化和 expected checksums。
10. 返回确定性 `plan_checksum`、`confirmable` 和 `confirmation_required`。

公开 archive plan 至少包含：

```json
{
  "action": "archive-create",
  "target": "raw/src-.../document.pdf",
  "size": 1048576,
  "checksum": "sha256:...",
  "staging_required": true
}
```

## Confirmed staging

带 `--confirm` 后，Core 先执行锁外 staging：

1. 再次检查磁盘空间、来源 fingerprint 和目标父路径安全性。
2. 创建最终 source 目录；空目录属于 confirmed preparation，不属于 dry-run。
3. 在目标同目录创建 `.<filename>.<random>.tmp`。
4. 使用固定大小 chunk 流式复制，同时计算 SHA-256，不把完整文件载入内存。
5. 对已打开来源执行复制前后 `fstat`，并再次检查路径 stat，检测复制期间替换或变化。
6. 实际 checksum 必须与 payload checksum 一致。
7. flush 文件、执行 `fsync`，关闭后再进入锁内提交。
8. 可预期失败时尽力删除 staging；进程崩溃遗留交给 Doctor/Maintain。

Staging 文件不参与普通 source discovery，也不改变已确认 plan 的业务目标。

## 锁内提交与发布顺序

Staging 完成后获取 Phase 2 Vault 写锁：

1. 重新加载 registries、operations、change log 和目标文件状态。
2. 重新校验外部来源 fingerprint、staging checksum、目标状态和 confirmed plan checksum。
3. 创建或恢复 running operation。
4. 写 source registry：目标 source 为 `pending`。
5. 原子发布 staging 为 archive target。
6. 写托管页面。
7. 写 page registry。
8. 生成并写三个确定性投影。
9. 写 source registry：目标 source 为 `processed`。
10. 追加 `ingest-apply` change event，其中包含 archive target 和 checksum 摘要。
11. 将 operation 标记为 `completed`。

Core 不在持锁期间重新读取或复制外部大文件；锁内只做 stat/CAS、归档发布和已有小型状态写入。

## 禁止覆盖的原子发布

归档发布必须同时满足“同文件系统原子可见”和“目标存在时不覆盖”：

- 目标不存在时，优先使用同目录 hard-link promotion：对 staging 建立目标 hard link，成功后删除 staging 名称。
- hard-link create 在目标已存在时必须失败，不得降级为覆盖式 `replace`。
- 文件系统不支持安全 no-replace 原子发布时返回 `atomic-publish-unsupported`；不使用非原子复制作为 fallback。
- 发布后 fsync 目标父目录（平台支持时）。
- 目标存在且 checksum 相同：删除 staging 并执行 `archive-reuse`。
- 目标存在且 checksum 不同：保留目标，删除 staging，返回 `archive-target-conflict`。

`raw/` 是 Core 管理区，但实现仍不能依赖“用户不会修改”来允许覆盖。

## 幂等与冲突

Archive action：

| 条件 | Action / Check | Confirmable |
|---|---|---:|
| 新 source、目标不存在 | `archive-create` | yes |
| registry 和目标存在且 checksum 相同 | `archive-reuse` / unchanged | yes |
| 目标存在且 checksum 不同 | `archive-target-conflict` | no |
| 相同 origin 出现新 checksum、未显式 resolution | `archive-content-changed` | no |
| 来源在 dry-run 后或 staging 中变化 | `source-changed` | no |
| 空间不足 | `insufficient-space` | no |
| 无安全原子发布能力 | `atomic-publish-unsupported` | no |
| raw 路径或父目录越界 | `unsafe-archive-path` | no |

Idempotency key 继续由规范化 payload 和已解析身份生成。成功事件存在时，相同 payload 返回既有 operation 结果，不再次复制或追加事件。

## 中断与恢复

不回滚已经安全发布的不可变归档文件：

- staging 前失败：无持久变化。
- staging 中可预期失败：尽力删除 temp；无 registry 变化。
- 进程在 staging 中崩溃：temp 可能遗留；Doctor 报告，Maintain 经确认清理。
- source 已为 pending、archive 尚未发布：operation 标记 failed；相同 payload 可重跑恢复。
- archive 已发布、后续 page/projection 失败：保留 archive 和 failed/pending 诊断状态；重跑识别相同 checksum 并继续。
- operation 已完成：相同 idempotency key 返回 completed/idempotent。

失败处理继续遵循 Phase 3：记录当前 step、completed targets、结构化 error 和 failed source 状态，不伪装成全局回滚事务。

## Doctor 一致性

Phase 3.1 扩展 Phase 4 的只读状态检查：

- `archive-import` source 缺少 `archive_relative_path`；
- archive path 不在 `raw/<source-id>/`；
- archive canonical resolution 越界或经过不安全链接；
- registry 指向的 archive 不存在；
- archive checksum 与 source checksum 不一致；
- 非 archive source 意外声明 archive path；
- running/failed operation 与 archive target 状态矛盾；
- `raw/` 下遗留已知原子 staging temp；
- `raw/` 下存在 registry 未登记普通文件：`unregistered-archive`。

Doctor 只读、零修复；Finding 六字段、score version 1 和现有评分权重保持不变。Archive findings 暂不改变评分，除非后续独立评分版本明确升级。

## Maintain 边界

Phase 3.1 只定义修复协议，不自动执行：

- orphan staging temp 可生成删除计划；
- unregistered archive 可生成“登记、移出 raw 或删除”的候选计划；
- missing/mismatched archive 不从外部 origin 静默重建；
- 所有删除、重绑或重新归档都需要用户确认。

## Inventory 契约

`raw/` 是保留的 Core 管理区。v0.3 Inventory 必须：

- 从普通新来源发现范围中排除整个 `raw/` 子树；
- 不把 registry 已登记归档副本重新识别为 candidate；
- 将未登记 raw 文件报告为 `unregistered-archive`，而不是普通未 ingest 文档；
- 继续扫描 Vault 其他用户内容目录以发现未 ingest 文档。

Phase 3.1 不实现 Inventory 命令，但用共享路径分类 helper 和契约测试固定该行为。

## 安全与隐私

- 外部 source path 是只读授权范围，不会被当作 Wiki root。
- 不删除、移动或修改外部原文件。
- 所有归档写目标必须位于 control center 的 `raw/`。
- 检查 symlink、junction、reparse point 和 case-fold 冲突。
- 不接受任意目标路径、overwrite、blind takeover 或无 checksum 归档。
- JSON、错误和 change log 不包含二进制内容或 managed body。
- 继续使用 Phase 4 redaction 处理 AK、SK、token 和 credential-like 数据。
- sensitivity 继续沿用 Phase 3 枚举和投影规则。

## 代码边界

建议新增：

- `llm_wiki_core/archive.py`：纯路径/identity planner、流式 staging、no-replace publication primitive。

建议修改：

- `state.py`：可选 `archive_relative_path` 与权威路径解析 helper。
- `ingest.py`：接受 `archive-import`，编排 staging 和已有 ingest transaction。
- `doctor_state.py`：archive consistency 和 bounded raw scan。
- CLI/launcher：保持现有命令，只扩展结构化 plan/result。
- Ingest、Doctor、Maintain Skills：同步确认、报告和修复边界。

`writer.py` 继续承载通用锁、文本/JSON 原子写和 operation primitives；二进制 archive primitive 不塞入通用文本 writer，除非实施中证明存在清晰复用边界。

## 测试策略

### Schema 与身份

- 旧 SourceRecord 无 archive 字段仍可加载。
- archive/non-archive 字段组合校验。
- 稳定 source ID、origin 内容变化和 rebind/new-source。
- Unicode、保留名、大小写和安全文件名。

### Planner 与 dry-run

- dry-run 全树快照零写入。
- 目标 create/reuse/conflict 分类。
- checksum、fingerprint、空间和路径安全诊断。
- 相同输入产生相同 plan checksum。

### 二进制 staging/publish

- 多 chunk 大文件，证明不整文件载入内存。
- 复制期间来源变化。
- checksum mismatch、空间不足和 I/O failure。
- no-replace 发布、目标竞争和 unsupported filesystem。
- temp cleanup、fsync 和同目录约束。

### Coordinator 与恢复

- 从 source pending、archive publish、page write、registry write、projection、event 和 completion 各步骤注入失败。
- 已发布 archive 后重跑恢复。
- completed operation 幂等返回且不重复 change event。
- 不持锁复制外部大文件。

### Doctor 与未来 Inventory

- missing/mismatched/unregistered archive。
- orphan archive temp。
- raw 全子树排除契约。
- Doctor 完整树只读快照。

### CLI 与 E2E

- file/stdin payload 等价。
- Unicode 文件名和二进制 PDF/Word 样本。
- dry-run、confirmation-required、confirmed apply、idempotent rerun。
- 根 launcher 与 canonical runtime 等价。
- 完整 unittest、`git diff --check` 和敏感信息回归。

## 验收标准

- `archive-import` 不再返回 `unsupported-mode`，其他未知 mode 仍被拒绝。
- dry-run 严格零写入并返回确定性归档计划。
- confirmed apply 流式复制，不在持锁期间读取外部大文件。
- 归档目标不同 checksum 时绝不覆盖或自动改名。
- SourceRecord 同时保留 origin provenance 和权威 archive path，旧记录无需迁移。
- 中断后 Doctor 能诊断，重复 apply 能按相同 payload 恢复或幂等完成。
- Doctor 不改变 Finding JSON、score version 1 或只读保证。
- `raw/` 排除契约能阻止未来 Inventory 重复 ingest。
- 完整测试通过，文档与三个 Obsidian Skills 行为一致。

## 实施前 Gate

本设计确认后，下一步单独编写 TDD 实施计划。实施不得在未写计划、未建立失败注入矩阵和未验证 baseline 的情况下开始。
