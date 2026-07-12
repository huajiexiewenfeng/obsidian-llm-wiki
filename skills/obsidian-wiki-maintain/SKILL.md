---
name: obsidian-wiki-maintain
description: Use this whenever the user wants to repair, fix, patch, update, or apply approved structural fixes to an Obsidian LLM Wiki. Route diagnosis, validation, scoring, and health reports to obsidian-wiki-doctor first. This skill is for applying confirmed structure and safety repairs, not knowledge Q&A.
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

# Obsidian Wiki Maintain

Repair confirmed Obsidian LLM Wiki structure, consistency, and safety issues.
Detection belongs to `obsidian-wiki-doctor`; maintain applies approved fixes.

## When To Use

Use this skill when the user wants to:

- apply approved structural repairs from `obsidian-wiki-doctor`
- fix confirmed missing `index.md` entries
- patch confirmed broken relative wiki links
- update `log.md` for an approved maintenance action
- apply a narrow, user-approved cleanup to specific wiki files
- plan a confirmed cleanup or registration decision for Doctor archive findings

Do not use this skill for read-only diagnosis, validation, scoring, or health
reports. Use `obsidian-wiki-doctor` first, then return here to apply approved
repairs. Do not use this skill to answer knowledge questions. Use
`obsidian-wiki-query`.

## Wiki Root Resolution

Before reading or updating any wiki page, resolve and state the actual wiki
root. Do not assume the current shell working directory is the Obsidian wiki.

Before reading or writing, resolve and state `vault_root`, `control_center`, and
`wiki_root` using the shared order:

1. User-provided Vault, control-center, or wiki path.
2. Nearest `.obsidian-llm-wiki.json` from the current working directory upward.
3. `OBSIDIAN_LLM_WIKI_ROOT`.
4. Exactly one active Vault in the user configuration.
5. Otherwise stop with `missing-config` or ask the user to choose when multiple roots exist.

Do not search the whole disk. Before writes, run or follow the equivalent of:

```text
python "<runtime-script>" root resolve --cwd <working-directory> --format json
```

If a project workspace contains an `index.md` but is not the resolved Obsidian
wiki root, do not maintain that workspace as the wiki unless the user
explicitly says it is the target wiki.

## Workflow

Follow `references/repair-policy.md`.

1. Resolve and state the active Obsidian wiki root.
2. Run `<skills-root>/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py` through `obsidian-wiki-doctor`, or
   consume doctor findings supplied by the user.
3. Restate the approved repair scope in concrete file paths.
4. Ask before broad repairs or sensitive cleanup.
5. Apply approved narrow fixes only.
6. Update `log.md` with the maintenance action.
7. Return changed files, skipped findings, and remaining risks.

## Output

- optional `index.md` updates
- optional `log.md` updates
- optional `ingest/index.md` consistency notes
- optional narrow page-link repairs

## Safety Rules

Follow `references/safety-rules.md`.

Do not rewrite large sets of pages without confirmation.
Never delete, move, register, or re-archive a `raw/` file solely because Doctor
reported it. Present the exact candidate path and require confirmation.

## Examples

Input:

```text
Apply the doctor finding that wiki/projects/foo.md is missing from index.md.
```

Expected behavior:

```text
Update index.md for the confirmed page and record the change in log.md.
```

Input:

```text
Fix missing index links only.
```

Expected behavior:

```text
Update index.md for confirmed missing pages and record the change in log.md.
```
