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
| Path index | Record where files are, what they are, topic, risk, and recommendation | No |
| Summary ingest | Read approved content and create wiki summaries | Optional |
| Archive import | Copy approved files into `raw/`, then summarize | Yes |

Default mode: path index.

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
  -> wiki page generation
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

## Groups

- ready for summary
- path index only
- needs confirmation
- sensitive or cautious
- skip for now
