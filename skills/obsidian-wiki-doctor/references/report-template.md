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
