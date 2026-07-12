The source of truth for detection is scripts/obsidian_wiki_doctor.py. This file explains the public vocabulary only.

# Doctor Checks

## ERROR

- `invalid-root`: the provided root is neither an Obsidian LLM Wiki control center nor a direct wiki root.
- `missing-control-center`: the script fallback could not find the default control center.
- `missing-wiki-index`: `wiki/log.md` exists but `wiki/index.md` is missing.
- `missing-wiki-log`: `wiki/index.md` exists but `wiki/log.md` is missing.
- `broken-index-link`: `wiki/index.md` links to a missing internal target.
- `missing-source-proxy`: a processed ingest row references a missing source proxy page.
- `sensitive-pattern`: a generated wiki page appears to contain a sensitive pattern.
- `missing-state-file`: `.meta/` is enabled but a required Phase 2/3 state file is missing.
- `invalid-state-file`: a schema, registry, or non-tail change-log record is invalid.
- `processed-source-missing-proxy`: a processed source has no valid proxy page record.
- `source-proxy-file-missing`: a source proxy record points to a missing Markdown file.
- `registered-page-missing`: a page registry record points to a missing Markdown file.
- `unsafe-registered-path`: a registered page resolves outside the control center.
- `page-frontmatter-drift`: managed identity, page type, or source IDs differ from the registry.
- `managed-checksum-drift`: computed, frontmatter, and registry managed checksums disagree.
- `managed-marker-conflict`: managed page or frontmatter markers cannot be parsed safely.
- `projection-marker-conflict`: a deterministic projection has invalid markers.
- `orphan-running-operation`: a running operation has no matching active lock.
- `running-operation-with-stale-lock`: a running operation is backed only by a stale lock.
- `missing-completion-event`: an audited completed operation has no completed change event.
- `invalid-lock`: lock JSON or required ownership fields are invalid.
- `archive-record-missing-path`: an archive source record has no authoritative `raw/` path.
- `unsafe-archive-path`: an archive record resolves outside its required `raw/<source-id>/` directory.
- `archive-file-missing`: the immutable archive target recorded for a source is missing.
- `archive-checksum-drift`: archive bytes differ from the checksum stored in the source registry.
- `unexpected-archive-path`: a non-archive source incorrectly declares an archive path.
- `archive-operation-target-drift`: a completed ingest event and source registry disagree on the archive target.

## WARN

- `missing-roadmap`: the control-center roadmap is missing after initialization.
- `missing-knowledge-map`: the control-center knowledge map is missing after initialization.
- `broken-internal-link`: a non-index wiki page links to a missing internal target.
- `torn-change-log-tail`: an incomplete final JSONL line was ignored while the valid prefix remained usable.
- `pending-source-without-active-operation`: a pending source has no active ingest operation explaining it.
- `failed-source`: a source registry record is marked failed.
- `orphan-managed-page`: managed Markdown has no page registry record.
- `projection-drift`: a projection differs from the authoritative renderer.
- `failed-operation`: an operation is marked failed.
- `operation-event-status-drift`: a completion event exists but the operation is not completed.
- `stale-lock`: a same-host lock exceeded the writer TTL and its PID is absent.
- `cross-host-lock`: a remote-host lock cannot be proven stale locally.
- `orphan-temp-file`: a writer-style atomic temporary file remains under `.meta/`, `wiki/`, `ingest/`, or an enabled `raw/` archive area.
- `unregistered-archive`: a regular file in `raw/` has no archive source record.

## INFO

- `active-operation`: a running operation matches the current live writer lock. INFO does not fail `--fail-on error` and does not change the maturity score.

## Report Vocabulary

- `not-applicable`: a score dimension was skipped because the required input signal does not exist yet.
- `no-findings`: no blocking doctor findings were detected.

These names are for reports and user explanations. If this catalog disagrees with `scripts/obsidian_wiki_doctor.py`, trust the script and update this reference later.

Archive findings extend validation only. They do not change score version 1, its five dimensions, or their weights.
