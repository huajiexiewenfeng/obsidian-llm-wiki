# Architecture

## Goal

`obsidian-llm-wiki` is designed for an existing Obsidian vault plus external document folders. It helps an AI agent organize notes into a structured LLM Wiki without blindly moving files or exposing sensitive content.

## Core Loop

The operating model has workflow skills plus a read-only measurement layer.

```text
obsidian-wiki-init
  -> obsidian-wiki-ingest
  -> obsidian-wiki-query

obsidian-wiki-doctor measures the wiki beside this loop.
obsidian-wiki-maintain applies approved repairs from doctor findings.
```

## Root Resolver Core

`skills/obsidian-wiki-runtime/scripts/llm_wiki_core/root.py` is the single Root
Resolver boundary for every workflow and Doctor invocation. It resolves an
explicit path, the nearest project `.obsidian-llm-wiki.json`,
`OBSIDIAN_LLM_WIKI_ROOT`, or exactly one active user-configured Vault in that
order. It returns a structured error rather than scanning the filesystem or
selecting between multiple Vaults.

## Runtime Packaging

`skills/obsidian-wiki-runtime/scripts/` is the canonical deterministic runtime.
Workflow skills locate it as a sibling beneath the installed skills root.
Repository-root `scripts/` files are compatibility launchers for development
and existing automation; they contain no runtime implementation.

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

### obsidian-wiki-doctor

Diagnoses the wiki without editing files. It validates structure, reports
deterministic findings, computes a directional maturity score, and explains
whether query quality problems are likely caused by missing wiki structure.

It is the measurement and diagnosis layer beside the loop. It can recommend
repair handoff, but repairs belong to `obsidian-wiki-maintain`.

### obsidian-wiki-maintain

Repairs confirmed wiki structure issues. It consumes doctor findings or a
user-approved repair request, then applies narrow changes such as:

- adding a missing page entry to `index.md`
- fixing an unambiguous internal wiki link
- updating `log.md` for a maintenance action
- correcting explicit `ingest/index.md` to source-proxy drift
- applying a narrow sensitive-cleanup request without printing secret values

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

## Why Five Workflow Skills

Five skills keep diagnosis separate from mutation:

- `init`: prepare the vault
- `ingest`: turn material into wiki pages
- `doctor`: measure, validate, score, and report without editing
- `maintain`: apply approved repairs after findings are confirmed
- `query`: use the wiki for answers and synthesis

`obsidian-wiki-runtime` is a shared installable dependency rather than a sixth
workflow. It packages root resolution and Doctor code so Skills CLI copies the
runtime together with the five workflow skills.

Future versions may split inventory, rules, and organize into separate skills if
they become large enough, but diagnosis and repair should remain separate.
