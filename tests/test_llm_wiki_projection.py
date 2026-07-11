import tempfile
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.projection import (
    apply_projection_rebuild,
    load_projection_rebuild_payload,
    plan_projection_rebuild,
    plan_projections,
    read_change_events,
    render_ingest_index,
    render_wiki_index,
    render_wiki_log,
)
from llm_wiki_core.state import PageRecord, SourceRecord


def source(source_id: str, path: str, proxy: str) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        display_path=path,
        canonical_path=path.replace("\\", "/"),
        source_type="markdown",
        mode="summary-ingest",
        status="processed",
        fingerprint={"size": 1, "mtime_ns": 1},
        checksum="sha256:" + "a" * 64,
        proxy_page_id=proxy,
        sensitivity="normal",
        last_verified_at="2026-07-11T00:00:00+00:00",
    )


class ProjectionRendererTests(unittest.TestCase):
    def setUp(self):
        self.pages = {
            "page-z": PageRecord("page-z", "wiki/topics/zeta.md", "topic", ("src-z",), "sha256:z"),
            "page-a": PageRecord("page-a", "wiki/sources/alpha.md", "source", ("src-a",), "sha256:a"),
            "page-b": PageRecord("page-b", "wiki/projects/beta.md", "project", ("src-z",), "sha256:b"),
        }
        self.sources = {
            "src-z": source("src-z", "D:/zeta.md", "page-z"),
            "src-a": source("src-a", "C:/alpha.md", "page-a"),
        }

    def test_wiki_and_ingest_indexes_are_stably_sorted(self):
        wiki = render_wiki_index(dict(reversed(list(self.pages.items()))))
        ingest = render_ingest_index(dict(reversed(list(self.sources.items()))), self.pages)

        self.assertLess(wiki.index("wiki/projects/beta"), wiki.index("wiki/sources/alpha"))
        self.assertLess(wiki.index("wiki/sources/alpha"), wiki.index("wiki/topics/zeta"))
        self.assertLess(ingest.index("C:/alpha.md"), ingest.index("D:/zeta.md"))
        self.assertIn("[[wiki/sources/alpha]]", ingest)

    def test_log_sorts_existing_and_prospective_events_by_sequence(self):
        events = [
            {"sequence": 2, "kind": "second", "operation_id": "op-2", "result": "completed"},
            {"sequence": 1, "kind": "first", "operation_id": "op-1", "result": "completed"},
            {"sequence": 3, "kind": "prospective", "operation_id": "pending", "result": "completed"},
        ]

        rendered = render_wiki_log(events)

        self.assertLess(rendered.index("first"), rendered.index("second"))
        self.assertLess(rendered.index("second"), rendered.index("prospective"))

    def test_change_log_reader_accepts_jsonl_and_rejects_non_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "change-log.jsonl"
            path.write_bytes(b'{"sequence":2}\n{"sequence":1}\n')
            self.assertEqual(
                [event["sequence"] for event in read_change_events(path)],
                [2, 1],
            )
            path.write_bytes(b'[]\n')
            with self.assertRaisesRegex(ValueError, "JSON object"):
                read_change_events(path)

    def test_plan_requires_takeover_per_projection_and_preserves_crlf_user_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            for relative in ("wiki/index.md", "ingest/index.md", "wiki/log.md"):
                target = control / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"User text\r\n")

            conflicts = plan_projections(control, self.sources, self.pages, [], ())
            plans = plan_projections(
                control,
                self.sources,
                self.pages,
                [],
                ("wiki/index.md", "ingest/index.md", "wiki/log.md"),
                prospective_event={
                    "sequence": 1,
                    "kind": "ingest-apply",
                    "operation_id": "prospective",
                    "result": "completed",
                },
            )

        self.assertTrue(all(plan.action == "conflict" for plan in conflicts))
        self.assertTrue(all(plan.action == "update" for plan in plans))
        self.assertTrue(all(plan.rendered_text.startswith("User text\r\n") for plan in plans))
        self.assertTrue(all("\n" not in plan.rendered_text.replace("\r\n", "") for plan in plans))
        log = next(plan for plan in plans if plan.relative_path == "wiki/log.md")
        self.assertIn("prospective", log.rendered_text)
        self.assertNotIn("rendered_text", log.to_public_dict())

    def test_projection_rebuild_payload_is_strict_and_apply_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            meta = control / ".meta"
            meta.mkdir(parents=True)
            for name in ("sources.json", "pages.json", "operations.json"):
                (meta / name).write_text(
                    '{"schema_version":1,"records":{}}', encoding="utf-8"
                )
            (meta / "change-log.jsonl").write_bytes(b"")
            payload = load_projection_rebuild_payload(
                '{"schema_version":1,"projection_takeovers":[]}'
            )

            first = plan_projection_rebuild(control, payload)
            result = apply_projection_rebuild(control, payload, first.plan_checksum)
            second = plan_projection_rebuild(control, payload)

        self.assertEqual(result.status, "completed")
        self.assertTrue(all(item.action == "unchanged" for item in second.projections))

        with self.assertRaisesRegex(ValueError, "unknown fields"):
            load_projection_rebuild_payload(
                '{"schema_version":1,"projection_takeovers":[],"source":{}}'
            )


if __name__ == "__main__":
    unittest.main()
