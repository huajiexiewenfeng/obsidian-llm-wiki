import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.knowledge_graph import analyze_knowledge_graph


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class KnowledgeGraphAnalysisTests(unittest.TestCase):
    def test_index_reaches_wiki_page_and_linked_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            wiki = vault / "control/wiki"
            write(wiki / "index.md", "[[topic]]")
            write(wiki / "topic.md", "[source](../../notes/covered.md)")
            write(vault / "notes/covered.md", "covered")

            analysis = analyze_knowledge_graph(vault, wiki, {"notes/covered.md"})

        self.assertIn("control/wiki/index.md", analysis.reachable_paths)
        self.assertIn("control/wiki/topic.md", analysis.reachable_paths)
        self.assertIn("notes/covered.md", analysis.reachable_paths)
        self.assertEqual(analysis.orphan_wiki_pages, ())

    def test_mutually_linked_pages_disconnected_from_index_are_detached(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            wiki = vault / "control/wiki"
            write(wiki / "index.md", "root")
            write(wiki / "orphan-a.md", "[[orphan-b]]")
            write(wiki / "orphan-b.md", "[[orphan-a]]")

            analysis = analyze_knowledge_graph(vault, wiki, set())

        self.assertEqual(analysis.orphan_wiki_pages, ("orphan-a.md", "orphan-b.md"))
        self.assertEqual(
            analysis.detached_components,
            (("control/wiki/orphan-a.md", "control/wiki/orphan-b.md"),),
        )

    def test_unlisted_sensitive_markdown_is_never_a_node_or_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            wiki = vault / "control/wiki"
            write(wiki / "index.md", "[[public]] [[private]]")
            write(vault / "notes/public.md", "public")
            secret = vault / "secret/private.md"
            secret.parent.mkdir(parents=True, exist_ok=True)
            secret.write_bytes(b"\xff\xfe\x00")

            analysis = analyze_knowledge_graph(vault, wiki, {"notes/public.md"})

        self.assertIn("notes/public.md", analysis.nodes)
        self.assertNotIn("secret/private.md", analysis.nodes)


if __name__ == "__main__":
    unittest.main()
