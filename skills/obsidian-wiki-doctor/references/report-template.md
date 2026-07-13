JSON reports contain `root`, `state`, `findings`, and `score`. Text reports use the Chinese-first section order from the design spec.

# Report Template

## Text Report Section Order

1. `# Obsidian Wiki Doctor 报告`
2. `## 关键结论`
3. `## 建议行动计划`
4. `## 总体评分`
5. `## 成熟度维度`
6. `## Doctor Findings`
7. `## 证据与路径`
8. `## Repair Handoff`

## JSON Keys

- `root`: resolved control center, wiki root, input root, source, and optional root error.
- `state`: initialization, onboarding, inventory, ingest, and generated-page signals.
- `findings`: deterministic findings with check name, severity, path, message, optional line, and optional hint.
- `score`: directional maturity score, level, dimensions, signals, and next steps.

When explaining a report, preserve the distinction between `findings` and `score`: findings are deterministic observations; score is a directional summary of maturity.

## Mandatory Inventory Baseline Language

If `missing-ingest-inventory` is present, include these lines in `关键结论` or
`建议行动计划` exactly as written:

```text
索引可达的历史文档 -> known-existing -> 不需要 ingest
不可达的历史文档 -> unverified/source-island -> 不自动 ingest
基线后新增 -> discovered/uningested-source -> 待处理
```

Do not describe the current Inventory document count as an ingest backlog. The
count is the classification scope. If `.meta` state files are missing, use this
action order:

1. Verify sensitive-pattern findings; rotate first only when a real credential is confirmed.
2. Initialize or adopt the required `.meta` state layer.
3. Preview Inventory initialization and review `disposition_counts`.
4. Confirm the baseline explicitly; current history remains non-automatic.
5. Repair broken links, source islands, and detached Wiki components.
6. Rerun Doctor.
