# Test Prompts

Use these prompts to manually evaluate whether each skill triggers correctly and follows its boundaries.

## obsidian-wiki-init

```text
Initialize the current Obsidian vault as an LLM Wiki. Create the control center and map the vault, but do not move any existing files.
```

```text
Only scan this vault's folder structure and file types. Do not read note bodies yet.
```

```text
Adopt this existing Obsidian vault and create index.md, log.md, AGENTS.md, a knowledge map, and a scope confirmation document.
```

```text
My Obsidian vault already has many folders. After initialization, guide me step by step and recommend what to ingest first.
```

Expected:

- creates or updates control-center structure
- inventories vault safely
- creates an LLM Wiki roadmap
- recommends a first ingest batch
- does not move, delete, or rewrite existing notes

## obsidian-wiki-ingest

```text
Scan D:\资料 and D:\Downloads and create an ingestion plan. Do not copy anything into the vault yet.
```

```text
Ingest this confirmed PDF as a source summary and update relevant topic or project pages if needed.
```

```text
Archive these approved files into raw and then generate an ingestion report.
```

```text
Ingest D:\projects\mas对接 without moving original files. Obsidian must show an ingest index, source proxy nodes for approved documents, and graph links from index/topic/project/SOP pages so query can find the external documents later.
```

```text
My shell workspace is C:\Users\admin\Documents\New project 2, but my active Obsidian vault is C:\Users\admin\Documents\Obsidian Vault\00-知识库中控. Ingest D:\projects\mas对接. Do not write only into the project workspace; update the vault's ingest/index.md and wiki pages.
```

Expected:

- defaults external folders to path-index mode
- resolves the active Obsidian control center before writing
- asks before copying into `raw/`
- creates or updates top-level `<control-center>/ingest/index.md`
- writes source proxy nodes under `<control-center>/wiki/sources/` for approved documents or explicit document groups
- links source proxy nodes from `<control-center>/wiki/index.md` and topic/project/entity/SOP pages so they appear in the Obsidian graph
- produces plan/report and updates wiki pages only after confirmation

## obsidian-wiki-maintain

```text
Run a health check on the current wiki and report Errors, Warnings, and Info.
```

```text
Find wiki pages missing from index.md and propose narrow fixes.
```

```text
Check whether generated wiki pages contain sensitive information. Do not print secret values.
```

Expected:

- reports structural health
- does not answer domain questions
- does not print secret values
- checks `ingest/index.md` consistency with source proxy nodes when present
- asks before broad repairs

## obsidian-wiki-query

```text
Based on the current wiki, summarize the video stream low-latency troubleshooting path.
```

```text
Use my knowledge base to create a team AI productivity talk outline.
```

```text
From my Obsidian wiki, what do my notes say about external document ingestion?
```

Expected:

- reads `index.md` first
- reads `ingest/index.md` when the question is about ingested or external documents
- cites relevant wiki pages
- states evidence gaps
- suggests saving durable synthesis only when useful
