# Change Brief: obsidian-v02-phase3-ingest-projection

## 摘要

- title: Obsidian LLM Wiki v0.2 Phase 3 Ingest 接入与确定性索引投影
- status: implemented-agent-local
- flow_id: obsidian-v02-phase3-ingest-projection

## 来源

- 总体设计：`docs/superpowers/specs/2026-07-10-obsidian-llm-wiki-v0.2-design.md`
- Phase 3 设计：`docs/superpowers/specs/2026-07-11-obsidian-llm-wiki-v0.2-phase3-ingest-projection-design.md`
- 前置 Flow：`obsidian-v02-phase2-state-layer`
- 实施基线：本地 `main` 必须包含 Phase 2 merge `e30f59f` 与首版设计 `f5542fe`；`origin/main@c5c6543` 尚未包含 Phase 2
- 后续依赖：v0.2 Phase 4 Doctor 状态一致性检查、v0.3 Inventory

## 目标

让 `obsidian-wiki-ingest` 在模型生成和用户确认完成后，把一个完整 operation payload 交给 deterministic Core；Core 在单进程、单锁、可诊断 operation 中完成来源登记、页面托管区写入、registry 更新、投影重建与 change-log 审计。

## 范围

- active: `ingest apply`、单 source proxy 与多个派生知识页、必要的 `page apply`/`projection rebuild` 内部或公开契约、source/page registry 更新、幂等与失败状态、托管投影、CLI/Skill/测试/文档
- read-only: Root Resolver、Phase 2 state/writer/managed 基础、Doctor 当前行为、Inventory 已确认的 sources registry 依赖
- candidate: none
- excluded: v0.3 Inventory、自动 migration、Context Pack、Doctor Phase 4 迁移、模型总结算法、页面删除/移动/重命名；archive-import 原子复制拆为 v0.2 Phase 3.1 子 Flow

## 初始验收

- Core 不在持锁期间读取来源、调用模型或等待用户确认。
- `ingest apply` 在同一把 Vault 锁和同一个 operation 下写入 source/page 状态、页面和投影。
- source 只有在页面、registry 与投影全部成功后进入 `processed`。
- 相同 idempotency key 的已完成请求不重复创建 proxy、页面或 change-log 完成事实。
- 冲突或中断产生可诊断的 `failed`/`pending` 状态，不伪造全量回滚。
- 投影只替换 marker 托管区，用户区域保持不变；缺失 marker 必须显式 takeover。
- canonical 实现位于 `skills/obsidian-wiki-runtime/scripts/`，根目录入口保持 compatibility launcher。
- Phase 3 不提前实现 `inventory` 命令。

## 计划

- active_plan: `docs/superpowers/plans/2026-07-11-obsidian-llm-wiki-v0.2-phase3-ingest-projection-implementation-plan.md`
- status: executed
- evidence: 实施提交 `ca9d6a4` 至 `bc3dc1d`；Task 8 文档与 E2E 待最终提交

## 外部依赖

- project-id: none
- edge_id: none
- dependency_type: none
- required_contract: none
- verification_status: source-verified
- impact_on_change: none

## Flow Record

| Step | Status | Evidence | Updated |
|---|---|---|---|
| source | done | v0.2 总体设计、Phase 2 handoff、Inventory 实施依赖 | 2026-07-11 |
| design | done | 用户确认按修订设计继续 | 2026-07-11 |
| plan | done | Phase 3 TDD 实施计划已写入仓库并完成覆盖自检 | 2026-07-11 |
| development | done | canonical runtime、三个 coordinator/CLI、Skill 与文档已实现 | 2026-07-12 |
| testing | done | passed-agent-local：144 passed, 2 skipped, 0 failures；真实 unittest/CLI/E2E，Test Integrity risk low | 2026-07-12 |
| archive | done | `.llm-wiki/handoff/obsidian-v02-phase3-ingest-projection-handoff.md` | 2026-07-12 |

## 待确认问题

- none

## 已确认决策

- 一个 `ingest apply` operation 绑定一个来源，必须包含一个 source proxy，并允许同时创建或更新多个派生知识页；这些页面、registry 与投影共享同一个 operation 成败边界。
- CLI 使用 `--payload <file|->`：普通路径读取 JSON 文件，`-` 从 stdin 读取；两者共享同一解析、schema 校验、规范化和幂等计算，不持久化原始 payload。
- takeover 在 payload 中按具体 page mutation 或 projection 相对路径逐项声明；未显式声明的既有无 marker 文件返回 conflict，不提供全局 takeover 开关。
- `ingest apply` 默认执行完整预检并零写入；只有同一 payload 加 `--confirm` 才进入写事务，payload 内字段不能替代 CLI 确认。
- Phase 3 新建专用 `llm_wiki_core/ingest.py`：纯 planner 负责校验和变更计划，coordinator 负责锁内执行；`writer.py` 保持通用 primitive 边界，CLI 不直接编排事务，也不提前抽象通用 transaction engine。
- 退出码 `1` 保持与现有 state init 一致，表示可预期未执行；具体原因读取 JSON status/check。
- move candidate 由 payload `move_resolution` 的 `rebind`/`new-source` 显式解除。
- checksum conflict 由 dry-run 返回当前 checksum 与安全提示，Agent 核对页面后回填 payload。
- 本 Flow 只接受 `path-index`、`summary-ingest`；`archive-import` 由 v0.2 Phase 3.1 子 Flow 交付。

## 验证计划

- payload/schema 单元测试
- 事务步骤、幂等、冲突与中断注入测试
- 页面用户区域与 CRLF 保留测试
- CLI dry-run/apply 冒烟测试
- shared runtime 布局和完整 unittest 回归
