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

Always resolve the target Obsidian control center before writing anything. The
current shell workspace is only the source or working directory unless it is
the user's active Obsidian vault. Do not satisfy ingest by writing generated
pages only into the project workspace.

Ingest has two different paths: source path(s) to scan and the target wiki root
to update. A user-provided source directory is not automatically the wiki root.
Resolve and state the target wiki root before reading or writing wiki pages.
Do not assume the current shell working directory is the Obsidian wiki.

## Wiki Root Resolution

Before reading or writing, resolve and state `vault_root`, `control_center`, and
`wiki_root` using the shared order:

1. User-provided Vault, control-center, or wiki path.
2. Nearest `.obsidian-llm-wiki.json` from the current working directory upward.
3. `OBSIDIAN_LLM_WIKI_ROOT`.
4. Exactly one active Vault in the user configuration.
5. Otherwise stop with `missing-config` or ask the user to choose when multiple roots exist.

Do not search the whole disk. A source path is not automatically the target
Wiki. Before writes, run or follow the equivalent of:

```text
python scripts/llm_wiki.py root resolve --cwd <working-directory> --format json
```

Target layout:

```text
<Obsidian Vault>/00-知识库中控/ingest/index.md
<Obsidian Vault>/00-知识库中控/wiki/index.md
<Obsidian Vault>/00-知识库中控/wiki/sources/*.md
<Obsidian Vault>/00-知识库中控/wiki/topics/*.md
<Obsidian Vault>/00-知识库中控/wiki/projects/*.md
<Obsidian Vault>/00-知识库中控/wiki/entities/*.md
<Obsidian Vault>/00-知识库中控/wiki/sops/*.md
```

Path-index mode is still an Obsidian graph operation. Even when raw external
files stay outside the vault, ingest must create or update wiki-visible pages
that make the external material discoverable from `index.md` and related topic
pages.

Minimum graph-first output for approved external material:

```text
ingest/index.md
  -> records ingest batches, document-level source paths, wiki entries, status
sources/<source-name>-summary-or-index.md
  -> acts as the Obsidian proxy node for an external document or document group
  -> linked from index.md or ingest/index.md
  -> linked from relevant topics/projects/entities/SOPs
  -> includes source path, status, summary, key topics, useful-for, related pages
```

## Workflow

Follow `references/ingest-workflow.md`.

Core steps:

1. Identify source path(s).
2. Resolve the active Obsidian vault/control center and confirm the target path if ambiguous.
3. Scan candidate files.
4. Classify files by type, topic, risk, and recommended handling.
5. Generate an ingestion plan.
6. Ask for confirmation before reading deeply or copying files.
7. Process approved items.
8. Write source summary/index/proxy pages into the Obsidian `wiki/` tree.
9. Update the Obsidian top-level `ingest/index.md`, `wiki/index.md`, related wiki pages, and `wiki/log.md`.
10. Write an ingestion report that lists graph links updated.

## Supported Outputs

- `sources/<name>-资料索引.md`
- `sources/<name>-summary.md`
- `ingest/index.md`
- `sources/外部资料摄入计划-YYYY-MM-DD.md`
- `sources/外部资料摄入报告-YYYY-MM-DD.md`
- `topics/<topic>.md`
- `projects/<project>.md`
- `entities/<entity>.md`
- `sops/<workflow>.md`

## Safety Rules

Follow `references/safety-rules.md`.

Never include raw secret values in generated pages. For sensitive sources, record only path, type, risk, and recommendation.

## Graph-First Requirements

- Before writing, locate the real Obsidian control center. Prefer an existing
  `00-知识库中控/` directory with `wiki/index.md`; if several candidates exist,
  ask the user which vault is active.
- Generated ingest content must be written into the Obsidian control center,
  not only into the coding/project workspace.
- `ingest/index.md` means `<control-center>/ingest/index.md`.
- `index.md`, `log.md`, `sources/`, `topics/`, `projects/`, `entities/`, and
  `sops/` mean paths under `<control-center>/wiki/`.
- Do not leave external material known only to the filesystem.
- Keep the ingest control-plane index outside the wiki knowledge folders:
  use top-level `ingest/index.md`, not `sources/ingested-document-index.md`.
- Every approved external source must have at least one wiki-visible source
  index or summary page under `sources/`.
- For approved individual documents, create a source proxy node when practical
  instead of only listing the document inside a batch table. The proxy node is
  what appears in the Obsidian graph.
- Every ingest batch must be listed in top-level `ingest/index.md` with source
  path, wiki entry, processing mode, status, and gaps.
- `index.md` must link to the new or updated source page, grouped under a clear
  section such as `Sources`, `Topics`, `Projects`, or `SOPs`.
- Relevant `topics/`, `projects/`, `entities/`, or `sops/` pages should link
  back to the source page when the relationship is durable.
- Source pages should include the original external path, processing mode,
  import status, sensitivity note, summary, key topics, useful-for section, and
  related wiki links.
- If a source is too sensitive to summarize, create a cautious path index only:
  path, type, risk category, recommended handling, and no sensitive values.

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
