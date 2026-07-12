import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "llm_wiki.py"


def run_cli(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("OBSIDIAN_LLM_WIKI_ROOT", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )


def payload_for(source: Path, name: str, *, takeovers: list[str]) -> str:
    stat = source.stat()
    checksum = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    return json.dumps({
        "schema_version": 1,
        "source": {
            "path": str(source.resolve()),
            "source_type": "markdown",
            "mode": "summary-ingest",
            "fingerprint": {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
            "checksum": checksum,
            "sensitivity": "normal",
            "move_resolution": None,
        },
        "pages": [{
            "role": "source-proxy",
            "page_type": "source",
            "path": f"wiki/sources/{name}.md",
            "managed_body": f"# {name}",
            "expected_managed_checksum": None,
            "takeover": False,
        }],
        "projection_takeovers": takeovers,
    })


class Phase3EndToEndTests(unittest.TestCase):
    def test_public_skill_and_docs_publish_transaction_contract(self):
        skill = (REPO_ROOT / "skills/obsidian-wiki-ingest/SKILL.md").read_text(encoding="utf-8")
        workflow = (
            REPO_ROOT / "skills/obsidian-wiki-ingest/references/ingest-workflow.md"
        ).read_text(encoding="utf-8")
        for token in ("ingest apply", "--plan-checksum", "must not directly edit", "Phase 3.1"):
            self.assertIn(token, skill)
        for token in ("path-index", "summary-ingest", "unsupported-mode", "Preview is mandatory"):
            self.assertIn(token, workflow)
        for relative in ("README.md", "README.zh.md", "docs/architecture.md", "docs/workflow.md"):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("ingest apply", text, relative)
            self.assertIn("projection rebuild", text, relative)

    def test_two_sources_file_and_stdin_then_idempotent_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = base / "Vault"
            control = vault / "00-知识库中控"
            (control / "wiki").mkdir(parents=True)
            (control / "wiki/index.md").write_bytes(b"# User Index\n")
            (control / "wiki/log.md").write_bytes(b"# User Log\n")
            initialized = run_cli("state", "init", "--root", str(vault), "--confirm")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            first_source = base / "first.md"
            second_source = base / "second.md"
            first_source.write_bytes(b"first")
            second_source.write_bytes(b"second")
            first_text = payload_for(first_source, "first", takeovers=["wiki/index.md", "wiki/log.md"])
            first_payload = base / "first.json"
            first_payload.write_text(first_text, encoding="utf-8")
            first_preview = run_cli(
                "ingest", "apply", "--root", str(vault), "--payload", str(first_payload)
            )
            first_checksum = json.loads(first_preview.stdout)["plan_checksum"]
            first_apply = run_cli(
                "ingest", "apply", "--root", str(vault), "--payload", str(first_payload),
                "--confirm", "--plan-checksum", first_checksum,
            )
            self.assertEqual(first_apply.returncode, 0, first_apply.stderr)

            second_text = payload_for(second_source, "second", takeovers=[])
            second_preview = run_cli(
                "ingest", "apply", "--root", str(vault), "--payload", "-", input_text=second_text
            )
            second_checksum = json.loads(second_preview.stdout)["plan_checksum"]
            second_apply = run_cli(
                "ingest", "apply", "--root", str(vault), "--payload", "-",
                "--confirm", "--plan-checksum", second_checksum, input_text=second_text,
            )
            replay = run_cli(
                "ingest", "apply", "--root", str(vault), "--payload", str(first_payload),
                "--confirm", "--plan-checksum", first_checksum,
            )

            sources = json.loads((control / ".meta/sources.json").read_text(encoding="utf-8"))["records"]
            pages = json.loads((control / ".meta/pages.json").read_text(encoding="utf-8"))["records"]
            events = [
                json.loads(line)
                for line in (control / ".meta/change-log.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            ingest_events = [event for event in events if event["kind"] == "ingest-apply"]
            index_text = (control / "wiki/index.md").read_text(encoding="utf-8")
            log_text = (control / "wiki/log.md").read_text(encoding="utf-8")

        self.assertEqual(second_apply.returncode, 0, second_apply.stderr)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertTrue(json.loads(replay.stdout)["idempotent"])
        self.assertEqual(len(sources), 2)
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(ingest_events), 2)
        self.assertIn("# User Index", index_text)
        self.assertIn("# User Log", log_text)


if __name__ == "__main__":
    unittest.main()
