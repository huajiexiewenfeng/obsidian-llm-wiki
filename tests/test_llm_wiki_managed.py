import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.managed import (
    ManagedConflict,
    PROJECTION_END,
    PROJECTION_START,
    inspect_managed_page,
    inspect_projection_region,
    managed_checksum,
    replace_frontmatter_region,
    replace_managed_body,
    replace_projection_region,
)


class ManagedRegionTests(unittest.TestCase):
    def test_inspect_managed_page_returns_canonical_snapshot(self):
        text = (
            "---\r\n# llm-wiki:frontmatter:start\r\n"
            'llm_wiki_page_id: "page-1"\r\n'
            'llm_wiki_page_type: "topic"\r\n'
            'llm_wiki_source_ids: ["source-1"]\r\n'
            'llm_wiki_managed_checksum: "sha256:old"\r\n'
            "# llm-wiki:frontmatter:end\r\n---\r\n"
            "<!-- llm-wiki:managed:start -->\r\nBody\r\n\r\n"
            "<!-- llm-wiki:managed:end -->\r\n"
        )

        snapshot = inspect_managed_page(text)

        self.assertEqual(snapshot.fields["llm_wiki_page_id"], "page-1")
        self.assertEqual(snapshot.fields["llm_wiki_source_ids"], ["source-1"])
        self.assertEqual(snapshot.managed_body, "Body")
        self.assertEqual(
            snapshot.computed_checksum,
            managed_checksum(snapshot.fields, "Body"),
        )

    def test_inspect_projection_region_normalizes_newlines_and_tail(self):
        snapshot = inspect_projection_region(
            "Before\r\n"
            "<!-- llm-wiki:projection:start -->\r\nA\r\nB\r\n\r\n"
            "<!-- llm-wiki:projection:end -->\r\nAfter\r\n"
        )

        self.assertEqual(snapshot.managed_body, "A\nB")

    def test_inspect_managed_page_rejects_invalid_json_value(self):
        text = (
            "---\n# llm-wiki:frontmatter:start\n"
            "llm_wiki_page_id: not-json\n"
            "# llm-wiki:frontmatter:end\n---\n"
            "<!-- llm-wiki:managed:start -->\nBody\n"
            "<!-- llm-wiki:managed:end -->\n"
        )

        with self.assertRaisesRegex(ManagedConflict, "managed frontmatter is invalid"):
            inspect_managed_page(text)

    def test_inspect_managed_page_rejects_duplicate_managed_markers(self):
        text = (
            "---\n# llm-wiki:frontmatter:start\n"
            'llm_wiki_page_id: "page-1"\n'
            "# llm-wiki:frontmatter:end\n---\n"
            "<!-- llm-wiki:managed:start -->\nA\n"
            "<!-- llm-wiki:managed:start -->\nB\n"
            "<!-- llm-wiki:managed:end -->\n"
        )

        with self.assertRaisesRegex(ManagedConflict, "managed markers"):
            inspect_managed_page(text)

    def test_projection_replace_preserves_user_text(self):
        original = "Before\n<!-- llm-wiki:projection:start -->\nold\n<!-- llm-wiki:projection:end -->\nAfter\n"
        updated = replace_projection_region(original, "new\n")
        self.assertEqual(
            updated,
            "Before\n<!-- llm-wiki:projection:start -->\nnew\n<!-- llm-wiki:projection:end -->\nAfter\n",
        )

    def test_missing_projection_requires_takeover(self):
        with self.assertRaisesRegex(ManagedConflict, "projection markers are missing"):
            replace_projection_region("User text\n", "managed\n")

    def test_duplicate_markers_are_conflict(self):
        text = (
            "<!-- llm-wiki:managed:start -->\na\n"
            "<!-- llm-wiki:managed:start -->\nb\n"
            "<!-- llm-wiki:managed:end -->\n"
        )
        with self.assertRaisesRegex(ManagedConflict, "managed markers"):
            replace_managed_body(text, "new\n")

    def test_out_of_order_markers_are_conflict(self):
        text = f"{PROJECTION_END}\nuser\n{PROJECTION_START}\n"
        with self.assertRaisesRegex(ManagedConflict, "out of order"):
            replace_projection_region(text, "new\n")

    def test_frontmatter_replace_preserves_user_fields(self):
        original = (
            "---\ntags:\n  - user\n"
            "# llm-wiki:frontmatter:start\n"
            "llm_wiki_schema: 1\n"
            "# llm-wiki:frontmatter:end\n"
            "aliases:\n  - Mine\n---\nBody\n"
        )
        updated = replace_frontmatter_region(
            original,
            {"llm_wiki_schema": 1, "llm_wiki_page_id": "page-1"},
        )
        self.assertIn("tags:\n  - user\n", updated)
        self.assertIn("aliases:\n  - Mine\n", updated)
        self.assertIn('llm_wiki_page_id: "page-1"', updated)
        self.assertTrue(updated.endswith("---\nBody\n"))

    def test_managed_checksum_is_stable_and_excludes_checksum_field(self):
        fields = {
            "llm_wiki_page_id": "page-1",
            "llm_wiki_managed_checksum": "sha256:old",
        }
        self.assertEqual(
            managed_checksum(fields, "body\n"),
            managed_checksum({"llm_wiki_page_id": "page-1"}, "body\n"),
        )

    def test_takeover_appends_projection_once(self):
        updated = replace_projection_region("User\n", "managed\n", takeover=True)
        self.assertEqual(updated.count("llm-wiki:projection:start"), 1)
        self.assertTrue(updated.startswith("User\n"))

    def test_frontmatter_json_array_is_single_line(self):
        original = (
            "---\n# llm-wiki:frontmatter:start\n"
            "# llm-wiki:frontmatter:end\n---\n"
        )
        updated = replace_frontmatter_region(
            original,
            {"llm_wiki_source_ids": ["src-1", "src-2"]},
        )
        self.assertIn('llm_wiki_source_ids: ["src-1","src-2"]', updated)

    def test_nested_projection_markers_are_rejected(self):
        text = (
            f"{PROJECTION_START}\n{PROJECTION_START}\nx\n"
            f"{PROJECTION_END}\n{PROJECTION_END}\n"
        )
        with self.assertRaises(ManagedConflict):
            replace_projection_region(text, "new\n")

    def test_crlf_frontmatter_preserves_crlf_user_regions(self):
        original = (
            "---\r\ntags:\r\n  - user\r\n"
            "# llm-wiki:frontmatter:start\r\n"
            "llm_wiki_schema: 1\r\n"
            "# llm-wiki:frontmatter:end\r\n"
            "aliases:\r\n  - Mine\r\n---\r\nBody\r\n"
        )
        updated = replace_frontmatter_region(original, {"llm_wiki_schema": 1})
        self.assertNotIn("\n", updated.replace("\r\n", ""))
        self.assertIn("aliases:\r\n  - Mine\r\n", updated)
