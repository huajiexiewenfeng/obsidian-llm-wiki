import tempfile
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.ingest import PageMutation
from llm_wiki_core.page import PagePlan, plan_page_mutation
from llm_wiki_core.state import PageRecord


def mutation(
    body: str = "# Generated\n",
    *,
    expected: str | None = None,
    takeover: bool = False,
    path: str = "wiki/topics/example.md",
) -> PageMutation:
    return PageMutation(
        role="derived",
        page_type="topic",
        relative_path=path,
        managed_body=body,
        expected_managed_checksum=expected,
        takeover=takeover,
    )


class PagePlannerTests(unittest.TestCase):
    def test_new_page_plan_contains_markers_but_public_result_has_no_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            control.mkdir()

            plan = plan_page_mutation(control, mutation(), {}, ("src-1",))

        self.assertIsInstance(plan, PagePlan)
        self.assertEqual(plan.action, "create")
        self.assertIn("llm_wiki_page_id", plan.rendered_text)
        self.assertIn("llm-wiki:managed:start", plan.rendered_text)
        self.assertIn("# Generated", plan.rendered_text)
        self.assertNotIn("rendered_text", plan.to_public_dict())
        self.assertNotIn("# Generated", str(plan.to_public_dict()))

    def test_existing_page_requires_expected_checksum_and_reports_safe_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            control.mkdir()
            created = plan_page_mutation(control, mutation(), {}, ("src-1",))
            target = control / created.relative_path
            target.parent.mkdir(parents=True)
            target.write_text(created.rendered_text, encoding="utf-8", newline="")
            records = {
                created.page_id: PageRecord(
                    page_id=created.page_id,
                    relative_path=created.relative_path,
                    page_type="topic",
                    source_ids=("src-1",),
                    managed_checksum=created.new_managed_checksum,
                )
            }

            plan = plan_page_mutation(control, mutation("SECRET-NEW-BODY"), records, ("src-1",))

        self.assertEqual(plan.action, "conflict")
        public = plan.to_public_dict()
        self.assertEqual(public["current_managed_checksum"], created.new_managed_checksum)
        self.assertEqual(public["registry_managed_checksum"], created.new_managed_checksum)
        self.assertIn("expected_managed_checksum", public["resolution_hint"])
        self.assertNotIn("SECRET-NEW-BODY", str(public))

    def test_matching_update_preserves_crlf_user_regions(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            control.mkdir()
            created = plan_page_mutation(control, mutation(), {}, ("src-1",))
            original = created.rendered_text.replace("\n", "\r\n")
            original = original.replace("---\r\n", "---\r\ntags: [user]\r\n", 1)
            original += "User tail\r\n"
            target = control / created.relative_path
            target.parent.mkdir(parents=True)
            target.write_text(original, encoding="utf-8", newline="")
            records = {
                created.page_id: PageRecord(
                    page_id=created.page_id,
                    relative_path=created.relative_path,
                    page_type="topic",
                    source_ids=("src-1",),
                    managed_checksum=created.new_managed_checksum,
                )
            }

            plan = plan_page_mutation(
                control,
                mutation("# Updated\n", expected=created.new_managed_checksum),
                records,
                ("src-1",),
            )

        self.assertEqual(plan.action, "update")
        self.assertIn("tags: [user]\r\n", plan.rendered_text)
        self.assertTrue(plan.rendered_text.endswith("User tail\r\n"))
        self.assertNotIn("\n", plan.rendered_text.replace("\r\n", ""))

    def test_same_body_and_checksum_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            control.mkdir()
            created = plan_page_mutation(control, mutation(), {}, ("src-1",))
            target = control / created.relative_path
            target.parent.mkdir(parents=True)
            target.write_text(created.rendered_text, encoding="utf-8", newline="")
            records = {
                created.page_id: PageRecord(
                    page_id=created.page_id,
                    relative_path=created.relative_path,
                    page_type="topic",
                    source_ids=("src-1",),
                    managed_checksum=created.new_managed_checksum,
                )
            }

            plan = plan_page_mutation(
                control,
                mutation(expected=created.new_managed_checksum),
                records,
                ("src-1",),
            )

        self.assertEqual(plan.action, "unchanged")
        self.assertIsNone(plan.rendered_text)

    def test_registry_drift_is_conflict_even_when_payload_matches_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            control.mkdir()
            created = plan_page_mutation(control, mutation(), {}, ("src-1",))
            target = control / created.relative_path
            target.parent.mkdir(parents=True)
            target.write_text(created.rendered_text, encoding="utf-8", newline="")
            records = {
                created.page_id: PageRecord(
                    page_id=created.page_id,
                    relative_path=created.relative_path,
                    page_type="topic",
                    source_ids=("src-1",),
                    managed_checksum="sha256:" + "f" * 64,
                )
            }

            plan = plan_page_mutation(
                control,
                mutation(expected=created.new_managed_checksum),
                records,
                ("src-1",),
            )

        self.assertEqual(plan.action, "conflict")
        self.assertEqual(plan.conflict["check"], "registry-page-drift")

    def test_existing_unmanaged_page_needs_per_page_takeover(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            target = control / "wiki/topics/example.md"
            target.parent.mkdir(parents=True)
            target.write_text("---\ntags: [user]\n---\nUser body\n", encoding="utf-8")

            conflict = plan_page_mutation(control, mutation(), {}, ("src-1",))
            takeover = plan_page_mutation(control, mutation(takeover=True), {}, ("src-1",))

        self.assertEqual(conflict.action, "conflict")
        self.assertEqual(conflict.conflict["check"], "takeover-required")
        self.assertEqual(takeover.action, "create")
        self.assertIn("tags: [user]", takeover.rendered_text)
        self.assertIn("User body", takeover.rendered_text)
        self.assertIn("llm-wiki:managed:start", takeover.rendered_text)

    def test_takeover_adds_frontmatter_to_plain_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            target = control / "wiki/topics/example.md"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"# User title\nUser body\n")

            plan = plan_page_mutation(
                control,
                mutation(takeover=True),
                {},
                ("src-1",),
            )

        self.assertEqual(plan.action, "create")
        self.assertTrue(plan.rendered_text.startswith("---\n"))
        self.assertIn("# User title\nUser body\n", plan.rendered_text)


if __name__ == "__main__":
    unittest.main()
