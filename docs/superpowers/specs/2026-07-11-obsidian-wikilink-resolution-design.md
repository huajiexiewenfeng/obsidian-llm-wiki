# Obsidian WikiLink Resolution Fix Design

Date: 2026-07-11
Status: Approved for implementation planning
Repository: huajiexiewenfeng/obsidian-llm-wiki

## Problem

The Doctor currently reports valid Obsidian WikiLinks as broken because its resolver does not model Vault-root paths and uses incomplete Markdown-extension inference.

Observed failures:

1. `[[00-知识库中控/wiki/topics/topic|Topic]]` is valid from the Vault root, but the resolver joins it to the source page directory.
2. `[[00.知识库地图]]` and versioned names such as `[[v1.5.0 release]]` do not receive an implicit `.md` candidate because `Path.suffix` is non-empty.
3. Basename lookup searches only `wiki/`, even though Obsidian can resolve a unique note elsewhere in the Vault.
4. Ambiguous basenames need an explicit safe failure instead of an arbitrary match.

## Goals

- Resolve explicit relative WikiLinks from the source page.
- Resolve path-bearing non-relative WikiLinks from the Vault root.
- Resolve basename WikiLinks uniquely across the Vault.
- Infer `.md` for all targets that do not already end in `.md`, including dotted filenames.
- Preserve broken findings for genuine misses and ambiguous basenames.
- Keep existing Markdown-link behavior unchanged.

## Non-Goals

- Do not change Vault discovery or user configuration.
- Do not change sensitive-pattern detection or redaction.
- Do not change scoring weights or finding severity.
- Do not add third-party dependencies.
- Do not implement every Obsidian URI or attachment behavior.

## Considered Approaches

### A. Extend the existing resolver

Recommended. Keep the deterministic Python engine and make the resolution context explicit. This is focused, testable, and compatible with the zero-dependency architecture.

### B. Add fallback logic inside `check_internal_links`

Rejected. It would split resolution behavior between scanning and resolver functions, making future callers inconsistent.

### C. Add an external Obsidian parsing dependency

Rejected. It adds packaging and maintenance cost that is disproportionate to this focused compatibility fix.

## Resolution Context

WikiLink resolution needs four values:

- source Markdown file
- raw WikiLink target
- resolved Vault root
- resolved generated Wiki root

The Vault root is authoritative for path-bearing WikiLinks. The Wiki root remains useful as a compatibility fallback when Doctor is invoked with a direct wiki root and no distinct Vault is available.

## Resolution Algorithm

1. Normalize aliases and heading fragments without changing the original finding text.
2. Ignore empty, heading-only, and external-scheme targets as today.
3. Build file candidates using the literal target, `<target>.md` when it does not already end in `.md`, and `<target>/index.md`.
4. For targets beginning with `./` or `../`, resolve only from the source page directory.
5. For targets containing `/` or `\\` without an explicit relative prefix, resolve from the Vault root, then use the Wiki root only as a compatibility fallback.
6. For basename targets, first accept a source-relative exact hit. Otherwise search Markdown files across the Vault by case-insensitive filename.
7. Return a basename match only when exactly one file matches. Return the unresolved candidate for zero or multiple matches so Doctor continues to report the link.
8. Keep Markdown links source-relative; this change applies only to Obsidian WikiLinks.

## API Shape

Extend `resolve_wikilink` to accept `vault_root` in addition to `wiki_root`. Update `check_internal_links` to pass both values from `ResolvedRoot`.

Refine candidate generation in one helper so source-relative, Vault-root, and Wiki-root checks share identical `.md` and directory-index behavior.

## Regression Tests

Add focused tests that prove:

1. A Vault-root WikiLink with directories resolves.
2. An explicit `../` WikiLink resolves from a nested source page.
3. A dotted extensionless note resolves by adding `.md`.
4. A basename outside `wiki/` resolves when unique across the Vault.
5. Duplicate basenames remain broken.
6. A genuinely missing target remains broken.
7. Existing Markdown and current WikiLink tests remain green.

Each new behavior must be introduced with a failing test before production code changes.

## Error And Safety Behavior

- Resolution must not read note contents; it may inspect file paths only.
- No link target is rewritten by Doctor.
- No duplicate basename is selected arbitrarily.
- Existing safe finding redaction remains unchanged.

## Verification

1. Run the new targeted unittest cases and observe the expected RED failures.
2. Implement the smallest resolver change and run targeted tests to GREEN.
3. Run the full test suite.
4. Run Doctor against the current real Vault using the source-tree Runtime.
5. Confirm structural link findings do not regress and genuine missing links remain reportable in fixtures.

## Acceptance Criteria

- All new regression tests pass.
- The full repository test suite passes.
- The current Vault produces no false broken-link findings for the covered semantics.
- Sensitive findings, scoring, and root-discovery behavior remain unchanged.
- No new dependency is introduced.
