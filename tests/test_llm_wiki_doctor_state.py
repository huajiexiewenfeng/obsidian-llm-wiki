import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
sys.path.insert(0, str(RUNTIME_SCRIPTS))

from llm_wiki_core.doctor_state import (
    inspect_state_consistency,
    load_doctor_state,
)


STATE_FILES = (
    "schema.json",
    "sources.json",
    "pages.json",
    "operations.json",
    "change-log.jsonl",
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_phase3_control_center(base: Path) -> Path:
    control = base / "00-知识库中控"
    meta = control / ".meta"
    write_json(
        meta / "schema.json",
        {"schema_version": 1, "state_format": "obsidian-llm-wiki"},
    )
    for name in ("sources.json", "pages.json", "operations.json"):
        write_json(meta / name, {"schema_version": 1, "records": {}})
    (meta / "change-log.jsonl").write_bytes(b"")
    return control


def event(sequence: int = 1) -> dict[str, object]:
    return {
        "sequence": sequence,
        "operation_id": f"op-{sequence}",
        "kind": "state-init",
        "record_ids": [],
        "old_checksums": {},
        "new_checksums": {},
        "result": "completed",
        "timestamp": "2026-07-12T00:00:00+00:00",
    }


class DoctorStateLoadingTests(unittest.TestCase):
    def test_absent_meta_disables_phase4_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            control.mkdir()

            issues = inspect_state_consistency(control)

        self.assertEqual(issues, ())

    def test_missing_state_file_is_reported_without_hiding_valid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            (control / ".meta/pages.json").unlink()

            snapshot, issues = load_doctor_state(control)

        self.assertIsNone(snapshot.pages)
        self.assertIsNotNone(snapshot.sources)
        self.assertIsNotNone(snapshot.operations)
        missing = [issue for issue in issues if issue.check == "missing-state-file"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].severity, "ERROR")
        self.assertEqual(missing[0].relative_path, ".meta/pages.json")

    def test_invalid_pages_does_not_hide_other_state_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            (control / ".meta/pages.json").write_text("{", encoding="utf-8")

            snapshot, issues = load_doctor_state(control)

        self.assertIsNone(snapshot.pages)
        self.assertIsNotNone(snapshot.sources)
        self.assertIsNotNone(snapshot.operations)
        self.assertEqual(
            [issue.check for issue in issues],
            ["invalid-state-file"],
        )

    def test_missing_files_are_stably_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            (control / ".meta").mkdir(parents=True)

            _, issues = load_doctor_state(control)

        self.assertEqual(
            [issue.relative_path for issue in issues],
            sorted(f".meta/{name}" for name in STATE_FILES),
        )


class ChangeLogLoadingTests(unittest.TestCase):
    def test_valid_event_without_final_newline_is_not_torn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            encoded = json.dumps(event(), sort_keys=True).encode("utf-8")
            (control / ".meta/change-log.jsonl").write_bytes(encoded)

            snapshot, issues = load_doctor_state(control)

        self.assertEqual(len(snapshot.events), 1)
        self.assertNotIn("torn-change-log-tail", [issue.check for issue in issues])

    def test_torn_tail_warns_and_keeps_valid_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            prefix = json.dumps(event(), sort_keys=True).encode("utf-8") + b"\n"
            (control / ".meta/change-log.jsonl").write_bytes(
                prefix + b'{"sequence": 2'
            )

            snapshot, issues = load_doctor_state(control)

        self.assertEqual(tuple(item["sequence"] for item in snapshot.events), (1,))
        torn = [issue for issue in issues if issue.check == "torn-change-log-tail"]
        self.assertEqual(len(torn), 1)
        self.assertEqual(torn[0].severity, "WARN")
        self.assertEqual(torn[0].line, 2)

    def test_invalid_middle_line_is_error_and_disables_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            first = json.dumps(event(), sort_keys=True)
            third = json.dumps(event(3), sort_keys=True)
            (control / ".meta/change-log.jsonl").write_text(
                f"{first}\nnot-json\n{third}\n",
                encoding="utf-8",
            )

            snapshot, issues = load_doctor_state(control)

        self.assertIsNone(snapshot.events)
        invalid = [issue for issue in issues if issue.check == "invalid-state-file"]
        self.assertEqual(len(invalid), 1)
        self.assertEqual(invalid[0].line, 2)

    def test_invalid_last_line_with_newline_is_error_not_torn(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            first = json.dumps(event(), sort_keys=True)
            (control / ".meta/change-log.jsonl").write_text(
                f"{first}\nnot-json\n",
                encoding="utf-8",
            )

            snapshot, issues = load_doctor_state(control)

        self.assertIsNone(snapshot.events)
        self.assertEqual(
            [issue.check for issue in issues],
            ["invalid-state-file"],
        )


if __name__ == "__main__":
    unittest.main()
