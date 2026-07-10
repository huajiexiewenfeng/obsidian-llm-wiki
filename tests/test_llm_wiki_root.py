import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from llm_wiki_core.root import (
    configure_user_default,
    default_obsidian_metadata_path,
    default_user_config_path,
    discover_recent_vaults,
    resolve_explicit_root,
    resolve_root,
)


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

    def test_rejects_non_wiki_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            unrelated = Path(tmp) / "unrelated"
            unrelated.mkdir()

            result = resolve_explicit_root(str(unrelated), source="argument")

            self.assertIsNotNone(result.error)
            self.assertEqual(result.error.check, "invalid-root")


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


class RecentVaultDiscoveryTests(unittest.TestCase):
    def test_discovers_existing_absolute_paths_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = (base / "first").resolve()
            second = (base / "second").resolve()
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

    def test_windows_metadata_path_uses_appdata(self):
        result = default_obsidian_metadata_path(
            platform_name="win32",
            environ={"APPDATA": "C:/Users/alice/AppData/Roaming"},
            home=Path("C:/Users/alice"),
        )

        self.assertEqual(result, Path("C:/Users/alice/AppData/Roaming/obsidian/obsidian.json"))


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

            result = configure_user_default(str(second), config, confirm=True)

            vaults = json.loads(config.read_text(encoding="utf-8"))["vaults"]
            self.assertTrue(result.configured)
            self.assertEqual(len(vaults), 2)
            self.assertFalse(vaults[0]["active"])
            self.assertTrue(vaults[1]["active"])

    def test_invalid_existing_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault, _, _ = make_vault(base)
            config = write(base / "config.json", "{invalid-json")

            result = configure_user_default(str(vault), config, confirm=True)

            self.assertFalse(result.configured)
            self.assertEqual(result.root.error.check, "invalid-config")
            self.assertEqual(config.read_text(encoding="utf-8"), "{invalid-json")


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


class DiscoveryDocumentationTests(unittest.TestCase):
    def test_every_skill_documents_discovery_confirmation_and_no_scan(self):
        phrases = ("root discover", "absolute", "confirm", "whole disk")
        names = (
            "obsidian-wiki-init",
            "obsidian-wiki-ingest",
            "obsidian-wiki-doctor",
            "obsidian-wiki-maintain",
            "obsidian-wiki-query",
        )
        for name in names:
            content = (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            for phrase in phrases:
                self.assertIn(phrase, content, name)


if __name__ == "__main__":
    unittest.main()
