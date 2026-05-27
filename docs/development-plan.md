# Development Plan

## Phase 0: Repository Skeleton

Deliver:

- `README.md`
- `docs/architecture.md`
- `docs/workflow.md`
- `docs/safety.md`
- `docs/development-plan.md`
- four skill folders under `skills/`

Acceptance:

- The repository clearly says this is not an Obsidian plugin.
- A reader can understand the four-skill loop from the README.
- Safety rules are documented once and referenced by all skills.

## Phase 1: obsidian-wiki-init

Deliver:

- `skills/obsidian-wiki-init/SKILL.md`
- `references/vault-structure.md`
- `references/page-templates.md`
- `references/safety-rules.md`

Acceptance prompts:

```text
Initialize the current Obsidian vault as an LLM Wiki. Create the control center and map the vault, but do not move any existing files.
```

```text
Only scan the vault folder structure and file types. Do not read note bodies yet.
```

```text
My Obsidian vault already has many folders. After init, guide me step by step and recommend the first ingest batch.
```

## Phase 2: obsidian-wiki-ingest

Deliver:

- `skills/obsidian-wiki-ingest/SKILL.md`
- `references/ingest-workflow.md`
- `references/supported-file-types.md`
- `references/ingest-report-template.md`
- `references/safety-rules.md`

Acceptance prompts:

```text
Scan these external folders and create an ingestion plan. Do not copy files into the vault yet.
```

```text
Ingest this confirmed PDF as a source summary and update any relevant topic or project pages.
```

```text
Archive these approved files into raw and then create an ingestion report.
```

## Phase 3: obsidian-wiki-maintain

Deliver:

- `skills/obsidian-wiki-maintain/SKILL.md`
- `references/health-check-rules.md`
- `references/health-report-template.md`
- `references/safety-rules.md`

Acceptance prompts:

```text
Run a health check on the current wiki and report Errors, Warnings, and Info.
```

```text
Find pages missing from index.md and propose narrow fixes.
```

## Phase 4: obsidian-wiki-query

Deliver:

- `skills/obsidian-wiki-query/SKILL.md`
- `references/query-workflow.md`
- `references/answer-format.md`
- `references/synthesis-rules.md`

Acceptance prompts:

```text
Based on the current wiki, summarize the video stream low-latency troubleshooting path.
```

```text
Use my knowledge base to create a team AI productivity talk outline.
```

## Phase 5: Manual Trial

Run the skills against a real or sample vault:

```text
init -> ingest -> maintain -> query
```

Record:

- what triggered correctly
- what triggered ambiguously
- where confirmation was missing
- what output format needs refinement

## Phase 6: Optional Scripts

Add scripts only after the manual workflow is stable.

Candidate scripts:

- directory inventory
- candidate file scanner
- ingestion plan generator
- markdown link checker
- sensitive-pattern scanner
- health report generator
