# Project LLM Wiki Log

## 2026-07-11

- Merged Phase 2 state contract and safe-write core into local `main`; canonical implementation moved under the shared runtime.
- Merged the WikiLink resolver fix into local `main`; real Vault validation reduced index-link false positives to zero and retained one genuine missing relative target.
- Added `.llm-wiki/index.md` and repaired stale Phase 2 integration/runtime notes. No dashboard is enabled.

## 2026-07-12

- Implemented Phase 3 transactional ingest/page/projection Core and CLI on `codex/v02-phase3-ingest-projection`; added agent-local unit, failure-injection, CLI, and two-source E2E coverage.
- Confirmed and recorded the Phase 4 Doctor state-consistency design; implementation remains gated on written-spec review.
- Revised the Phase 4 Doctor design from external review, confirmed the written specification, and produced a six-task TDD implementation plan; production implementation has not started.
- Implemented Phase 4 Doctor state consistency on `codex/v02-phase4-doctor-consistency`; agent-local verification passed 187 tests with 2 existing platform/opt-in skips, and CI/reviewer verification remains pending.
- Fast-forwarded Phase 4 into `main@117b28c` and pushed it to `origin/main`; retained `passed-agent-local` verification authority and routed the next design flow to Phase 3.1 archive import.
- Confirmed the Phase 3.1 archive import child Flow on `main@2414f68`: immutable `raw/` authority, Core-derived paths, lock-free streaming staging, atomic no-replace publication, archive Doctor findings, and future Inventory exclusion; implementation planning remains pending.
- Revised Phase 3.1 after external design review: registry-authoritative collision-safe IDs, no lock-time origin/full-target reads, deterministic reuse drift handling, hard-link cleanup/FS limitations, and a Phase 4 conditional `raw/` scan amendment; Inventory alignment was committed separately as `56f064a`.
- Wrote and self-reviewed the eight-task Phase 3.1 TDD implementation plan; production implementation remains gated on plan review and explicit execution selection.
