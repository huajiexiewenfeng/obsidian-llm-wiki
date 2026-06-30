# Onboarding Roadmap

Use this reference when the vault already contains many notes or when the user needs step-by-step guidance after initialization.

## Principle

Initialization should not stop at creating folders. It should leave the user with a concrete next action.

The user should understand:

- what exists in the vault
- what should be handled first
- what should be delayed
- what should be treated cautiously
- how to move from init to ingest

## Required Roadmap File

Generate or update:

```text
00.LLM Wiki 建设路线图.md
```

## Roadmap Shape

```markdown
# LLM Wiki 建设路线图

## 当前状态判断

Describe whether the vault is:

- empty or nearly empty
- an existing active vault
- a mixed vault with project, learning, temporary, and sensitive material
- a migrated or imported vault

## 总体策略

State the strategy. For an existing vault, prefer:

- do not move original files
- do not reorganize all folders at once
- build a wiki layer above existing material
- start with one to three high-value batches
- run `obsidian-wiki-doctor` after each meaningful batch

## 第一阶段：盘点和范围确认

Outputs:

- `00.知识库地图.md`
- `00.整理范围确认.md`

## 第二阶段：选择第一批 ingest 范围

Recommend 1-3 first batches.

Good first-batch candidates:

- high-frequency folders
- active project folders
- learning folders with reusable notes
- folders already mostly in Markdown
- low-sensitivity material

Avoid as first batch:

- password or credential folders
- raw logs
- very large mixed downloads folders
- unclear binary-heavy folders
- old archives with unknown content

## 第三阶段：执行 obsidian-wiki-ingest

Explain that the next skill should:

- generate source indexes
- create topic pages
- create project/entity/SOP pages when needed
- update `index.md`
- append `log.md`

## 第四阶段：执行 obsidian-wiki-doctor

Explain that doctor diagnosis should run after each meaningful ingest batch.

Doctor checks:

- missing index entries
- broken links
- orphan pages
- missing entity/project/SOP pages
- sensitive information spread
- hand off approved repair findings to obsidian-wiki-maintain only when edits are needed

## 第五阶段：执行 obsidian-wiki-query

Explain that query becomes useful once the first wiki pages exist.

Examples:

- summarize a topic
- generate a learning path
- generate a project handoff
- generate an article outline
- identify common patterns across troubleshooting notes

## 推荐第一批整理候选

Use a table:

| Priority | Folder | Why | Suggested mode | Risk |
|---|---|---|---|---|

Suggested modes:

- `vault-ingest`
- `path-index`
- `summary-ingest`
- `skip-for-now`
- `needs-confirmation`

## 用户需要确认的问题

Ask one concrete question at the end:

```text
I recommend starting with [folder/category]. Should we process this first with obsidian-wiki-ingest?
```

If there are several reasonable options, ask:

```text
Which first batch should we ingest?
1. [option]
2. [option]
3. [option]
```

Do not end with only "initialization complete".
