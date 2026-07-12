# Project LLM Wiki Log

## 2026-07-11

- Merged Phase 2 state contract and safe-write core into local `main`; canonical implementation moved under the shared runtime.
- Merged the WikiLink resolver fix into local `main`; real Vault validation reduced index-link false positives to zero and retained one genuine missing relative target.
- Added `.llm-wiki/index.md` and repaired stale Phase 2 integration/runtime notes. No dashboard is enabled.

## 2026-07-12

- Implemented Phase 3 transactional ingest/page/projection Core and CLI on `codex/v02-phase3-ingest-projection`; added agent-local unit, failure-injection, CLI, and two-source E2E coverage.
