import json
import hashlib
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


def run_cli(
    *args: str,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
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
        input=input_text,
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


class StateInitCliTests(unittest.TestCase):
    def test_preview_writes_nothing_and_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            result = run_cli("state", "init", "--root", str(vault), "--format", "json")
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["confirmation_required"])
            self.assertFalse(payload["initialized"])
            self.assertFalse((vault / "00-知识库中控" / ".meta").exists())

    def test_confirm_creates_state_and_second_run_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            first = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(first.returncode, 0, first.stderr)
            meta = vault / "00-知识库中控" / ".meta"
            expected = {
                "schema.json",
                "sources.json",
                "pages.json",
                "operations.json",
                "change-log.jsonl",
            }
            self.assertTrue(expected.issubset({path.name for path in meta.iterdir()}))
            first_events = (meta / "change-log.jsonl").read_text(encoding="utf-8").splitlines()

            second = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(second.stdout)["create"], [])
            second_events = (meta / "change-log.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(second_events, first_events)

    def test_invalid_existing_schema_returns_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = make_vault(Path(tmp))
            meta = vault / "00-知识库中控" / ".meta"
            meta.mkdir()
            (meta / "schema.json").write_text('{"schema_version": 99}', encoding="utf-8")
            result = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["error"]["check"], "invalid-state")


class DefaultVaultCliTests(unittest.TestCase):
    def test_discover_returns_recent_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = make_vault(base)
            appdata = base / "appdata"
            if sys.platform.startswith("win"):
                metadata = appdata / "obsidian" / "obsidian.json"
            elif sys.platform == "darwin":
                metadata = base / "Library" / "Application Support" / "obsidian" / "obsidian.json"
            else:
                metadata = base / ".config" / "obsidian" / "obsidian.json"
            write(metadata, json.dumps({
                "vaults": {"recent": {"path": str(vault), "ts": 1, "open": True}},
            }))
            environment = os.environ.copy()
            environment.update({"APPDATA": str(appdata), "HOME": str(base)})
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "root", "discover", "--format", "json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["candidates"], [str(vault.resolve())])

    def test_configure_without_confirm_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = make_vault(base)
            config = base / "config.json"

            result = run_cli(
                "root", "configure", "--root", str(vault), "--activate",
                "--user-config", str(config), "--format", "json",
            )

            self.assertEqual(result.returncode, 1)
            self.assertTrue(json.loads(result.stdout)["confirmation_required"])
            self.assertFalse(config.exists())


def make_ingest_payload(source: Path) -> dict[str, object]:
    stat = source.stat()
    checksum = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    return {
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
            "path": "wiki/sources/example.md",
            "managed_body": "SECRET-GENERATED-BODY",
            "expected_managed_checksum": None,
            "takeover": False,
        }],
        "projection_takeovers": ["wiki/index.md", "wiki/log.md"],
    }


class IngestApplyCliTests(unittest.TestCase):
    def test_file_and_stdin_dry_run_match_and_write_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = make_vault(base)
            init = run_cli("state", "init", "--root", str(vault), "--confirm")
            self.assertEqual(init.returncode, 0, init.stderr)
            source = write(base / "source.md", "source")
            payload_text = json.dumps(make_ingest_payload(source))
            payload_path = write(base / "payload.json", payload_text)

            from_file = run_cli(
                "ingest", "apply", "--root", str(vault),
                "--payload", str(payload_path), "--format", "json",
            )
            from_stdin = run_cli(
                "ingest", "apply", "--root", str(vault),
                "--payload", "-", "--format", "json", input_text=payload_text,
            )

            target = vault / "00-知识库中控/wiki/sources/example.md"
            self.assertFalse(target.exists())

        self.assertEqual(from_file.returncode, 1, from_file.stderr)
        self.assertEqual(from_stdin.returncode, 1, from_stdin.stderr)
        file_json = json.loads(from_file.stdout)
        stdin_json = json.loads(from_stdin.stdout)
        self.assertEqual(file_json["plan_checksum"], stdin_json["plan_checksum"])
        self.assertEqual(file_json["status"], "confirmation-required")
        self.assertTrue(file_json["confirmable"])
        self.assertNotIn("SECRET-GENERATED-BODY", from_file.stdout)

    def test_confirm_requires_checksum_then_applies_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = make_vault(base)
            self.assertEqual(
                run_cli("state", "init", "--root", str(vault), "--confirm").returncode,
                0,
            )
            source = write(base / "source.md", "source")
            payload_path = write(base / "payload.json", json.dumps(make_ingest_payload(source)))
            preview = run_cli(
                "ingest", "apply", "--root", str(vault), "--payload", str(payload_path)
            )
            plan_checksum = json.loads(preview.stdout)["plan_checksum"]

            missing = run_cli(
                "ingest", "apply", "--root", str(vault),
                "--payload", str(payload_path), "--confirm",
            )
            applied = run_cli(
                "ingest", "apply", "--root", str(vault),
                "--payload", str(payload_path), "--confirm",
                "--plan-checksum", plan_checksum,
            )

            target = vault / "00-知识库中控/wiki/sources/example.md"
            target_text = target.read_text(encoding="utf-8")

        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["error"]["check"], "missing-plan-checksum")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(json.loads(applied.stdout)["status"], "completed")
        self.assertIn("SECRET-GENERATED-BODY", target_text)
        self.assertNotIn("SECRET-GENERATED-BODY", applied.stdout)


class PageAndProjectionCliTests(unittest.TestCase):
    def test_page_apply_then_projection_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = make_vault(base)
            self.assertEqual(run_cli("state", "init", "--root", str(vault), "--confirm").returncode, 0)
            page_payload = {
                "schema_version": 1,
                "pages": [{
                    "role": "derived",
                    "page_type": "topic",
                    "path": "wiki/topics/cli.md",
                    "managed_body": "# CLI topic",
                    "expected_managed_checksum": None,
                    "takeover": False,
                }],
                "projection_takeovers": ["wiki/index.md", "wiki/log.md"],
            }
            page_path = write(base / "page.json", json.dumps(page_payload))
            preview = run_cli("page", "apply", "--root", str(vault), "--payload", str(page_path))
            applied = run_cli(
                "page", "apply", "--root", str(vault), "--payload", str(page_path),
                "--confirm", "--plan-checksum", json.loads(preview.stdout)["plan_checksum"],
            )
            rebuild_payload = write(
                base / "rebuild.json",
                '{"schema_version":1,"projection_takeovers":[]}',
            )
            rebuild_preview = run_cli(
                "projection", "rebuild", "--root", str(vault), "--payload", str(rebuild_payload)
            )
            rebuilt = run_cli(
                "projection", "rebuild", "--root", str(vault), "--payload", str(rebuild_payload),
                "--confirm", "--plan-checksum", json.loads(rebuild_preview.stdout)["plan_checksum"],
            )

        self.assertEqual(preview.returncode, 1, preview.stderr)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(rebuild_preview.returncode, 1, rebuild_preview.stderr)
        self.assertTrue(all(item["action"] == "unchanged" for item in json.loads(rebuild_preview.stdout)["projections"]))
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)


if __name__ == "__main__":
    unittest.main()
