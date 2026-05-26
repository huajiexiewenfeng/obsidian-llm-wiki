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

## Workflow

Follow `references/health-check-rules.md`.

1. Resolve the active Obsidian control center.
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
