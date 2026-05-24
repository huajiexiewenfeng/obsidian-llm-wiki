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

Expected:

- creates or updates control-center structure
- inventories vault safely
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

Expected:

- defaults external folders to path-index mode
- asks before copying into `raw/`
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
- cites relevant wiki pages
- states evidence gaps
- suggests saving durable synthesis only when useful
