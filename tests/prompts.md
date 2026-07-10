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
My shell workspace is C:\Users\<user>\Documents\project, but my active Obsidian vault is C:\Users\<user>\Documents\Obsidian Vault\00-知识库中控. Ingest D:\projects\mas对接. Do not write only into the project workspace; update the vault's ingest/index.md and wiki pages.
```

Expected:

- defaults external folders to path-index mode
- resolves the active Obsidian control center before writing
- asks before copying into `raw/`
- creates or updates top-level `<control-center>/ingest/index.md`
- writes source proxy nodes under `<control-center>/wiki/sources/` for approved documents or explicit document groups
- links source proxy nodes from `<control-center>/wiki/index.md` and topic/project/entity/SOP pages so they appear in the Obsidian graph
- produces plan/report and updates wiki pages only after confirmation

## obsidian-wiki-doctor

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
- routes repair work to `obsidian-wiki-maintain` only after findings are concrete

## obsidian-wiki-maintain

```text
Apply the doctor finding that wiki/projects/foo.md is missing from index.md.
```

```text
Patch only the confirmed broken relative link in wiki/topics/video.md to wiki/projects/streaming.md.
```

```text
Update log.md after applying the approved ingest/index.md consistency fix. Do not touch other files.
```

Expected:

- resolves and states the active Obsidian wiki root
- consumes doctor findings or user-approved structural fixes
- restates the repair scope in concrete file paths
- asks before broad repairs or sensitive cleanup
- updates `log.md` for applied maintenance
- returns changed files, skipped findings, and remaining risks
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

## Default Vault Discovery And Confirmation

Use this prompt group to evaluate the user-facing setup flow. These are the
primary acceptance tests for the new experience; the Python CLI tests are
developer regression coverage for the implementation underneath.

### First use: recent Vault candidates

Start with no project root configuration, no environment root, and no active
LLM Wiki user default. Then use one prompt from each Skill:

```text
Initialize an Obsidian LLM Wiki for me.
```

```text
Ingest this confirmed article into my LLM Wiki.
```

```text
Run Obsidian Wiki Doctor for me.
```

```text
Based on my LLM Wiki, summarize my recent notes.
```

Expected:

- the Skill does not ask the user to hand-write JSON configuration
- it discovers recent Obsidian Vault candidates without reading note bodies
- it displays existing candidates as numbered absolute paths, for example `1. D:\notes\Work Wiki`
- it asks the user to select a number or provide another absolute path
- it does not scan the whole disk
- it does not write a default configuration before the user confirms

### Confirmation and continuation

After the Skill displays candidates, reply with a selected path or candidate
number, then reply that it should become the default.

```text
Use 2. Set it as my default LLM Wiki, then continue the Doctor health check.
```

Expected:

- the Skill states the resolved `vault_root`, `control_center`, and `wiki_root`
- it saves the confirmed Vault as the user default in the background
- it continues the original request instead of ending after configuration
- Doctor remains read-only; Init, Ingest, and Maintain still follow their own confirmation rules before writes

### Existing default: no unnecessary interruption

In a new conversation, with a valid default Vault already saved, use:

```text
Run a health check on my wiki and give me the Chinese report.
```

Expected:

- the Skill resolves the saved default without asking the user to select it again
- it briefly states which absolute root it is using
- it proceeds directly to the requested Doctor report

### Explicit path overrides the default

```text
Use D:\another\Obsidian Vault for this one Doctor report. Do not change my default.
```

Expected:

- the supplied absolute path is used for this request
- the existing default Vault is not changed
- the Skill reports an invalid root safely if the path is not an LLM Wiki

### Switch default deliberately

```text
I want to use another Obsidian Vault from now on. Show available Vault paths and let me choose.
```

Expected:

- the Skill shows recent absolute-path candidates again
- it waits for explicit user confirmation before changing the default
- the newly selected Vault becomes active
- the previous default remains remembered but inactive

### No candidates or inaccessible metadata

```text
I have not configured an LLM Wiki yet. Help me run Doctor.
```

Expected:

- if no recent candidates are available, the Skill asks for one absolute Vault path
- it does not invent a path or scan arbitrary folders
- after the path is provided, it resolves and shows the three root paths before asking for confirmation
- if the path has no control center, Init may offer initialization; Doctor, Query, Ingest, and Maintain do not silently create one
