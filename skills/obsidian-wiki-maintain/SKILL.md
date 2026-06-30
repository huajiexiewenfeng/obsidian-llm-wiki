---
name: obsidian-wiki-maintain
description: Use this whenever the user wants to repair, fix, patch, update, or apply approved structural fixes to an Obsidian LLM Wiki. Route diagnosis, validation, scoring, and health reports to obsidian-wiki-doctor first. This skill is for applying confirmed structure and safety repairs, not knowledge Q&A.
---

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

Do not use this skill for read-only diagnosis, validation, scoring, or health
reports. Use `obsidian-wiki-doctor` first, then return here to apply approved
repairs. Do not use this skill to answer knowledge questions. Use
`obsidian-wiki-query`.

## Wiki Root Resolution

Before reading or updating any wiki page, resolve and state the actual wiki
root. Do not assume the current shell working directory is the Obsidian wiki.

Resolution priority:

1. If the user provides a vault, control-center, or wiki path, use it.
2. If `C:\Users\admin\Documents\Obsidian Vault\00-知识库中控\wiki`
   exists, prefer it as the default wiki root.
3. Otherwise, search for an Obsidian control center that has `wiki/index.md`
   and `wiki/log.md`, or a wiki root that has `index.md` and `log.md`.
4. If multiple candidates exist, ask the user which wiki is active.
5. Before making edits, say which wiki root is being used.

If a project workspace contains an `index.md` but is not the resolved Obsidian
wiki root, do not maintain that workspace as the wiki unless the user
explicitly says it is the target wiki.

## Workflow

Follow `references/repair-policy.md`.

1. Resolve and state the active Obsidian wiki root.
2. Run `scripts/obsidian_wiki_doctor.py` through `obsidian-wiki-doctor`, or
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
