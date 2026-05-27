# Health Check Rules

## Inputs

- active Obsidian control center
- wiki root under `<control-center>/wiki/`
- ingest index under `<control-center>/ingest/index.md` when present
- optional scope: full wiki, topic, project, source, recent changes
- optional permission: report only or apply confirmed fixes

## Checks

### Link Checks

- `index.md` links exist
- `ingest/index.md` links to wiki entries resolve
- internal wiki links resolve
- source/topic/project/entity/SOP cross-links are present where expected

### Coverage Checks

- generated pages are included in `index.md`
- approved external sources listed in `ingest/index.md` have source proxy nodes
- source proxy nodes have a source path, processing status, and related wiki links
- important additions are recorded in `log.md`
- sources have a clear topic or project relationship
- repeated entities have entity pages
- repeated procedures have SOP pages

### Safety Checks

Look for suspicious patterns such as:

- `password=`
- `token=`
- `secret=`
- `AK/SK`
- private key blocks
- connection strings
- RTSP URLs with credentials
- cookies

Do not print secret values in the report. Report only file path, line category, and risk.

### Consistency Checks

- page type matches folder
- file names are stable and readable
- log entries match material changes
- ingestion plans have corresponding reports when processed
- `ingest/index.md` batch entries match source proxy pages and ingestion reports

## Repair Policy

Safe without extra confirmation:

- add missing index link for a known wiki page
- add log entry for the current maintenance action
- fix clearly broken relative wiki links when target is unambiguous

Requires confirmation:

- renaming files
- moving pages
- rewriting summaries
- deleting duplicate pages
- broad sensitive-content cleanup
