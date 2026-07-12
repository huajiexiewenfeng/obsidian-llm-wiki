# Handoff: obsidian-ingest-inventory

## 状态

- flow_id: obsidian-ingest-inventory
- branch: codex/v03-inventory
- stage: ready-for-user-test

## 已交付

- Inventory scope/scanner/baseline codec and registry comparator
- `inventory inspect`, `initialize`, `configure`, `ignore`, `unignore`
- confirmed plan checksum, lock, operation, atomic replace, change-log, idempotent replay
- Doctor findings, scoring, sensitive summaries, and grouped text output
- Doctor/Ingest/Maintain skill guidance and runtime packaging coverage

## 验证

- Full suite: 257 unittest cases, 3 platform skips, 0 failures.
- Installed runtime hashes match the development branch for all seven updated files.
- Real Vault read-only inspect found 220 supported documents and wrote nothing.
- Temporary local Vault confirmed baseline-after-new-file detection and Doctor wrote nothing.

## 用户测试入口

The real Vault currently lacks v0.2 `.meta/schema.json`. Run `state init` preview,
review it, confirm it, then run `inventory initialize` preview and confirm its
plan checksum. After adding a Markdown document, Doctor should report
`uningested-source`.

## 后续

- Await user local-test feedback.
- After acceptance, run project-finish, merge to main, update installed hashes if needed, and push GitHub.
