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
| Archive import | Copy approved files into `raw/`, then summarize | Yes |

Default mode: path index.

Path index does not mean "filesystem only." It means raw content stays outside
the vault, while Obsidian receives source index/summary pages and durable links
so query workflows can discover the material from `index.md`.

The ingest control-plane index belongs outside the wiki knowledge folders. Use
top-level `ingest/index.md` to record batches and document-level source mappings.
Do not put this global ingest index under `sources/`.

## Steps

```text
source paths
  -> candidate scan
  -> irrelevant-file filter
  -> sensitivity and duplicate flagging
  -> topic/type/risk grouping
  -> ingestion plan
  -> confirmation
  -> approved processing
  -> top-level ingest/index.md update
  -> source index/summary generation
  -> related topic/project/entity/SOP link update
  -> index/log update
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

1. Create or update a `sources/<name>-summary.md` or
   `sources/<name>-资料索引.md` page.
   - For approved individual documents, prefer one source proxy node per
     document when practical.
   - For large folders or many low-value files, one source proxy node per
     coherent document group is acceptable.
2. Create or update top-level `ingest/index.md` with:
   - ingest batch
   - source path
   - wiki entry
   - processing mode
   - status
   - gaps or confirmation needed
3. Include in source pages:
   - original external path
   - processing mode: path-index, summary-ingest, or archive-import
   - import status
   - sensitivity/risk note
   - short summary or cautious description
   - key topics
   - useful-for section
   - related wiki links
4. Update `index.md` so the source page and `ingest/index.md` are discoverable from the wiki root.
5. Update durable related pages under `topics/`, `projects/`, `entities/`, or
   `sops/` with a backlink to the source page when the relationship is clear.
6. If the relationship is uncertain, list candidate links in the ingestion
   report instead of editing broad pages.

Minimum successful path-index output:

```text
external file/folder remains in place
ingest/index.md lists the batch and document mapping
sources/<source-name>-summary-or-index.md exists
approved external documents have source proxy nodes or an explicit grouping reason
index.md links to that source page
ingestion report lists graph links updated or intentionally deferred
```
