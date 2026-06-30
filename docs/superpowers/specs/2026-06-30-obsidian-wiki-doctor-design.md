# Obsidian Wiki Doctor Design (v2)

Date: 2026-06-30
Status: Revised draft for implementation
Repository: huajiexiewenfeng/obsidian-llm-wiki
Supersedes: 2026-06-30-obsidian-wiki-doctor-design.md

## What Changed In v2

This revision keeps the original goal (add a deterministic, read-only health
doctor) but fixes the structural problems found when checking the design
against the real repository:

1. **Single detection engine, two entry points.** The Python script becomes the
   single source of truth for all checks. `obsidian-wiki-doctor` (read-only) and
   `obsidian-wiki-maintain` (repair) both consume it. Checks are no longer
   documented twice.
2. **Skills are split by read vs. write, not by check list.** Doctor diagnoses
   and scores; maintain repairs. This removes the routing collision between the
   two skills.
3. **`maintain` is re-scoped, not duplicated.** `maintain/references/repair-policy.md`
   stops owning detection prose and instead points at the doctor engine.
4. **Four-skill framing is fixed everywhere.** `README.md`, `README.zh.md`,
   `docs/architecture.md`, and `docs/safety.md` are updated to describe five
   skills and to place doctor as an orthogonal "measurement" role beside the
   linear loop.
5. **Python introduction is made explicit in the plan.** This is the repo's
   first script and first unittest surface; `docs/development-plan.md` and the
   README "Status" section are updated to say so deliberately.
6. **State-dependent checks get concrete signals.** Checks that depend on
   "init has run" or "ingest has started" now key off observable files instead
   of an undefined state.
7. **The default vault path is parameterized.** The hardcoded Windows path is
   kept only as a fallback default, overridable by `--root` and config.

## Goal

Add `obsidian-wiki-doctor` as the fifth Obsidian LLM Wiki skill. It diagnoses,
validates, scores, and explains the health of an Obsidian LLM Wiki control
center, and never writes to the vault. It answers one practical question for an
initialized or ingested vault:

> Is this wiki actually usable, safe, discoverable, and ready for query?

It is Obsidian-specific. It must not import external project-lifecycle concepts
(Project Graph, Flow Record, requirements, bugs, dashboards, release gates).
The script borrows the *shape* of a project doctor but keeps every rule native
to Obsidian vaults.

## Non-Goals

- Do not replace `obsidian-wiki-maintain`. Doctor only reads; maintain writes.
- Do not auto-repair, move, delete, or rewrite any vault file.
- Do not duplicate detection logic in two places. Detection lives in the script.
- Do not deep-scan every vault file without a user-approved scope.
- Do not add Project Graph, cross-project refs, Flow Records, dashboards, or
  lifecycle gates to any Obsidian doc or SKILL.md.

## Architecture: One Engine, Two Skills

```text
                 +-------------------------------+
                 |  scripts/obsidian_wiki_doctor.py
                 |  (single detection + scoring engine)
                 +-------------------------------+
                    ^                         ^
        read-only   |                         |   read-then-write
   +----------------+                         +------------------+
   | obsidian-wiki-doctor                     | obsidian-wiki-maintain
   | validate / score / report                | takes findings, applies
   | never writes the vault                   | approved structural repairs
   +--------------------------+               +-----------------------------+
```

The key rule: **checks are defined once, in the script.** Doctor renders them as
a read-only diagnosis. Maintain calls the same engine to find issues, then does
the writes the doctor refuses to do. Neither skill re-describes the check set in
prose.

### Routing Boundary (this is what prevents collision)

Pick `obsidian-wiki-doctor` when the user wants to **look**:

- "跑一下 Obsidian Wiki Doctor / 诊断 wiki / 看看初始化后有没有用"
- "给 wiki 打个健康分 / 成熟度评分"
- "出一份中文健康报告"
- "查询质量为什么差，是结构问题吗"
- a future hook or CI job reporting doctor findings.

Pick `obsidian-wiki-maintain` when the user wants to **change**:

- "修复 / fix / repair"
- "补 index 链接 / 补 source proxy / 修断链"
- "把 doctor 报告里的问题改掉"

The two SKILL.md `description` fields must be rewritten so the trigger verbs do
not overlap. Doctor owns diagnose/score/report verbs; maintain owns repair/fix
verbs. This is the single most important change in v2.

## Recommended Approach

Create a dedicated `skills/obsidian-wiki-doctor/` child skill plus a
deterministic Python standard-library script.

The child skill owns:

- natural-language routing (diagnose/score/report intent only);
- root / control-center resolution;
- strictly read-only behavior;
- interpretation of validate, score, and report output;
- handoff to `obsidian-wiki-maintain` for approved structural repairs.

The script owns:

- all repeatable checks (the only place they are defined);
- structured findings;
- scoring signals;
- Chinese-first report formatting;
- optional JSON output for future automation and CI.

## CLI Model

Use explicit subcommands. The default vault path is a fallback only.

```text
python scripts/obsidian_wiki_doctor.py validate --root <control-center-or-vault> --format text --fail-on error
python scripts/obsidian_wiki_doctor.py score    --root <control-center-or-vault> --format json
python scripts/obsidian_wiki_doctor.py report   --root <control-center-or-vault> --format text
```

- `--root` is optional; resolution falls back to the default path and search.
- `--format` is `text` (default) or `json`.
- `--fail-on` is `error` (default for CI) or `none`.

### `validate`

Deterministic checks. Returns non-zero when `--fail-on error` is set and ERROR
findings exist. Suitable for future pre-commit or CI. V0 does not enforce hooks.

### `score`

Structured maturity scoring. Always exits 0. The score is directional guidance,
not a KPI.

### `report`

Human-facing Chinese-first report. Always exits 0. Includes findings, maturity,
and next actions. Default command for interactive use.

## Root Resolution

The doctor must not assume the current shell directory is the Obsidian wiki.
This logic is shared with `maintain` and kept identical.

1. If the user provides a vault, control-center, or wiki path, use it (`--root`).
2. Else, if `OBSIDIAN_LLM_WIKI_ROOT` is set, use it. Repo config is deferred to V0.1.
3. Else, if the default control center
   `C:\Users\admin\Documents\Obsidian Vault\00-知识库中控` exists, use it.
   This path is a fallback default only, never a hard requirement.
4. Else, search for a control center containing `wiki/index.md` and `wiki/log.md`.
5. Else, accept a direct wiki root containing `index.md` and `log.md`.
6. If multiple candidates exist, ask the user to choose.

The report must print the resolved control center and wiki root.

## State Signals (fixes the "did init/ingest happen?" gap)

State-dependent checks must key off observable files, not an assumed state.
The script defines these state predicates:

- `init_done` = `wiki/index.md` and `wiki/log.md` both exist.
- `onboarding_done` = `00.LLM Wiki 建设路线图.md` exists (init's roadmap output).
- `inventory_done` = `00.知识库地图.md` exists (init's knowledge-map output).
- `ingest_started` = `ingest/index.md` exists and contains at least one source row.

A check that depends on a state only fires when its predicate is true. For
example `missing-source-proxy` only runs when `ingest_started` is true, and
`missing-roadmap` is only a WARN when `init_done` is true but `onboarding_done`
is false. No check may rely on an undefined "the wiki claims init is complete".

## V0 Checks (defined in the script, single source of truth)

### Structure Checks

- `invalid-root`: `--root` or `OBSIDIAN_LLM_WIKI_ROOT` points to a path that does not exist or is not a vault/control center.
- `missing-control-center`: no resolvable control center when no explicit root is provided.
- `missing-wiki-index`: `wiki/index.md` (or direct `index.md`) missing.
- `missing-wiki-log`: `wiki/log.md` (or direct `log.md`) missing.
- `missing-ingest-index`: `ingest/index.md` missing while other ingest artifacts
  exist (e.g. files under `wiki/sources/`).
- `missing-roadmap`: `00.LLM Wiki 建设路线图.md` missing while `init_done`.
- `missing-knowledge-map`: `00.知识库地图.md` missing while `init_done`.

### Link And Coverage Checks

- `broken-index-link`: a link in `wiki/index.md` does not resolve.
- `broken-internal-link`: a wiki internal Markdown link does not resolve.
- `orphan-wiki-page`: generated page is unreachable from index, topic, project,
  entity, SOP, or source-proxy links.
- `missing-source-proxy`: an `ingest/index.md` source row has no proxy page
  (only when `ingest_started`).
- `source-proxy-incomplete`: proxy lacks original path, processing status, or
  related wiki links.
- `ingest-row-without-wiki-entry`: a processed ingest row has no linked wiki entry.
- `log-missing-material-change`: generated/updated pages exist with no matching
  recent `log.md` entry.

### Safety Checks

Reuse the exact pattern set already documented in `docs/safety.md` and the
existing maintain rules (password, token, secret, AK/SK, private key, cookie,
credentialed RTSP URL, connection string, internal endpoint).

- `sensitive-pattern`: generated wiki pages contain a risky pattern.
- `raw-secret-value-risk`: report only category, file path, line number; never
  print the secret value.
- `external-path-overexposure`: a proxy exposes more workstation-local path
  detail than a folder-level path would need.

### Query Readiness Checks

- `thin-index`: index exists but has too few navigable sections or links.
- `thin-topic-page`: a topic/entity/project/SOP page is mostly placeholder text.
- `missing-query-entrypoints`: proxies exist but no topic/project/entity/SOP
  pages make query routing useful.

## Finding Severity

ERROR:

- invalid explicit root or missing control center when no target can be resolved;
- broken required entrypoint while `init_done`;
- sensitive value risk in a generated wiki page;
- broken link that makes a processed source unreachable.

WARN:

- missing roadmap, knowledge map, log alignment, proxy fields, or query
  entrypoints;
- orphan pages (not dangerous, but hurt discoverability);
- thin or placeholder-heavy pages.

INFO:

- optional improvements, intentionally deferred areas, safe next-batch advice.

These three levels map exactly to maintain's existing Error / Warning / Info.

## Maturity Score

Score version: 1.

| Dimension | Weight | Meaning |
|---|---:|---|
| Control center resolution | 20 | Can the doctor reliably find the active wiki/control center? |
| Navigation and discoverability | 25 | Are index links, source proxies, and page links coherent? |
| Ingest traceability | 20 | Can material be traced from ingest index to wiki entries? |
| Safety hygiene | 20 | Are generated pages free of obvious sensitive patterns? |
| Query readiness | 15 | Are there enough topic/project/entity/SOP entrypoints? |

N/A rules:

- If `ingest_started` is false, ingest traceability is `not-applicable`, not penalized.
- If the vault is freshly initialized and not populated, query readiness explains
  the limitation rather than implying failure.
- Safety is always applicable once generated wiki pages exist.

Normalize over applicable dimensions only. The score is directional, not a KPI.

## Report Format

Text report order:

```text
# Obsidian Wiki Doctor 报告

## 关键结论
## 建议行动计划
## 总体评分
## 成熟度维度
## Doctor Findings
## 证据与路径
## Repair Handoff
```

Rules:

- Chinese-first prose.
- Preserve file paths and check names verbatim.
- Never print secret values.
- Recommend concrete next actions, not numeric-score chasing.
- The Repair Handoff section names the narrow scope to pass to
  `obsidian-wiki-maintain`, never performs the repair itself.

## Re-Scoping `obsidian-wiki-maintain`

This is required so the two skills do not collide.

- Rewrite `obsidian-wiki-maintain/SKILL.md` `description` to trigger on **repair**
  verbs only (fix / repair / 补链接 / 修复 / 改 index), not on "check / lint /
  find broken links / find orphan pages".
- In `maintain/references/repair-policy.md`, replace the duplicated check
  list with a pointer: detection is performed by the doctor engine; this file
  now documents only the **repair policy** (what is safe to fix automatically vs.
  what needs confirmation).
- maintain's workflow becomes: resolve root → run doctor engine for findings →
  present them → apply only approved fixes → log changes.

If the team prefers minimal churn instead, the documented fallback is to NOT add
a fifth skill and add `score` plus a read-only mode to maintain. v2 recommends
the split because the goal is a deterministic, CI-able, score-producing tool,
and a clean read/write boundary is cheaper to maintain long-term.

## File Plan

Create:

- `skills/obsidian-wiki-doctor/SKILL.md`
- `skills/obsidian-wiki-doctor/references/doctor-checks.md`
- `skills/obsidian-wiki-doctor/references/report-template.md`
- `skills/obsidian-wiki-doctor/references/safety-rules.md`
- `scripts/obsidian_wiki_doctor.py`
- `tests/test_obsidian_wiki_doctor.py`

Modify (note the four previously-missing files marked *new in v2*):

- `README.md`
- `README.zh.md`
- `docs/architecture.md`  *(new in v2 — fix "Why Four Skills" / loop diagram)*
- `docs/safety.md`  *(new in v2 — note doctor is read-only and reuses the pattern set)*
- `docs/development-plan.md`  *(add Phase: doctor; state the Python introduction)*
- `docs/workflow.md`
- `tests/prompts.md`
- `skills/obsidian-wiki-init/SKILL.md`
- `skills/obsidian-wiki-maintain/SKILL.md`  *(re-scope to repair-only)*
- `skills/obsidian-wiki-maintain/references/repair-policy.md`  *(new in v2 — point at engine)*
- `skills/obsidian-wiki-query/SKILL.md`

Optional V0.1:

- Vendor the script from init into the control center, e.g.
  `00-知识库中控/tools/obsidian_wiki_doctor.py`. Deferred until behavior is proven.
- Add a drift-check script only after the source script is stable.

## Documentation Consistency Tasks

Because doctor is the fifth skill, these must change together:

- README "Core Architecture" table → five rows; add doctor as a read-only
  diagnosis/score role.
- README "Project Structure" → add `skills/obsidian-wiki-doctor/` and `scripts/`.
- README "Status" → state that the repo now ships its first deterministic script
  and unittest surface, consistent with the previously "optional" Phase 6 plan.
- `docs/architecture.md` "Why Four Skills" → "Why Five", and show doctor beside
  the linear `init -> ingest -> maintain -> query` loop as a measurement layer,
  not a new step in the loop.
- `docs/development-plan.md` → add a doctor phase and explicitly move the
  link-checker / sensitive-pattern-scanner / health-report-generator scripts
  from "optional Phase 6" into this deliverable.

## Acceptance Cases

1. Doctor routes from `跑一下 Obsidian Wiki Doctor，看看初始化后有没有用。`
2. A repair prompt (`帮我把断链修好`) routes to maintain, not doctor.
3. Report mode resolves the active control center and produces a Chinese report.
4. Validate mode detects an invalid explicit `--root` as ERROR.
5. Validate mode detects missing `wiki/index.md` as ERROR.
6. Validate mode detects broken links from `wiki/index.md`.
7. Validate mode detects a missing source proxy for a processed ingest row.
8. Safety check reports secret categories without printing values.
9. Score mode marks ingest traceability N/A for a fresh init with no ingest rows.
10. Doctor never modifies any vault file under any prompt.
11. Repair requests hand off to `obsidian-wiki-maintain` with a narrow scope.
12. maintain's detection comes from the doctor engine (no duplicate check list).
13. Skill package listing includes all five Obsidian skills.

## Verification Plan

```text
python -m unittest discover tests
npx.cmd skills add . --list
rg -n "obsidian-wiki-doctor|obsidian_wiki_doctor|Doctor" README.md README.zh.md docs skills tests scripts
rg -n "four skills|Why Four Skills" README.md README.zh.md docs   # must return nothing
rg -n "Project Graph|Flow Record|release gate" skills/obsidian-wiki-doctor docs   # must return nothing
```

Expected:

- unit tests pass;
- package listing includes all five Obsidian skills;
- README, architecture, and workflow docs describe the fifth skill consistently;
- no stale "four skills" framing remains;
- no external project-lifecycle concepts leak into doctor or Obsidian docs.

## Open Design Decision

V0 runs the script from `scripts/obsidian_wiki_doctor.py` only. V0.1 decides
whether `obsidian-wiki-init` should vendor the script into each control center.
This keeps V0 small and avoids silently writing automation files into a user's
vault before doctor behavior is proven.
