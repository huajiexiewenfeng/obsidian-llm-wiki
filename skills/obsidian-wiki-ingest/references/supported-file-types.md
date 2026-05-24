# Supported File Types

## First-Class

- Markdown: `.md`, `.markdown`
- text: `.txt`
- CSV: `.csv`
- common docs by metadata/path: `.pdf`, `.docx`, `.xlsx`, `.xls`

## Conditional

Read these only when the user confirms:

- PDF body text
- Word body text
- Excel workbook contents
- exported HTML
- images requiring OCR or visual inspection

## Usually Skip

- executables
- archives unless explicitly requested
- caches
- dependency folders such as `node_modules`, `.gradle`, `.m2`
- build outputs such as `target`, `dist`, `build`
- version-control internals such as `.git`

## Code Repositories

For code repos, usually inspect:

- `README*`
- `docs/`
- `requirements*`
- `pom.xml`, `package.json`, `build.gradle`
- architecture or design documents

Avoid copying source code wholesale into wiki pages.
