---
name: obsidian-wiki-doctor
description: Use this whenever the user wants to diagnose, validate, score, report on, or explain the health or maturity of an Obsidian LLM Wiki, including prompts like "run Obsidian Wiki Doctor", "诊断 wiki", "给 wiki 打健康分", "出中文健康报告", "看看初始化后有没有用", or questions about whether poor query quality is caused by wiki structure. This skill is read-only and never repairs files.
---


## First-Use Vault Setup

Treat root configuration as background setup, not a JSON-file task for the user. If normal resolution has no root, run `python "<runtime-script>" root discover --format json`. Show returned existing absolute paths as numbered candidates and ask the user to select one or provide another absolute Vault path. Resolve the selected path and state `vault_root`, `control_center`, and `wiki_root`. Only after the user confirms it should become the default, run `root configure --root <path> --activate --confirm`.

Do not read note content or scan the whole disk during discovery. Continue the user's original request after setup succeeds.
## Runtime Resolution

Before running any command, resolve this skill's `SKILL.md` directory, take its
parent as `<skills-root>`, and set:

```text
<runtime-script> = <skills-root>/obsidian-wiki-runtime/scripts/llm_wiki.py
```

Verify that `<runtime-script>` exists, then invoke it by absolute path. If it is
missing, stop with `missing-runtime`, report the expected path, and recommend:

```text
npx skills add huajiexiewenfeng/obsidian-llm-wiki --skill '*' --copy --yes
```

Do not fall back to a repository-relative `scripts/llm_wiki.py` path.

# Obsidian Wiki Doctor

Diagnose an Obsidian LLM Wiki with the deterministic doctor engine.

## Boundary

Use this skill to look, score, validate, and explain. Do not edit vault files.

Use `obsidian-wiki-maintain` when the user asks to fix, repair, patch links, update `index.md`, add source proxies, or apply findings from a doctor report.

## Wiki Root Resolution

Before reading, resolve and state `vault_root`, `control_center`, and
`wiki_root` using the shared order: user path, nearest project
`.obsidian-llm-wiki.json`, `OBSIDIAN_LLM_WIKI_ROOT`, then exactly one active
Vault in user configuration. Otherwise stop with `missing-config` or ask the
user to choose when multiple roots exist. Do not search the whole disk.

```text
python "<runtime-script>" root resolve --cwd <working-directory> --format json
```

## Commands

Human report:

```text
python "<runtime-script>" doctor report --root <control-center-or-vault> --format text
```

Machine validation:

```text
python "<runtime-script>" doctor validate --root <control-center-or-vault> --format json --fail-on error
```

Structured score:

```text
python "<runtime-script>" doctor score --root <control-center-or-vault> --format json
```

`<skills-root>/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py` remains compatible in v0.2.

## Interpretation Rules

- Treat script findings as deterministic evidence.
- Treat score as directional guidance, not a KPI.
- Never print secret values.
- Keep Chinese-first explanations for Chinese users.
- Explain `not-applicable` dimensions instead of treating them as failures.
- If the user asks to repair, hand off to `obsidian-wiki-maintain` with a narrow repair scope.
- Explain archive registry/path/checksum drift, unregistered `raw/` files, and
  orphan archive staging files as read-only findings; never repair them here.

## References

- Read `references/doctor-checks.md` when explaining finding names.
- Read `references/report-template.md` when summarizing report structure.
- Read `references/safety-rules.md` before presenting sensitive-pattern findings.
