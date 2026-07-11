# Change Brief: obsidian-ingest-inventory

## 摘要

- title: 发现 Obsidian Vault 中未摄入或摄入后变更的文档
- status: clarified
- flow_id: obsidian-ingest-inventory

## 来源

- 用户确认：当前 Vault 新增了大量未进入 Wiki 的文档，需要 Doctor 能发现。
- 设计：`docs/superpowers/specs/2026-07-11-obsidian-ingest-inventory-design.md`
- 现有实现参考：`scripts/obsidian_wiki_doctor.py`
- 现有流程参考：`skills/obsidian-wiki-ingest/`、`skills/obsidian-wiki-maintain/`

## 范围

- active: Inventory Core、Doctor inventory finding、Inventory CLI、Ingest/Maintain 状态协作及对应测试和文档
- reference-only: Root Resolver、现有 ingest/index 结构、Doctor 评分与报告模型
- excluded: WikiLink 解析、删除/重命名检测、内容哈希、正文读取、自动 ingest、Vault 外扫描

## 验收

- Doctor 能只读发现新增但未摄入的支持文档。
- Doctor 能发现已摄入后元数据发生变化的文档。
- `discovered`、`processed`、`ignored` 状态语义确定且可验证。
- 敏感范围只输出目录级汇总，不输出文件名或正文。
- 所有写入命令默认 dry-run，必须显式 `--confirm`。
- 目录级 ingest 只覆盖确认时快照，后续新增文档仍会被发现。
- 损坏基线或不完整扫描不得产生误导性的健康结论。

## 计划

- active_plan:
- status: none
- evidence:

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
| design | done | `docs/superpowers/specs/2026-07-11-obsidian-ingest-inventory-design.md` | 2026-07-11 |
| plan | pending |  |  |
| development | pending |  |  |
| testing | pending |  |  |
| archive | pending |  |  |

## 待确认问题

- 用户审阅书面设计后，是否进入实施计划阶段。

## 说明

- Doctor 保持只读；Ingest/Maintain 只在显式确认后更新 Inventory。
- 本 Flow 与 `2026-07-11-obsidian-wikilink-resolution` 相互独立，不共享实施范围。
