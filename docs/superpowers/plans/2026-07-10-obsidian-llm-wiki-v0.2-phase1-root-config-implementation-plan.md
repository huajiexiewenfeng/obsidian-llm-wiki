# Obsidian LLM Wiki v0.2 Phase 1 Root And Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the personal-machine Vault default and introduce one tested Root Resolver, JSON configuration contract, and canonical CLI that both the new entry point and the existing Doctor use.

**Architecture:** Add a focused `llm_wiki_core.root` module that owns root models, explicit path classification, project configuration, environment fallback, and user configuration. Keep the current Doctor checks intact; Phase 1 only replaces its root-resolution implementation and adds a `llm_wiki.py` dispatcher so old and new Doctor invocations resolve the same Vault.

**Tech Stack:** Python 3.10+ standard library (`argparse`, `dataclasses`, `json`, `os`, `pathlib`, `subprocess`, `unittest`), Markdown Agent Skills, GitHub Actions on Ubuntu and Windows.

---

## Scope

This plan implements only v0.2 Phase 1:

- `.obsidian-llm-wiki.json` project configuration.
- Cross-platform user configuration path discovery.
- One Root Resolver with the approved priority order.
- `scripts/llm_wiki.py root resolve`.
- `scripts/llm_wiki.py doctor validate/score/report` compatibility dispatch.
- Existing `scripts/obsidian_wiki_doctor.py` using the shared resolver.
- Skill and public documentation aligned to the shared contract.
- Python 3.10+, Ubuntu, and Windows test coverage.

This plan does not implement `.meta`, registries, locks, `ingest apply`, managed Markdown regions, projection rebuilding, or migration.

## Prerequisites

- Execute in a dedicated worktree created from `032608c` or a descendant containing the approved design and this plan.
- Use a branch named `codex/obsidian-llm-wiki-v0.2-phase1` unless the user chooses another name.
- Commit the approved design and implementation plan before creating an implementation worktree, so the worker can read both files.
- A Python 3.10+ interpreter is required. The planning workstation currently has no working `python` or `py` command, so implementation must not claim local test success until an interpreter or CI run provides evidence.

Preflight commands:

```powershell
git status --short --branch
git rev-parse --short HEAD
python --version
```

Expected:

```text
The implementation worktree is on codex/obsidian-llm-wiki-v0.2-phase1.
HEAD contains the approved design and plan.
Python reports 3.10 or newer.
```

If `python` is unavailable, stop local implementation and arrange Python 3.10+ or execute the test commands in the GitHub Actions matrix before making any passing claim.

## File Map

### Create

- `scripts/llm_wiki_core/__init__.py`: public exports for root-resolution models and functions.
- `scripts/llm_wiki_core/root.py`: the only Root Resolver implementation.
- `scripts/llm_wiki.py`: canonical CLI for `root resolve` and Doctor compatibility dispatch.
- `tests/test_llm_wiki_root.py`: direct unit tests for explicit roots and configuration priority.
- `tests/test_llm_wiki_cli.py`: subprocess tests for the canonical CLI and Doctor parity.
- `.github/workflows/test.yml`: Ubuntu and Windows Python 3.10/3.12 matrix.

### Modify

- `scripts/obsidian_wiki_doctor.py:7-168`: remove the personal default and import shared root models/functions.
- `scripts/obsidian_wiki_doctor.py:423-443`: convert shared root issues into Doctor findings without changing public JSON fields.
- `scripts/obsidian_wiki_doctor.py:670-704`: keep existing commands while using the shared resolver.
- `tests/test_obsidian_wiki_doctor.py:1-63`: add working-directory and project-config support to subprocess helpers and preserve legacy behavior tests.
- `skills/obsidian-wiki-init/SKILL.md`: require the shared resolution order before initialization writes.
- `skills/obsidian-wiki-ingest/SKILL.md:27-50`: remove the personal default and broad filesystem search.
- `skills/obsidian-wiki-doctor/SKILL.md:16-36`: document canonical and compatibility commands.
- `skills/obsidian-wiki-maintain/SKILL.md:25-44`: replace duplicated root logic with the shared contract.
- `skills/obsidian-wiki-query/SKILL.md:24-43`: replace duplicated root logic with the shared contract.
- `README.md`: add Python requirement, project config, and Root Resolver usage.
- `README.zh.md`: add the same public contract in Chinese.
- `docs/architecture.md`: record Root Resolver as a shared Core boundary.
- `docs/workflow.md`: show resolution before every read/write workflow.
- `docs/development-plan.md`: mark Phase 1 deliverables and acceptance.
- `tests/prompts.md`: replace personal paths with generic fixture paths.
- `docs/superpowers/specs/2026-06-30-obsidian-wiki-doctor-design.md`: replace the historical personal path with a generic example and note that v0.2 supersedes the fallback.
- `docs/superpowers/plans/2026-06-30-obsidian-wiki-doctor-implementation-plan.md`: replace the historical personal path constant with a generic historical example and add a supersession note.

## Public Contracts

### Project Configuration

```json
{
  "schema_version": 1,
  "vault_root": "D:/notes/My Vault",
  "control_center": "00-知识库中控",
  "active": true
}
```

### User Configuration

```json
{
  "schema_version": 1,
  "vaults": [
    {
      "vault_root": "D:/notes/My Vault",
      "control_center": "00-知识库中控",
      "active": true
    }
  ]
}
```

### Resolution Priority

```text
explicit --root
-> nearest .obsidian-llm-wiki.json found from --cwd upward
-> OBSIDIAN_LLM_WIKI_ROOT
-> exactly one active user-config Vault
-> missing-config or multiple-roots
```

### Exit Codes For `root resolve`

```text
0  resolved successfully
1  missing-config, disabled-config, or multiple-roots
2  invalid-root or invalid-config
```

## Task 1: Add Shared Root Models And Explicit Path Resolution

**Files:**
- Create: `scripts/llm_wiki_core/__init__.py`
- Create: `scripts/llm_wiki_core/root.py`
- Create: `tests/test_llm_wiki_root.py`

- [ ] **Step 1: Write failing explicit-root tests**

Create `tests/test_llm_wiki_root.py` with imports and fixture helpers:

```python
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from llm_wiki_core.root import resolve_explicit_root


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_vault(base: Path) -> tuple[Path, Path, Path]:
    vault = base / "My Vault"
    control = vault / "00-知识库中控"
    wiki = control / "wiki"
    write(wiki / "index.md", "# Index\n")
    write(wiki / "log.md", "# Log\n")
    return vault, control, wiki


class ExplicitRootTests(unittest.TestCase):
    def test_resolves_vault_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control, wiki = make_vault(Path(tmp))
            result = resolve_explicit_root(str(vault), source="argument")
            self.assertIsNone(result.error)
            self.assertEqual(result.vault_root, vault.resolve())
            self.assertEqual(result.control_center, control.resolve())
            self.assertEqual(result.wiki_root, wiki.resolve())

    def test_resolves_control_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control, wiki = make_vault(Path(tmp))
            result = resolve_explicit_root(str(control), source="argument")
            self.assertIsNone(result.error)
            self.assertEqual(result.vault_root, vault.resolve())
            self.assertEqual(result.control_center, control.resolve())
            self.assertEqual(result.wiki_root, wiki.resolve())

    def test_resolves_direct_wiki_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control, wiki = make_vault(Path(tmp))
            result = resolve_explicit_root(str(wiki), source="argument")
            self.assertIsNone(result.error)
            self.assertEqual(result.vault_root, vault.resolve())
            self.assertEqual(result.control_center, control.resolve())
            self.assertEqual(result.wiki_root, wiki.resolve())

    def test_invalid_root_is_safe_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            result = resolve_explicit_root(str(missing), source="argument")
            self.assertEqual(result.error.check, "invalid-root")
            self.assertIsNone(result.control_center)
            self.assertIsNone(result.wiki_root)
```

- [ ] **Step 2: Run the explicit-root tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_llm_wiki_root.ExplicitRootTests -v
```

Expected: `ERROR` with `ModuleNotFoundError: No module named 'llm_wiki_core'`.

- [ ] **Step 3: Implement the shared root models and explicit classifier**

Create `scripts/llm_wiki_core/root.py` with these public models and functions:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONTROL_CENTER_NAME = "00-知识库中控"
ENV_ROOT = "OBSIDIAN_LLM_WIKI_ROOT"
PROJECT_CONFIG_NAME = ".obsidian-llm-wiki.json"


@dataclass(frozen=True)
class RootIssue:
    check: str
    path: str
    message: str
    hint: str
    severity: str = "ERROR"
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedRoot:
    control_center: Path | None
    wiki_root: Path | None
    input_root: Path | None
    source: str
    error: RootIssue | None = None
    vault_root: Path | None = None


def has_wiki_marker(path: Path) -> bool:
    return (path / "index.md").is_file() or (path / "log.md").is_file()


def is_control_center(path: Path) -> bool:
    return path.is_dir() and ((path / "wiki").is_dir() or has_wiki_marker(path / "wiki"))


def is_direct_wiki_root(path: Path) -> bool:
    return path.is_dir() and has_wiki_marker(path)


def invalid_root(path: Path, source: str) -> ResolvedRoot:
    return ResolvedRoot(
        control_center=None,
        wiki_root=None,
        input_root=path,
        source=source,
        error=RootIssue(
            check="invalid-root",
            path=str(path),
            message=f"{source} root does not point to an Obsidian LLM Wiki vault, control center, or wiki root.",
            hint=f"Pass --root, create {PROJECT_CONFIG_NAME}, or set {ENV_ROOT}.",
        ),
    )


def resolve_explicit_root(
    root_value: str,
    source: str = "argument",
    control_center_name: str = DEFAULT_CONTROL_CENTER_NAME,
) -> ResolvedRoot:
    input_root = Path(root_value).expanduser()
    try:
        resolved = input_root.resolve()
    except OSError:
        return invalid_root(input_root, source)

    vault_control = resolved / control_center_name
    if is_control_center(vault_control):
        return ResolvedRoot(
            control_center=vault_control.resolve(),
            wiki_root=(vault_control / "wiki").resolve(),
            input_root=resolved,
            source=source,
            vault_root=resolved,
        )

    if is_control_center(resolved):
        return ResolvedRoot(
            control_center=resolved,
            wiki_root=(resolved / "wiki").resolve(),
            input_root=resolved,
            source=source,
            vault_root=resolved.parent,
        )

    if is_direct_wiki_root(resolved):
        control_center = resolved.parent if resolved.name == "wiki" else None
        vault_root = control_center.parent if control_center is not None else None
        return ResolvedRoot(
            control_center=control_center.resolve() if control_center else None,
            wiki_root=resolved,
            input_root=resolved,
            source=source,
            vault_root=vault_root.resolve() if vault_root else None,
        )

    return invalid_root(resolved, source)
```

Create `scripts/llm_wiki_core/__init__.py`:

```python
from .root import ResolvedRoot, RootIssue, resolve_explicit_root, resolve_root

__all__ = ["ResolvedRoot", "RootIssue", "resolve_explicit_root", "resolve_root"]
```

During Task 1, temporarily add this safe stub at the bottom of `root.py`; Task 2 replaces it with the real implementation:

```python
def resolve_root(*args, **kwargs) -> ResolvedRoot:
    raise NotImplementedError("configuration resolution is added in Task 2")
```

- [ ] **Step 4: Run the explicit-root tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_llm_wiki_root.ExplicitRootTests -v
```

Expected: `Ran 4 tests` and `OK`.

- [ ] **Step 5: Commit Task 1**

```powershell
git add scripts/llm_wiki_core/__init__.py scripts/llm_wiki_core/root.py tests/test_llm_wiki_root.py
git commit -m "feat: add shared Obsidian wiki root models"
```

## Task 2: Implement Project JSON Configuration

**Files:**
- Modify: `scripts/llm_wiki_core/root.py`
- Modify: `tests/test_llm_wiki_root.py`

- [ ] **Step 1: Add failing project-config tests**

Append to `tests/test_llm_wiki_root.py`:

```python
import json

from llm_wiki_core.root import resolve_root


def write_json(path: Path, payload: dict[str, object]) -> Path:
    return write(path, json.dumps(payload, ensure_ascii=False, indent=2))


class ProjectConfigTests(unittest.TestCase):
    def test_nearest_project_config_beats_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault, control, wiki = make_vault(base / "configured")
            other_vault, _, _ = make_vault(base / "environment")
            project = base / "project"
            nested = project / "src" / "module"
            nested.mkdir(parents=True)
            write_json(project / ".obsidian-llm-wiki.json", {
                "schema_version": 1,
                "vault_root": str(vault),
                "control_center": "00-知识库中控",
                "active": True,
            })
            result = resolve_root(
                cwd=nested,
                environ={"OBSIDIAN_LLM_WIKI_ROOT": str(other_vault)},
                user_config_path=base / "missing-user-config.json",
            )
            self.assertIsNone(result.error)
            self.assertEqual(result.source, "project-config")
            self.assertEqual(result.control_center, control.resolve())
            self.assertEqual(result.wiki_root, wiki.resolve())

    def test_relative_vault_path_is_relative_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            vault, control, _ = make_vault(project / "notes")
            project.mkdir(exist_ok=True)
            write_json(project / ".obsidian-llm-wiki.json", {
                "schema_version": 1,
                "vault_root": "notes/My Vault",
                "control_center": "00-知识库中控",
                "active": True,
            })
            result = resolve_root(cwd=project, environ={}, user_config_path=base / "missing.json")
            self.assertIsNone(result.error)
            self.assertEqual(result.vault_root, vault.resolve())
            self.assertEqual(result.control_center, control.resolve())

    def test_invalid_json_stops_without_falling_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            project.mkdir()
            write(project / ".obsidian-llm-wiki.json", "{not-json")
            result = resolve_root(cwd=project, environ={}, user_config_path=base / "missing.json")
            self.assertEqual(result.error.check, "invalid-config")
            self.assertEqual(result.source, "project-config")

    def test_inactive_project_config_stops_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            project.mkdir()
            write_json(project / ".obsidian-llm-wiki.json", {
                "schema_version": 1,
                "vault_root": "D:/not-used",
                "control_center": "00-知识库中控",
                "active": False,
            })
            result = resolve_root(cwd=project, environ={}, user_config_path=base / "missing.json")
            self.assertEqual(result.error.check, "disabled-config")

    def test_control_center_cannot_escape_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            project.mkdir()
            write_json(project / ".obsidian-llm-wiki.json", {
                "schema_version": 1,
                "vault_root": str(base / "vault"),
                "control_center": "../outside",
                "active": True,
            })
            result = resolve_root(cwd=project, environ={}, user_config_path=base / "missing.json")
            self.assertEqual(result.error.check, "invalid-config")
```

- [ ] **Step 2: Run project-config tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_llm_wiki_root.ProjectConfigTests -v
```

Expected: failures caused by the Task 1 `NotImplementedError` stub.

- [ ] **Step 3: Implement project-config discovery and validation**

Replace the Task 1 stub in `scripts/llm_wiki_core/root.py` and add:

```python
import json
import os
import sys
from collections.abc import Mapping


def config_issue(
    check: str,
    path: Path,
    message: str,
    source: str,
    candidates: tuple[str, ...] = (),
) -> ResolvedRoot:
    return ResolvedRoot(
        control_center=None,
        wiki_root=None,
        input_root=path,
        source=source,
        error=RootIssue(
            check=check,
            path=str(path),
            message=message,
            hint="Fix or remove the invalid configuration before continuing.",
            candidates=candidates,
        ),
    )


def find_project_config(cwd: Path) -> Path | None:
    current = cwd.expanduser().resolve()
    for candidate in (current, *current.parents):
        config = candidate / PROJECT_CONFIG_NAME
        if config.is_file():
            return config
    return None


def load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("configuration root must be a JSON object")
    return payload


def resolve_config_record(record: Mapping[str, object], config_path: Path, source: str) -> ResolvedRoot:
    if record.get("schema_version") != 1:
        return config_issue("invalid-config", config_path, "schema_version must be 1", source)
    if record.get("active") is not True:
        return config_issue("disabled-config", config_path, "configuration is not active", source)

    vault_value = record.get("vault_root")
    control_value = record.get("control_center", DEFAULT_CONTROL_CENTER_NAME)
    if not isinstance(vault_value, str) or not vault_value.strip():
        return config_issue("invalid-config", config_path, "vault_root must be a non-empty string", source)
    control_path = Path(control_value) if isinstance(control_value, str) else None
    if (
        control_path is None
        or not control_value.strip()
        or control_path.is_absolute()
        or ".." in control_path.parts
    ):
        return config_issue(
            "invalid-config",
            config_path,
            "control_center must be a non-empty relative path contained by the Vault",
            source,
        )

    vault_path = Path(vault_value).expanduser()
    if not vault_path.is_absolute():
        vault_path = config_path.parent / vault_path
    return resolve_explicit_root(str(vault_path), source=source, control_center_name=control_value)
```

Add the initial `resolve_root` implementation:

```python
def resolve_root(
    root_arg: str | None = None,
    cwd: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    user_config_path: str | Path | None = None,
) -> ResolvedRoot:
    if root_arg:
        return resolve_explicit_root(root_arg, source="argument")

    current = Path(cwd) if cwd is not None else Path.cwd()
    project_config = find_project_config(current)
    if project_config is not None:
        try:
            return resolve_config_record(load_json_object(project_config), project_config, "project-config")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return config_issue("invalid-config", project_config, str(exc), "project-config")

    environment = os.environ if environ is None else environ
    env_root = environment.get(ENV_ROOT)
    if env_root:
        return resolve_explicit_root(env_root, source="environment")

    return config_issue("missing-config", current, "No Obsidian LLM Wiki root configuration was found.", "resolver")
```

The unused `user_config_path` parameter is accepted in Task 2 so the public signature is stable; Task 3 consumes it.

- [ ] **Step 4: Run Task 1 and Task 2 tests**

Run:

```powershell
python -m unittest tests.test_llm_wiki_root -v
```

Expected: `Ran 9 tests` and `OK`.

- [ ] **Step 5: Commit Task 2**

```powershell
git add scripts/llm_wiki_core/root.py tests/test_llm_wiki_root.py
git commit -m "feat: resolve Obsidian wiki project config"
```

## Task 3: Add Environment And User Configuration Fallbacks

**Files:**
- Modify: `scripts/llm_wiki_core/root.py`
- Modify: `tests/test_llm_wiki_root.py`

- [ ] **Step 1: Add failing environment and user-config tests**

Append to `tests/test_llm_wiki_root.py`:

```python
from llm_wiki_core.root import default_user_config_path


class FallbackResolutionTests(unittest.TestCase):
    def test_default_user_config_path_on_windows(self):
        result = default_user_config_path(
            platform_name="win32",
            environ={"APPDATA": "C:/Users/alice/AppData/Roaming"},
            home=Path("C:/Users/alice"),
        )
        self.assertEqual(result, Path("C:/Users/alice/AppData/Roaming/obsidian-llm-wiki/config.json"))

    def test_default_user_config_path_on_linux(self):
        result = default_user_config_path(
            platform_name="linux",
            environ={},
            home=Path("/home/alice"),
        )
        self.assertEqual(result, Path("/home/alice/.config/obsidian-llm-wiki/config.json"))

    def test_environment_is_used_without_project_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault, control, _ = make_vault(base)
            result = resolve_root(
                cwd=base / "work",
                environ={"OBSIDIAN_LLM_WIKI_ROOT": str(vault)},
                user_config_path=base / "missing.json",
            )
            self.assertIsNone(result.error)
            self.assertEqual(result.source, "environment")
            self.assertEqual(result.control_center, control.resolve())

    def test_exactly_one_active_user_vault_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault, control, _ = make_vault(base / "vaults")
            config = write_json(base / "config.json", {
                "schema_version": 1,
                "vaults": [{
                    "vault_root": str(vault),
                    "control_center": "00-知识库中控",
                    "active": True,
                }],
            })
            result = resolve_root(cwd=base / "work", environ={}, user_config_path=config)
            self.assertIsNone(result.error)
            self.assertEqual(result.source, "user-config")
            self.assertEqual(result.control_center, control.resolve())

    def test_multiple_active_user_vaults_are_not_auto_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first, _, _ = make_vault(base / "first")
            second, _, _ = make_vault(base / "second")
            config = write_json(base / "config.json", {
                "schema_version": 1,
                "vaults": [
                    {"vault_root": str(first), "control_center": "00-知识库中控", "active": True},
                    {"vault_root": str(second), "control_center": "00-知识库中控", "active": True},
                ],
            })
            result = resolve_root(cwd=base / "work", environ={}, user_config_path=config)
            self.assertEqual(result.error.check, "multiple-roots")
            self.assertEqual(len(result.error.candidates), 2)

    def test_missing_configuration_is_safe_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = resolve_root(cwd=base, environ={}, user_config_path=base / "missing.json")
            self.assertEqual(result.error.check, "missing-config")
            self.assertIsNone(result.wiki_root)
```

- [ ] **Step 2: Run fallback tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_llm_wiki_root.FallbackResolutionTests -v
```

Expected: the environment test passes, while user-config tests fail because Task 2 does not read user configuration.

- [ ] **Step 3: Implement user configuration path and active-vault selection**

Add to `scripts/llm_wiki_core/root.py`:

```python
def default_user_config_path(
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_value = sys.platform if platform_name is None else platform_name
    environment = os.environ if environ is None else environ
    home_path = Path.home() if home is None else home
    if platform_value.startswith("win"):
        appdata = environment.get("APPDATA")
        base = Path(appdata) if appdata else home_path / "AppData" / "Roaming"
        return base / "obsidian-llm-wiki" / "config.json"
    if platform_value == "darwin":
        return home_path / "Library" / "Application Support" / "obsidian-llm-wiki" / "config.json"
    return home_path / ".config" / "obsidian-llm-wiki" / "config.json"


def resolve_user_config(path: Path) -> ResolvedRoot:
    try:
        payload = load_json_object(path)
    except FileNotFoundError:
        return config_issue("missing-config", path, "User configuration was not found.", "user-config")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return config_issue("invalid-config", path, str(exc), "user-config")

    if payload.get("schema_version") != 1 or not isinstance(payload.get("vaults"), list):
        return config_issue("invalid-config", path, "User configuration requires schema_version 1 and a vaults array.", "user-config")
    active = [item for item in payload["vaults"] if isinstance(item, dict) and item.get("active") is True]
    if not active:
        return config_issue("missing-config", path, "No active Vault is configured.", "user-config")
    if len(active) > 1:
        candidates = tuple(
            str(Path(item["vault_root"]).expanduser())
            for item in active
            if isinstance(item.get("vault_root"), str)
        )
        return config_issue(
            "multiple-roots",
            path,
            "More than one active Vault is configured.",
            "user-config",
            candidates=candidates,
        )
    return resolve_config_record(active[0], path, "user-config")
```

Replace the final `missing-config` return in `resolve_root` with:

```python
    config_path = Path(user_config_path) if user_config_path is not None else default_user_config_path(environ=environment)
    return resolve_user_config(config_path)
```

- [ ] **Step 4: Run all root tests**

Run:

```powershell
python -m unittest tests.test_llm_wiki_root -v
```

Expected: `Ran 15 tests` and `OK`.

- [ ] **Step 5: Commit Task 3**

```powershell
git add scripts/llm_wiki_core/root.py tests/test_llm_wiki_root.py
git commit -m "feat: add Obsidian wiki root fallbacks"
```

## Task 4: Add The Canonical Root CLI

**Files:**
- Create: `scripts/llm_wiki.py`
- Create: `tests/test_llm_wiki_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_llm_wiki_cli.py`:

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "llm_wiki.py"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_vault(base: Path) -> Path:
    vault = base / "My Vault"
    write(vault / "00-知识库中控" / "wiki" / "index.md", "# Index\n")
    write(vault / "00-知识库中控" / "wiki" / "log.md", "# Log\n")
    return vault


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("OBSIDIAN_LLM_WIKI_ROOT", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )


class RootCliTests(unittest.TestCase):
    def test_root_resolve_emits_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            result = run_cli("root", "resolve", "--root", str(vault), "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["source"], "argument")
            self.assertEqual(payload["vault_root"], str(vault.resolve()))
            self.assertEqual(payload["control_center"], str((vault / "00-知识库中控").resolve()))

    def test_missing_config_returns_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli("root", "resolve", "--cwd", tmp, "--user-config", str(Path(tmp) / "missing.json"), "--format", "json")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["error"]["check"], "missing-config")
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_llm_wiki_cli.RootCliTests -v
```

Expected: failures because `scripts/llm_wiki.py` does not exist.

- [ ] **Step 3: Implement `llm_wiki.py root resolve`**

Create `scripts/llm_wiki.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm_wiki_core.root import ResolvedRoot, resolve_root


def root_to_dict(root: ResolvedRoot) -> dict[str, object]:
    payload: dict[str, object] = {
        "vault_root": str(root.vault_root) if root.vault_root else None,
        "control_center": str(root.control_center) if root.control_center else None,
        "wiki_root": str(root.wiki_root) if root.wiki_root else None,
        "input_root": str(root.input_root) if root.input_root else None,
        "source": root.source,
    }
    if root.error is not None:
        payload["error"] = {
            "check": root.error.check,
            "severity": root.error.severity,
            "path": root.error.path,
            "message": root.error.message,
            "hint": root.error.hint,
            "candidates": list(root.error.candidates),
        }
    return payload


def root_exit_code(root: ResolvedRoot) -> int:
    if root.error is None:
        return 0
    if root.error.check in {"missing-config", "disabled-config", "multiple-roots"}:
        return 1
    return 2


def run_root_resolve(args: argparse.Namespace) -> int:
    root = resolve_root(
        root_arg=args.root,
        cwd=args.cwd,
        user_config_path=args.user_config,
    )
    payload = root_to_dict(root)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"source: {payload['source']}")
        print(f"vault_root: {payload['vault_root']}")
        print(f"control_center: {payload['control_center']}")
        print(f"wiki_root: {payload['wiki_root']}")
        if "error" in payload:
            print(f"error: {payload['error']['check']}")
    return root_exit_code(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-wiki")
    groups = parser.add_subparsers(dest="group", required=True)
    root = groups.add_parser("root")
    root_commands = root.add_subparsers(dest="command", required=True)
    resolve = root_commands.add_parser("resolve")
    resolve.add_argument("--root")
    resolve.add_argument("--cwd", default=str(Path.cwd()))
    resolve.add_argument("--user-config")
    resolve.add_argument("--format", choices=("text", "json"), default="json")
    resolve.set_defaults(handler=run_root_resolve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI and root tests**

Run:

```powershell
python -m unittest tests.test_llm_wiki_cli.RootCliTests tests.test_llm_wiki_root -v
```

Expected: `Ran 17 tests` and `OK`.

- [ ] **Step 5: Commit Task 4**

```powershell
git add scripts/llm_wiki.py tests/test_llm_wiki_cli.py
git commit -m "feat: add canonical LLM Wiki root CLI"
```

## Task 5: Make Existing Doctor Use The Shared Resolver

**Files:**
- Modify: `scripts/obsidian_wiki_doctor.py:7-168`
- Modify: `scripts/obsidian_wiki_doctor.py:423-443`
- Modify: `scripts/llm_wiki.py`
- Modify: `tests/test_obsidian_wiki_doctor.py:1-63`
- Modify: `tests/test_llm_wiki_cli.py`

- [ ] **Step 1: Add failing Doctor config and parity tests**

Extend `run_doctor` in `tests/test_obsidian_wiki_doctor.py`:

```python
def run_doctor(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
        check=False,
    )
```

Add to `RootResolutionTests`:

```python
    def test_project_config_is_used_when_no_root_argument_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            control = make_control_center(base / "vault")
            vault = control.parent
            project = base / "project"
            project.mkdir()
            write(project / ".obsidian-llm-wiki.json", json.dumps({
                "schema_version": 1,
                "vault_root": str(vault),
                "control_center": "00-知识库中控",
                "active": True,
            }))
            result = run_doctor("score", "--format", "json", cwd=project)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["root"]["control_center"], str(control.resolve()))
```

Append to `tests/test_llm_wiki_cli.py`:

```python
OLD_DOCTOR = REPO_ROOT / "scripts" / "obsidian_wiki_doctor.py"


class DoctorCompatibilityTests(unittest.TestCase):
    def test_new_and_old_doctor_json_are_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            old = subprocess.run(
                [sys.executable, str(OLD_DOCTOR), "report", "--root", str(vault), "--format", "json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            new = run_cli("doctor", "report", "--root", str(vault), "--format", "json")
            self.assertEqual(new.returncode, old.returncode)
            self.assertEqual(json.loads(new.stdout), json.loads(old.stdout))
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_obsidian_wiki_doctor.RootResolutionTests.test_project_config_is_used_when_no_root_argument_is_given tests.test_llm_wiki_cli.DoctorCompatibilityTests -v
```

Expected: the old Doctor ignores project config and the new CLI rejects the `doctor` group.

- [ ] **Step 3: Replace Doctor-local root resolution with the shared module**

In `scripts/obsidian_wiki_doctor.py`:

1. Remove `DEFAULT_CONTROL_CENTER`, `ENV_ROOT`, the local `ResolvedRoot` dataclass, and local functions `has_wiki_marker`, `is_control_center`, `is_direct_wiki_root`, `invalid_root`, `resolve_explicit_root`, and `resolve_root`.
2. Add:

```python
from llm_wiki_core.root import ResolvedRoot, RootIssue, resolve_root
```

3. Add this converter beside `Finding`:

```python
def finding_from_root_issue(issue: RootIssue) -> Finding:
    return Finding(
        check=issue.check,
        severity=issue.severity,
        path=issue.path,
        message=issue.message,
        hint=issue.hint,
    )
```

4. Change `run_checks` root-error handling to:

```python
    if root.error is not None:
        return [finding_from_root_issue(root.error)]
```

5. Change `root_to_dict` root-error handling to:

```python
    if root.error is not None:
        payload["error"] = safe_finding_dict(finding_from_root_issue(root.error))
```

Keep the existing `root_to_dict` keys unchanged; do not add `vault_root` to the legacy Doctor JSON in Phase 1.

- [ ] **Step 4: Add `doctor` dispatch to the canonical CLI**

In `scripts/llm_wiki.py`, import the existing Doctor module:

```python
import obsidian_wiki_doctor
```

Before normal parser dispatch in `main`, add:

```python
def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["doctor"]:
        return obsidian_wiki_doctor.main(arguments[1:])
    args = build_parser().parse_args(arguments)
    return args.handler(args)
```

This is a Phase 1 compatibility bridge. Moving Doctor implementation into `llm_wiki_core.doctor` and turning the old script into a thin deprecation wrapper remains Phase 4 work.

- [ ] **Step 5: Run the complete Doctor and CLI suites**

Run:

```powershell
python -m unittest tests.test_obsidian_wiki_doctor tests.test_llm_wiki_root tests.test_llm_wiki_cli -v
```

Expected: all tests pass, including old/new Doctor JSON equality.

- [ ] **Step 6: Commit Task 5**

```powershell
git add scripts/obsidian_wiki_doctor.py scripts/llm_wiki.py tests/test_obsidian_wiki_doctor.py tests/test_llm_wiki_cli.py
git commit -m "refactor: share Obsidian wiki root resolution"
```

## Task 6: Align Skills And Public Documentation

**Files:**
- Modify: `skills/obsidian-wiki-init/SKILL.md`
- Modify: `skills/obsidian-wiki-ingest/SKILL.md`
- Modify: `skills/obsidian-wiki-doctor/SKILL.md`
- Modify: `skills/obsidian-wiki-maintain/SKILL.md`
- Modify: `skills/obsidian-wiki-query/SKILL.md`
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflow.md`
- Modify: `docs/development-plan.md`
- Modify: `tests/prompts.md`
- Modify: `docs/superpowers/specs/2026-06-30-obsidian-wiki-doctor-design.md`
- Modify: `docs/superpowers/plans/2026-06-30-obsidian-wiki-doctor-implementation-plan.md`
- Modify: `tests/test_llm_wiki_root.py`

- [ ] **Step 1: Add a failing personal-path regression test**

Append to `tests/test_llm_wiki_root.py`:

```python
class RepositoryContractTests(unittest.TestCase):
    def test_personal_default_path_is_absent(self):
        forbidden = "C:" + "\\Users\\admin\\Documents\\Obsidian Vault"
        roots = [
            REPO_ROOT / "scripts",
            REPO_ROOT / "skills",
            REPO_ROOT / "README.md",
            REPO_ROOT / "README.zh.md",
            REPO_ROOT / "docs",
            REPO_ROOT / "tests" / "prompts.md",
        ]
        matches: list[str] = []
        for root in roots:
            files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
            for path in files:
                if path.suffix.lower() not in {".py", ".md"}:
                    continue
                if forbidden in path.read_text(encoding="utf-8-sig"):
                    matches.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(matches, [])
```

- [ ] **Step 2: Run the regression test and verify it fails**

Run:

```powershell
python -m unittest tests.test_llm_wiki_root.RepositoryContractTests.test_personal_default_path_is_absent -v
```

Expected: `FAIL` listing the runtime script, Skill files, historical Doctor design/plan, and prompt fixture that still contain the personal path.

- [ ] **Step 3: Replace duplicated Skill resolution instructions**

Use this exact shared contract in Init, Ingest, Maintain, and Query, adapted only for read/write wording:

```markdown
## Wiki Root Resolution

Before reading or writing, resolve and state `vault_root`, `control_center`, and `wiki_root` using the shared order:

1. User-provided Vault, control-center, or wiki path.
2. Nearest `.obsidian-llm-wiki.json` from the current working directory upward.
3. `OBSIDIAN_LLM_WIKI_ROOT`.
4. Exactly one active Vault in the user configuration.
5. Otherwise stop with `missing_config` or ask the user to choose when multiple roots exist.

Do not search the whole disk. A source path is not automatically the target Wiki. Before writes, run or follow the equivalent of:

```text
python scripts/llm_wiki.py root resolve --cwd <working-directory> --format json
```
```

In Doctor, preserve the old examples and add canonical examples:

```text
python scripts/llm_wiki.py doctor report --root <vault-or-control-center> --format text
python scripts/llm_wiki.py doctor validate --root <vault-or-control-center> --format json --fail-on error
python scripts/llm_wiki.py doctor score --root <vault-or-control-center> --format json
```

State that `scripts/obsidian_wiki_doctor.py` remains compatible in v0.2.

- [ ] **Step 4: Update public documentation**

Add the following contract to both READMEs and summarize it in architecture/workflow docs:

```markdown
### Root configuration

Requires Python 3.10 or newer. Create `.obsidian-llm-wiki.json` in the working project when the Vault is not supplied explicitly:

```json
{
  "schema_version": 1,
  "vault_root": "D:/notes/My Vault",
  "control_center": "00-知识库中控",
  "active": true
}
```

Resolve without writing:

```text
python scripts/llm_wiki.py root resolve --cwd . --format json
```
```

In `docs/development-plan.md`, mark Phase 1 acceptance as:

```text
- no personal default Vault path
- one shared Root Resolver
- project config -> environment -> user config precedence after explicit root
- old and new Doctor commands produce equivalent JSON and exit codes
- Ubuntu and Windows tests pass on Python 3.10+
```

- [ ] **Step 5: Scrub the historical personal path without rewriting history semantics**

Replace only the literal personal path in the 2026-06-30 design/plan and `tests/prompts.md` with:

```text
C:\Users\<user>\Documents\Obsidian Vault\00-知识库中控
```

Add this sentence near the historical fallback description in both June documents:

```text
Superseded by the v0.2 shared Root Resolver; this path is a historical example, not a runtime default.
```

- [ ] **Step 6: Run the contract and all Python tests**

Run:

```powershell
python -m unittest discover tests -v
```

Expected: all tests pass and `RepositoryContractTests` reports no personal-path matches.

- [ ] **Step 7: Commit Task 6**

```powershell
git add README.md README.zh.md `
  docs/architecture.md docs/workflow.md docs/development-plan.md `
  docs/superpowers/specs/2026-06-30-obsidian-wiki-doctor-design.md `
  docs/superpowers/plans/2026-06-30-obsidian-wiki-doctor-implementation-plan.md `
  skills/obsidian-wiki-init/SKILL.md `
  skills/obsidian-wiki-ingest/SKILL.md `
  skills/obsidian-wiki-doctor/SKILL.md `
  skills/obsidian-wiki-maintain/SKILL.md `
  skills/obsidian-wiki-query/SKILL.md `
  tests/prompts.md tests/test_llm_wiki_root.py
git commit -m "docs: publish shared Obsidian wiki root contract"
```

## Task 7: Add Cross-Platform CI And Final Verification

**Files:**
- Create: `.github/workflows/test.yml`
- Modify: `README.md`
- Modify: `README.zh.md`

- [ ] **Step 1: Create the GitHub Actions test matrix**

Create `.github/workflows/test.yml`:

```yaml
name: test

on:
  push:
    branches: [main]
  pull_request:

jobs:
  python-tests:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ["3.10", "3.12"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Run unit tests
        run: python -m unittest discover tests -v
      - name: Resolve sample Vault through canonical CLI
        shell: pwsh
        run: |
          $vault = Join-Path $env:RUNNER_TEMP "Sample Vault"
          New-Item -ItemType Directory -Force -Path (Join-Path $vault "00-知识库中控/wiki") | Out-Null
          Set-Content -Encoding utf8 -Path (Join-Path $vault "00-知识库中控/wiki/index.md") -Value "# Index"
          Set-Content -Encoding utf8 -Path (Join-Path $vault "00-知识库中控/wiki/log.md") -Value "# Log"
          python scripts/llm_wiki.py root resolve --root $vault --format json
```

- [ ] **Step 2: Add the CI badge and Python requirement**

Add to both READMEs near the title and installation sections:

```markdown
[![test](https://github.com/huajiexiewenfeng/obsidian-llm-wiki/actions/workflows/test.yml/badge.svg)](https://github.com/huajiexiewenfeng/obsidian-llm-wiki/actions/workflows/test.yml)

Runtime requirement: Python 3.10 or newer.
```

- [ ] **Step 3: Run local verification**

Run:

```powershell
python -m unittest discover tests -v
python scripts/llm_wiki.py --help
python scripts/llm_wiki.py root resolve --help
python scripts/llm_wiki.py doctor --help
npx.cmd skills add . --list
```

Expected:

- All Python tests pass.
- CLI help lists `root` and accepts `doctor` dispatch.
- Skill listing includes all five Obsidian Wiki Skills.

- [ ] **Step 4: Run static compatibility checks**

Run:

```powershell
rg -n "C:\\Users\\admin\\Documents\\Obsidian Vault" .
rg -n "DEFAULT_CONTROL_CENTER" scripts skills README.md README.zh.md docs/architecture.md docs/workflow.md docs/development-plan.md tests
rg -n "\.obsidian-llm-wiki\.json|root resolve|OBSIDIAN_LLM_WIKI_ROOT" README.md README.zh.md docs skills scripts tests
git diff --check
git status --short
```

Expected:

- The first and second commands return no matches.
- The third command shows the shared contract across code, docs, and Skills.
- `git diff --check` returns no whitespace errors.
- Git status contains only intended Phase 1 changes.

- [ ] **Step 5: Commit Task 7**

```powershell
git add .github/workflows/test.yml README.md README.zh.md
git commit -m "ci: test Obsidian wiki root resolution"
```

## Final Review Checklist

- [ ] Explicit root, project config, environment, and user config follow the approved priority order.
- [ ] Invalid or disabled project config does not silently fall through to another Vault.
- [ ] Multiple active user Vaults are never auto-selected.
- [ ] The personal-machine default path and `DEFAULT_CONTROL_CENTER` are absent.
- [ ] Existing Doctor checks, output fields, score behavior, and exit codes remain compatible.
- [ ] Canonical and legacy Doctor invocations produce equivalent JSON for the same fixture.
- [ ] No broad filesystem scan was added.
- [ ] All Skills state the resolved Vault before reads or writes.
- [ ] Python 3.10 and 3.12 pass on Ubuntu and Windows.
- [ ] The implementation commits are focused and contain no v0.2 Phase 2 registry or write-transaction work.

## Execution Handoff

After this plan is approved and the design/plan are committed, execute it in a dedicated worktree.

Two supported execution modes:

1. **Subagent-Driven (recommended):** use `superpowers:subagent-driven-development`, dispatch one fresh worker per task, and review after each task.
2. **Inline Execution:** use `superpowers:executing-plans`, run tasks in small batches, and stop at review checkpoints.
