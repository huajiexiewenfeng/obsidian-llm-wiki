The source of truth for detection is scripts/obsidian_wiki_doctor.py. This file explains the public vocabulary only.

# Doctor Checks

## ERROR

- `invalid-root`: the provided root is neither an Obsidian LLM Wiki control center nor a direct wiki root.
- `missing-control-center`: the script fallback could not find the default control center.
- `missing-wiki-index`: `wiki/log.md` exists but `wiki/index.md` is missing.
- `missing-wiki-log`: `wiki/index.md` exists but `wiki/log.md` is missing.
- `missing-ingest-index`: the ingest area is expected but `ingest/index.md` is missing.
- `broken-index-link`: `wiki/index.md` links to a missing internal target.
- `missing-source-proxy`: a processed ingest row references a missing source proxy page.
- `sensitive-pattern`: a generated wiki page appears to contain a sensitive pattern.

## WARN

- `missing-roadmap`: the control-center roadmap is missing after initialization.
- `missing-knowledge-map`: the control-center knowledge map is missing after initialization.
- `broken-internal-link`: a non-index wiki page links to a missing internal target.
- `source-proxy-incomplete`: a source proxy exists but is missing expected traceability fields.
- `ingest-row-without-wiki-entry`: an ingest row has no corresponding generated wiki entry.

## INFO

- `not-applicable`: a score dimension was skipped because the required input signal does not exist yet.
- `no-findings`: no blocking doctor findings were detected.

These names are for reports and user explanations. If this catalog disagrees with `scripts/obsidian_wiki_doctor.py`, trust the script and update this reference later.
