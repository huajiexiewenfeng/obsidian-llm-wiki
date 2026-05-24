---
name: obsidian-wiki-ingest
description: Use this whenever the user wants to ingest, import, index, summarize, organize, or turn Obsidian notes or external folders into an Obsidian LLM Wiki. Trigger on requests like "整理这个目录", "把这个目录做成 wiki", "ingest this file", "scan these external folders", "bring these documents into my knowledge base", or "process raw files". External files are path-indexed by default and copied into raw only after explicit confirmation.
---

# Obsidian Wiki Ingest

Ingest existing vault content, files in `raw/`, or external files and folders into the LLM Wiki.

## When To Use

Use this skill when the user wants to:

- organize a vault folder into wiki pages
- ingest a single file
- scan one or more external directories
- process new files under `raw/`
- create source/topic/project/entity/SOP pages from material

## Default Position

External folders use path-index mode by default:

```text
scan -> classify -> plan -> confirm -> process approved items
```

Do not copy external files into `raw/` unless the user explicitly confirms archival import.

## Workflow

Follow `references/ingest-workflow.md`.

Core steps:

1. Identify source path(s).
2. Scan candidate files.
3. Classify files by type, topic, risk, and recommended handling.
4. Generate an ingestion plan.
5. Ask for confirmation before reading deeply or copying files.
6. Process approved items.
7. Create or update wiki pages.
8. Update `index.md` and `log.md`.
9. Write an ingestion report.

## Supported Outputs

- `sources/<name>-资料索引.md`
- `sources/外部资料摄入计划-YYYY-MM-DD.md`
- `sources/外部资料摄入报告-YYYY-MM-DD.md`
- `topics/<topic>.md`
- `projects/<project>.md`
- `entities/<entity>.md`
- `sops/<workflow>.md`

## Safety Rules

Follow `references/safety-rules.md`.

Never include raw secret values in generated pages. For sensitive sources, record only path, type, risk, and recommendation.

## Confirmation Points

Always confirm before:

- copying external files into `raw/`
- reading PDF, Word, Excel, or large binary-heavy directories deeply
- processing suspicious or sensitive folders
- creating many pages at once
- modifying existing wiki pages broadly

## Report Format

Use `references/ingest-report-template.md`.

## Examples

Input:

```text
Scan D:\资料 and D:\Downloads, but do not copy anything into Obsidian yet.
```

Expected behavior:

```text
Create an ingestion plan using path-index mode. Do not copy external files.
```

Input:

```text
Ingest this confirmed PDF into the wiki.
```

Expected behavior:

```text
Read the PDF, create a source summary, update related wiki pages if needed, and avoid copying sensitive values.
```

Input:

```text
Archive these approved files into raw and then summarize them.
```

Expected behavior:

```text
Copy only the approved files into raw, then create source summaries and an ingestion report.
```
