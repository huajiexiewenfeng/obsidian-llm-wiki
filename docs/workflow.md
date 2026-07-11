# Workflow

## 1. Initialize

Use `obsidian-wiki-init` when adopting or preparing a vault.

Expected flow:

```text
detect vault
  -> create control center if missing
  -> create wiki folders
  -> preview state init
  -> confirm and create .meta state
  -> create index/log/AGENTS
  -> inventory vault structure
  -> generate knowledge map and scope confirmation
  -> generate LLM Wiki roadmap
  -> recommend the first ingest batch
```

The init step should be conservative. It creates structure and maps the current state, but does not rewrite the vault.

`state init` is dry-run by default:

```text
python scripts/llm_wiki.py state init --root <vault-or-control-center> --format json
python scripts/llm_wiki.py state init --root <vault-or-control-center> --confirm --format json
```

The confirmed command creates `.meta` schema, source/page registries,
operations, and change-log state through the shared lock and atomic writer. It
does not ingest sources or make Markdown projections authoritative. Phase 3
will connect semantic ingest to these contracts through `ingest apply`.

For existing vaults with many files, initialization must also act as onboarding. It should guide the user into a step-by-step build path instead of leaving them with empty folders.

Expected onboarding outputs:

- `00.知识库地图.md`
- `00.整理范围确认.md`
- `00.LLM Wiki 建设路线图.md`

The final init response should recommend 1-3 first ingest candidates and ask the user which batch to process first.

## 2. Ingest

Use `obsidian-wiki-ingest` when turning material into wiki pages.

Expected flow:

```text
read requested source path(s)
  -> resolve active Obsidian control center
  -> scan candidate files
  -> filter irrelevant files
  -> flag sensitive, duplicate, binary, and large files
  -> generate an ingestion plan
  -> wait for user confirmation
  -> process approved material
  -> update top-level ingest/index.md
  -> create or update source proxy nodes
  -> create or update topic/project/entity/SOP links
  -> update index.md and log.md
  -> write an ingestion report
```

Default external-folder mode:

```text
path index only
```

This means the skill records where files are, creates Obsidian-visible proxy
nodes and links in the active vault, but does not copy the original files into
the vault.

Minimum path-index graph:

```text
ingest/index.md
  -> sources/<external-document-proxy>.md
  -> topics/projects/entities/sops
```

## 3. Doctor

Use `obsidian-wiki-doctor` when diagnosing wiki structure, validating a root,
scoring maturity, producing a report, or investigating whether query quality is
limited by wiki coverage.

Expected flow:

```text
resolve vault, control center, and wiki root through the shared Root Resolver
  -> run read-only doctor checks
  -> classify findings as Errors or Warnings, with not-applicable score dimensions when signals are absent
  -> compute directional score
  -> report evidence and redacted paths
  -> hand repair scope to maintain when the user approves fixes
```

Before every read or write workflow, resolve with the same order: explicit path,
nearest `.obsidian-llm-wiki.json`, `OBSIDIAN_LLM_WIKI_ROOT`, then exactly one
active user-configured Vault. Use `python scripts/llm_wiki.py root resolve --cwd . --format json` to inspect it without writing.

Doctor is for measurement and diagnosis. It must not edit vault files.

## 4. Maintain

Use `obsidian-wiki-maintain` to apply confirmed repairs.

Expected flow:

```text
read doctor findings or explicit repair request
  -> resolve active wiki root
  -> restate approved repair scope
  -> ask before broad repairs or sensitive cleanup
  -> apply approved narrow fixes
  -> update log.md
  -> report changed files and remaining risks
```

Maintain is for repair, not diagnosis or answering knowledge questions.

## 5. Query

Use `obsidian-wiki-query` when the user asks a question that should be answered from the wiki.

Expected flow:

```text
read index.md
  -> identify relevant wiki pages
  -> read relevant pages
  -> answer with citations to wiki pages
  -> state evidence gaps
  -> optionally save durable output
```

Query is for using the knowledge base. It can suggest new pages but should not silently create them unless the user asks.

## Recommended First Test Run

1. Run init on a small sample vault.
2. Review the generated roadmap and choose the first ingest batch.
3. Ingest one existing Obsidian folder.
4. Ingest one external folder in path-index mode.
5. Run doctor and review the report.
6. Apply one approved maintain repair if the report identifies a narrow fix.
7. Ask a query that requires reading topic, source, and SOP pages.
