# Maintain Repair Policy

Detection is performed by scripts/obsidian_wiki_doctor.py through obsidian-wiki-doctor. This file documents repair rules only.

## Inputs

- active Obsidian wiki root
- doctor finding list or user-approved repair request
- concrete file paths approved for modification
- permission scope: narrow apply, broad repair, or sensitive cleanup

## Allowed Repairs

Safe without extra confirmation:

- add missing index link for a known wiki page
- add log entry for the current maintenance action
- fix clearly broken relative wiki links when target is unambiguous
- update stale ingest/index references when the replacement path is explicit

Requires confirmation:

- renaming files
- moving pages
- rewriting summaries
- deleting duplicate pages
- broad sensitive-content cleanup
- deleting or moving an orphan archive staging file
- registering, moving, deleting, or re-archiving an unregistered `raw/` file
- repairing an archive registry path or checksum relationship

Do not:

- invent new findings without running or consuming doctor output
- repair files outside the stated active wiki root
- print secret values while explaining a sensitive cleanup
- convert broad cleanup requests into edits without approval
- overwrite immutable archive bytes or infer an archive origin from filename alone
