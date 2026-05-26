---
name: obsidian-wiki-maintain
description: Use this whenever the user wants to health-check, lint, audit, repair, or maintain an Obsidian LLM Wiki. Trigger on requests like "做健康检查", "check the wiki", "lint wiki", "find broken links", "find orphan pages", "check index/log consistency", "check sensitive information spread", or "repair missing index links". This skill is for structure and safety, not knowledge Q&A.
---

# Obsidian Wiki Maintain

Maintain wiki structure, consistency, and safety.

## When To Use

Use this skill when the user wants to:

- run a wiki health check
- find broken links
- find orphan pages
- check `index.md` and `log.md` consistency
- check `ingest/index.md` batch and source proxy consistency
- detect missing topic/project/entity/SOP pages
- scan for sensitive information spread
- apply narrow structural repairs

Do not use this skill to answer knowledge questions. Use `obsidian-wiki-query`.

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

Follow `references/health-check-rules.md`.

1. Resolve and state the active Obsidian wiki root.
2. Read `wiki/index.md`, `wiki/log.md`, and `ingest/index.md` when present.
3. Inspect page groups.
4. Check links, coverage, and consistency.
5. Scan generated wiki pages for sensitive patterns.
6. Produce a health report.
7. Ask before broad repairs.
8. Apply only approved fixes.

## Output

- `健康检查-YYYY-MM-DD.md`
- optional `index.md` updates
- optional `log.md` updates
- optional `ingest/index.md` consistency notes
- optional narrow page-link repairs

## Finding Levels

- Error: broken or dangerous state requiring action
- Warning: likely issue or missing structure
- Info: useful observation or improvement idea

## Safety Rules

Follow `references/safety-rules.md`.

Do not rewrite large sets of pages without confirmation.

## Report Format

Use `references/health-report-template.md`.

## Examples

Input:

```text
Run a health check on the current wiki.
```

Expected behavior:

```text
Create a health report with Errors, Warnings, Info, and suggested fixes.
```

Input:

```text
Fix missing index links only.
```

Expected behavior:

```text
Update index.md for confirmed missing pages and record the change in log.md.
```
