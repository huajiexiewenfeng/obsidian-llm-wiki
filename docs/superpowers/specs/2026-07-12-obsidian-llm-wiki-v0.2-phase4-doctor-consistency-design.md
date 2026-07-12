# Obsidian LLM Wiki v0.2 Phase 4：Doctor 状态一致性设计

## 状态

- 日期：2026-07-12
- flow_id：`obsidian-v02-phase4-doctor-consistency`
- 状态：对话设计已确认，书面规格已按评审修订，待用户复审
- 实施基线：本地 `main@e1f270d`，包含 Phase 3 transactional ingest/projection
- 前置 Flow：`obsidian-v02-phase3-ingest-projection`

## 目标

Phase 4 让现有只读 Doctor 理解 Phase 2/3 的机器状态与托管 Markdown，能够检查 registry、页面、投影、operation、change log、lock 和临时文件之间的一致性，并给出可交给 Maintain 的窄范围恢复建议。

Doctor 继续回答“当前状态是否一致、哪里不一致、下一步应检查什么”，但不获取写锁、不修改 Vault、不清锁、不重建投影，也不自动决定如何处置孤儿页面。

## 非目标

- 不改变 `validate`、`score`、`report` 命令或退出码。
- 不改变现有五个成熟度维度和权重。
- 不扩展 Finding JSON 字段。
- 不实现 Maintain 修复、operation resume、metadata rollback 或 stale-lock 隔离。
- 不扫描 control center 之外的 Vault 笔记。
- 不实现 Inventory、archive-import、migration 或 Context Pack。

## 已确认决策

1. 新的一致性 findings 不改变现有 100 分评分契约。
2. running operation 必须与当前 lock 联合判断。
3. 扫描范围限制在 control center 的 `.meta/`、`wiki/**/*.md` 和 `ingest/`。
4. Finding 保持 `check/severity/path/message/line/hint` 六个字段。
5. 新建纯只读 `llm_wiki_core/doctor_state.py`，现有 Doctor 负责适配与渲染。
6. Page planner 与 Doctor 共用托管区解析和 checksum 语义，不复制 parser。

## 架构

canonical runtime 增加：

```text
skills/obsidian-wiki-runtime/scripts/
  obsidian_wiki_doctor.py
  llm_wiki_core/
    doctor_state.py
    managed.py
    state.py
    projection.py
    writer.py
```

职责：

- `doctor_state.py`：读取机器状态、比较页面与投影、关联 operation/lock、发现遗留 temp，返回内部 `ConsistencyIssue`。
- `managed.py`：提供公共只读 `inspect_managed_page()` 与 `inspect_projection_region()`，统一 marker、frontmatter、checksum 和换行语义。
- `state.py`：继续拥有 registry codec 与 record 校验。
- `projection.py`：继续拥有三个确定性 renderer，Doctor 只调用 renderer，不调用 apply coordinator。
- `writer.py`：复用 `classify_lock()`；Doctor 不调用任何 writer 写函数。
- `obsidian_wiki_doctor.py`：把 `ConsistencyIssue` 转成现有 `Finding`，复用 redaction、JSON/text 输出和退出码。

依赖方向保持单向：Doctor CLI 可导入 Core；`doctor_state.py` 不导入 CLI；状态与渲染 primitives 不反向导入 Doctor。

## 状态启用与读取范围

- `.meta/` 不存在：Phase 4 检查整体为不适用，不为旧 Wiki 生成缺失状态 findings。
- `.meta/` 存在：状态层已启用，以下文件均为必要文件：`schema.json`、`sources.json`、`pages.json`、`operations.json`、`change-log.jsonl`。
- 只枚举 `.meta/`、`wiki/` 和 `ingest/`；不枚举 Vault 其他目录。
- 任何 registry 相对路径在读取前必须解析并验证仍位于 control center；symlink/junction 越界返回 `unsafe-registered-path`。
- Doctor 不读取遗留临时文件正文，只读取其路径和文件元数据。

## 公共托管区检查器

`managed.py` 增加不可变快照：

```text
ManagedPageSnapshot
  fields
  managed_body
  computed_checksum

ProjectionSnapshot
  managed_body
```

规则：

- marker 缺失、重复、嵌套、失衡或乱序抛出只读解析冲突。
- frontmatter 托管字段继续按 JSON scalar/array 规则解析。
- `computed_checksum` 排除 `llm_wiki_managed_checksum` 字段，与 Page planner 完全一致。
- 比较前只把 CRLF/CR 规范化为 LF，并统一移除托管区末尾换行；marker 外字节不参与比较。
- `page.py` 改为调用该公共检查器，避免出现两套 checksum 语义。

## 检查项

### 状态文件

- `missing-state-file`，ERROR：`.meta` 已启用但必要文件缺失。
- `invalid-state-file`，ERROR：JSON、schema、registry record 或 change-log 中间行损坏。
- `torn-change-log-tail`，WARN：change log 的合法事件前缀之后仅有一个未完成尾行。判定条件为最后一个非空片段无法解析且文件末尾没有换行；合法前缀继续参与 log projection 与 completion event 检查。

每个状态文件独立加载。单文件损坏只阻断依赖它的检查：

- `schema.json` 缺失或损坏：状态版本不可确认，跳过 source/page/operation/event 与投影比较，但继续 lock 和 temp 检查。
- `sources.json` 损坏：跳过 source/proxy 与 ingest projection。
- `pages.json` 损坏：跳过 page/frontmatter、orphan 与 wiki index projection。
- `operations.json` 损坏：跳过 operation/event 关联。
- `change-log.jsonl` 中间行损坏：跳过 log projection 与 completion event 关联。
- `change-log.jsonl` 仅尾行撕裂：报告 `torn-change-log-tail`，忽略未完成尾行并用合法前缀继续检查；恢复 hint 要求 Maintain 先核对关联 operation，再经用户确认截断尾行。Doctor 本身不截断。

### Source registry

- `processed-source-missing-proxy`，ERROR：processed source 没有 proxy page ID，或 ID 不在 page registry。
- `source-proxy-file-missing`，ERROR：proxy page record 存在但目标 Markdown 缺失。
- `pending-source-without-active-operation`，WARN：pending source 没有能解释当前状态的 active ingest operation。相关性以 `ingest-apply` operation 的 `record_ids` 包含 source ID 判断：没有相关 operation，或最新相关 operation 已 completed 但 source 仍为 pending 时，报告本 finding；最新相关 operation 为 running 时交给 lock 联合检查；最新相关 operation 为 failed 时由 `failed-operation` 单独报告并在 hint 中指出 source，不重复生成本 finding。
- `failed-source`，WARN：source 状态为 failed。

### Page registry 与托管页面

- `registered-page-missing`，ERROR：page record 指向的文件不存在。
- `unsafe-registered-path`，ERROR：page path 通过 symlink/junction 逃逸 control center。
- `page-frontmatter-drift`，ERROR：`llm_wiki_page_id`、page type 或 source IDs 与 registry 不一致。
- `managed-checksum-drift`，ERROR：实际托管区 checksum、frontmatter 镜像或 registry checksum 不一致。
- `managed-marker-conflict`，ERROR：已登记页面的 managed/frontmatter marker 不可安全解析。
- `orphan-managed-page`，WARN：`wiki/**/*.md` 含 LLM Wiki 托管 marker，但没有 page record。

孤儿页若 marker 同时损坏，可以同时产生 `orphan-managed-page` 与 `managed-marker-conflict`；两者分别表达身份缺口和文本结构风险。

### 确定性投影

- `projection-marker-conflict`，ERROR：三个投影之一的 marker 不可安全解析。
- `projection-drift`，WARN：marker 内实际内容与 renderer 从权威状态生成的内容不同。

Doctor 使用：

- `render_wiki_index(pages)`
- `render_ingest_index(sources, pages)`
- `render_wiki_log(events)`

缺少 `wiki/index.md`、`wiki/log.md` 或条件性缺失 `ingest/index.md` 继续由现有 checks 报告，Phase 4 不生成重复 finding。恢复 hint 指向 `projection rebuild` dry-run。

### Operation、event 与 lock

- `active-operation`，INFO：running operation 与有效 lock 匹配。
- `orphan-running-operation`，ERROR：running operation 没有 lock。
- `running-operation-with-stale-lock`，ERROR：running operation 只有 stale lock。
- `failed-operation`，WARN：operation 为 failed；其他 drift findings 说明实际影响。
- `operation-event-status-drift`，WARN：completed event 已存在，但 operation 不是 completed。
- `missing-completion-event`，ERROR：要求审计的 completed operation 缺少对应 completed event。
- `stale-lock`，WARN：同 host、超过 writer TTL 且 PID 不存在。
- `cross-host-lock`，WARN：跨 host 锁无法安全判断存活性。
- `invalid-lock`，ERROR：lock JSON 或必要字段损坏。

要求 completion event 的 operation kind 为 `state-init`、`ingest-apply`、`page-apply`；`projection-rebuild` 在 Phase 3 契约中不追加 change event，因此不适用该检查。

`INFO` 是 Phase 4 新增的 Finding severity 约定值，但不改变 Finding 字段集合。现有 `Finding.severity` 为字符串，`safe_finding()`、JSON/text renderer 均透传该值，`--fail-on error` 只检查 `ERROR`；因此 `active-operation` 不影响退出码或评分。实现测试必须固定 INFO 的 JSON/text 渲染以及 `--fail-on error` 返回 0。

有效锁与 operation 的匹配使用规范化 command/kind、目标 control center 和时间关系。若多个 running operation 同时匹配一把锁，只把最新 `updated_at` 的一个视为 active，其余报告 `orphan-running-operation`。

cross-host lock 不计为已确认 active，但其存在会抑制 `orphan-running-operation`，因为本机无法证明远端 writer 已退出；此时只报告 `cross-host-lock` WARN。invalid lock 不提供这种保护：同时报告 `invalid-lock`，相关 running operation 仍按 orphan 处理。

### 遗留临时文件

- `orphan-temp-file`，WARN：在允许扫描的三个目录中发现 writer 风格 `.<target>.<random>.tmp` 文件。

Doctor 只报告 control-center-relative path，不读取内容，也不根据年龄自动删除或降级。
临时文件命名的前缀、后缀或匹配 predicate 必须与 writer 实现同源，Doctor 不维护一份独立正则。

## Finding 兼容与排序

内部 `ConsistencyIssue` 字段映射到现有 Finding：

```text
check -> check
severity -> severity
relative_path -> path
message -> message
line -> line
recovery_hint -> hint
```

所有文本进入现有 `safe_finding()` redaction。Finding JSON 不新增 `details`、`evidence` 或 `repair`。

Phase 4 issues 在适配前按以下稳定键排序：severity rank（ERROR、WARN、INFO）、check、path、line。现有 Doctor findings 保持原顺序，新 issues 作为一个稳定块追加。

## CLI 与评分兼容

- `doctor validate --fail-on error`：存在任意 ERROR（含 Phase 4）时返回 1，否则 0。
- `doctor validate --fail-on none`：始终返回 0。
- `doctor score`、`doctor report`：始终返回 0。
- 原 `score_version: 1`、五维名称、权重与 N/A 规则不变。
- 新 check 名不加入评分扣分映射；它们通过 findings 与报告建议表达。
- 根 compatibility launcher 与 canonical runtime 输出继续等价。

## 恢复建议

- projection drift：运行 `projection rebuild` dry-run，确认后再重建。
- page/frontmatter/checksum drift：Maintain 核对当前托管区后生成 `page apply` payload。
- orphan managed page：由用户确认登记页面或移除托管身份。
- failed/running operation：核对 operation、change event 与原 payload 后再 retry。
- stale lock：Maintain 经用户确认后隔离旧锁。
- temp file：确认没有活动 writer 后由 Maintain 清理。

Doctor 不生成可自动执行 payload，不调用 Maintain，不在 hint 中承诺无条件安全修复。

## 测试策略

### Core 单元测试

新增 `tests/test_llm_wiki_doctor_state.py`：

- `.meta` absent/partial/invalid 的 gating、change-log 中间损坏与 torn tail 合法前缀恢复。
- source proxy、pending/failed source，以及最新 failed ingest operation 对 pending 重复告警的抑制。
- registered/orphan page、frontmatter/checksum/marker drift。
- symlink/junction 越界（平台不允许时按既有理由 skip）。
- 三投影 healthy/drift/marker conflict 与 CRLF 等价。
- active/orphan/failed operation、event status、missing event，以及 INFO 渲染和退出码兼容。
- live/stale/cross-host/invalid lock。
- writer 同源 temp pattern 与窄扫描边界。
- issues 稳定排序。

### Doctor 集成测试

扩展 `tests/test_obsidian_wiki_doctor.py`：

- validate/report JSON 包含 Phase 4 findings。
- Finding 字段集合保持不变。
- score version、维度和权重保持不变。
- 运行前后 control center 文件集合、size、mtime_ns 与 checksum 快照完全相同；快照明确包含 `.meta/lock.json`，证明 Doctor 连锁文件也未触碰。
- 根 launcher 与 canonical runtime 等价。

### 全量回归

- bundled Python 运行完整 unittest。
- `git diff --check` 无输出。
- 静态搜索确认 Doctor Core 不调用 atomic write、append event、lock acquire 或删除 API。
- Windows 与 Ubuntu 使用相同协议；无 symlink 权限的 Windows 环境允许既有 skip。

## 验收标准

1. 健康的 Phase 3 Vault 不产生新的 ERROR/WARN。
2. `.meta` 完全不存在时保持旧 Wiki 兼容。
3. 单状态文件损坏不会阻断其他安全检查；change-log 仅尾行撕裂时保留合法前缀检查能力。
4. registry/page/frontmatter/checksum drift 可以区分。
5. 三个投影可分别识别 marker conflict 与内容 drift。
6. running operation 与 lock 联合判断，不把正常 writer 误报为 orphan。
7. completed event、operation 状态和审计缺口可检查；projection-rebuild 按 Phase 3 契约免除 completion event 审计。
8. orphan managed page、stale lock和 writer temp 可发现。
9. 扫描和路径解析不离开 control center。
10. Doctor 运行前后文件快照完全一致，包括 `.meta/lock.json`。
11. Finding JSON、五维评分和三条 CLI 保持兼容。
12. 敏感路径和错误文本继续经过现有 redaction。

## 后续关系

- Maintain 可在后续 Flow 消费 Phase 4 check 名并生成用户确认的修复计划。
- Phase 3.1 archive-import 可在交付后补充对应归档一致性检查。
- v0.3 Inventory 继续负责新文件发现，不由 Doctor 扫描推断。
