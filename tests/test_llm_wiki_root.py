import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from llm_wiki_core.root import resolve_explicit_root, resolve_root


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


if __name__ == "__main__":
    unittest.main()
