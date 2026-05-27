# Workflow

## 1. Initialize

Use `obsidian-wiki-init` when adopting or preparing a vault.

Expected flow:

```text
detect vault
  -> create control center if missing
  -> create wiki folders
  -> create index/log/AGENTS
  -> inventory vault structure
  -> generate knowledge map and scope confirmation
  -> generate LLM Wiki roadmap
  -> recommend the first ingest batch
```

The init step should be conservative. It creates structure and maps the current state, but does not rewrite the vault.

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

## 3. Maintain

Use `obsidian-wiki-maintain` to keep the wiki coherent.

Expected flow:

```text
read index/log/wiki tree
  -> check links and page coverage
  -> classify findings as Errors, Warnings, or Info
  -> produce a health report
  -> ask before broad repairs
  -> apply approved narrow fixes
```

Maintain is for structure, not answering knowledge questions.

## 4. Query

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
5. Run maintain.
6. Ask a query that requires reading topic, source, and SOP pages.
