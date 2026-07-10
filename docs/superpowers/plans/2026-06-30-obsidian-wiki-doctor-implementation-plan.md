# Obsidian Wiki Doctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `obsidian-wiki-doctor` as the fifth Obsidian LLM Wiki skill, backed by a deterministic read-only Python doctor engine that validates, scores, and reports on Obsidian LLM Wiki health.

**Architecture:** `scripts/obsidian_wiki_doctor.py` is the single detection and scoring engine. `obsidian-wiki-doctor` routes diagnose/score/report requests to that engine and never writes vault files. `obsidian-wiki-maintain` consumes doctor findings, applies only approved structural fixes, and no longer owns a duplicate check list.

**Tech Stack:** Python 3 standard library (`argparse`, `dataclasses`, `json`, `pathlib`, `re`, `unittest`, `tempfile`, `subprocess`), Markdown skill docs, Skills CLI (`npx.cmd skills add . --list`), `rg`.

---

## File Structure

Create:

- `scripts/obsidian_wiki_doctor.py`: CLI and library module for root resolution, state predicates, checks, score, report, JSON/text formatting, exit policy.
- `tests/test_obsidian_wiki_doctor.py`: unit tests for root resolution, checks, safety redaction, score/report output, and read-only behavior.
- `skills/obsidian-wiki-doctor/SKILL.md`: read-only routing and interpretation rules.
- `skills/obsidian-wiki-doctor/references/doctor-checks.md`: public check catalog; script remains source of truth.
- `skills/obsidian-wiki-doctor/references/report-template.md`: text and JSON report shape.
- `skills/obsidian-wiki-doctor/references/safety-rules.md`: doctor-safe reporting rules.

Modify:

- `skills/obsidian-wiki-maintain/SKILL.md`: repair-only trigger and workflow.
- `skills/obsidian-wiki-maintain/references/repair-policy.md`: repair policy only.
- `skills/obsidian-wiki-init/SKILL.md`: recommend doctor report after init; no vendoring in V0.
- `skills/obsidian-wiki-query/SKILL.md`: route structural/query-quality diagnosis to doctor.
- `README.md`, `README.zh.md`, `docs/architecture.md`, `docs/safety.md`, `docs/development-plan.md`, `docs/workflow.md`, `tests/prompts.md`: five-skill framing and verification prompts.

## Task 1: Root Resolution Tests

**Files:**
- Create: `tests/test_obsidian_wiki_doctor.py`

- [ ] **Step 1: Create failing tests**

Create `tests/test_obsidian_wiki_doctor.py`:

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "obsidian_wiki_doctor.py"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_control_center(base: Path) -> Path:
    control = base / "00-知识库中控"
    write(control / "wiki" / "index.md", "# Index\n\n- [Topic](topics/topic.md)\n")
    write(control / "wiki" / "log.md", "# Log\n")
    write(control / "wiki" / "topics" / "topic.md", "# Topic\n\nUseful topic text.\n")
    return control


def run_doctor(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=merged_env, check=False)


class RootResolutionTests(unittest.TestCase):
    def test_report_resolves_explicit_control_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            result = run_doctor("report", "--root", str(control), "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["root"]["control_center"], str(control.resolve()))
            self.assertEqual(payload["root"]["wiki_root"], str((control / "wiki").resolve()))
            self.assertTrue(payload["state"]["init_done"])

    def test_validate_reports_invalid_explicit_root_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            result = run_doctor("validate", "--root", str(missing), "--format", "json", "--fail-on", "error")
            self.assertEqual(result.returncode, 1)
            findings = json.loads(result.stdout)
            self.assertEqual(findings[0]["check"], "invalid-root")
            self.assertEqual(findings[0]["severity"], "ERROR")

    def test_environment_root_is_used_when_no_root_argument_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            result = run_doctor("score", "--format", "json", env={"OBSIDIAN_LLM_WIKI_ROOT": str(control)})
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["root"]["control_center"], str(control.resolve()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify failure**

```powershell
python -m unittest tests.test_obsidian_wiki_doctor.RootResolutionTests
```

Expected: ERROR because `scripts/obsidian_wiki_doctor.py` is missing.

- [ ] **Step 3: Commit the red tests**

```powershell
git add tests/test_obsidian_wiki_doctor.py
git commit -m "test: add obsidian wiki doctor root tests"
```

## Task 2: CLI Skeleton And Root Resolution

**Files:**
- Create: `scripts/obsidian_wiki_doctor.py`

- [ ] **Step 1: Implement script skeleton**

Create `scripts/obsidian_wiki_doctor.py` with these units:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_CONTROL_CENTER = Path(r"C:\Users\<user>\Documents\Obsidian Vault\00-知识库中控")
ENV_ROOT = "OBSIDIAN_LLM_WIKI_ROOT"

@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    path: str
    message: str
    line: int | None = None
    hint: str | None = None

@dataclass(frozen=True)
class ResolvedRoot:
    control_center: Path | None
    wiki_root: Path | None
    input_root: Path | None
    source: str
    error: Finding | None = None

@dataclass(frozen=True)
class WikiState:
    init_done: bool
    onboarding_done: bool
    inventory_done: bool
    ingest_started: bool
    generated_pages_exist: bool
```

Superseded by the v0.2 shared Root Resolver; this path is a historical example,
not a runtime default.

Add `read_text`, `is_control_center`, `is_direct_wiki_root`, `resolve_root`, `resolve_explicit_root`, `invalid_root`, `parse_markdown_table_rows`, `build_state`, `run_checks`, `run_validate`, `run_score`, `run_report`, `build_parser`, and `main`. The signatures must be exactly:

Use these exact function names and signatures in the script:

- `resolve_root(root_arg: str | None) -> ResolvedRoot`
- `build_state(root: ResolvedRoot) -> WikiState`
- `run_checks(root: ResolvedRoot, state: WikiState) -> list[Finding]`
- `run_validate(args: argparse.Namespace) -> int`
- `run_score(args: argparse.Namespace) -> int`
- `run_report(args: argparse.Namespace) -> int`
- `main(argv: list[str] | None = None) -> int`

Minimum behavior:

- `--root` wins over environment.
- `OBSIDIAN_LLM_WIKI_ROOT` is used when no `--root` is provided.
- invalid explicit root returns `invalid-root` ERROR.
- unresolved fallback returns `missing-control-center` ERROR.
- `report --format json` returns `root`, `state`, `findings`, and `score` keys.
- `score --format json` returns `root`, `score_version`, `score`, `dimensions`, `signals`, and `next_steps` keys.

- [ ] **Step 2: Run root tests**

```powershell
python -m unittest tests.test_obsidian_wiki_doctor.RootResolutionTests
```

Expected: `OK`.

- [ ] **Step 3: Commit implementation**

```powershell
git add scripts/obsidian_wiki_doctor.py tests/test_obsidian_wiki_doctor.py
git commit -m "feat: add obsidian wiki doctor root resolution"
```
## Task 3: Structure, Link, Ingest, And Safety Checks

**Files:**
- Modify: `tests/test_obsidian_wiki_doctor.py`
- Modify: `scripts/obsidian_wiki_doctor.py`

- [ ] **Step 1: Add failing validation tests**

Add `ValidationCheckTests` before the `if __name__ == "__main__"` block:

```python
class ValidationCheckTests(unittest.TestCase):
    def test_missing_wiki_index_is_error_when_log_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-知识库中控"
            write(control / "wiki" / "log.md", "# Log\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing-wiki-index", {item["check"] for item in findings})

    def test_broken_index_link_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-知识库中控"
            write(control / "wiki" / "index.md", "# Index\n\n- [Missing](topics/missing.md)\n")
            write(control / "wiki" / "log.md", "# Log\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            broken = [item for item in findings if item["check"] == "broken-index-link"]
            self.assertEqual(result.returncode, 1)
            self.assertEqual(broken[0]["severity"], "ERROR")
            self.assertIn("topics/missing.md", broken[0]["message"])

    def test_missing_source_proxy_for_processed_ingest_row_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "ingest" / "index.md", "| source | proxy | status | wiki_entry |\n|---|---|---|---|\n| D:/docs/a.md | sources/a.md | processed | topics/a.md |\n")
            write(control / "wiki" / "topics" / "a.md", "# A\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertIn("missing-source-proxy", {item["check"] for item in findings})

    def test_safety_check_redacts_secret_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "sources" / "secret.md", "# Secret\n\ntoken=<secret-fixture>\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            sensitive = [item for item in findings if item["check"] == "sensitive-pattern"]
            self.assertTrue(sensitive)
            serialized = json.dumps(sensitive, ensure_ascii=False)
            self.assertIn("token", serialized)
            self.assertNotIn("secret-fixture", serialized)
```

- [ ] **Step 2: Run validation tests and verify failure**

```powershell
python -m unittest tests.test_obsidian_wiki_doctor.ValidationCheckTests
```

Expected: FAIL because checks are not implemented.

- [ ] **Step 3: Implement check helpers**

In `scripts/obsidian_wiki_doctor.py`, add:

```python
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SENSITIVE_PATTERNS = [
    ("password", re.compile(r"(?i)\bpassword\s*[:=]")),
    ("token", re.compile(r"(?i)\btoken\s*[:=]")),
    ("secret", re.compile(r"(?i)\bsecret\s*[:=]")),
    ("ak-sk", re.compile(r"(?i)\bAK/SK\b|access[_-]?key|secret[_-]?key")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("cookie", re.compile(r"(?i)\bcookie\s*[:=]")),
    ("credentialed-rtsp", re.compile(r"(?i)rtsp://[^\s/@:]+:[^\s/@]+@")),
    ("connection-string", re.compile(r"(?i)(jdbc:|mongodb://|postgres://|mysql://)")),
    ("internal-endpoint", re.compile(r"(?i)https?://(?:10\.|172\.(?:1[6-9]|2\d|3[0-1])\.|192\.168\.|localhost|127\.0\.0\.1)")),
]
```

Add helpers with exact names:

Implement these exact helper functions:

- `iter_markdown_files(wiki_root: Path) -> list[Path]`
- `repo_path(root: Path, path: Path) -> str`
- `resolve_markdown_link(source: Path, target: str) -> Path | None`
- `table_dicts(text: str) -> list[dict[str, str]]`
- `check_required_structure(root: ResolvedRoot, state: WikiState) -> list[Finding]`
- `check_links(root: ResolvedRoot) -> list[Finding]`
- `check_ingest(root: ResolvedRoot, state: WikiState) -> list[Finding]`
- `check_safety(root: ResolvedRoot) -> list[Finding]`

Implementation requirements:

- `missing-wiki-index` is ERROR when `wiki/log.md` exists but `wiki/index.md` does not.
- `missing-wiki-log` is ERROR when `wiki/index.md` exists but `wiki/log.md` does not.
- `missing-roadmap` and `missing-knowledge-map` are WARN only when `init_done` is true.
- Markdown links ignore external URLs and anchors.
- `broken-index-link` is ERROR; `broken-internal-link` is WARN.
- `missing-source-proxy` only fires when `ingest_started` is true and a processed row names a proxy that does not exist.
- `sensitive-pattern` message includes category, path, and line; it does not include the matched line value.

Replace `run_checks` so it returns root errors first, then structure, links, ingest, and safety checks.

- [ ] **Step 4: Run tests**

```powershell
python -m unittest tests.test_obsidian_wiki_doctor.ValidationCheckTests
python -m unittest tests.test_obsidian_wiki_doctor
```

Expected: both commands end with `OK`.

- [ ] **Step 5: Commit checks**

```powershell
git add scripts/obsidian_wiki_doctor.py tests/test_obsidian_wiki_doctor.py
git commit -m "feat: add obsidian wiki doctor checks"
```

## Task 4: Score And Chinese Report

**Files:**
- Modify: `tests/test_obsidian_wiki_doctor.py`
- Modify: `scripts/obsidian_wiki_doctor.py`

- [ ] **Step 1: Add failing score/report tests**

Add `ScoreAndReportTests`:

```python
class ScoreAndReportTests(unittest.TestCase):
    def test_score_marks_ingest_not_applicable_for_fresh_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            result = run_doctor("score", "--root", str(control), "--format", "json")
            payload = json.loads(result.stdout)
            ingest = [item for item in payload["dimensions"] if item["name"] == "Ingest traceability"][0]
            self.assertEqual(result.returncode, 0)
            self.assertEqual(ingest["applicability"], "not-applicable")

    def test_report_text_is_chinese_first_and_always_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-知识库中控"
            write(control / "wiki" / "log.md", "# Log\n")
            result = run_doctor("report", "--root", str(control), "--format", "text")
            self.assertEqual(result.returncode, 0)
            self.assertIn("# Obsidian Wiki Doctor 报告", result.stdout)
            self.assertIn("## 建议行动计划", result.stdout)
            self.assertIn("missing-wiki-index", result.stdout)

    def test_report_json_contains_root_state_findings_and_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            result = run_doctor("report", "--root", str(control), "--format", "json")
            payload = json.loads(result.stdout)
            self.assertIn("root", payload)
            self.assertIn("state", payload)
            self.assertIn("findings", payload)
            self.assertIn("score", payload)
```

- [ ] **Step 2: Run score/report tests and verify failure**

```powershell
python -m unittest tests.test_obsidian_wiki_doctor.ScoreAndReportTests
```

Expected: FAIL because dimensions and report formatting are incomplete.

- [ ] **Step 3: Implement scoring types and formatters**

Add dataclasses:

```python
@dataclass(frozen=True)
class ScoreDimension:
    name: str
    weight: int
    score: int | None
    applicability: str
    message: str

@dataclass(frozen=True)
class ScoreReport:
    score_version: int
    score: int
    level: str
    dimensions: list[ScoreDimension]
    signals: dict[str, object]
    next_steps: list[str]
```

Add functions with exact names:

Implement these exact scoring/report functions:

- `score_level(score: int) -> str`
- `build_score_report(root: ResolvedRoot, state: WikiState, findings: list[Finding]) -> ScoreReport`
- `score_to_dict(report: ScoreReport, root: ResolvedRoot) -> dict[str, object]`
- `format_report_text(root: ResolvedRoot, state: WikiState, findings: list[Finding]) -> str`

Scoring requirements:

- `Control center resolution`: 20 points, 0 on root error.
- `Navigation and discoverability`: 25 points, 0 on missing index/log or broken index link, 15 when only WARNs exist.
- `Ingest traceability`: 20 points, `not-applicable` when `ingest_started` is false.
- `Safety hygiene`: 20 points, 0 on `sensitive-pattern` ERROR.
- `Query readiness`: 15 points, 15 when generated pages exist and no root error.
- Normalize over applicable dimensions.

Report sections must be exactly:

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

- [ ] **Step 4: Run tests**

```powershell
python -m unittest tests.test_obsidian_wiki_doctor.ScoreAndReportTests
python -m unittest tests.test_obsidian_wiki_doctor
```

Expected: both commands end with `OK`.

- [ ] **Step 5: Commit score/report**

```powershell
git add scripts/obsidian_wiki_doctor.py tests/test_obsidian_wiki_doctor.py
git commit -m "feat: add obsidian wiki doctor reports"
```
## Task 5: Add The `obsidian-wiki-doctor` Skill

**Files:**
- Create: `skills/obsidian-wiki-doctor/SKILL.md`
- Create: `skills/obsidian-wiki-doctor/references/doctor-checks.md`
- Create: `skills/obsidian-wiki-doctor/references/report-template.md`
- Create: `skills/obsidian-wiki-doctor/references/safety-rules.md`

- [ ] **Step 1: Create `SKILL.md`**

```markdown
---
name: obsidian-wiki-doctor
description: Use this whenever the user wants to diagnose, validate, score, report on, or explain the health or maturity of an Obsidian LLM Wiki, including prompts like "run Obsidian Wiki Doctor", "诊断 wiki", "给 wiki 打健康分", "出中文健康报告", "看看初始化后有没有用", or questions about whether poor query quality is caused by wiki structure. This skill is read-only and never repairs files.
---

# Obsidian Wiki Doctor

Diagnose an Obsidian LLM Wiki with the deterministic doctor engine.

## Boundary

Use this skill to look, score, validate, and explain. Do not edit vault files.

Use `obsidian-wiki-maintain` when the user asks to fix, repair, patch links, update `index.md`, add source proxies, or apply findings from a doctor report.

## Required First Check

1. Resolve the target control center or wiki root.
2. Prefer the user-provided path.
3. Otherwise honor `OBSIDIAN_LLM_WIKI_ROOT`.
4. Otherwise allow the doctor script fallback behavior.
5. State the resolved control center and wiki root in the answer.

## Commands

Human report:

```text
python scripts/obsidian_wiki_doctor.py report --root <control-center-or-vault> --format text
```

Machine validation:

```text
python scripts/obsidian_wiki_doctor.py validate --root <control-center-or-vault> --format json --fail-on error
```

Structured score:

```text
python scripts/obsidian_wiki_doctor.py score --root <control-center-or-vault> --format json
```

## Interpretation Rules

- Treat script findings as deterministic evidence.
- Treat score as directional guidance, not a KPI.
- Never print secret values.
- Keep Chinese-first explanations for Chinese users.
- Explain `not-applicable` dimensions instead of treating them as failures.
- If the user asks to repair, hand off to `obsidian-wiki-maintain` with a narrow repair scope.
```

- [ ] **Step 2: Create reference docs**

Create `references/doctor-checks.md` with ERROR/WARN/INFO check names from the v2 spec and this opening line:

```markdown
The source of truth for detection is `scripts/obsidian_wiki_doctor.py`. This file explains the public vocabulary only.
```

Create `references/report-template.md` with the report section order and JSON keys:

```markdown
JSON reports contain `root`, `state`, `findings`, and `score`. Text reports use the Chinese-first section order from the design spec.
```

Create `references/safety-rules.md` with this rule:

```markdown
The doctor reports risk category, file path, line number, and repair hint. It never prints secret values in text or JSON output.
```

- [ ] **Step 3: Run package listing**

```powershell
npx.cmd skills add . --list
```

Expected: output includes `obsidian-wiki-doctor` plus the existing four skills.

- [ ] **Step 4: Commit the skill**

```powershell
git add skills/obsidian-wiki-doctor
git commit -m "feat: add obsidian wiki doctor skill"
```

## Task 6: Re-Scope `obsidian-wiki-maintain` To Repair-Only

**Files:**
- Modify: `skills/obsidian-wiki-maintain/SKILL.md`
- Modify: `skills/obsidian-wiki-maintain/references/repair-policy.md`
- Modify: `tests/prompts.md`

- [ ] **Step 1: Rewrite maintain description**

Set the frontmatter description to:

```markdown
description: Use this whenever the user wants to repair, fix, patch, update, or apply approved structural fixes to an Obsidian LLM Wiki, including fixing broken links, adding missing index links, adding source proxy links, updating log entries, or applying findings from an Obsidian Wiki Doctor report. This skill writes only approved narrow repairs; use obsidian-wiki-doctor for read-only diagnosis, validation, scoring, or health reports.
```

Replace the purpose text with:

```markdown
Apply approved structural repairs to an Obsidian LLM Wiki.

This skill is the write side of the Doctor/Maintain pair. Detection belongs to `scripts/obsidian_wiki_doctor.py` and the `obsidian-wiki-doctor` skill. Maintain consumes doctor findings, confirms repair scope, applies narrow fixes, and records changes in `log.md`.
```

- [ ] **Step 2: Replace maintain workflow**

```markdown
## Workflow

1. Resolve and state the active Obsidian wiki root.
2. Run or consume `obsidian-wiki-doctor` findings.
3. Restate the repair scope in concrete file paths.
4. Ask before broad repairs or sensitive-content cleanup.
5. Apply only approved narrow fixes.
6. Update `log.md` for maintenance changes.
7. Return changed files, skipped findings, and remaining risks.
```

- [ ] **Step 3: Replace health-check rules with repair policy**

`skills/obsidian-wiki-maintain/references/repair-policy.md` must start with:

```markdown
# Maintain Repair Policy

Detection is performed by `scripts/obsidian_wiki_doctor.py` through `obsidian-wiki-doctor`. This file documents repair rules only.
```

Keep allowed repairs narrow:

- add missing `wiki/index.md` links for known wiki pages;
- add a `log.md` entry for the current maintenance action;
- fix clearly broken relative links when the target is unambiguous;
- add a missing source proxy link when the proxy page already exists;
- add a source proxy shell only when the ingest row already names the source and wiki entry.

- [ ] **Step 4: Update prompts**

Move read-only health prompts into an `obsidian-wiki-doctor` section. Keep maintain prompts as repair prompts such as:

```text
帮我把 doctor 报告里的断链修好，只修明确能定位的链接。
```

Expected behavior for maintain:

- consumes doctor findings or runs the doctor engine first;
- asks before broad repairs;
- applies only approved narrow fixes;
- records maintenance changes in `log.md`.

- [ ] **Step 5: Run trigger-boundary grep**

```powershell
rg -n "Run a health check|find broken links|find orphan pages|check index/log|diagnose|score" skills/obsidian-wiki-maintain tests/prompts.md
```

Expected: maintain-owned read-only diagnosis phrases are gone; references are allowed only when routing to doctor.

- [ ] **Step 6: Commit maintain re-scope**

```powershell
git add skills/obsidian-wiki-maintain/SKILL.md skills/obsidian-wiki-maintain/references/repair-policy.md tests/prompts.md
git commit -m "refactor: route wiki diagnosis through doctor"
```

## Task 7: Update Five-Skill Documentation

**Files:**
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/architecture.md`
- Modify: `docs/safety.md`
- Modify: `docs/development-plan.md`
- Modify: `docs/workflow.md`
- Modify: `skills/obsidian-wiki-init/SKILL.md`
- Modify: `skills/obsidian-wiki-query/SKILL.md`

- [ ] **Step 1: Update README files**

In `README.md`, replace four-skill framing with five-skill framing and add:

```markdown
| `obsidian-wiki-doctor` | Read-only validation, maturity scoring, and Chinese-first health reports for the active Obsidian LLM Wiki |
```

In `README.zh.md`, add:

```markdown
| `obsidian-wiki-doctor` | 对当前 Obsidian LLM Wiki 做只读校验、成熟度评分和中文健康报告 |
```

Update intent split:

```text
doctor   = read-only diagnosis, scoring, and reports
maintain = apply approved structural repairs
```

- [ ] **Step 2: Update architecture**

Replace `## Why Four Skills` with `## Why Five Skills`. Add doctor as a read-only measurement layer beside the loop, not as a replacement for maintain.

- [ ] **Step 3: Update safety, development plan, and workflow**

Add to `docs/safety.md`:

```markdown
## Doctor Safety

`obsidian-wiki-doctor` is read-only. It may scan generated wiki pages for sensitive patterns, but reports only risk category, file path, and line number. It must not print secret values in text or JSON output.
```

Add a Doctor phase to `docs/development-plan.md`, explicitly saying this introduces the repo's first deterministic script and unittest surface.

Add a Doctor workflow section to `docs/workflow.md`: use after init/ingest, before maintain repairs, and when query quality seems structurally poor.

- [ ] **Step 4: Update init and query routing notes**

In `skills/obsidian-wiki-init/SKILL.md`, add a final-output note recommending `obsidian-wiki-doctor report` after init.

In `skills/obsidian-wiki-query/SKILL.md`, add a boundary note: if the user asks why query quality is poor or whether init/ingest created enough entrypoints, route to `obsidian-wiki-doctor`.

- [ ] **Step 5: Run consistency grep**

```powershell
rg -n "four skills|4 skills|Why Four Skills|4 个 skills" README.md README.zh.md docs
rg -n "obsidian-wiki-doctor|obsidian_wiki_doctor|Doctor" README.md README.zh.md docs skills tests scripts
```

Expected: first command returns no stale framing; second command shows the new skill, docs, tests, and script.

- [ ] **Step 6: Commit docs**

```powershell
git add README.md README.zh.md docs/architecture.md docs/safety.md docs/development-plan.md docs/workflow.md skills/obsidian-wiki-init/SKILL.md skills/obsidian-wiki-query/SKILL.md
git commit -m "docs: document obsidian wiki doctor workflow"
```

## Task 8: Final Verification

**Files:**
- All files touched by previous tasks.

- [ ] **Step 1: Run all tests**

```powershell
python -m unittest discover tests
```

Expected: all tests pass.

- [ ] **Step 2: Run Skills CLI listing**

```powershell
npx.cmd skills add . --list
```

Expected: output includes all five skills:

```text
obsidian-wiki-init
obsidian-wiki-ingest
obsidian-wiki-doctor
obsidian-wiki-maintain
obsidian-wiki-query
```

- [ ] **Step 3: Run spec grep checks**

```powershell
rg -n "four skills|Why Four Skills" README.md README.zh.md docs --glob "!docs/superpowers/**"
rg -n "Project Graph|Flow Record|release gate" skills/obsidian-wiki-doctor docs --glob "!docs/superpowers/**"
rg -n "secret-fixture" . --glob "!tests/test_obsidian_wiki_doctor.py" --glob "!docs/superpowers/**"
```

Expected: no stale four-skill framing, no project-lifecycle leakage in production docs, and no test secret example outside the test file.

- [ ] **Step 4: Run manual CLI smoke checks**

```powershell
python scripts/obsidian_wiki_doctor.py report --root <temp>\00-知识库中控 --format text
python scripts/obsidian_wiki_doctor.py validate --root <temp>\00-知识库中控 --format json --fail-on error
python scripts/obsidian_wiki_doctor.py score --root <temp>\00-知识库中控 --format json
```

Expected: report exits 0, score exits 0, validate exits 0 for a healthy sample or 1 for an intentionally broken sample.

- [ ] **Step 5: Check Git hygiene**

```powershell
git status --short
git log --oneline -5
```

Expected: only intended files are modified. Do not create an empty verification commit if no files changed.

## Self-Review

Spec coverage:

- Dedicated fifth skill: Task 5.
- One detection engine, two entry points: Tasks 2-6.
- Read/write routing split: Tasks 5-7.
- Root resolution with `OBSIDIAN_LLM_WIKI_ROOT` and `invalid-root`: Tasks 1-2.
- State predicates: Tasks 1-2.
- Structure, link, ingest, safety checks: Task 3.
- Score and Chinese report: Task 4.
- Maintain re-scope: Task 6.
- Five-skill docs and Python/unittest introduction: Task 7.
- Verification commands: Task 8.

No empty-marker scan:

- The plan has no unresolved work markers.
- Every task names exact files.
- Every code-changing task includes exact function names, expected behavior, and commands.

Type consistency:

- `Finding`, `ResolvedRoot`, `WikiState`, `ScoreDimension`, and `ScoreReport` are defined before use.
- CLI subcommands are consistently `validate`, `score`, and `report`.
- Check names match the v2 design: `invalid-root`, `missing-control-center`, `missing-wiki-index`, `missing-wiki-log`, `missing-ingest-index`, `missing-roadmap`, `missing-knowledge-map`, `broken-index-link`, `broken-internal-link`, `missing-source-proxy`, `source-proxy-incomplete`, `ingest-row-without-wiki-entry`, and `sensitive-pattern`.
