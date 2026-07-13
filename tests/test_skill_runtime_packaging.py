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
    "scripts/llm_wiki_core/state.py",
    "scripts/llm_wiki_core/writer.py",
    "scripts/llm_wiki_core/managed.py",
    "scripts/llm_wiki_core/doctor_state.py",
    "scripts/llm_wiki_core/archive.py",
    "scripts/llm_wiki_core/inventory.py",
    "scripts/llm_wiki_core/knowledge_graph.py",
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
        skill_file = RUNTIME_SKILL / "SKILL.md"
        self.assertTrue(skill_file.is_file(), skill_file)
        text = skill_file.read_text(encoding="utf-8")
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

    def test_doctor_documents_rooted_graph_inventory_vocabulary(self):
        documents = (
            SKILLS_ROOT / "obsidian-wiki-doctor" / "SKILL.md",
            SKILLS_ROOT / "obsidian-wiki-doctor" / "references" / "doctor-checks.md",
            REPO_ROOT / "README.md",
        )
        required = (
            "known-existing",
            "unverified",
            "source-island",
            "orphan-wiki-page",
        )
        for path in documents:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                for term in required:
                    self.assertIn(term, text)


if __name__ == "__main__":
    unittest.main()
