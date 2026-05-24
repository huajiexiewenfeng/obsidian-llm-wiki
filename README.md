# obsidian-llm-wiki

AI-assisted Obsidian LLM Wiki workflow for organizing, ingesting, maintaining, and querying personal knowledge bases.

This repository is not an Obsidian plugin. It is a set of Codex/agent skills and workflow documents for turning an existing Obsidian vault, plus external document folders, into a safer and more useful LLM-facing knowledge wiki.

## Why This Exists

Many personal knowledge bases are not clean, new systems. They usually contain:

- existing Obsidian notes with uneven structure
- project notes, meeting notes, drafts, exports, PDFs, Word files, spreadsheets, and code docs
- external folders that should be indexed before anything is copied
- sensitive material that should never be blindly summarized into a wiki

`obsidian-llm-wiki` provides a cautious workflow:

```text
initialize -> ingest -> maintain -> query
```

## First-Version Skills

| Skill | Purpose |
|---|---|
| `obsidian-wiki-init` | Initialize or adopt an Obsidian vault, create a wiki control center, inventory the vault, and establish rules. |
| `obsidian-wiki-ingest` | Convert existing vault content or external folders into wiki pages, with external files indexed by path by default. |
| `obsidian-wiki-maintain` | Run health checks for broken links, orphan pages, index/log drift, missing pages, and sensitive information spread. |
| `obsidian-wiki-query` | Answer questions from the wiki, summarize knowledge, generate outlines, and suggest durable pages to save. |

## Repository Layout

```text
docs/
  architecture.md
  workflow.md
  safety.md
  development-plan.md
skills/
  obsidian-wiki-init/
  obsidian-wiki-ingest/
  obsidian-wiki-maintain/
  obsidian-wiki-query/
```

Each skill has a `SKILL.md` file and a small `references/` folder. The skill files are intentionally instruction-first. Scripts can be added later for deterministic tasks such as directory scanning, link checking, and sensitive-pattern checks.

## Default Safety Position

- Do not delete or move user files.
- Do not copy external files into the vault by default.
- Treat external folders as untrusted until scanned and confirmed.
- Never copy secrets, tokens, credentials, cookies, private endpoints, production logs, or customer data into generated wiki pages.
- Prefer path-level indexing before summary ingestion.
- Copy files into `raw/` only after explicit user confirmation.

## Typical Usage

1. Use `obsidian-wiki-init` to adopt an existing vault and create the wiki control center.
2. Use `obsidian-wiki-ingest` to scan vault folders, `raw/`, or external directories and create source/topic/project/entity/SOP pages.
3. Use `obsidian-wiki-maintain` to check wiki health and repair structure after confirmation.
4. Use `obsidian-wiki-query` to answer questions from the wiki and save durable outputs.

## Status

This is the first documentation-based MVP. The current goal is to make the skill boundaries, workflows, output formats, and safety rules clear before adding automation scripts.
