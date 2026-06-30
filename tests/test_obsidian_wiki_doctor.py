import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "obsidian_wiki_doctor.py"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_control_center(base: Path) -> Path:
    control = base / "00-知识库中控"
    write(control / "wiki" / "index.md", "# Index\n\n- [Topic](topics/topic.md)\n")
    write(control / "wiki" / "log.md", "# Log\n")
    write(control / "wiki" / "topics" / "topic.md", "# Topic\n\nUseful topic text.\n")
    return control


def run_doctor(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=merged_env, check=False)


class RootResolutionTests(unittest.TestCase):
    def test_report_resolves_explicit_control_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            result = run_doctor("report", "--root", str(control), "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["root"]["control_center"], str(control.resolve()))
            self.assertEqual(payload["root"]["wiki_root"], str((control / "wiki").resolve()))
            self.assertTrue(payload["state"]["init_done"])

    def test_validate_reports_invalid_explicit_root_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            result = run_doctor("validate", "--root", str(missing), "--format", "json", "--fail-on", "error")
            self.assertEqual(result.returncode, 1)
            findings = json.loads(result.stdout)
            self.assertEqual(findings[0]["check"], "invalid-root")
            self.assertEqual(findings[0]["severity"], "ERROR")

    def test_environment_root_is_used_when_no_root_argument_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            result = run_doctor("score", "--format", "json", env={"OBSIDIAN_LLM_WIKI_ROOT": str(control)})
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["root"]["control_center"], str(control.resolve()))


if __name__ == "__main__":
    unittest.main()
