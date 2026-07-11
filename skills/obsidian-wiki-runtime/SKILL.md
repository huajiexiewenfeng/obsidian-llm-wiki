---
name: obsidian-wiki-runtime
description: Shared deterministic runtime dependency for the Obsidian LLM Wiki workflow skills. Use only when another obsidian-wiki skill needs root resolution or Doctor commands.
---

# Obsidian Wiki Runtime

This skill packages the shared Python runtime required by the Obsidian Wiki
workflow skills. It is an installable dependency, not a user-facing workflow.

## Runtime Entry Point

Resolve this skill directory and invoke:

```text
python <this-skill-directory>/scripts/llm_wiki.py <group> <command> ...
```

Supported groups are `root` and `doctor`.

## Boundary

- Do not select this skill instead of init, ingest, maintain, query, or doctor.
- Do not edit Vault files unless the calling workflow explicitly authorizes it.
- Do not copy or expose sensitive values.
