# Safety Rules

These rules apply to all skills.

## File Safety

- Do not delete user files.
- Do not move user files.
- Do not rewrite original notes unless the user explicitly asks.
- Do not copy external files into the vault by default.
- Copy files into `raw/` only after explicit confirmation.
- Treat system directories, application config directories, browser caches, and credential folders as out of scope unless explicitly confirmed.

## Sensitive Information

Never copy these values into generated wiki pages:

- API keys
- access tokens
- passwords
- AK/SK pairs
- cookies
- private keys
- certificates
- RTSP credentials
- database connection strings
- internal service addresses
- production endpoint URLs
- customer data
- production logs with secrets or identifiers

When sensitive content is suspected, record only:

- file path
- file type
- risk category
- recommended handling

Do not quote or summarize secret values.

## External Folder Policy

External folders are handled in three modes:

| Mode | Behavior | Copies files into vault |
|---|---|---|
| Path index | Record path, type, topic, risk, recommendation, and wiki graph entry | No |
| Summary ingest | Read approved content and create wiki summaries | Optional |
| Archive import | Copy approved files to `raw/` and then process | Yes |

Default mode is path index.

Path index must not leave external material known only to the filesystem.
Resolve the active Obsidian control center first. Create or update
`ingest/index.md` and source proxy nodes under `wiki/sources/`, then link them
from durable wiki pages when the relationship is clear.

## Confirmation Required

Ask for confirmation before:

- reading PDF, Word, Excel, or binary-heavy folders in depth
- copying external files into `raw/`
- processing folders that look sensitive
- applying broad fixes across many wiki pages
- saving query output as a durable wiki page

## Output Safety

Generated wiki pages should preserve knowledge, not secrets. Prefer:

- summaries
- procedures
- topic maps
- system boundaries
- risk notes
- source references
- redacted examples

Avoid:

- raw credentials
- full production logs
- sensitive URLs
- account data
- private customer details
