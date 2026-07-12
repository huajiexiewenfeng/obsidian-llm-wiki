# Handoff: 2026-07-12-doctor-control-center-wikilink

## Status

- fix: merged and pushed to `origin/main@cd31cc3`
- verification: passed-agent-local
- installation: current Vault project-level runtime updated and manually verified

## Diagnosis And Fix

Core projections emit control-center-relative Wikilinks such as
`[[wiki/sources/source]]`. Doctor previously tried only vault-root and wiki-root
for directory targets. The resolver now accepts `control_center`, and
`check_links()` passes the resolved control center before the existing roots.

## Verification

- `.llm-wiki/verification/2026-07-12-doctor-control-center-wikilink.md`
- 230 tests passed with 2 conditional skips.
- Installed-runtime archive bytes matched and Doctor returned exit 0 with no ERROR.

## Next Gate

Begin a small real-Vault trial with one to three non-sensitive sources. Keep
v0.3 Inventory as the next development flow for automatic un-ingested-file discovery.
