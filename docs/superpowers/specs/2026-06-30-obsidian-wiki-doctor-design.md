# Obsidian Wiki Doctor Design

Date: 2026-06-30
Status: Draft for user review
Repository: huajiexiewenfeng/obsidian-llm-wiki

## Goal

Add `obsidian-wiki-doctor` as the fifth Obsidian LLM Wiki skill. It diagnoses, validates, scores, and explains the health of an Obsidian LLM Wiki control center. It is Obsidian-specific and must not import Project Develop Copilot lifecycle concepts such as Project Graph, Flow Record, requirements, bugs, dashboards, or release gates.

The doctor should make an initialized or ingested vault answer one practical question:

> Is this wiki actually usable, safe, discoverable, and ready for query?

## Non-Goals

- Do not replace `obsidian-wiki-maintain`.
- Do not auto-repair files by default.
- Do not move, delete, or rewrite original Obsidian notes.
- Do not scan every vault file deeply without a user-approved scope.
- Do not create a shared Project/Obsidian doctor core in V0.
- Do not add Project Graph, cross-project refs, Flow Records, project dashboards, or project lifecycle gates.

## Recommended Approach

Create a dedicated `skills/obsidian-wiki-doctor/` child skill plus a deterministic Python standard-library script.

The child skill owns:

- natural-language routing;
- root/control-center resolution;
- read-only default behavior;
- interpretation of validate, score, and report output;
- handoff to `obsidian-wiki-maintain` for approved structural repairs.

The script owns:

- repeatable checks;
- structured findings;
- scoring signals;
- Chinese-first report formatting;
- optional JSON output for future automation.

This mirrors the useful shape of the Project Doctor while keeping the rule set native to Obsidian vaults.

## Skill Boundary

### Use `obsidian-wiki-doctor` When

- The user asks to run Doctor, check wiki health, score the wiki, explain whether init produced a useful wiki, or diagnose why query quality is poor.
- The user asks whether `index.md`, `log.md`, `ingest/index.md`, source proxies, or generated wiki pages are coherent.
- The user asks for a Chinese health report or maturity score.
- A future hook or CI job reports doctor findings.

### Keep `obsidian-wiki-maintain` For

- approved index/log/link repairs;
- missing page-link fixes;
- narrow source proxy consistency repairs;
- structural cleanup after the doctor report.

### Keep `obsidian-wiki-init` For

- creating the control center;
- creating starter wiki files;
- generating onboarding roadmap and knowledge map;
- installing or refreshing the doctor scaffold if V0 includes vendoring.

### Keep `obsidian-wiki-query` For

- answering knowledge questions from wiki pages;
- citing wiki pages;
- suggesting durable outputs after query.

## CLI Model

Use explicit subcommands:

```text
python scripts/obsidian_wiki_doctor.py validate --root <control-center-or-vault> --format text --fail-on error
python scripts/obsidian_wiki_doctor.py score --root <control-center-or-vault> --format json
python scripts/obsidian_wiki_doctor.py report --root <control-center-or-vault> --format text
```

### `validate`

Deterministic checks. It may return non-zero when `--fail-on error` is used and ERROR findings exist. It is suitable for future pre-commit or CI, but V0 does not have to enforce hooks.

### `score`

Structured maturity scoring. It always exits 0. The score is directional guidance, not a KPI.

### `report`

Human-facing Chinese-first report. It always exits 0 and includes findings, maturity, and next actions. It is the default command for interactive use.

## Root Resolution

The doctor must not assume the current shell directory is the Obsidian wiki.

Resolution order:

1. If the user provides a vault, control-center, or wiki path, use it.
2. If the default control center exists at `C:\Users\admin\Documents\Obsidian Vault\00-知识库中控`, use it.
3. Otherwise search for a control center containing `wiki/index.md` and `wiki/log.md`.
4. If a direct wiki root is provided, accept a root containing `index.md` and `log.md`.
5. If multiple candidates exist, ask the user to choose.

The report must show the resolved control center and wiki root.

## V0 Checks

### Structure Checks

- `missing-control-center`: no resolvable Obsidian LLM Wiki control center.
- `missing-wiki-index`: `wiki/index.md` or direct `index.md` is missing.
- `missing-wiki-log`: `wiki/log.md` or direct `log.md` is missing.
- `missing-ingest-index`: `ingest/index.md` is missing after ingest has started.
- `missing-roadmap`: `00.LLM Wiki 建设路线图.md` is missing after init/onboarding.
- `missing-knowledge-map`: `00.知识库地图.md` is missing when init claims vault inventory was created.

### Link And Coverage Checks

- `broken-index-link`: a link from `wiki/index.md` does not resolve.
- `broken-internal-link`: a wiki internal Markdown link does not resolve.
- `orphan-wiki-page`: generated wiki page is not reachable from index, topic, project, entity, SOP, or source proxy links.
- `missing-source-proxy`: an `ingest/index.md` source row has no source proxy page.
- `source-proxy-incomplete`: source proxy lacks original path, processing status, or related wiki links.
- `ingest-row-without-wiki-entry`: ingest row is processed but has no linked wiki entry.
- `log-missing-material-change`: generated or updated wiki pages exist without a matching recent log entry.

### Safety Checks

- `sensitive-pattern`: generated wiki pages contain risky patterns such as password, token, secret, AK/SK, private key, cookie, credentialed RTSP URL, or connection string.
- `raw-secret-value-risk`: report only the category, file path, and line number; never print secret values.
- `external-path-overexposure`: source proxy exposes too much workstation-local path detail where a safer folder-level path would work.

### Query Readiness Checks

- `thin-index`: index exists but has too few navigable sections or links.
- `thin-topic-page`: topic/entity/project/SOP page is mostly placeholder text.
- `missing-query-entrypoints`: wiki has source proxies but no topic/project/entity/SOP pages that make query routing useful.

## Finding Severity

ERROR:

- missing control center when no target can be resolved;
- broken required entrypoint after the wiki claims initialization is complete;
- sensitive value risk in generated wiki pages;
- broken links that make a processed source unreachable.

WARN:

- missing roadmap, knowledge map, log alignment, source proxy fields, or useful query entrypoints;
- orphan pages that are not dangerous but reduce discoverability;
- thin pages or placeholder-heavy pages.

INFO:

- optional improvements, intentionally deferred areas, or safe recommendations for the next ingest batch.

## Maturity Score

Score version: 1.

Dimensions:

| Dimension | Weight | Meaning |
|---|---:|---|
| Control center resolution | 20 | Can the doctor reliably find the active wiki/control center? |
| Navigation and discoverability | 25 | Are index links, source proxies, and page links coherent? |
| Ingest traceability | 20 | Can source material be traced from ingest index to wiki entries? |
| Safety hygiene | 20 | Are generated pages free of obvious sensitive patterns? |
| Query readiness | 15 | Are there enough topic/project/entity/SOP entrypoints to support useful answers? |

N/A rules:

- If no ingest has been performed, ingest traceability can be `not-applicable` instead of penalized.
- If the vault is newly initialized and not yet populated, query readiness should explain the limitation rather than imply failure.
- Safety is always applicable once generated wiki pages exist.

The score should normalize over applicable dimensions only.

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
- Do not print secret values.
- Recommend concrete next actions, not numeric-score chasing.
- When repair is requested, hand off to `obsidian-wiki-maintain` with a narrow repair scope.

## File Plan

Create:

- `skills/obsidian-wiki-doctor/SKILL.md`
- `skills/obsidian-wiki-doctor/references/doctor-checks.md`
- `skills/obsidian-wiki-doctor/references/report-template.md`
- `skills/obsidian-wiki-doctor/references/safety-rules.md`
- `scripts/obsidian_wiki_doctor.py`
- `tests/test_obsidian_wiki_doctor.py`

Modify:

- `README.md`
- `README.zh.md`
- `docs/development-plan.md`
- `docs/workflow.md`
- `tests/prompts.md`
- `skills/obsidian-wiki-init/SKILL.md`
- `skills/obsidian-wiki-maintain/SKILL.md`
- `skills/obsidian-wiki-query/SKILL.md`

Optional V0.1:

- Add scaffold installation from init into the control center, for example `00-知识库中控/tools/obsidian_wiki_doctor.py`.
- Add a drift-check script only after the source script is stable.

## Acceptance Cases

1. Doctor routes correctly from a prompt like: `跑一下 Obsidian Wiki Doctor，看看初始化后有没有用。`
2. Report mode resolves the active control center and produces a Chinese report.
3. Validate mode detects missing `wiki/index.md` as ERROR.
4. Validate mode detects broken links from `wiki/index.md`.
5. Validate mode detects missing source proxy for a processed ingest row.
6. Safety check reports secret categories without printing values.
7. Score mode marks ingest traceability as N/A for a fresh init with no ingest rows.
8. Doctor does not modify wiki files unless the user explicitly asks for repair.
9. Repair requests hand off to `obsidian-wiki-maintain` with a narrow scope.
10. Skill package listing includes `obsidian-wiki-doctor`.

## Verification Plan

Run:

```text
python -m unittest discover tests
npx.cmd skills add . --list
rg -n "obsidian-wiki-doctor|obsidian_wiki_doctor|Doctor" README.md README.zh.md docs skills tests scripts
```

Expected:

- unit tests pass;
- package listing includes all five Obsidian skills;
- README and workflow docs describe the fifth skill;
- no Project Graph or Project Develop lifecycle concepts are introduced into Obsidian Doctor docs.

## Open Design Decision

V0 should start with repository-source script execution from `scripts/obsidian_wiki_doctor.py`. A later V0.1 can decide whether `obsidian-wiki-init` should vendor the script into each control center. This keeps V0 small and avoids silently writing automation files into a user's vault before the doctor behavior is proven.
