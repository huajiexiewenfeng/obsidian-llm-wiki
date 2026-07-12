# Phase 3 Ingest And Projection Handoff

- flow_id: `obsidian-v02-phase3-ingest-projection`
- status: implemented; agent-local verification passed
- branch: `codex/v02-phase3-ingest-projection`
- base: local `main@01509a6`
- implementation commits: `ca9d6a4`, `be8d183`, `7b11002`, `9ae0584`, `afb0315`, `f1af90e`, `bc3dc1d`

## 已实现

- 严格、版本化、脱敏的 ingest/page/projection payload parser
- 单 source、单 source proxy、零到多个派生页的确定性 `IngestPlan`
- move candidate 的 `rebind` / `new-source` 解决通道
- managed checksum、逐目标 takeover、用户文本与 CRLF 保留
- `wiki/index.md`、`ingest/index.md`、`wiki/log.md` 确定性投影
- 单 Vault 锁、plan checksum 复核、pending/processed source 状态、operation 诊断
- completed change event 幂等恢复和七步骤 failure-injection 记录
- `ingest apply`、`page apply`、`projection rebuild` dry-run/confirm CLI
- Ingest Skill 改为生成 payload 并调用 Core，不再直接修改 registry 或投影

## 验证范围

- payload schema、未知字段、枚举、file/stdin 等价与正文脱敏
- source identity、checksum/fingerprint 漂移、move resolution
- 页面 create/update/unchanged/conflict、marker、takeover、CRLF
- 三投影排序、prospective event 和重复 rebuild
- 七个事务步骤失败注入、幂等 event/operation 修复
- 根 launcher CLI 与两个来源的真实 subprocess E2E
- 完整 `unittest discover` 与 `git diff --check`

最终验证（Codex agent-local，2026-07-12）：bundled Python 执行
`python -m unittest discover -s tests -v`，结果 144 tests passed、0 failures、
2 skipped、exit code 0；`git diff --check` exit code 0。跳过项为 Windows
当前账户无 symlink 权限，以及未显式启用的 Skills CLI integration。

## Test Integrity

生产代码与测试同步增加。事务和 E2E 使用真实临时 Vault、真实文件、registry、锁和 subprocess；没有用 mock 替代业务 coordinator。仅把 Phase 2 的“不得出现 ingest parser”过时断言替换为“不得提前出现 Inventory”。assertion strength 为 high，over-mocking risk 为 low。

## 边界与后续

- `archive-import` 二进制原子复制仍是 v0.2 Phase 3.1 子 Flow。
- Doctor 对 registry/frontmatter/projection/operation 的一致性检查仍是 Phase 4。
- 新文件自动发现与 stale/ignored inventory 仍是 v0.3。
- 当前验证为 agent-local；合并前仍建议 CI 或 reviewer 复核。
