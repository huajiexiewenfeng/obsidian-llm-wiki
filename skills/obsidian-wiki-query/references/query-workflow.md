# Query Workflow

## Inputs

- user question
- optional scope: all wiki, topic, project, source, entity, SOP
- optional output type: answer, summary, outline, plan, checklist, synthesis
- optional save-back instruction

## Steps

```text
read wiki/index.md
  -> read ingest/index.md when the question may involve external/ingested documents
  -> identify relevant page groups
  -> read relevant wiki pages
  -> check whether evidence is enough
  -> read source/raw material only when needed
  -> answer with page references
  -> suggest save-back when durable
```

## Evidence Preference

1. `wiki/index.md`
2. `ingest/index.md` when external-source discovery or ingest status matters
3. `topics/`
4. `projects/`
5. `entities/`
6. `sops/`
7. `sources/`
8. `raw/` or original external files

Do not skip directly to raw files unless wiki pages are missing or insufficient.

## Scope Handling

If the user gives a scope, stay inside it unless evidence is insufficient.

If scope is unclear, start from `wiki/index.md` and infer likely relevant pages.
