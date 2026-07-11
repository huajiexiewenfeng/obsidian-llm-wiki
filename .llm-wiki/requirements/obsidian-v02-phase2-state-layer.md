# Change Brief: obsidian-v02-phase2-state-layer

## 摘要

- title: Obsidian LLM Wiki v0.2 Phase 2 状态契约与安全写入
- status: planned
- flow_id: obsidian-v02-phase2-state-layer

## 来源

- 设计：`docs/superpowers/specs/2026-07-10-obsidian-llm-wiki-v0.2-design.md`
- 前置实现：v0.2 Phase 1 Root Resolver 与 canonical CLI
- 后续依赖：v0.2 Phase 3 `ingest apply`、v0.3 Inventory

## 范围

- active: `.meta` schema、source/page/operation registry 契约、state init、锁、原子写、change log、fingerprint/checksum、托管 marker 纯函数及测试和文档
- reference-only: Root Resolver、现有 CLI、现有 Doctor、v0.2 Phase 3/4 数据消费方式
- excluded: `ingest apply`、`page apply`、`projection rebuild` 公开命令、Doctor 迁移、Inventory、自动 migration、WikiLink 修复

## 验收

- `state init` 默认 dry-run，显式 `--confirm` 后才创建 `.meta`。
- 重复初始化幂等，只补缺失且有效的状态文件，不覆盖无效或未知 schema。
- source/page/operation snapshot 具有明确 schema、唯一键校验和确定性 JSON 编码。
- 所有 control-center 写入通过独占锁、checksum 复核、同目录临时文件和原子替换。
- change log sequence 单调递增，operation 状态可诊断，锁只能由所有者释放。
- fingerprint 使用 `size + mtime_ns`，内容 checksum 使用流式 SHA-256。
- frontmatter、managed body 和 projection marker 冲突时停止；用户区域保持字节级内容不变。
- Windows 与 Ubuntu 兼容规则由标准库单元测试覆盖。
- Phase 3/4/Inventory 不在本 Flow 中提前实现。

## 计划

- active_plan: `docs/superpowers/plans/2026-07-11-obsidian-llm-wiki-v0.2-phase2-state-layer-implementation-plan.md`
- status: candidate
- evidence: 已完成逐测试、逐提交计划，待用户选择执行方式

## 外部依赖

- project-id: none
- edge_id: none
- dependency_type: none
- required_contract: none
- evidence: none
- verification_status: source-verified
- derived_staleness: fresh
- impact_on_change: none
- fallback_or_handoff: none

## Flow Record

| Step | Status | Evidence | Updated |
|---|---|---|---|
| source | done | v0.2 可靠性设计与 Phase 1 实现 | 2026-07-11 |
| design | done | `docs/superpowers/specs/2026-07-10-obsidian-llm-wiki-v0.2-design.md` | 2026-07-11 |
| plan | done | `docs/superpowers/plans/2026-07-11-obsidian-llm-wiki-v0.2-phase2-state-layer-implementation-plan.md` | 2026-07-11 |
| development | pending |  |  |
| testing | pending |  |  |
| archive | pending |  |  |

## 待确认问题

- 实施计划完成后由用户选择 Subagent-Driven 或 Inline Execution。

## 说明

- 当前基线使用 bundled Python 3.12.13 运行 50 个测试全部通过。
- 当前仓库权威实现仍位于根目录 `scripts/`；runtime 打包不在本 Phase 2 计划中处理。
- Inventory 设计必须等待本 Flow 和 Phase 3 的状态写入路径完成。
