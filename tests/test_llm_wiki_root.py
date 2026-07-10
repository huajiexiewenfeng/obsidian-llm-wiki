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

    def test_rejects_non_wiki_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            unrelated = Path(tmp) / "unrelated"
            unrelated.mkdir()

            result = resolve_explicit_root(str(unrelated), source="argument")

            self.assertIsNotNone(result.error)
            self.assertEqual(result.error.check, "invalid-root")


if __name__ == "__main__":
    unittest.main()
