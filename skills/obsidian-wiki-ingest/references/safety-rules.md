# Safety Rules

- Do not delete external files.
- Do not move external files.
- Do not copy external files into `raw/` directly. Use confirmed `archive-import` through Core.
- Treat `raw/` as a managed destination, not an ingest inbox; never overwrite an archive target or delete the external origin.
- Default to path-index mode for large external folders.
- Path-index mode still writes safe wiki metadata into the active Obsidian control center: `ingest/index.md` and source proxy nodes under `wiki/sources/`.
- Do not satisfy ingest by writing generated pages only into a coding or project workspace.
- Never copy raw API keys, tokens, passwords, AK/SK, cookies, certificates, RTSP credentials, database URLs, internal endpoints, production logs, or customer data.
- If sensitive content is suspected, record path, file type, risk category, and recommendation only.
- Ask before deep-reading PDF, Word, Excel, archives, images, or binary-heavy folders.
