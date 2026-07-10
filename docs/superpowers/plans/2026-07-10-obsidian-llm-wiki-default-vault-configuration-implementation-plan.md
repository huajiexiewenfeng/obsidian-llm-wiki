# Default Vault Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax.

**Goal:** Discover recent Obsidian Vault paths, require human selection, and save the confirmed selection as the user default.

**Architecture:** The shared root module owns discovery and persistence. Discovery only reads Obsidian metadata. Configuration is an explicit, confirmation-gated atomic write. Root resolution remains read-only.

**Tech Stack:** Python standard library, unittest, existing GitHub Actions.

---

## Constraints

- Execute on main because the user requested one branch only.
- Use C:\tmp\python-3.12.10-embed-amd64\python.exe for tests.
- Do not print actual local Vault paths.
- Recent Obsidian metadata is a JSON vaults object; its records use path, ts, and open.

## Task 1: Recent Vault Discovery Core

Files:
- Modify: scripts/llm_wiki_core/root.py
- Modify: scripts/llm_wiki_core/__init__.py
- Modify: tests/test_llm_wiki_root.py

- [ ] Step 1: Write failing tests.

~~~python
from llm_wiki_core.root import default_obsidian_metadata_path, discover_recent_vaults

class RecentVaultDiscoveryTests(unittest.TestCase):
    def test_discovers_existing_absolute_paths_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first, second = (base / "first").resolve(), (base / "second").resolve()
            first.mkdir()
            second.mkdir()
            metadata = write_json(base / "obsidian.json", {
                "vaults": {
                    "one": {"path": str(first), "ts": 2, "open": True},
                    "two": {"path": str(second), "ts": 1, "open": False},
                    "duplicate": {"path": str(first), "ts": 0, "open": False},
                    "relative": {"path": "relative/path", "ts": 0, "open": False},
                },
            })
            result = discover_recent_vaults(metadata)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.candidates, (first, second))

    def test_missing_and_invalid_metadata_are_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertEqual(discover_recent_vaults(base / "missing.json").candidates, ())
            malformed = write(base / "bad.json", "{invalid-json")
            self.assertEqual(discover_recent_vaults(malformed).status, "invalid-metadata")
~~~

- [ ] Step 2: Verify RED.

Run:

~~~powershell
& 'C:\tmp\python-3.12.10-embed-amd64\python.exe' -m unittest discover -s tests -p test_llm_wiki_root.py -v
~~~

Expected: import error for discover_recent_vaults.

- [ ] Step 3: Implement minimal API.

~~~python
@dataclass(frozen=True)
class DiscoveryResult:
    candidates: tuple[Path, ...]
    source: str
    status: str
    message: str | None = None

def default_obsidian_metadata_path(
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_value = sys.platform if platform_name is None else platform_name
    environment = os.environ if environ is None else environ
    home_path = Path.home() if home is None else home
    if platform_value.startswith("win"):
        return Path(environment.get("APPDATA", home_path / "AppData" / "Roaming")) / "obsidian" / "obsidian.json"
    if platform_value == "darwin":
        return home_path / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    return home_path / ".config" / "obsidian" / "obsidian.json"

def discover_recent_vaults(metadata_path: Path) -> DiscoveryResult:
    try:
        payload = load_json_object(metadata_path)
    except FileNotFoundError:
        return DiscoveryResult((), "obsidian-recent", "missing-metadata")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return DiscoveryResult((), "obsidian-recent", "invalid-metadata", str(exc))
    vaults = payload.get("vaults")
    if not isinstance(vaults, dict):
        return DiscoveryResult((), "obsidian-recent", "unsupported-metadata")
    paths, seen = [], set()
    for record in vaults.values():
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            candidate = Path(record["path"]).expanduser()
            if candidate.is_absolute() and candidate.is_dir() and candidate.resolve() not in seen:
                paths.append(candidate.resolve())
                seen.add(candidate.resolve())
    return DiscoveryResult(tuple(paths), "obsidian-recent", "ok")
~~~

Export the result type and functions through __init__.py.

- [ ] Step 4: Verify GREEN and commit.

~~~powershell
& 'C:\tmp\python-3.12.10-embed-amd64\python.exe' -m unittest discover -s tests -p test_llm_wiki_root.py -v
git add scripts/llm_wiki_core/root.py scripts/llm_wiki_core/__init__.py tests/test_llm_wiki_root.py
git commit -m "feat: discover recent Obsidian Vaults"
~~~

## Task 2: Confirmed Default Vault Persistence

Files:
- Modify: scripts/llm_wiki_core/root.py
- Modify: tests/test_llm_wiki_root.py

- [ ] Step 1: Write failing tests.

~~~python
from llm_wiki_core.root import configure_user_default

class DefaultVaultConfigurationTests(unittest.TestCase):
    def test_preview_requires_confirmation_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault, _, _ = make_vault(base)
            config = base / "config.json"
            result = configure_user_default(str(vault), config, confirm=False)
            self.assertTrue(result.confirmation_required)
            self.assertFalse(result.configured)
            self.assertFalse(config.exists())

    def test_switch_keeps_old_vault_inactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first, _, _ = make_vault(base / "first")
            second, _, _ = make_vault(base / "second")
            config = base / "config.json"
            configure_user_default(str(first), config, confirm=True)
            configure_user_default(str(second), config, confirm=True)
            vaults = json.loads(config.read_text(encoding="utf-8"))["vaults"]
            self.assertEqual(len(vaults), 2)
            self.assertFalse(vaults[0]["active"])
            self.assertTrue(vaults[1]["active"])
~~~

- [ ] Step 2: Verify RED with the Task 1 command.

Expected: import error for configure_user_default.

- [ ] Step 3: Implement configuration result, update, and atomic write.

~~~python
@dataclass(frozen=True)
class ConfigureResult:
    root: ResolvedRoot
    config_path: Path
    confirmation_required: bool
    configured: bool

def configure_user_default(root_value: str, user_config_path: Path, confirm: bool) -> ConfigureResult:
    root = resolve_explicit_root(root_value, source="configure")
    if root.error is not None:
        return ConfigureResult(root, user_config_path, False, False)
    payload = load_json_object(user_config_path) if user_config_path.exists() else {"schema_version": 1, "vaults": []}
    if payload.get("schema_version") != 1 or not isinstance(payload.get("vaults"), list):
        return ConfigureResult(config_issue("invalid-config", user_config_path, "User configuration requires schema_version 1 and a vaults array.", "configure"), user_config_path, False, False)
    if not confirm:
        return ConfigureResult(root, user_config_path, True, False)
    write_json_atomically(user_config_path, update_active_vault(payload, root))
    return ConfigureResult(root, user_config_path, False, True)
~~~

update_active_vault preserves unknown fields, deactivates every non-target record, and appends the normalized target only if absent. write_json_atomically writes a UTF-8 temporary sibling and uses os.replace after the temporary write succeeds. Existing malformed configuration is never overwritten.

- [ ] Step 4: Verify GREEN and commit.

~~~powershell
& 'C:\tmp\python-3.12.10-embed-amd64\python.exe' -m unittest discover -s tests -p test_llm_wiki_root.py -v
git add scripts/llm_wiki_core/root.py scripts/llm_wiki_core/__init__.py tests/test_llm_wiki_root.py
git commit -m "feat: configure confirmed default Vault"
~~~

## Task 3: CLI Commands And Conversation-First Docs

Files:
- Modify: scripts/llm_wiki.py
- Modify: tests/test_llm_wiki_cli.py
- Modify: five Skill files, README.md, README.zh.md, docs/architecture.md, docs/workflow.md

- [ ] Step 1: Write failing CLI tests.

~~~python
class DefaultVaultCliTests(unittest.TestCase):
    def test_configure_without_confirm_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = make_vault(base)
            config = base / "config.json"
            result = run_cli("root", "configure", "--root", str(vault), "--activate", "--user-config", str(config), "--format", "json")
            self.assertEqual(result.returncode, 1)
            self.assertTrue(json.loads(result.stdout)["confirmation_required"])
            self.assertFalse(config.exists())
~~~

- [ ] Step 2: Verify RED.

~~~powershell
& 'C:\tmp\python-3.12.10-embed-amd64\python.exe' -m unittest discover -s tests -p test_llm_wiki_cli.py -v
~~~

Expected: argparse rejects root configure.

- [ ] Step 3: Implement parsers and handlers.

~~~python
discover = root_commands.add_parser("discover")
discover.add_argument("--format", choices=("text", "json"), default="json")
discover.set_defaults(handler=run_root_discover)

configure = root_commands.add_parser("configure")
configure.add_argument("--root", required=True)
configure.add_argument("--activate", action="store_true", required=True)
configure.add_argument("--confirm", action="store_true")
configure.add_argument("--user-config")
configure.add_argument("--format", choices=("text", "json"), default="json")
configure.set_defaults(handler=run_root_configure)
~~~

run_root_discover emits candidates, source, status, and message and returns zero for an empty list. run_root_configure emits root fields, user_config, confirmation_required, and configured; it returns one for preview, zero for a confirmed write, and two for errors.

- [ ] Step 4: Document the same first-use flow in every Skill and public doc.

~~~markdown
If normal resolution has no root, run root discover. Show returned existing absolute paths as numbered candidates. Ask the user to select one or provide another absolute Vault path. Resolve it and display vault_root, control_center, and wiki_root. Only after the user confirms it should become default, run root configure with --activate --confirm. Do not read note content or scan the whole disk; continue the original request after setup.
~~~

For init, retain a separate confirmation before creating a missing control center. Keep JSON configuration in the README as advanced/manual setup.

- [ ] Step 5: Verify GREEN, full suite, and commit.

~~~powershell
& 'C:\tmp\python-3.12.10-embed-amd64\python.exe' -m unittest discover tests -v
& 'C:\tmp\python-3.12.10-embed-amd64\python.exe' scripts/llm_wiki.py root discover --format json
& 'C:\tmp\python-3.12.10-embed-amd64\python.exe' scripts/llm_wiki.py root configure --help
rg -n "root discover|root configure|whole disk|absolute" skills README.md README.zh.md docs
git diff --check
git add scripts/llm_wiki.py tests/test_llm_wiki_cli.py skills README.md README.zh.md docs/architecture.md docs/workflow.md
git commit -m "feat: guide first-use Vault discovery"
~~~

## Final Verification

- [ ] Full unittest suite passes.
- [ ] Discovery is read-only and returns JSON with candidates.
- [ ] Configure without confirm exits one and writes nothing.
- [ ] Configure with confirm produces exactly one active user Vault.
- [ ] Root resolve remains read-only and preserves explicit, project, environment, user-default priority.
- [ ] git diff --check and git status are clean after commits.

