---
name: obsidian-wiki-doctor
description: Use this whenever the user wants to diagnose, validate, score, report on, or explain the health or maturity of an Obsidian LLM Wiki, including prompts like "run Obsidian Wiki Doctor", "诊断 wiki", "给 wiki 打健康分", "出中文健康报告", "看看初始化后有没有用", or questions about whether poor query quality is caused by wiki structure. This skill is read-only and never repairs files.
---

# Obsidian Wiki Doctor

Diagnose an Obsidian LLM Wiki with the deterministic doctor engine.

## Boundary

Use this skill to look, score, validate, and explain. Do not edit vault files.

Use `obsidian-wiki-maintain` when the user asks to fix, repair, patch links, update `index.md`, add source proxies, or apply findings from a doctor report.

## Required First Check

1. Resolve the target control center or wiki root.
2. Prefer the user-provided path.
3. Otherwise honor `OBSIDIAN_LLM_WIKI_ROOT`.
4. Otherwise allow the doctor script fallback behavior.
5. State the resolved control center and wiki root in the answer.

## Commands

Human report:

```text
python scripts/obsidian_wiki_doctor.py report --root <control-center-or-vault> --format text
```

Machine validation:

```text
python scripts/obsidian_wiki_doctor.py validate --root <control-center-or-vault> --format json --fail-on error
```

Structured score:

```text
python scripts/obsidian_wiki_doctor.py score --root <control-center-or-vault> --format json
```

## Interpretation Rules

- Treat script findings as deterministic evidence.
- Treat score as directional guidance, not a KPI.
- Never print secret values.
- Keep Chinese-first explanations for Chinese users.
- Explain `not-applicable` dimensions instead of treating them as failures.
- If the user asks to repair, hand off to `obsidian-wiki-maintain` with a narrow repair scope.

## References

- Read `references/doctor-checks.md` when explaining finding names.
- Read `references/report-template.md` when summarizing report structure.
- Read `references/safety-rules.md` before presenting sensitive-pattern findings.
