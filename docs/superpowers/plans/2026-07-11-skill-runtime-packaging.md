# Installable Skill Runtime Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `npx skills add huajiexiewenfeng/obsidian-llm-wiki` install and execute the complete deterministic Python runtime.

**Architecture:** Add a normal, installable `obsidian-wiki-runtime` skill that owns the canonical Python implementation. The five workflow skills resolve that sibling skill explicitly, while repository-root scripts become compatibility launchers. Static contract tests and an isolated Skills CLI smoke test enforce both source layout and installed behavior.

**Tech Stack:** Python 3.10+, `unittest`, Skills CLI 1.5.16, GitHub Actions, Markdown skill definitions.

---

### Task 1: Lock the Runtime Packaging Contract with a Failing Test

**Files:**
- Create: `tests/test_skill_runtime_packaging.py`
- Read: `docs/superpowers/specs/2026-07-11-skill-runtime-packaging-design.md`

- [ ] **Step 1: Write the failing repository contract tests**

Create `tests/test_skill_runtime_packaging.py`:

```python
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills"
RUNTIME_SKILL = SKILLS_ROOT / "obsidian-wiki-runtime"
CONSUMERS = (
    "obsidian-wiki-doctor",
    "obsidian-wiki-ingest",
    "obsidian-wiki-init",
    "obsidian-wiki-maintain",
    "obsidian-wiki-query",
)
REQUIRED_RUNTIME_FILES = (
    "SKILL.md",
    "scripts/llm_wiki.py",
    "scripts/obsidian_wiki_doctor.py",
    "scripts/llm_wiki_core/__init__.py",
    "scripts/llm_wiki_core/root.py",
)


class RuntimeSkillLayoutTests(unittest.TestCase):
    def test_runtime_skill_contains_complete_python_runtime(self):
        missing = [
            relative
            for relative in REQUIRED_RUNTIME_FILES
            if not (RUNTIME_SKILL / relative).is_file()
        ]
        self.assertEqual(missing, [])

    def test_runtime_skill_is_installed_by_default(self):
        text = (RUNTIME_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?m)^\s*internal:\s*true\s*$")

    def test_consumers_resolve_the_shared_runtime(self):
        for name in CONSUMERS:
            with self.subTest(skill=name):
                text = (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("## Runtime Resolution", text)
                self.assertIn("obsidian-wiki-runtime/scripts/llm_wiki.py", text)
                self.assertNotIn("python scripts/llm_wiki.py", text)

    def test_repository_scripts_are_compatibility_launchers(self):
        for relative, target in (
            ("scripts/llm_wiki.py", "obsidian-wiki-runtime"),
            ("scripts/obsidian_wiki_doctor.py", "obsidian-wiki-runtime"),
        ):
            with self.subTest(script=relative):
                text = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("runpy.run_path", text)
                self.assertIn(target, text)
                self.assertIsNone(re.search(r"from llm_wiki_core|^def build_parser", text, re.M))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest tests.test_skill_runtime_packaging -v
```

Expected: FAIL because `skills/obsidian-wiki-runtime/SKILL.md` and its runtime files do not exist.

- [ ] **Step 3: Commit the regression test**

```powershell
git add tests/test_skill_runtime_packaging.py
git commit -m "test: reproduce missing installed skill runtime"
```

### Task 2: Make the Runtime Skill Self-Contained

**Files:**
- Create: `skills/obsidian-wiki-runtime/SKILL.md`
- Move: `scripts/llm_wiki.py` to `skills/obsidian-wiki-runtime/scripts/llm_wiki.py`
- Move: `scripts/obsidian_wiki_doctor.py` to `skills/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py`
- Move: `scripts/llm_wiki_core/__init__.py` to `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/__init__.py`
- Move: `scripts/llm_wiki_core/root.py` to `skills/obsidian-wiki-runtime/scripts/llm_wiki_core/root.py`
- Recreate: `scripts/llm_wiki.py`
- Recreate: `scripts/obsidian_wiki_doctor.py`

- [ ] **Step 1: Move the canonical implementation under the installable skill**

Run:

```powershell
New-Item -ItemType Directory -Force skills/obsidian-wiki-runtime/scripts/llm_wiki_core
git mv scripts/llm_wiki.py skills/obsidian-wiki-runtime/scripts/llm_wiki.py
git mv scripts/obsidian_wiki_doctor.py skills/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py
git mv scripts/llm_wiki_core/__init__.py skills/obsidian-wiki-runtime/scripts/llm_wiki_core/__init__.py
git mv scripts/llm_wiki_core/root.py skills/obsidian-wiki-runtime/scripts/llm_wiki_core/root.py
```

- [ ] **Step 2: Add the runtime skill definition**

Create `skills/obsidian-wiki-runtime/SKILL.md`:

````markdown
---
name: obsidian-wiki-runtime
description: Shared deterministic runtime dependency for the Obsidian LLM Wiki workflow skills. Use only when another obsidian-wiki skill needs root resolution or Doctor commands.
---

# Obsidian Wiki Runtime

This skill packages the shared Python runtime required by the Obsidian Wiki
workflow skills. It is an installable dependency, not a user-facing workflow.

## Runtime Entry Point

Resolve this skill directory and invoke:

```text
python <this-skill-directory>/scripts/llm_wiki.py <group> <command> ...
```

Supported groups are `root` and `doctor`.

## Boundary

- Do not select this skill instead of init, ingest, maintain, query, or doctor.
- Do not edit Vault files unless the calling workflow explicitly authorizes it.
- Do not copy or expose sensitive values.
````

- [ ] **Step 3: Add repository compatibility launchers**

Create `scripts/llm_wiki.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

RUNTIME = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "obsidian-wiki-runtime"
    / "scripts"
    / "llm_wiki.py"
)

if not RUNTIME.is_file():
    raise SystemExit(f"missing-runtime: {RUNTIME}")

runpy.run_path(str(RUNTIME), run_name="__main__")
```

Create `scripts/obsidian_wiki_doctor.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

RUNTIME = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "obsidian-wiki-runtime"
    / "scripts"
    / "obsidian_wiki_doctor.py"
)

if not RUNTIME.is_file():
    raise SystemExit(f"missing-runtime: {RUNTIME}")

runpy.run_path(str(RUNTIME), run_name="__main__")
```

- [ ] **Step 4: Run compatibility and layout tests**

Run:

```powershell
python -m unittest tests.test_llm_wiki_cli tests.test_obsidian_wiki_doctor tests.test_skill_runtime_packaging -v
```

Expected: runtime file and launcher assertions pass; consumer-resolution assertions still fail.

- [ ] **Step 5: Commit the runtime package**

```powershell
git add scripts skills/obsidian-wiki-runtime
git commit -m "fix: package shared runtime as an installable skill"
```

### Task 3: Make Every Workflow Skill Resolve the Installed Runtime

**Files:**
- Modify: `skills/obsidian-wiki-doctor/SKILL.md`
- Modify: `skills/obsidian-wiki-ingest/SKILL.md`
- Modify: `skills/obsidian-wiki-init/SKILL.md`
- Modify: `skills/obsidian-wiki-maintain/SKILL.md`
- Modify: `skills/obsidian-wiki-query/SKILL.md`
- Test: `tests/test_skill_runtime_packaging.py`

- [ ] **Step 1: Add the runtime-resolution contract to all five skills**

Insert this section after each skill's boundary/introduction and before its first runtime command:

````markdown
## Runtime Resolution

Before running any command, resolve this skill's `SKILL.md` directory, take its
parent as `<skills-root>`, and set:

```text
<runtime-script> = <skills-root>/obsidian-wiki-runtime/scripts/llm_wiki.py
```

Verify that `<runtime-script>` exists, then invoke it by absolute path. If it is
missing, stop with `missing-runtime`, report the expected path, and recommend:

```text
npx skills add huajiexiewenfeng/obsidian-llm-wiki --skill '*' --copy --yes
```

Do not fall back to a repository-relative `scripts/llm_wiki.py` path.
````

- [ ] **Step 2: Replace every runtime command example**

Replace:

```text
python scripts/llm_wiki.py
```

with:

```text
python "<runtime-script>"
```

Also replace Doctor compatibility references with:

```text
<skills-root>/obsidian-wiki-runtime/scripts/obsidian_wiki_doctor.py
```

- [ ] **Step 3: Run the contract test and verify GREEN**

Run:

```powershell
python -m unittest tests.test_skill_runtime_packaging -v
```

Expected: 4 tests pass.

- [ ] **Step 4: Run root documentation tests**

Run:

```powershell
python -m unittest tests.test_llm_wiki_root.DiscoveryDocumentationTests -v
```

Expected: all discovery documentation checks pass.

- [ ] **Step 5: Commit consumer resolution changes**

```powershell
git add skills/obsidian-wiki-doctor skills/obsidian-wiki-ingest skills/obsidian-wiki-init skills/obsidian-wiki-maintain skills/obsidian-wiki-query
git commit -m "fix: resolve runtime from installed skill root"
```

### Task 4: Prove Skills CLI Installs and Runs the Runtime

**Files:**
- Create: `tests/test_skills_cli_install.py`
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: Write the environment-gated integration test**

Create `tests/test_skills_cli_install.py`:

```python
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    os.environ.get("RUN_SKILLS_CLI_INTEGRATION") == "1",
    "set RUN_SKILLS_CLI_INTEGRATION=1 to run Skills CLI integration",
)
class SkillsCliInstallTests(unittest.TestCase):
    def test_project_copy_install_contains_and_runs_runtime(self):
        executable = shutil.which("npx.cmd" if os.name == "nt" else "npx")
        self.assertIsNotNone(executable, "npx is required")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "install-project"
            home = base / "home"
            project.mkdir()
            home.mkdir()
            environment = os.environ.copy()
            environment.update({
                "HOME": str(home),
                "USERPROFILE": str(home),
                "DISABLE_TELEMETRY": "1",
                "DO_NOT_TRACK": "1",
            })
            install = subprocess.run(
                [
                    executable,
                    "--yes",
                    "skills@1.5.16",
                    "add",
                    str(REPO_ROOT),
                    "--skill",
                    "*",
                    "--agent",
                    "codex",
                    "--copy",
                    "--yes",
                ],
                cwd=project,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=180,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)

            matches = list(project.rglob("obsidian-wiki-runtime/scripts/llm_wiki.py"))
            self.assertTrue(matches, install.stdout + install.stderr)
            runtime = matches[0]
            skills_root = runtime.parents[2]
            for name in (
                "obsidian-wiki-doctor",
                "obsidian-wiki-ingest",
                "obsidian-wiki-init",
                "obsidian-wiki-maintain",
                "obsidian-wiki-query",
            ):
                self.assertTrue((skills_root / name / "SKILL.md").is_file(), name)

            vault = base / "Sample Vault"
            wiki = vault / "00-知识库中控" / "wiki"
            wiki.mkdir(parents=True)
            (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
            (wiki / "log.md").write_text("# Log\n", encoding="utf-8")

            resolved = subprocess.run(
                [sys.executable, str(runtime), "root", "resolve", "--root", str(vault), "--format", "json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            self.assertEqual(json.loads(resolved.stdout)["vault_root"], str(vault.resolve()))

            report = subprocess.run(
                [sys.executable, str(runtime), "doctor", "report", "--root", str(vault), "--format", "json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("score", json.loads(report.stdout))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Add a dedicated CI integration job**

Append to `.github/workflows/test.yml`:

```yaml
  skills-cli-install:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: Install skills and run installed runtime
        env:
          RUN_SKILLS_CLI_INTEGRATION: "1"
        run: python -m unittest tests.test_skills_cli_install -v
```

- [ ] **Step 3: Run the installed-runtime acceptance test**

The static packaging contract in Task 1 is the mandatory RED evidence for this
bug. This black-box test verifies the same contract through the real installer.
Run:

```powershell
$env:RUN_SKILLS_CLI_INTEGRATION='1'
python -m unittest tests.test_skills_cli_install -v
```

Expected: 1 test passes; output shows all six skills copied into the temporary project.

- [ ] **Step 4: Commit installation coverage**

```powershell
git add tests/test_skills_cli_install.py .github/workflows/test.yml
git commit -m "test: verify Skills CLI installs shared runtime"
```

### Task 5: Document the Install Contract and Verify Everything

**Files:**
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: Document the installed runtime in both READMEs**

Add after the installation commands:

````markdown
The complete repository install includes the shared `obsidian-wiki-runtime`
skill. It carries the Python files used by root resolution and Wiki Doctor.
Install the complete skill set; installing only a workflow skill leaves its
runtime dependency unavailable.

Verify a local checkout before publishing with:

```text
npx skills add . --skill '*' --agent codex --copy --yes
```
````

Add this text to `README.zh.md`:

````markdown
完整仓库安装会同时安装共享的 `obsidian-wiki-runtime` 技能。该技能携带根目录解析和 Wiki Doctor 使用的 Python 文件。请安装完整技能集；如果只安装单个工作流技能，其运行时依赖将不可用。

发布前可在本地仓库执行以下命令验证：

```text
npx skills add . --skill '*' --agent codex --copy --yes
```
````

- [ ] **Step 2: Document canonical and compatibility paths**

Add this architecture rule to `docs/architecture.md`:

```markdown
## Runtime Packaging

`skills/obsidian-wiki-runtime/scripts/` is the canonical deterministic runtime.
Workflow skills locate it as a sibling beneath the installed skills root.
Repository-root `scripts/` files are compatibility launchers for development
and existing automation; they contain no runtime implementation.
```

- [ ] **Step 3: Run the complete Python suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass; the Skills CLI test is skipped unless explicitly enabled.

- [ ] **Step 4: Run the isolated Skills CLI integration test**

Run:

```powershell
$env:RUN_SKILLS_CLI_INTEGRATION='1'
python -m unittest tests.test_skills_cli_install -v
```

Expected: 1 test passes.

- [ ] **Step 5: Verify repository hygiene**

Run:

```powershell
git diff --check
git status --short
git log --oneline --max-count=6
```

Expected: no whitespace errors; only intended documentation changes remain before the final commit.

- [ ] **Step 6: Commit documentation**

```powershell
git add README.md README.zh.md docs/architecture.md
git commit -m "docs: explain installable shared runtime"
```

- [ ] **Step 7: Run fresh final verification after the commit**

Run both commands again:

```powershell
python -m unittest discover -s tests -v
$env:RUN_SKILLS_CLI_INTEGRATION='1'
python -m unittest tests.test_skills_cli_install -v
```

Expected: full unit suite passes and isolated install smoke passes.

### Task 6: Synchronize the Verified Skills for User Testing

**Files:**
- Source: `skills/obsidian-wiki-runtime/`
- Source: `skills/obsidian-wiki-doctor/`
- Source: `skills/obsidian-wiki-ingest/`
- Source: `skills/obsidian-wiki-init/`
- Source: `skills/obsidian-wiki-maintain/`
- Source: `skills/obsidian-wiki-query/`
- Destination: `C:/Users/admin/.agents/skills/`

- [ ] **Step 1: Install the local checkout through Skills CLI**

Run outside the test sandbox only after all verification passes:

```powershell
npx.cmd skills add . --skill '*' --agent codex --copy --global --yes
```

Expected: all six Obsidian skills are installed under the user's canonical skills directory.

- [ ] **Step 2: Verify the local installed files without reading a real Vault**

Check that the installed runtime has all required files, then run:

```powershell
python C:/Users/admin/.agents/skills/obsidian-wiki-runtime/scripts/llm_wiki.py --help
```

Expected: CLI help exits successfully and the installed runtime imports its sibling modules.

- [ ] **Step 3: Hand off to user testing**

Report the local `main` commit IDs, installed runtime path, unit-test result, Skills CLI smoke result, and that GitHub has not been pushed. Ask the user to restart Codex before invoking `obsidian-wiki-doctor` so skill discovery refreshes.
