import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "llm_wiki.py"
CONTROL_CENTER_NAME = "00-知识库中控"


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_vault(base: Path) -> tuple[Path, Path]:
    vault = base / "Vault"
    control = vault / CONTROL_CENTER_NAME
    write(control / "wiki/index.md", "# Index\n")
    write(control / "wiki/log.md", "# Log\n")
    return vault, control


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


class InventoryCliTests(unittest.TestCase):
    def initialize_inventory(self, vault: Path) -> dict[str, object]:
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
        return json.loads(confirmed.stdout)

    def test_inspect_reports_missing_baseline_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control = make_vault(Path(tmp))
            write(vault / "notes/new.md")
            before = sorted(path.relative_to(vault).as_posix() for path in vault.rglob("*") if path.is_file())

            result = run_cli("inventory", "inspect", "--root", str(vault), "--format", "json")

            after = sorted(path.relative_to(vault).as_posix() for path in vault.rglob("*") if path.is_file())
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["findings"][0]["check"], "missing-ingest-inventory")
        self.assertEqual(after, before)
        self.assertFalse((control / ".meta/inventory.json").exists())

    def test_initialize_preview_then_confirm_records_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control = make_vault(Path(tmp))
            state = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(state.returncode, 0, state.stderr)
            write(vault / "notes/new.md", "new")

            preview = run_cli("inventory", "initialize", "--root", str(vault), "--format", "json")
            self.assertEqual(preview.returncode, 1, preview.stderr)
            plan = json.loads(preview.stdout)
            self.assertTrue(plan["confirmation_required"])
            self.assertTrue(plan["confirmable"])
            self.assertEqual(plan["candidate_count"], 1)
            self.assertFalse((control / ".meta/inventory.json").exists())

            missing_checksum = run_cli(
                "inventory", "initialize", "--root", str(vault), "--confirm", "--format", "json"
            )
            self.assertEqual(missing_checksum.returncode, 2)
            self.assertEqual(json.loads(missing_checksum.stdout)["error"]["check"], "missing-plan-checksum")

            confirmed = run_cli(
                "inventory", "initialize", "--root", str(vault), "--confirm",
                "--plan-checksum", plan["plan_checksum"], "--format", "json",
            )
            self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
            result = json.loads(confirmed.stdout)
            self.assertEqual(result["status"], "completed")
            baseline = json.loads((control / ".meta/inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(baseline["documents"]["notes/new.md"]["disposition"], "discovered")
            operations = json.loads((control / ".meta/operations.json").read_text(encoding="utf-8"))["records"]
            operation = operations[result["operation_id"]]
            self.assertEqual(operation["kind"], "inventory-initialize")
            self.assertEqual(operation["status"], "completed")
            events = [
                json.loads(line)
                for line in (control / ".meta/change-log.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-1]["kind"], "inventory-initialize")
            self.assertEqual(events[-1]["result"], "completed")

            repeated = run_cli(
                "inventory", "initialize", "--root", str(vault), "--confirm",
                "--plan-checksum", plan["plan_checksum"], "--format", "json",
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            repeated_payload = json.loads(repeated.stdout)
            self.assertTrue(repeated_payload["idempotent"])
            self.assertEqual(repeated_payload["operation_id"], result["operation_id"])
            repeated_events = [
                json.loads(line)
                for line in (control / ".meta/change-log.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(repeated_events, events)

            (control / ".meta/change-log.jsonl").write_text(
                "\n".join(
                    json.dumps(event, ensure_ascii=False, sort_keys=True)
                    for event in events
                    if event["kind"] != "inventory-initialize"
                ) + "\n",
                encoding="utf-8",
            )
            doctor = run_cli(
                "doctor", "validate", "--root", str(vault),
                "--format", "json", "--fail-on", "none",
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            missing_events = [
                finding
                for finding in json.loads(doctor.stdout)
                if finding["check"] == "missing-completion-event"
            ]
            self.assertTrue(
                any(result["operation_id"] in finding["message"] for finding in missing_events)
            )

    def test_initialize_rejects_plan_after_vault_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, control = make_vault(Path(tmp))
            state = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(state.returncode, 0, state.stderr)
            source = vault / "notes/new.md"
            write(source, "before")
            preview = run_cli("inventory", "initialize", "--root", str(vault), "--format", "json")
            self.assertEqual(preview.returncode, 1, preview.stderr)
            plan_checksum = json.loads(preview.stdout)["plan_checksum"]
            write(source, "after and larger")

            confirmed = run_cli(
                "inventory", "initialize", "--root", str(vault), "--confirm",
                "--plan-checksum", plan_checksum, "--format", "json",
            )

            self.assertEqual(confirmed.returncode, 2)
            self.assertEqual(json.loads(confirmed.stdout)["error"]["check"], "inventory-conflict")
            self.assertFalse((control / ".meta/inventory.json").exists())

    def test_initialize_accepts_safe_scope_overrides_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, _ = make_vault(Path(tmp))
            state = run_cli("state", "init", "--root", str(vault), "--confirm", "--format", "json")
            self.assertEqual(state.returncode, 0, state.stderr)
            write(vault / "notes/new.md")

            safe = run_cli(
                "inventory", "initialize", "--root", str(vault),
                "--exclude", "notes/**", "--format", "json",
            )
            unsafe = run_cli(
                "inventory", "initialize", "--root", str(vault),
                "--include", "../outside/**", "--format", "json",
            )

        self.assertEqual(safe.returncode, 1, safe.stderr)
        self.assertEqual(json.loads(safe.stdout)["candidate_count"], 0)
        self.assertEqual(unsafe.returncode, 2)
        self.assertEqual(json.loads(unsafe.stdout)["error"]["check"], "inventory-conflict")

    def test_ignore_unignore_and_configure_are_confirmed_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault, _ = make_vault(Path(tmp))
            write(vault / "notes/a.md", "a")
            write(vault / "notes/b.md", "b")
            self.initialize_inventory(vault)

            ignore_preview = run_cli(
                "inventory", "ignore", "--root", str(vault),
                "--path", "notes/a.md", "--reason", "user-approved", "--format", "json",
            )
            self.assertEqual(ignore_preview.returncode, 1, ignore_preview.stderr)
            ignore_plan = json.loads(ignore_preview.stdout)
            self.assertEqual(ignore_plan["affected_count"], 1)
            ignore_confirm = run_cli(
                "inventory", "ignore", "--root", str(vault),
                "--path", "notes/a.md", "--reason", "user-approved", "--confirm",
                "--plan-checksum", ignore_plan["plan_checksum"], "--format", "json",
            )
            self.assertEqual(ignore_confirm.returncode, 0, ignore_confirm.stderr)
            after_ignore = run_cli("inventory", "inspect", "--root", str(vault), "--format", "json")
            ignored_paths = {
                item["path"] for item in json.loads(after_ignore.stdout)["findings"]
                if item["check"] == "uningested-source"
            }
            self.assertEqual(ignored_paths, {"notes/b.md"})

            unignore_preview = run_cli(
                "inventory", "unignore", "--root", str(vault),
                "--path", "notes/a.md", "--format", "json",
            )
            self.assertEqual(unignore_preview.returncode, 1, unignore_preview.stderr)
            unignore_plan = json.loads(unignore_preview.stdout)
            unignore_confirm = run_cli(
                "inventory", "unignore", "--root", str(vault),
                "--path", "notes/a.md", "--confirm",
                "--plan-checksum", unignore_plan["plan_checksum"], "--format", "json",
            )
            self.assertEqual(unignore_confirm.returncode, 0, unignore_confirm.stderr)

            configure_preview = run_cli(
                "inventory", "configure", "--root", str(vault),
                "--exclude", "notes/b.md", "--format", "json",
            )
            self.assertEqual(configure_preview.returncode, 1, configure_preview.stderr)
            configure_plan = json.loads(configure_preview.stdout)
            configure_confirm = run_cli(
                "inventory", "configure", "--root", str(vault),
                "--exclude", "notes/b.md", "--confirm",
                "--plan-checksum", configure_plan["plan_checksum"], "--format", "json",
            )
            self.assertEqual(configure_confirm.returncode, 0, configure_confirm.stderr)
            after_configure = run_cli(
                "inventory", "inspect", "--root", str(vault), "--format", "json"
            )
            remaining_paths = {
                item["path"] for item in json.loads(after_configure.stdout)["findings"]
                if item["check"] == "uningested-source"
            }
            self.assertEqual(remaining_paths, {"notes/a.md"})


if __name__ == "__main__":
    unittest.main()
