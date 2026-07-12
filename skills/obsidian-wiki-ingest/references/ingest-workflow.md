# Ingest Workflow

## Input Types

- single Markdown/TXT/PDF/Word/Excel/CSV file
- single directory
- multiple directories
- external path list
- new files under `raw/`
- existing Obsidian folder

## Modes

| Mode | Behavior | Copies files into vault |
|---|---|---|
| Path index | Record where files are, what they are, topic, risk, recommendation, and wiki graph links | No |
| Summary ingest | Read approved content and create wiki summaries | Optional |
| Archive import | Phase 3.1 only; Phase 3 returns `unsupported-mode` | Not in Phase 3 |

Default mode: path index.

## Target Resolution

Before writing generated pages, resolve the actual Obsidian control center.

Preferred target:

```text
<Obsidian Vault>/00-知识库中控/
  ingest/index.md
  wiki/index.md
  wiki/log.md
  wiki/sources/
  wiki/topics/
  wiki/projects/
  wiki/entities/
  wiki/sops/
```

Rules:

- Do not assume the current shell workspace is the Obsidian vault.
- Search for an existing `00-知识库中控/wiki/index.md` when the target is not
  explicit.
- If multiple candidates exist, ask the user which vault is active.
- Write generated source proxy, topic, project, entity, and SOP pages into the
  selected Obsidian `wiki/` tree.
- Write the ingest control-plane index into `<control-center>/ingest/index.md`.

Path index does not mean "filesystem only." It means raw content stays outside
the vault, while Obsidian receives source index/summary pages and durable links
so query workflows can discover the material from `index.md`.

The ingest control-plane index belongs outside the wiki knowledge folders. Use
top-level `ingest/index.md` to record batches and document-level source mappings.
Do not put this global ingest index under `sources/`.

## Steps

```text
source paths
  -> target Obsidian control center resolution
  -> candidate scan
  -> irrelevant-file filter
  -> sensitivity and duplicate flagging
  -> topic/type/risk grouping
  -> ingestion plan
  -> confirmation
  -> approved source read and payload generation outside the Core lock
  -> ingest apply dry-run
  -> user confirms the exact plan checksum
  -> ingest apply --confirm
  -> deterministic registry/page/projection transaction
  -> Doctor validation
  -> ingestion report
```

## Candidate Metadata

Record:

- path
- name
- type
- size
- modified time
- parent folder
- initial topic guess
- sensitivity risk
- duplicate suspicion
- recommended mode
- planned wiki page path
- ingest index entry
- related wiki pages to link
- graph update status

## Groups

- ready for summary
- path index only
- needs confirmation
- sensitive or cautious
- skip for now

## Graph-First Processing

For each approved external source or source group:

1. Create or update a `<control-center>/wiki/sources/<name>-summary.md` or
   `<control-center>/wiki/sources/<name>-资料索引.md` page.
   - For approved individual documents, prefer one source proxy node per
     document when practical.
   - For large folders or many low-value files, one source proxy node per
     coherent document group is acceptable.
2. Create or update `<control-center>/ingest/index.md` with:
   - ingest batch
   - source path
   - wiki entry
   - processing mode
   - status
   - gaps or confirmation needed
3. Put the generated managed source-page content into the operation payload:
   - original external path
   - processing mode: path-index, summary-ingest, or archive-import
   - import status
   - sensitivity/risk note
   - short summary or cautious description
   - key topics
   - useful-for section
   - related wiki links
4. Let Core derive `<control-center>/wiki/index.md`, `ingest/index.md`, and
   `wiki/log.md` from registries and change log. Do not supply projection bodies.
5. Put durable related topic/project/entity/SOP managed bodies into the same
   payload when the relationship is clear.
6. If the relationship is uncertain, list candidate links in the ingestion
   report instead of editing broad pages.

Minimum successful path-index output:

```text
external file/folder remains in place
<control-center>/ingest/index.md lists the batch and document mapping
<control-center>/wiki/sources/<source-name>-summary-or-index.md exists
approved external documents have source proxy nodes or an explicit grouping reason
<control-center>/wiki/index.md links to that source page or ingest index
ingestion report lists graph links updated or intentionally deferred
```

## Deterministic Apply Contract

- One payload represents one confirmed source.
- It contains exactly one `role: source-proxy` page and zero or more derived pages.
- Supported modes are `path-index` and `summary-ingest`.
- Preview is mandatory and writes nothing.
- Confirmed execution must reuse the same payload and returned `plan_checksum`.
- Existing managed pages require `expected_managed_checksum`; missing markers
  require takeover for that exact page or projection path.
- File and stdin payloads use the same parser; generated bodies are not echoed
  in public plan/error JSON.
