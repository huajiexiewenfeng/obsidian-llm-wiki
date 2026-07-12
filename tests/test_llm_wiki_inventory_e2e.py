import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/llm_wiki.py"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("OBSIDIAN_LLM_WIKI_ROOT", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )


def snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*")
        if path.is_file()
    }


class InventoryEndToEndTests(unittest.TestCase):
    def test_initialize_then_new_markdown_is_reported_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "Vault"
            write(vault / "00-知识库中控/wiki/index.md", "# Index\n")
            write(vault / "00-知识库中控/wiki/log.md", "# Log\n")
            write(vault / "notes/existing.md", "existing")
            state = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(state.returncode, 0, state.stderr)
            preview = run_cli("inventory", "initialize", "--root", str(vault), "--format", "json")
            self.assertEqual(preview.returncode, 1, preview.stderr)
            plan = json.loads(preview.stdout)
            confirmed = run_cli(
                "inventory", "initialize", "--root", str(vault), "--confirm",
                "--plan-checksum", plan["plan_checksum"], "--format", "json",
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
            write(vault / "notes/new-after-baseline.md", "new")
            before = snapshot(vault)

            doctor = run_cli(
                "doctor", "validate", "--root", str(vault),
                "--format", "json", "--fail-on", "none",
            )

            after = snapshot(vault)
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        paths = {
            item["path"] for item in json.loads(doctor.stdout)
            if item["check"] == "uningested-source"
        }
        self.assertIn("notes/new-after-baseline.md", paths)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
