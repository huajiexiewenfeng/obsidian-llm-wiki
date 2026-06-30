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


class ValidationCheckTests(unittest.TestCase):
    def test_missing_wiki_index_is_error_when_log_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-\u77e5\u8bc6\u5e93\u4e2d\u63a7"
            write(control / "wiki" / "log.md", "# Log\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing-wiki-index", {item["check"] for item in findings})

    def test_broken_index_link_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-\u77e5\u8bc6\u5e93\u4e2d\u63a7"
            write(control / "wiki" / "index.md", "# Index\n\n- [Missing](topics/missing.md)\n")
            write(control / "wiki" / "log.md", "# Log\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            broken = [item for item in findings if item["check"] == "broken-index-link"]
            self.assertEqual(result.returncode, 1)
            self.assertEqual(broken[0]["severity"], "ERROR")
            self.assertIn("topics/missing.md", broken[0]["message"])

    def test_missing_source_proxy_for_processed_ingest_row_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "ingest" / "index.md", "| source | proxy | status | wiki_entry |\n|---|---|---|---|\n| D:/docs/a.md | sources/a.md | processed | topics/a.md |\n")
            write(control / "wiki" / "topics" / "a.md", "# A\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertIn("missing-source-proxy", {item["check"] for item in findings})

    def test_safety_check_redacts_secret_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "sources" / "secret.md", "# Secret\n\ntoken=redacted-example-value\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            sensitive = [item for item in findings if item["check"] == "sensitive-pattern"]
            self.assertTrue(sensitive)
            serialized = json.dumps(sensitive, ensure_ascii=False)
            self.assertIn("token", serialized)
            self.assertNotIn("redacted-example-value", serialized)


    def test_ingest_title_case_source_proxy_header_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "ingest" / "index.md", "| Source | Source Proxy | Status | Wiki Entry |\n|---|---|---|---|\n| D:/docs/a.md | sources/a.md | Processed | topics/a.md |\n")
            write(control / "wiki" / "topics" / "a.md", "# A\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertIn("missing-source-proxy", {item["check"] for item in findings})

    def test_valid_markdown_title_link_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "index.md", "# Index\n\n- [Topic](topics/topic.md \"title\")\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_valid_extensionless_markdown_link_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "index.md", "# Index\n\n- [Topic](topics/topic)\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_valid_obsidian_wikilink_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "index.md", "# Index\n\n- [[topics/topic|Topic]]\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_sensitive_pattern_redacts_secret_like_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "sources" / "token=redacted-example-value.md", "# Secret\n\ntoken=another-example-value\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            sensitive = [item for item in findings if item["check"] == "sensitive-pattern"]
            self.assertTrue(sensitive)
            serialized = json.dumps(sensitive, ensure_ascii=False)
            self.assertIn("token", serialized)
            self.assertNotIn("redacted-example-value", serialized)
            self.assertNotIn("another-example-value", serialized)


    def test_valid_obsidian_basename_wikilink_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "index.md", "# Index\n\n- [[Topic]]\n")
            write(control / "wiki" / "topics" / "Topic.md", "# Topic\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_sensitive_pattern_redacts_dash_secret_like_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "sources" / "token-redacted-example-value.md", "# Secret\n\ntoken=another-secret\n")
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            sensitive = [item for item in findings if item["check"] == "sensitive-pattern"]
            self.assertTrue(sensitive)
            serialized = json.dumps(sensitive, ensure_ascii=False)
            self.assertIn("token", serialized)
            self.assertNotIn("redacted-example-value", serialized)
            self.assertNotIn("another-secret", serialized)

    def test_score_remains_neutral_when_findings_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "sources" / "secret.md", "# Secret\n\ntoken=redacted-example-value\n")
            result = run_doctor("report", "--root", str(control), "--format", "json")
            payload = json.loads(result.stdout)
            self.assertTrue(payload["findings"])
            self.assertEqual(payload["score"]["score"], 100)


if __name__ == "__main__":
    unittest.main()
