---
name: obsidian-wiki-init
description: Use this whenever the user wants to initialize, adopt, map, or set rules for an Obsidian vault as an LLM Wiki. Trigger on requests like "initialize Obsidian LLM Wiki", "adopt this vault", "create a knowledge center", "generate a knowledge map", "scan my vault", or "set Obsidian wiki rules". This skill creates structure and inventory only; it must not move or delete existing user files.
---

# Obsidian Wiki Init

Initialize or adopt an Obsidian vault as an LLM Wiki.

## When To Use

Use this skill when the user wants to:

- create the wiki control center
- adopt an existing Obsidian vault
- generate a vault inventory or knowledge map
- establish wiki page and safety rules
- prepare the vault before ingesting content

Do not use this skill for answering knowledge questions. Use `obsidian-wiki-query` for that.

## Required Context

Before writing files, inspect:

- current working directory
- whether it appears to be an Obsidian vault
- existing `00-知识库中控/`, `index.md`, `log.md`, or `AGENTS.md`
- whether the user requested full scanning or structure-only scanning

## Workflow

1. Confirm the target vault path from context or user instruction.
2. Check for existing wiki control files.
3. Create missing control structure conservatively.
4. Inventory directories and file types.
5. Generate or update:
   - `00-知识库中控/wiki/index.md`
   - `00-知识库中控/wiki/log.md`
   - `00-知识库中控/wiki/AGENTS.md`
   - `00.知识库地图.md`
   - `00.整理范围确认.md`
6. Record assumptions and next steps.

## Output Files

Use the structure in `references/vault-structure.md`.

Use the templates in `references/page-templates.md`.

## Safety Rules

Follow `references/safety-rules.md`.

Key points:

- Do not move existing notes.
- Do not delete existing notes.
- Do not rewrite original notes.
- Do not copy secrets into generated wiki pages.
- If the user asks for structure-only scanning, do not read note bodies.

## Confirmation Points

Ask for confirmation before:

- scanning very large folders deeply
- reading note bodies when the user asked for metadata-only inventory
- changing existing wiki rules
- replacing an existing index, log, or AGENTS file

## Report Format

End with:

```markdown
## Init Summary
- Vault:
- Created:
- Updated:
- Inventory:
- Skipped:
- Risks:
- Next:
```

## Examples

Input:

```text
Initialize the current Obsidian vault as an LLM Wiki. Do not move my existing files.
```

Expected behavior:

```text
Create missing control directories and files, generate a knowledge map and scope confirmation, and report that no existing files were moved.
```

Input:

```text
Only scan directory structure and file types.
```

Expected behavior:

```text
Produce a metadata-only inventory without reading note bodies.
```
