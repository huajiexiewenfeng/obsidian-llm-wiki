# Development Plan

## Phase 0: Repository Skeleton

Deliver:

- `README.md`
- `docs/architecture.md`
- `docs/workflow.md`
- `docs/safety.md`
- `docs/development-plan.md`
- five skill folders under `skills/`

Acceptance:

- The repository clearly says this is not an Obsidian plugin.
- A reader can understand the five-skill model from the README.
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

Acceptance:

- Creates `00-知识库中控/ingest/index.md` as part of the control center.
- Creates `00-知识库中控/wiki/index.md`, `log.md`, and `AGENTS.md`.
- Creates `00.LLM Wiki 建设路线图.md`.
- Recommends the first ingest batch instead of suggesting full-vault ingestion.
- Does not move, delete, or rewrite original notes.

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

```text
My shell workspace is not my Obsidian vault. Ingest this external folder into my active Obsidian control center without moving original files.
```

Acceptance:

- Resolves the active Obsidian control center before writing.
- Updates `<control-center>/ingest/index.md`.
- Writes source proxy nodes under `<control-center>/wiki/sources/`.
- Links source proxy nodes from `<control-center>/wiki/index.md` and related topic/project/entity/SOP pages.
- Does not copy external originals into `raw/` unless explicitly confirmed.

## Phase 3: obsidian-wiki-doctor

Deliver:

- `skills/obsidian-wiki-doctor/SKILL.md`
- `skills/obsidian-wiki-doctor/references/doctor-checks.md`
- `skills/obsidian-wiki-doctor/references/report-template.md`
- `skills/obsidian-wiki-doctor/references/safety-rules.md`
- `scripts/obsidian_wiki_doctor.py`
- first deterministic unit-test surface for invalid roots, report output,
  validation exit behavior, redaction, and score dimensions

Acceptance prompts:

```text
Run Obsidian Wiki Doctor on the current wiki and give me a Chinese report.
```

```text
Validate this wiki root and fail on Errors.
```

```text
Is poor query quality here caused by missing wiki structure?
```

Acceptance:

- Doctor is read-only and never edits vault files.
- Invalid roots return a safe diagnostic instead of broad filesystem scanning.
- Reports redact sensitive values.
- Repair requests route to `obsidian-wiki-maintain`.

## Phase 4: obsidian-wiki-maintain

Deliver:

- `skills/obsidian-wiki-maintain/SKILL.md`
- `references/repair-policy.md`
- `references/safety-rules.md`

Acceptance prompts:

```text
Apply the doctor finding that specific wiki pages are missing from index.md.
```

```text
Apply approved doctor findings for ingest/index.md source proxy consistency.
```

Acceptance:

- Maintain consumes doctor findings or explicit user-approved repair scope.
- Maintain does not perform diagnosis, scoring, or reporting itself.
- Broad repairs require confirmation.

## Phase 5: obsidian-wiki-query

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

```text
What external documents have been ingested about MAS, and where are their source proxy nodes?
```

## Phase 6: Manual Trial

Run the skills against a real or sample vault:

```text
init -> ingest -> doctor -> maintain -> query
```

Record:

- what triggered correctly
- what triggered ambiguously
- whether doctor findings route to maintain only for approved repairs
- where confirmation was missing
- what output format needs refinement

## Phase 7: Optional Scripts

Add scripts only after the manual workflow is stable.

Candidate scripts:

- directory inventory
- candidate file scanner
- ingestion plan generator
- markdown link checker
- sensitive-pattern scanner
- health report generator
