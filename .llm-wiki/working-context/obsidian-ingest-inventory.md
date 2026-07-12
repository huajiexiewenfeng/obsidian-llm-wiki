# Working Context: obsidian-ingest-inventory

## 生命周期

- flow_id: obsidian-ingest-inventory
- status: ready-for-user-test
- branch: codex/v03-inventory
- baseline: main@0cb31a5

## 活动范围

- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/inventory.py`
- `skills/obsidian-wiki-runtime/scripts/llm_wiki.py`
- `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/doctor_state.py`
- `skills/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py`
- Inventory、CLI、Doctor、事务和端到端测试
- Doctor、Ingest、Maintain 技能说明及工作流文档

## 只读参考范围

- `llm_wiki_core/state.py` 的 registry、路径和 fingerprint 契约
- `llm_wiki_core/writer.py` 的锁、operation、原子替换和 change log 契约
- `llm_wiki_core/ingest.py` 的 processed 证据和幂等事务模式
- v0.2、Phase 3、Phase 3.1、Phase 4 规格与测试

## 候选范围

- `llm_wiki_core/state.py`：仅当 Inventory schema 需要共享验证函数时升级为活动范围。
- `llm_wiki_core/writer.py`：仅当现有原语无法安全提交 inventory.json 时升级为活动范围。

## 排除范围

- 自动 ingest、自动移动或删除原文档
- 删除和重命名检测
- 默认读取候选正文或计算 checksum
- WikiLink 解析行为
- Vault 外部扫描
- 已安装 skill 缓存作为实现来源

## 已确认约束

- Doctor 和 `inventory inspect` 严格零写入。
- `raw/` 永久排除普通候选；未登记 raw 文件沿用 `unregistered-archive`。
- processed 只由完整 source/page/proxy registry 证据推导。
- 所有 Inventory 写入默认 dry-run，必须显式 `--confirm`。
- 敏感范围不输出逐文件路径。

## 验证计划

- 每个任务先写失败测试，再写最小实现。
- 运行新增 Inventory 测试、相关 CLI/Doctor 回归测试和完整 pytest。
- 在临时 Vault 做初始化、新增、修改、忽略、解除忽略端到端验证。
- 最后在真实 Vault 只读运行 Doctor；未经用户确认不初始化真实基线。

## 范围升级日志

- 2026-07-12：无升级；先保持 state.py 和 writer.py 为只读参考。

## 验证结果

- 完整 unittest discovery：257 tests，0 failures，3 skips。
- 新增 Inventory E2E：baseline 后新增 Markdown 被 Doctor 报告，Doctor 零写入。
- 已安装 runtime 与开发分支 7 个目标文件 SHA-256 一致。
- 真实 Vault `inventory inspect`：220 个支持文档，`missing-ingest-inventory`，运行前后 0 个文件变化。
- 临时本地 Vault：state init、Inventory initialize、baseline 后新增文档发现均成功。
