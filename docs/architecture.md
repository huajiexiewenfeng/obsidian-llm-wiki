# Architecture

## Goal

`obsidian-llm-wiki` is designed for an existing Obsidian vault plus external document folders. It helps an AI agent organize notes into a structured LLM Wiki without blindly moving files or exposing sensitive content.

## Core Loop

```text
obsidian-wiki-init
  -> obsidian-wiki-ingest
  -> obsidian-wiki-maintain
  -> obsidian-wiki-query
```

## Skill Boundaries

### obsidian-wiki-init

Initializes or adopts a vault. It creates a control center, performs an inventory, and establishes rules.

It may create:

- `00-知识库中控/`
- `00-知识库中控/ingest/`
- `00-知识库中控/raw/`
- `00-知识库中控/wiki/`
- `00-知识库中控/wiki/index.md`
- `00-知识库中控/wiki/log.md`
- `00-知识库中控/wiki/AGENTS.md`
- `00.知识库地图.md`
- `00.整理范围确认.md`

It must not move, delete, or reorganize original user files.

### obsidian-wiki-ingest

Turns source material into wiki pages. Sources may come from:

- existing Obsidian folders
- files already placed in `raw/`
- a single external file
- one or more external directories
- an external path list

External sources are indexed by path by default. Path indexing still creates
Obsidian-visible source proxy nodes and graph links in the active Obsidian
control center. Summary ingestion and archival copying into `raw/` require
confirmation.

### obsidian-wiki-maintain

Checks and repairs wiki structure. It focuses on:

- broken links
- orphan pages
- index/log consistency
- missing topic/project/entity/SOP pages
- sensitive information spread
- stale or ambiguous source pages

Large repairs require user confirmation.

### obsidian-wiki-query

Answers questions from the wiki. It reads in this order:

```text
index.md
  -> relevant topic/project/entity/SOP/source pages
  -> original source material only when needed
```

Durable answers can be saved as synthesis, project, SOP, or outline pages.

## Wiki Page Types

The first version uses these page groups:

- `topics/`: durable subject areas
- `sources/`: source inventories, source proxy nodes, source summaries, and ingestion reports
- `projects/`: project-level knowledge
- `entities/`: systems, people, libraries, APIs, products, or concepts with stable identity
- `sops/`: repeatable procedures, checklists, prompts, and operational workflows
- `ingest/`: top-level ingest control-plane index, batch history, source path mappings, and processing status

## Why Four Skills

Four skills provide a complete loop without creating too many trigger boundaries:

- `init`: prepare the vault
- `ingest`: turn material into wiki pages
- `maintain`: keep the wiki healthy
- `query`: use the wiki for answers and synthesis

Future versions may split inventory, rules, and organize into separate skills if they become large enough.
