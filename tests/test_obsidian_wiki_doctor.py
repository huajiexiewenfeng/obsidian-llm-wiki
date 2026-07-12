import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "obsidian_wiki_doctor.py"
RUNTIME_SCRIPTS = REPO_ROOT / "skills" / "obsidian-wiki-runtime" / "scripts"
CANONICAL_SCRIPT = RUNTIME_SCRIPTS / "obsidian_wiki_doctor.py"
sys.path.insert(0, str(RUNTIME_SCRIPTS))
import obsidian_wiki_doctor as doctor
from llm_wiki_core.projection import (
    render_ingest_index,
    render_wiki_index,
    render_wiki_log,
)
from llm_wiki_core.state import OperationRecord


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


def projection_page(body: str) -> str:
    return (
        "<!-- llm-wiki:projection:start -->\n"
        f"{body.rstrip()}\n"
        "<!-- llm-wiki:projection:end -->\n"
    )


def write_json(path: Path, payload: object) -> None:
    write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def make_phase3_control_center(base: Path) -> Path:
    control = make_control_center(base)
    meta = control / ".meta"
    write_json(
        meta / "schema.json",
        {"schema_version": 1, "state_format": "obsidian-llm-wiki"},
    )
    for name in ("sources.json", "pages.json", "operations.json"):
        write_json(meta / name, {"schema_version": 1, "records": {}})
    write(meta / "change-log.jsonl", "")
    write(control / "wiki/index.md", projection_page(render_wiki_index({})))
    write(control / "ingest/index.md", projection_page(render_ingest_index({}, {})))
    write(control / "wiki/log.md", projection_page(render_wiki_log(())))
    return control


def write_active_operation(control: Path) -> None:
    acquired = datetime.now(timezone.utc)
    started = acquired + timedelta(milliseconds=1)
    operation = OperationRecord(
        operation_id="op-active",
        idempotency_key="key-active",
        kind="ingest-apply",
        record_ids=(),
        current_step="write-pages",
        status="running",
        started_at=started.isoformat(),
        updated_at=(started + timedelta(milliseconds=1)).isoformat(),
    )
    write_json(
        control / ".meta/operations.json",
        {"schema_version": 1, "records": {operation.operation_id: operation.to_dict()}},
    )
    write_json(
        control / ".meta/lock.json",
        {
            "lock_id": "lock-active",
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "command": "ingest apply",
            "acquired_at": acquired.isoformat(),
            "target": str(control.resolve()),
        },
    )


def tree_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        stat = path.stat()
        snapshot[path.relative_to(root).as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return snapshot


def run_doctor(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return run_doctor_script(SCRIPT, *args, env=env, cwd=cwd)


def run_doctor_script(
    script: Path,
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
        check=False,
    )


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

    def test_project_config_is_used_when_no_root_argument_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            control = make_control_center(base / "vault")
            vault = control.parent
            project = base / "project"
            project.mkdir()
            write(project / ".obsidian-llm-wiki.json", json.dumps({
                "schema_version": 1,
                "vault_root": str(vault),
                "control_center": "00-知识库中控",
                "active": True,
            }))

            result = run_doctor("score", "--format", "json", cwd=project)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["root"]["control_center"], str(control.resolve()))


class ValidationCheckTests(unittest.TestCase):
    def test_empty_control_center_wiki_reports_missing_index_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-\u77e5\u8bc6\u5e93\u4e2d\u63a7"
            (control / "wiki").mkdir(parents=True)
            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)
            checks = {item["check"] for item in findings}
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing-wiki-index", checks)
            self.assertIn("missing-wiki-log", checks)


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

    def test_control_center_relative_wikilink_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "sources" / "source.md", "# Source\n")
            write(
                control / "wiki" / "index.md",
                "# Index\n\n- [[wiki/sources/source|Source]]\n",
            )

            result = run_doctor("validate", "--root", str(control), "--format", "json")
            findings = json.loads(result.stdout)

        self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_vault_root_wikilink_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = make_control_center(vault)
            write(
                control / "wiki" / "index.md",
                "# Index\n\n- [[00-知识库中控/wiki/topics/topic|Topic]]\n",
            )

            result = run_doctor("validate", "--root", str(vault), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_dotted_extensionless_wikilink_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = make_control_center(vault)
            write(control / "00.知识库地图.md", "# Map\n")
            write(control / "wiki" / "index.md", "# Index\n\n- [[00.知识库地图]]\n")

            result = run_doctor("validate", "--root", str(vault), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_unique_vault_basename_wikilink_outside_wiki_is_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = make_control_center(vault)
            write(vault / "00.整理范围确认.md", "# Scope\n")
            write(control / "wiki" / "index.md", "# Index\n\n- [[00.整理范围确认]]\n")

            result = run_doctor("validate", "--root", str(vault), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertNotIn("broken-index-link", {item["check"] for item in findings})

    def test_ambiguous_vault_basename_wikilink_remains_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            control = make_control_center(vault)
            write(control / "wiki" / "topics" / "Duplicate.md", "# Topic\n")
            write(vault / "archive" / "Duplicate.md", "# Archived Topic\n")
            write(control / "wiki" / "index.md", "# Index\n\n- [[Duplicate]]\n")

            result = run_doctor("validate", "--root", str(vault), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertIn("broken-index-link", {item["check"] for item in findings})

    def test_explicit_relative_wikilink_resolves_from_source_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(
                control / "wiki" / "projects" / "project.md",
                "# Project\n\n- [[../topics/topic|Topic]]\n",
            )

            result = run_doctor("validate", "--root", str(control), "--format", "json")

            findings = json.loads(result.stdout)
            project_findings = [item for item in findings if item["path"] == "projects/project.md"]
            self.assertNotIn("broken-internal-link", {item["check"] for item in project_findings})

    def test_genuinely_missing_wikilink_remains_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "index.md", "# Index\n\n- [[Missing Topic]]\n")

            result = run_doctor("validate", "--root", str(control), "--format", "json")

            findings = json.loads(result.stdout)
            self.assertIn("broken-index-link", {item["check"] for item in findings})

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

    def test_obsidian_basename_wikilink_prefers_exact_case_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            source = write(wiki_root / "index.md", "# Index\n")
            folded = wiki_root / "topics" / "topic.md"
            exact = wiki_root / "topics" / "Topic.md"

            with patch.object(doctor, "iter_markdown_files", return_value=[folded, exact]):
                resolved = doctor.resolve_wikilink(source, "Topic", wiki_root)

            self.assertEqual(resolved, exact.resolve())

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

    def test_sensitive_pattern_reduces_safety_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            write(control / "wiki" / "sources" / "secret.md", "# Secret\n\ntoken=redacted-example-value\n")
            result = run_doctor("report", "--root", str(control), "--format", "json")
            payload = json.loads(result.stdout)
            safety = [item for item in payload["score"]["dimensions"] if item["name"] == "Safety hygiene"][0]
            self.assertTrue(payload["findings"])
            self.assertEqual(safety["score"], 0)
            self.assertLess(payload["score"]["score"], 100)


class Phase4IntegrationTests(unittest.TestCase):
    def test_archive_finding_keeps_public_schema_and_score_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            raw = control / "raw/unregistered.bin"
            raw.parent.mkdir()
            raw.write_bytes(b"private-binary-body")

            validate = run_doctor(
                "validate",
                "--root",
                str(control),
                "--format",
                "json",
                "--fail-on",
                "error",
            )
            score = run_doctor("score", "--root", str(control), "--format", "json")

        self.assertEqual(validate.returncode, 0, validate.stderr)
        finding = next(
            item
            for item in json.loads(validate.stdout)
            if item["check"] == "unregistered-archive"
        )
        self.assertEqual(
            set(finding),
            {"check", "severity", "path", "message", "line", "hint"},
        )
        self.assertNotIn("private-binary-body", validate.stdout)
        score_payload = json.loads(score.stdout)
        self.assertEqual(score_payload["score_version"], 1)
        self.assertEqual(len(score_payload["dimensions"]), 5)

    def test_validate_score_and_report_do_not_modify_control_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_active_operation(control)
            before = tree_snapshot(control)
            self.assertIn(".meta/lock.json", before)

            results = [
                run_doctor(
                    "validate",
                    "--root",
                    str(control),
                    "--format",
                    "json",
                    "--fail-on",
                    "error",
                ),
                run_doctor("score", "--root", str(control), "--format", "json"),
                run_doctor("report", "--root", str(control), "--format", "json"),
            ]
            after = tree_snapshot(control)

        self.assertTrue(all(result.returncode == 0 for result in results))
        self.assertEqual(after, before)

    def test_root_launcher_matches_canonical_phase4_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write(control / "wiki/index.md", projection_page("# Drift"))
            args = (
                "validate",
                "--root",
                str(control),
                "--format",
                "json",
                "--fail-on",
                "none",
            )

            root_result = run_doctor_script(SCRIPT, *args)
            canonical_result = run_doctor_script(CANONICAL_SCRIPT, *args)

        self.assertEqual(root_result.returncode, canonical_result.returncode)
        self.assertEqual(json.loads(root_result.stdout), json.loads(canonical_result.stdout))
        self.assertIn(
            "projection-drift",
            [item["check"] for item in json.loads(root_result.stdout)],
        )

    def test_active_operation_info_renders_in_json_and_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_active_operation(control)

            result = run_doctor(
                "validate",
                "--root",
                str(control),
                "--format",
                "json",
                "--fail-on",
                "error",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        findings = json.loads(result.stdout)
        active = [item for item in findings if item["check"] == "active-operation"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["severity"], "INFO")
        self.assertEqual(
            set(active[0]),
            {"check", "severity", "path", "message", "line", "hint"},
        )

    def test_active_operation_info_renders_in_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_active_operation(control)

            result = run_doctor(
                "validate",
                "--root",
                str(control),
                "--format",
                "text",
                "--fail-on",
                "error",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INFO: active-operation:", result.stdout)

    def test_phase4_error_fails_validate_but_not_score_or_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            (control / ".meta/pages.json").unlink()

            validate = run_doctor(
                "validate",
                "--root",
                str(control),
                "--format",
                "json",
                "--fail-on",
                "error",
            )
            score = run_doctor("score", "--root", str(control), "--format", "json")
            report = run_doctor("report", "--root", str(control), "--format", "json")

        self.assertEqual(validate.returncode, 1, validate.stderr)
        self.assertIn("missing-state-file", [item["check"] for item in json.loads(validate.stdout)])
        self.assertEqual(score.returncode, 0, score.stderr)
        self.assertEqual(report.returncode, 0, report.stderr)
        score_payload = json.loads(score.stdout)
        self.assertEqual(score_payload["score_version"], 1)
        self.assertEqual(len(score_payload["dimensions"]), 5)

    def test_phase4_finding_path_is_redacted(self):
        secret_name = "-sk-abcdefghijklmnopqrstuvwxyz123456.md"
        with tempfile.TemporaryDirectory() as tmp:
            control = make_phase3_control_center(Path(tmp))
            write_json(
                control / ".meta/pages.json",
                {
                    "schema_version": 1,
                    "records": {
                        "page-secret": {
                            "page_id": "page-secret",
                            "relative_path": f"wiki/topics/{secret_name}",
                            "page_type": "topic",
                            "source_ids": [],
                            "managed_checksum": "sha256:missing",
                            "revision": 1,
                        }
                    },
                },
            )

            result = run_doctor(
                "validate",
                "--root",
                str(control),
                "--format",
                "json",
                "--fail-on",
                "none",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(secret_name, result.stdout)
        self.assertIn("<redacted>", result.stdout)


class ScoreAndReportTests(unittest.TestCase):
    def test_score_marks_ingest_not_applicable_for_fresh_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            result = run_doctor("score", "--root", str(control), "--format", "json")
            payload = json.loads(result.stdout)
            ingest = [item for item in payload["dimensions"] if item["name"] == "Ingest traceability"][0]
            self.assertEqual(result.returncode, 0)
            self.assertEqual(ingest["applicability"], "not-applicable")

    def test_report_text_is_chinese_first_and_always_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "00-知识库中控"
            write(control / "wiki" / "log.md", "# Log\n")
            result = run_doctor("report", "--root", str(control), "--format", "text")
            self.assertEqual(result.returncode, 0)
            self.assertIn("# Obsidian Wiki Doctor 报告", result.stdout)
            self.assertIn("## 建议行动计划", result.stdout)
            self.assertIn("missing-wiki-index", result.stdout)

    def test_report_json_contains_root_state_findings_and_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = make_control_center(Path(tmp))
            result = run_doctor("report", "--root", str(control), "--format", "json")
            payload = json.loads(result.stdout)
            self.assertIn("root", payload)
            self.assertIn("state", payload)
            self.assertIn("findings", payload)
            self.assertIn("score", payload)

    def test_invalid_root_blocks_downstream_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "token-redacted-example-value"
            result = run_doctor("score", "--root", str(missing), "--format", "json")
            payload = json.loads(result.stdout)
            dimensions = {item["name"]: item for item in payload["dimensions"]}
            self.assertEqual(result.returncode, 0)
            self.assertEqual(payload["score"], 0)
            self.assertEqual(dimensions["Control center resolution"]["score"], 0)
            self.assertEqual(dimensions["Safety hygiene"]["applicability"], "not-applicable")
            self.assertIsNone(dimensions["Safety hygiene"]["score"])

    def test_secret_like_invalid_root_is_redacted_in_report_and_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "token-redacted-example-value"
            report_json = run_doctor("report", "--root", str(missing), "--format", "json")
            report_text = run_doctor("report", "--root", str(missing), "--format", "text")
            score_json = run_doctor("score", "--root", str(missing), "--format", "json")
            self.assertEqual(report_json.returncode, 0)
            self.assertEqual(report_text.returncode, 0)
            self.assertEqual(score_json.returncode, 0)
            self.assertNotIn("redacted-example-value", report_json.stdout)
            self.assertNotIn("redacted-example-value", report_text.stdout)
            self.assertNotIn("redacted-example-value", score_json.stdout)

if __name__ == "__main__":
    unittest.main()
