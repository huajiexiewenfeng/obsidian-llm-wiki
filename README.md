# Obsidian LLM Wiki

[![test](https://github.com/huajiexiewenfeng/obsidian-llm-wiki/actions/workflows/test.yml/badge.svg)](https://github.com/huajiexiewenfeng/obsidian-llm-wiki/actions/workflows/test.yml)

AI-assisted Obsidian LLM Wiki skills for organizing existing vaults, ingesting external documents, diagnosing wiki structure, applying approved repairs, and querying a personal knowledge base.

English | [简体中文](./README.zh.md)

## What Is This?

Obsidian LLM Wiki is a workflow and skill set for turning an existing Obsidian vault into a safer, more structured, AI-readable knowledge wiki.

It is not an Obsidian plugin. It is a set of Codex/agent skills and workflow documents that help an AI assistant work with your vault in a controlled way:

```text
initialize -> ingest -> doctor -> maintain -> query
```

The goal is not to dump every file into Obsidian. The goal is to build a careful knowledge layer on top of your real notes, project files, and external folders.

## Why It Exists

Most personal knowledge bases are messy in real life:

- 60% of useful material may already live in Obsidian.
- The rest may be scattered across Downloads, project folders, meeting exports, PDFs, Word files, spreadsheets, and code repositories.
- Some files are useful as references but should not be copied into the vault.
- Some files contain secrets, internal addresses, credentials, customer data, or production logs.

Obsidian LLM Wiki is designed for that reality.

It starts with inventory and confirmation, then turns selected material into wiki-visible nodes such as ingest indexes, source proxy pages, topics, projects, entities, SOPs, and checklists.

## Core Architecture

The first version uses five skills:

| Skill | Use When |
|---|---|
| `obsidian-wiki-init` | Initialize or adopt an Obsidian vault, create a wiki control center, inventory the vault, establish rules, and generate an onboarding roadmap |
| `obsidian-wiki-ingest` | Organize existing vault folders or ingest external files and directories into wiki pages |
| `obsidian-wiki-doctor` | Diagnose, validate, score, and report on wiki structure and maturity without editing files |
| `obsidian-wiki-maintain` | Apply approved repairs from a doctor report, such as narrow index, link, log, or source-proxy updates |
| `obsidian-wiki-query` | Answer questions from the wiki, summarize knowledge, generate outlines, and suggest durable pages to save |

The skills are intentionally split by user intent:

```text
init      = prepare the vault
ingest    = turn material into wiki pages
doctor    = diagnose, validate, score, and report
maintain  = apply approved structural repairs
query     = use the wiki for answers and synthesis
```

## External Document Ingestion

External folders are handled cautiously.

The default mode is path indexing:

```text
scan external paths
-> classify files by topic, type, risk, and value
-> generate an ingestion plan
-> wait for confirmation
-> process only approved material
```

Supported modes:

| Mode | Behavior | Copies Files Into Vault |
|---|---|---|
| Path index | Record where files are and create wiki-visible source proxy nodes with graph links | No |
| Summary ingest | Read approved content and create source/topic/project pages | Optional |
| Archive import | Copy approved files into `raw/`, then process them | Yes |

External files are never copied into `raw/` by default.

Path index is still an Obsidian graph operation:

- The active Obsidian control center must be resolved before writing. Do not
  satisfy ingest by writing only into the current shell/project workspace.
- `ingest/index.md` records ingest batches, source paths, wiki entries, status, and gaps.
- `sources/<name>.md` acts as the source proxy node for an external document or coherent document group.
- `index.md`, topic, project, entity, and SOP pages link to those proxy nodes so they appear in the Obsidian graph and can be reached by query workflows.

## Safety Model

All skills follow the same safety stance:

- Do not delete or move user files.
- Do not rewrite original notes unless explicitly requested.
- Do not copy external files into the vault by default.
- Do not copy API keys, tokens, passwords, AK/SK pairs, cookies, private keys, certificates, RTSP credentials, internal endpoints, customer data, or production logs into generated wiki pages.
- Treat suspicious files as path-level references until confirmed.
- Ask before reading PDFs, Word files, spreadsheets, archives, or sensitive-looking folders deeply.

Generated wiki pages should preserve knowledge structure, not secrets.

## Installation

Install with Skills CLI:

```bash
npx skills add huajiexiewenfeng/obsidian-llm-wiki
```

For local development from the repository root:

```bash
npx skills add .
```

The complete repository install includes the shared `obsidian-wiki-runtime`
skill. It carries the Python files used by root resolution and Wiki Doctor.
Install the complete skill set; installing only a workflow skill leaves its
runtime dependency unavailable.

Verify a local checkout before publishing with:

```bash
npx skills add . --skill '*' --agent codex --copy --yes
```

After installation, restart Codex or your agent runtime so the skills can be rediscovered.

### Root configuration

Runtime requirement: Python 3.10 or newer. When a Vault is not supplied
explicitly, create `.obsidian-llm-wiki.json` in the working project:

```json
{
  "schema_version": 1,
  "vault_root": "D:/notes/My Vault",
  "control_center": "00-知识库中控",
  "active": true
}
```

Resolve without writing:

```text
python scripts/llm_wiki.py root resolve --cwd . --format json
```

Resolution order is explicit path, nearest project configuration, environment,
then exactly one active user-configured Vault. The tools never scan the whole disk.

### State initialization

Phase 2 adds a machine-state foundation under `00-知识库中控/.meta/`. Preview
the operation first, then confirm explicitly:

```text
python scripts/llm_wiki.py state init --root <vault-or-control-center> --format json
python scripts/llm_wiki.py state init --root <vault-or-control-center> --confirm --format json
```

The first command is read-only. The confirmed command creates versioned source,
page, operation, and change-log state through the shared lock and atomic writer.
`.meta/sources.json` and `.meta/pages.json` are the machine-state authority for
later phases; `ingest/index.md`, `wiki/index.md`, and `wiki/log.md` remain
human-readable projections. State initialization alone does not mean that any
source has been ingested.

## Usage Examples

### First-use Vault setup

You do not need to create JSON configuration first. If no Wiki is configured,
the Skill reads Obsidian recent-Vault metadata, shows existing absolute paths,
and asks you to choose one. After you confirm, it saves that Vault as your
default and continues the request. Discovery never reads notes or scans the
whole disk.

Use it naturally:

```text
Initialize the current Obsidian vault as an LLM Wiki.
```

```text
My Obsidian vault already has many folders. Guide me step by step and recommend the first ingest batch.
```

```text
Only scan the vault folder structure and file types. Do not read note bodies yet.
```

```text
Scan D:\资料 and D:\Downloads and create an ingestion plan. Do not copy anything into the vault yet.
```

```text
Ingest this confirmed PDF as a source summary and update relevant topic or project pages.
```

```text
Run Obsidian Wiki Doctor on the current wiki and report Errors, Warnings, not-applicable dimensions, and score.
```

```text
Based on the current wiki, summarize the video stream low-latency troubleshooting path.
```

Or force a specific skill:

```text
Use obsidian-wiki-ingest to scan these external folders in path-index mode.
```

```text
Use obsidian-wiki-query to answer this from my Obsidian wiki.
```

## How to Know It Is Working

Obsidian LLM Wiki is working when:

- Existing notes are not moved or rewritten without permission.
- External folders are scanned and planned before files are copied or summarized.
- Sensitive values are not reproduced in generated wiki pages.
- `index.md` becomes the main navigation entry for the wiki.
- `ingest/index.md` becomes the ingest control-plane index.
- Source proxy pages explain where external material came from and how it was handled.
- Topic, project, entity, and SOP pages become easier to query than raw scattered notes.
- Doctor reports produce clear Errors, Warnings, not-applicable dimensions, and score instead of vague advice.
- Maintain applies only approved repairs from confirmed findings.
- Query answers cite wiki pages and state evidence gaps.

## Project Structure

```text
skills/
  obsidian-wiki-init/
  obsidian-wiki-ingest/
  obsidian-wiki-maintain/
  obsidian-wiki-doctor/
  obsidian-wiki-query/
  obsidian-wiki-runtime/
    scripts/
      llm_wiki.py
      obsidian_wiki_doctor.py
      llm_wiki_core/
        root.py
        state.py
        writer.py
        managed.py

docs/
  architecture.md
  workflow.md
  safety.md
  development-plan.md

scripts/
  llm_wiki.py
  obsidian_wiki_doctor.py

tests/
  prompts.md
```

## Documentation

- [Architecture](docs/architecture.md)
- [Workflow](docs/workflow.md)
- [Safety](docs/safety.md)
- [Development Plan](docs/development-plan.md)
- [Test Prompts](tests/prompts.md)

## Status

This project is in an early documentation-based MVP stage.

The current focus is to make the skill boundaries, workflows, output formats, and safety rules clear. The doctor script is the first deterministic validation and scoring surface; additional deterministic helpers may be added after the manual workflow is stable.

## License

MIT
