# Bug Brief: 2026-07-11-obsidian-wikilink-resolution

## Summary

- title: Obsidian Wiki Doctor incorrectly reports valid WikiLinks as broken
- status: verified
- flow_id: 2026-07-11-obsidian-wikilink-resolution
- severity: high
- owner: Codex
- updated_at: 2026-07-11

## Routing

- intent: fix
- primary_stage: project-fix
- secondary_bridges: systematic-debugging, brainstorming, test-driven-development
- confidence: high
- reason: The production resolver disagrees with Obsidian Vault-root and dotted-filename semantics.
- next_gate: external review or Phase 3 planning
- routed_at: 2026-07-11

## Source

- path/url/log/user_report: Current Obsidian Vault Doctor run reported 1,588 valid links as broken.
- source_proxy: none
- sensitivity: none

## Symptom

Doctor treats valid Vault-root WikiLinks and extensionless dotted filenames as missing. It also limits basename lookup to the generated wiki directory rather than the Vault.

## Expected

WikiLink resolution should follow Obsidian-oriented rules: explicit relative links resolve from the source page, path links resolve from the Vault root, basename links resolve uniquely across the Vault, and `.md` inference works even when a filename contains dots.

## Evidence

- `resolve_wikilink` returns early whenever a target contains `/` or `\\`, preventing Vault-root resolution.
- `resolve_link_candidate` appends `.md` only when `Path.suffix == ""`, so names such as `00.知识库地图` and `v1.5.0` do not resolve.
- A real Vault run produced approximately 1,588 false broken-link findings.
- Existing tests cover wiki-relative and basename links inside `wiki/`, but not Vault-root paths, dotted names, Vault-global basenames, or ambiguity.

## Reproduction

- status: reproduced
- command_or_steps: Run Doctor against a Vault containing `[[00-知识库中控/wiki/topics/topic]]` or `[[00.知识库地图]]` with matching files present.
- observed: Doctor emits `broken-index-link` or `broken-internal-link`.
- expected: No broken-link finding.
- limitation: none

## Scope

- active: `skills/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py`, `tests/test_obsidian_wiki_doctor.py`
- read_only: root resolution model and existing Doctor design docs
- candidate: none
- excluded: Vault discovery, sensitive redaction, scoring, Maintain behavior
- escalation_history: none

## Diagnosis

The resolver models path-bearing WikiLinks as source-relative paths and uses Python suffix detection as a proxy for Markdown-extension inference. Both assumptions conflict with the required Obsidian behavior.

## Fix Plan

Follow `docs/superpowers/plans/2026-07-11-obsidian-wikilink-resolution-implementation-plan.md`: add failing regression tests, implement the approved resolver order, run the full suite and real Vault verification, then sync verified evidence. Keep Markdown-link behavior unchanged.

## Verification

- status: passed
- commands_or_checks: 20 targeted Doctor validation tests; full unittest discovery; canonical runtime Doctor validation against the current Vault
- result_summary: All 101 tests passed with 2 environment-gated skips. Real Vault validation reports zero broken index links; the sole remaining internal link has no Vault candidate and is a genuine missing relative target.
- limitation: Windows symlink coverage and opt-in Skills CLI integration were skipped; the installed user-skill cache is not updated by this source merge.
- residual_risk: Obsidian syntax outside the approved scope remains unchanged; ambiguous duplicate basenames intentionally remain unresolved.
- executor: agent-local
- authority: agent-local
- raw_output_ref: current Codex task RED, GREEN, full unittest, and real Vault command outputs
- test_integrity: six real CLI tests added, existing exact-case regression preserved, ambiguous fixture made Windows-portable; no assertions weakened; over-mocking risk low

## Flow Record

| Step | Status | Evidence | Updated |
|---|---|---|---|
| source | done | User report and real Vault Doctor output | 2026-07-11 |
| design | done | Approved Chinese resolver design | 2026-07-11 |
| plan | done | `docs/superpowers/plans/2026-07-11-obsidian-wikilink-resolution-implementation-plan.md` | 2026-07-11 |
| development | done | Resolver commit `d0ab175` integrated into canonical shared runtime on local `main` | 2026-07-11 |
| testing | active | 101 agent-local tests and real Vault canonical-runtime verification; awaiting CI or review | 2026-07-11 |
| archive | done | `.llm-wiki/handoff/2026-07-11-obsidian-wikilink-resolution-handoff.md` | 2026-07-11 |

## Artifacts

- `docs/superpowers/specs/2026-07-11-obsidian-wikilink-resolution-design.md`
- `docs/superpowers/plans/2026-07-11-obsidian-wikilink-resolution-implementation-plan.md`
- `.llm-wiki/handoff/2026-07-11-obsidian-wikilink-resolution-handoff.md`
- `.llm-wiki/artifacts/index.md`

## Open Questions

None for the approved scope.

## Residual Risk

Obsidian supports additional syntax variants not included in this focused bug fix; genuine missing targets and ambiguous basenames must continue to be reported.
