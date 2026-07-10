---
name: obsidian-wiki-init
description: Use this whenever the user wants to initialize, adopt, map, onboard, or set rules for an Obsidian vault as an LLM Wiki. Trigger on requests like "initialize Obsidian LLM Wiki", "adopt this vault", "create a knowledge center", "generate a knowledge map", "scan my vault", "guide me step by step", or "set Obsidian wiki rules". This skill creates structure, inventories existing content, generates an onboarding roadmap, and guides the user toward the first ingest batch. It must not move or delete existing user files.
---


## First-Use Vault Setup

Treat root configuration as background setup, not a JSON-file task for the user. If normal resolution has no root, run `python scripts/llm_wiki.py root discover --format json`. Show returned existing absolute paths as numbered candidates and ask the user to select one or provide another absolute Vault path. Resolve the selected path and state `vault_root`, `control_center`, and `wiki_root`. Only after the user confirms it should become the default, run `root configure --root <path> --activate --confirm`.

Do not read note content or scan the whole disk during discovery. Continue the user's original request after setup succeeds.
# Obsidian Wiki Init

Initialize or adopt an Obsidian vault as an LLM Wiki, then guide the user into the first knowledge-building steps.

## When To Use

Use this skill when the user wants to:

- create the wiki control center
- adopt an existing Obsidian vault
- generate a vault inventory or knowledge map
- establish wiki page and safety rules
- prepare the vault before ingesting content
- create a step-by-step roadmap for building the wiki from an existing vault
- decide what to ingest first when the vault already contains many notes

Do not use this skill for answering knowledge questions. Use `obsidian-wiki-query` for that.

## Required Context

Before writing files, inspect:

- current working directory
- whether it appears to be an Obsidian vault
- existing `00-知识库中控/`, `index.md`, `log.md`, or `AGENTS.md`
- existing `00-知识库中控/ingest/index.md`
- whether the user requested full scanning or structure-only scanning

## Wiki Root Resolution

Before writing, resolve and state `vault_root`, `control_center`, and
`wiki_root` using this shared order:

1. User-provided Vault, control-center, or wiki path.
2. Nearest `.obsidian-llm-wiki.json` from the current working directory upward.
3. `OBSIDIAN_LLM_WIKI_ROOT`.
4. Exactly one active Vault in the user configuration.
5. Otherwise stop with `missing-config` or ask the user to choose when multiple roots exist.

Do not search the whole disk. For init, the confirmed target may be a new Vault
whose control center does not yet exist; create it only after the user confirms
the resolved Vault. Before writing, run or follow the equivalent of:

```text
python scripts/llm_wiki.py root resolve --cwd <working-directory> --format json
```

## Workflow

1. Confirm the target vault path from context or user instruction.
2. Check for existing wiki control files.
3. Create missing control structure conservatively.
4. Inventory directories and file types.
5. Classify the vault into practical next-step buckets:
   - high-value / frequently used
   - project material
   - learning material
   - temporary or messy material
   - sensitive or cautious material
   - external-material candidates
6. Generate or update:
   - `00-知识库中控/wiki/index.md`
   - `00-知识库中控/wiki/log.md`
   - `00-知识库中控/wiki/AGENTS.md`
   - `00-知识库中控/ingest/index.md`
   - `00.知识库地图.md`
   - `00.整理范围确认.md`
   - `00.LLM Wiki 建设路线图.md`
7. Do not vendor doctor scripts or deterministic enforcement files into the
   vault in V0. Use the installed repository skill and `scripts/` tooling.
8. Recommend running `obsidian-wiki-doctor` after initialization to validate
   the structure and produce a read-only report.
9. Recommend the first 1-3 ingest candidates and ask which batch to process with `obsidian-wiki-ingest`.

## Output Files

Use the structure in `references/vault-structure.md`.

Use the templates in `references/page-templates.md`.

Use `references/onboarding-roadmap.md` when generating `00.LLM Wiki 建设路线图.md` and the final guidance message.

## Safety Rules

Follow `references/safety-rules.md`.

Key points:

- Do not move existing notes.
- Do not delete existing notes.
- Do not rewrite original notes.
- Do not copy secrets into generated wiki pages.
- If the user asks for structure-only scanning, do not read note bodies.
- Existing vaults should be guided progressively. Do not suggest full-vault ingestion as the default next step.

## Confirmation Points

Ask for confirmation before:

- scanning very large folders deeply
- reading note bodies when the user asked for metadata-only inventory
- changing existing wiki rules
- replacing an existing index, log, or AGENTS file
- proceeding from inventory into the first ingest batch
- reading note bodies when the next step can be decided from directory names and metadata

## Report Format

End with:

```markdown
## Init Summary
- Vault:
- Created:
- Updated:
- Inventory:
- Roadmap:
- Recommended first batch:
- Skipped:
- Doctor recommendation:
- Risks:
- Next:
```

The `Next` field should be a concrete onboarding question, not a generic completion message. Example:

```text
I recommend starting with one of these first ingest batches:
1. 高频使用目录
2. 项目资料目录
3. 学习资料目录

Before ingest, I recommend running obsidian-wiki-doctor once to validate the new structure. Which batch should we process first with obsidian-wiki-ingest after that?
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

Input:

```text
My Obsidian vault already has many folders. Guide me step by step to build the LLM Wiki after initialization.
```

Expected behavior:

```text
Generate a roadmap, classify the vault into first-batch candidates, and ask the user which batch to ingest first.
```
