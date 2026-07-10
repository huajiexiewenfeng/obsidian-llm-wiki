import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "llm_wiki.py"
OLD_DOCTOR = REPO_ROOT / "scripts" / "obsidian_wiki_doctor.py"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_vault(base: Path) -> Path:
    vault = base / "My Vault"
    write(vault / "00-知识库中控" / "wiki" / "index.md", "# Index\n")
    write(vault / "00-知识库中控" / "wiki" / "log.md", "# Log\n")
    return vault


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("OBSIDIAN_LLM_WIKI_ROOT", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )


class RootCliTests(unittest.TestCase):
    def test_root_resolve_emits_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))

            result = run_cli("root", "resolve", "--root", str(vault), "--format", "json")

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["source"], "argument")
            self.assertEqual(payload["vault_root"], str(vault.resolve()))
            self.assertEqual(payload["control_center"], str((vault / "00-知识库中控").resolve()))

    def test_missing_config_returns_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(
                "root",
                "resolve",
                "--cwd",
                tmp,
                "--user-config",
                str(Path(tmp) / "missing.json"),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["error"]["check"], "missing-config")


class DoctorCompatibilityTests(unittest.TestCase):
    def test_new_and_old_doctor_json_are_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            old = subprocess.run(
                [sys.executable, str(OLD_DOCTOR), "report", "--root", str(vault), "--format", "json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            new = run_cli("doctor", "report", "--root", str(vault), "--format", "json")

            self.assertEqual(new.returncode, old.returncode)
            self.assertEqual(json.loads(new.stdout), json.loads(old.stdout))


if __name__ == "__main__":
    unittest.main()
