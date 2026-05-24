# Query Workflow

## Inputs

- user question
- optional scope: all wiki, topic, project, source, entity, SOP
- optional output type: answer, summary, outline, plan, checklist, synthesis
- optional save-back instruction

## Steps

```text
read index.md
  -> identify relevant page groups
  -> read relevant wiki pages
  -> check whether evidence is enough
  -> read source/raw material only when needed
  -> answer with page references
  -> suggest save-back when durable
```

## Evidence Preference

1. `index.md`
2. `topics/`
3. `projects/`
4. `entities/`
5. `sops/`
6. `sources/`
7. `raw/` or original external files

Do not skip directly to raw files unless wiki pages are missing or insufficient.

## Scope Handling

If the user gives a scope, stay inside it unless evidence is insufficient.

If scope is unclear, start from `index.md` and infer likely relevant pages.
