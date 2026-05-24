# Vault Structure

Default control center:

```text
00-知识库中控/
  raw/
  wiki/
    index.md
    log.md
    AGENTS.md
    topics/
    sources/
    entities/
    projects/
    sops/
```

Top-level inventory files:

```text
00.知识库地图.md
00.整理范围确认.md
```

## Directory Purpose

- `raw/`: confirmed source archive. Do not treat this as a dumping ground.
- `wiki/index.md`: main navigation and wiki inventory.
- `wiki/log.md`: chronological change log.
- `wiki/AGENTS.md`: local operating rules for AI agents.
- `topics/`: durable subject pages.
- `sources/`: source indexes, ingestion plans, and ingestion reports.
- `entities/`: systems, APIs, tools, concepts, and people.
- `projects/`: project-level pages.
- `sops/`: procedures, checklists, prompts, and workflows.
