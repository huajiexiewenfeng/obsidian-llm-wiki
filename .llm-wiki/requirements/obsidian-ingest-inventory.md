# Change Brief: obsidian-ingest-inventory

## 摘要

- title: 发现 Obsidian Vault 中未摄入或摄入后变更的文档
- status: ready
- flow_id: obsidian-ingest-inventory

## 来源

- 用户确认：当前 Vault 新增了大量未进入 Wiki 的文档，需要 Doctor 能发现。
- 用户评审：要求与 v0.2 `.meta` 单一事实源、写入事务和 runtime 布局对齐。
- 设计：`docs/superpowers/specs/2026-07-11-obsidian-ingest-inventory-design.md`
- 目标架构参考：`docs/superpowers/specs/2026-07-10-obsidian-llm-wiki-v0.2-design.md`
- 当前实现参考：`scripts/obsidian_wiki_doctor.py`
- 现有流程参考：`skills/obsidian-wiki-ingest/`、`skills/obsidian-wiki-maintain/`

## 范围

- active: v0.3 Inventory Core、Doctor inventory finding、Inventory CLI、事务写入接入及对应测试和文档
- reference-only: Root Resolver、`.meta/sources.json`、`.meta/pages.json`、state writer、`ingest apply`、Doctor 评分与报告模型
- excluded: WikiLink 解析、删除/重命名检测、默认正文读取、自动 ingest、Vault 外扫描

## 验收

- Doctor 能只读发现新增但未摄入的支持文档。
- Doctor 能发现已摄入后元数据发生变化的文档。
- Inventory 只持久化 `discovered`/`ignored`；`processed`/`stale` 只从 registry 与当前扫描推导。
- 敏感范围只输出目录级汇总，不输出文件名或正文。
- 所有写入命令默认 dry-run，必须显式 `--confirm`。
- 所有确认写入复用 lock、operation、原子替换和 change log 协议。
- 目录级 ingest 只覆盖确认时快照，后续新增文档仍会被发现。
- `00-知识库中控/raw/` 永久排除于普通候选扫描；未登记文件由 Doctor 报告 `unregistered-archive`。
- `unignore`、casefold 冲突和范围变更具有确定性行为。
- 损坏基线或不完整扫描不得产生误导性的健康结论。

## 实施依赖

- v0.2 Phase 2 `.meta` 状态层已合入并由测试覆盖。
- v0.2 Phase 3 `ingest apply` 已成为 processed 唯一写入路径，Phase 3.1 archive-import 已合入。
- installable runtime 权威源码布局已提交到仓库；已安装缓存不作为实现来源。
- 本能力按 v0.3 `inventory` 交付，不在旧投影证据模型上先行实现。

## 计划

- active_plan: `docs/superpowers/plans/2026-07-12-obsidian-v03-inventory-implementation-plan.md`
- status: confirmed
- evidence: 用户确认继续开发，Inventory 为当前最高优先级主线

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
| source | done | 用户需求与现有 Doctor/Maintain 行为 | 2026-07-11 |
| design | done | 用户确认的 `docs/superpowers/specs/2026-07-11-obsidian-ingest-inventory-design.md` | 2026-07-12 |
| plan | done | `docs/superpowers/plans/2026-07-12-obsidian-v03-inventory-implementation-plan.md` | 2026-07-12 |
| development | done | `codex/v03-inventory` commits through Inventory CLI, Doctor, skills, and E2E | 2026-07-12 |
| testing | done | 256-test full suite plus installed-runtime temporary/real Vault read-only trials | 2026-07-12 |
| archive | pending |  |  |

## 待确认问题

- 用户可开始本地测试；真实 Vault 尚缺 v0.2 state，需先自行确认 `state init`，再确认 Inventory baseline。

## 说明

- Doctor 保持只读；Inventory 不复制 source/page registry 的摄入事实。
- 实施分支基于 `main` 的 `0cb31a5`，runtime 权威源码目录和 v0.2 前置均已存在。
- 本 Flow 与 `2026-07-11-obsidian-wikilink-resolution` 相互独立，不共享实施范围。
