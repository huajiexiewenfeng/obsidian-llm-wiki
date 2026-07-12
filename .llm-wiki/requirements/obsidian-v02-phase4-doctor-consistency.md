# Change Brief: obsidian-v02-phase4-doctor-consistency

## 摘要

- title: Obsidian LLM Wiki v0.2 Phase 4 Doctor 状态一致性
- status: designed
- flow_id: obsidian-v02-phase4-doctor-consistency

## 来源

- 总体设计：`docs/superpowers/specs/2026-07-10-obsidian-llm-wiki-v0.2-design.md`
- Phase 3 设计：`docs/superpowers/specs/2026-07-11-obsidian-llm-wiki-v0.2-phase3-ingest-projection-design.md`
- Phase 4 设计：`docs/superpowers/specs/2026-07-12-obsidian-llm-wiki-v0.2-phase4-doctor-consistency-design.md`
- 前置 Flow：`obsidian-v02-phase3-ingest-projection`
- 实施基线：本地 `main@e1f270d`

## 目标与原因

Phase 3 已能生成 registry、托管页面、确定性投影和可诊断 operation，但现有 Doctor 仍主要读取旧 Markdown 信号。Phase 4 增加只读状态一致性检查，使中断、人工修改、投影漂移和锁/temp 遗留能够被确定性发现并交给 Maintain 处理。

## 范围

- active: `doctor_state.py`、公共托管区 inspector、Doctor Finding 适配、状态/页面/投影/operation/lock/temp 测试、Skill/文档
- read-only: Phase 3 registry schema、projection renderer、writer lock classifier、现有 Root Resolver 与评分契约
- candidate: Maintain 结构化修复、评分 v2、archive consistency
- excluded: 自动修复、清锁、Inventory、archive-import、migration、Context Pack、全 Vault 扫描

## 验收标准

- 健康 Phase 3 Vault 无新 ERROR/WARN。
- `.meta` absent 兼容，partial/invalid 独立诊断。
- change-log 中间损坏为 ERROR；仅尾行撕裂为 WARN，并继续使用合法事件前缀检查。
- page/frontmatter/checksum、三个投影、operation/event/lock/temp 均有确定性检查。
- INFO finding 正常渲染且不影响 `--fail-on error`；同一 failed ingest 根因不重复产生 pending source 告警。
- 扫描不离开 control center，Doctor 严格零写入。
- Finding 六字段、score version 1、五维权重和现有 CLI/退出码不变。
- 完整 unittest、只读快照、redaction 和 runtime packaging 回归通过。

## 已确认决策

- 一致性 findings 不改变评分。
- running operation 与 lock 联合判断。
- 扫描限制在 `.meta/`、`wiki/`、`ingest/`。
- Finding JSON 不扩字段，恢复建议写入 `hint`。
- 使用独立只读 `llm_wiki_core/doctor_state.py`。
- 托管页/投影 inspector 由 Page planner 与 Doctor 共用。
- `projection-rebuild` 按 Phase 3 明文契约不追加 change event，也不要求 completion event 审计。
- Doctor 对 torn change-log tail 使用合法前缀继续检查，修复仍交给 Maintain 并要求用户确认。

## 验证计划

- `tests/test_llm_wiki_doctor_state.py` 覆盖全部状态检查与错误隔离。
- `tests/test_obsidian_wiki_doctor.py` 覆盖 CLI/Finding/score/只读兼容。
- 根 launcher 与 canonical runtime 等价。
- 完整 unittest、`git diff --check` 与只读 API 静态搜索。

## 外部依赖

- project-id: none
- edge_id: none
- dependency_type: none
- verification_status: source-verified-local
- impact_on_change: none

## Flow Record

| Step | Status | Evidence | Updated |
|---|---|---|---|
| source | done | v0.2 总体设计、Phase 3 设计与 handoff | 2026-07-12 |
| design | done | 对话四部分设计确认；书面设计已生成并按外部评审的四项问题修订 | 2026-07-12 |
| plan | done | `docs/superpowers/plans/2026-07-12-obsidian-llm-wiki-v0.2-phase4-doctor-consistency-implementation-plan.md` | 2026-07-12 |
| development | pending |  |  |
| testing | pending |  |  |
| archive | pending |  |  |

## 待确认问题

- 设计与实施计划均已完成；下一 gate 为选择执行方式并开始 Task 1。
