---
name: obsidian-wiki-query
description: Use this whenever the user asks questions that should be answered from an Obsidian LLM Wiki or personal knowledge base. Trigger on requests like "基于当前 wiki 回答", "according to my knowledge base", "从 Obsidian 里找", "summarize from my wiki", "generate an outline from my knowledge base", or "what do my notes say about...". This skill reads wiki pages first and only falls back to raw/source material when needed.
---


## First-Use Vault Setup

Treat root configuration as background setup, not a JSON-file task for the user. If normal resolution has no root, run `python scripts/llm_wiki.py root discover --format json`. Show returned existing absolute paths as numbered candidates and ask the user to select one or provide another absolute Vault path. Resolve the selected path and state `vault_root`, `control_center`, and `wiki_root`. Only after the user confirms it should become the default, run `root configure --root <path> --activate --confirm`.

Do not read note content or scan the whole disk during discovery. Continue the user's original request after setup succeeds.
# Obsidian Wiki Query

Answer questions from the Obsidian LLM Wiki.

## When To Use

Use this skill when the user wants to:

- answer a question from the knowledge base
- summarize a topic or project from wiki pages
- generate a plan, outline, checklist, or explanation from existing wiki knowledge
- locate relevant pages in the wiki
- save a durable synthesis after answering

Do not use this skill for diagnosis, validation, scoring, structure-quality
questions, or questions about whether weak answers are caused by wiki coverage.
Use `obsidian-wiki-doctor` for those cases. Use `obsidian-wiki-maintain` only
after the user approves repairs from confirmed findings.

## Wiki Root Resolution

Before reading any wiki page, resolve and state the actual wiki root. Do not
assume the current shell working directory is the Obsidian wiki.

Before reading or writing, resolve and state `vault_root`, `control_center`, and
`wiki_root` using the shared order:

1. User-provided Vault, control-center, or wiki path.
2. Nearest `.obsidian-llm-wiki.json` from the current working directory upward.
3. `OBSIDIAN_LLM_WIKI_ROOT`.
4. Exactly one active Vault in the user configuration.
5. Otherwise stop with `missing-config` or ask the user to choose when multiple roots exist.

Do not search the whole disk. Before answering, run or follow the equivalent of:

```text
python scripts/llm_wiki.py root resolve --cwd <working-directory> --format json
```

If a project workspace contains an `index.md` but is not the resolved Obsidian
wiki root, do not use it as the knowledge base unless the user explicitly says
that workspace is the target wiki.

## Reading Order

Follow `references/query-workflow.md`.

Default order:

```text
wiki/index.md
  -> ingest/index.md when external-source discovery is relevant
  -> relevant topic/project/entity/SOP/source pages
  -> original source material only when necessary
```

## Answer Rules

Use `references/answer-format.md`.

- Cite or name the wiki pages used.
- State when evidence is insufficient.
- Do not expose sensitive information.
- Separate sourced knowledge from inference.
- Suggest durable page creation when the answer has long-term value.

## Optional Save-Back

Use `references/synthesis-rules.md` when saving durable answers.

Ask before creating or updating wiki pages unless the user explicitly requested saving.

## Examples

Input:

```text
Based on the current wiki, summarize the video stream low-latency troubleshooting path.
```

Expected behavior:

```text
Read index and related topic/SOP/entity pages, then answer with page references and clear gaps.
```

Input:

```text
Use my knowledge base to generate a team AI productivity talk outline.
```

Expected behavior:

```text
Use relevant AI learning and productivity pages to generate an outline and suggest saving it as a project or article-outline page.
```
