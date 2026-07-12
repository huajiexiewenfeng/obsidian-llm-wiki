# Change Brief: obsidian-v02-phase31-archive-import

## 摘要

- title: Obsidian LLM Wiki v0.2 Phase 3.1 Archive Import
- status: design-confirmed
- flow_id: obsidian-v02-phase31-archive-import
- parent_flow_id: obsidian-v02-phase3-ingest-projection

## 来源

- v0.2 总体设计：`docs/superpowers/specs/2026-07-10-obsidian-llm-wiki-v0.2-design.md`
- Phase 3 设计：`docs/superpowers/specs/2026-07-11-obsidian-llm-wiki-v0.2-phase3-ingest-projection-design.md`
- Phase 3.1 设计：`docs/superpowers/specs/2026-07-12-obsidian-llm-wiki-v0.2-phase31-archive-import-design.md`
- 实施基线：`main@2414f68`

## 目标与原因

Phase 3 已提供确定性 ingest/page/projection transaction，但暂时拒绝公开过的 `archive-import`。本子 Flow 在 v0.2 tag 前恢复该能力：把已确认外部文件安全复制为不可变 `raw/` 权威副本，并与 registry、页面、投影、operation 和 change log 使用同一次确认及恢复模型。

## 范围

- active: archive payload/planner、稳定身份与目标路径、锁外流式 staging、禁止覆盖的原子发布、ingest coordinator、SourceRecord 可选 archive 字段、Doctor archive consistency、Skill/CLI/测试/文档
- read-only: Phase 2 writer/state 契约、Phase 3 page/projection/CAS/idempotency、Phase 4 Finding/score/redaction 契约
- candidate: Maintain 结构化 archive 修复、v0.3 Inventory 实现、多版本 archive registry
- excluded: Vault 新文件自动发现、批量 source、外部原文件删除/移动、归档覆盖、自动 migration、模型总结、自动清理

## 已确认决策

- `raw/` 副本是权威来源，外部路径保留 provenance。
- 目标为 `raw/<source-id>/<safe-original-filename>`，由 Core 推导。
- 复用 `ingest apply` 和现有 payload/confirm/plan-checksum 协议。
- 归档不可变：相同 checksum 幂等，不同 checksum 严格冲突。
- origin 内容变化需要显式 `new-source`。
- 大文件锁外流式 staging，锁内重新校验和原子 no-replace 发布。
- `raw/` 是 Core 管理区；未来 Inventory 排除，未登记文件单独报告。
- SourceRecord 使用可选 `archive_relative_path`，schema version 1 和旧记录保持兼容。
- Doctor 只读且不改变 Finding 六字段、score version 1 或评分权重。

## 验收标准

- `archive-import` 可完成 dry-run、确认执行和幂等重跑。
- dry-run 全树零写入；confirm 不持锁复制大文件。
- 不允许 payload 指定任意 archive target 或 overwrite。
- 来源、staging 和归档 checksum 必须一致。
- 目标不同 checksum 时绝不覆盖或自动改名。
- 中断状态可诊断且相同 payload 可恢复。
- Doctor 报告 missing、mismatched、temp 和 unregistered archive。
- `raw/` Inventory 排除契约有共享 helper 与测试。
- 完整 unittest、CLI/E2E、failure injection、read-only 和 redaction 回归通过。

## 外部依赖

- project-id: none
- edge_id: none
- dependency_type: none
- verification_status: source-verified-local
- impact_on_change: none

## Flow Record

| Step | Status | Evidence | Updated |
|---|---|---|---|
| source | done | v0.2 总体设计、Phase 3 archive delivery boundary、Phase 4 handoff | 2026-07-12 |
| design | done | 用户授权按推荐方案定稿；正式设计已写入仓库 | 2026-07-12 |
| plan | pending | TDD 实施计划尚未编写 | 2026-07-12 |
| development | pending | 尚未开始 | 2026-07-12 |
| testing | baseline-passed-agent-local | 187 passed, 2 existing skips at `main@2414f68` | 2026-07-12 |
| archive | pending | 实施完成后生成 handoff | 2026-07-12 |

## 下一 Gate

评审书面设计，然后使用 writing-plans 编写 Phase 3.1 TDD 实施计划；计划确认前不修改 production code。
