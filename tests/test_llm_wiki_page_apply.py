import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills/obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.page import (
    apply_pages,
    load_page_apply_payload,
    plan_page_apply,
)
from llm_wiki_core.state import decode_page_registry


def write_registry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema_version":1,"records":{}}', encoding="utf-8")


def make_control(base: Path) -> Path:
    control = base / "control"
    for name in ("sources.json", "pages.json", "operations.json"):
        write_registry(control / ".meta" / name)
    (control / ".meta/change-log.jsonl").write_bytes(b"")
    return control


def page_payload() -> dict[str, object]:
    def page(path: str, page_type: str, body: str) -> dict[str, object]:
        return {
            "role": "derived",
            "page_type": page_type,
            "path": path,
            "managed_body": body,
            "expected_managed_checksum": None,
            "takeover": False,
        }
    return {
        "schema_version": 1,
        "pages": [
            page("wiki/topics/alpha.md", "topic", "# Alpha"),
            page("wiki/projects/beta.md", "project", "# Beta"),
        ],
        "projection_takeovers": [],
    }


class PageApplyTests(unittest.TestCase):
    def test_payload_rejects_source_and_accepts_multiple_pages(self):
        raw = page_payload()
        parsed = load_page_apply_payload(json.dumps(raw))
        self.assertEqual(len(parsed.pages), 2)

        raw["source"] = {"path": "forbidden"}
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            load_page_apply_payload(json.dumps(raw))

    def test_dry_run_is_stable_and_confirm_writes_pages_registry_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control(Path(tmp))
            payload = load_page_apply_payload(json.dumps(page_payload()))

            first = plan_page_apply(control, payload)
            second = plan_page_apply(control, payload)
            result = apply_pages(control, payload, first.plan_checksum)

            records = decode_page_registry(
                json.loads((control / ".meta/pages.json").read_text(encoding="utf-8"))
            )
            index = (control / "wiki/index.md").read_text(encoding="utf-8")

        self.assertEqual(first.plan_checksum, second.plan_checksum)
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(records), 2)
        self.assertIn("wiki/topics/alpha", index)
        self.assertIn("wiki/projects/beta", index)


if __name__ == "__main__":
    unittest.main()
