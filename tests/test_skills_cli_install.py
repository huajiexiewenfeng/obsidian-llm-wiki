import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSUMERS = (
    "obsidian-wiki-doctor",
    "obsidian-wiki-ingest",
    "obsidian-wiki-init",
    "obsidian-wiki-maintain",
    "obsidian-wiki-query",
)


@unittest.skipUnless(
    os.environ.get("RUN_SKILLS_CLI_INTEGRATION") == "1",
    "set RUN_SKILLS_CLI_INTEGRATION=1 to run Skills CLI integration",
)
class SkillsCliInstallTests(unittest.TestCase):
    def test_project_copy_install_contains_and_runs_runtime(self):
        executable = shutil.which("npx.cmd" if os.name == "nt" else "npx")
        self.assertIsNotNone(executable, "npx is required")

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "install-project"
            home = base / "home"
            project.mkdir()
            home.mkdir()
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "USERPROFILE": str(home),
                    "DISABLE_TELEMETRY": "1",
                    "DO_NOT_TRACK": "1",
                }
            )
            offline_modules = os.environ.get("SKILLS_CLI_OFFLINE_NODE_MODULES")
            if offline_modules:
                shutil.copytree(offline_modules, project / "node_modules")
                package_args = ["--offline", "skills"]
            else:
                package_args = ["--yes", "skills@1.5.14"]
            install = subprocess.run(
                [
                    executable,
                    *package_args,
                    "add",
                    str(REPO_ROOT),
                    "--skill",
                    "*",
                    "--agent",
                    "codex",
                    "--copy",
                    "--yes",
                ],
                cwd=project,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=180,
            )
            output = install.stdout + install.stderr
            self.assertEqual(install.returncode, 0, output)

            matches = list(project.rglob("obsidian-wiki-runtime/scripts/llm_wiki.py"))
            self.assertTrue(matches, output)
            runtime = matches[0]
            skills_root = runtime.parents[2]
            for name in CONSUMERS:
                self.assertTrue((skills_root / name / "SKILL.md").is_file(), name)

            vault = base / "Sample Vault"
            wiki = vault / "00-知识库中控" / "wiki"
            wiki.mkdir(parents=True)
            (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
            (wiki / "log.md").write_text("# Log\n", encoding="utf-8")

            resolved = subprocess.run(
                [
                    sys.executable,
                    str(runtime),
                    "root",
                    "resolve",
                    "--root",
                    str(vault),
                    "--format",
                    "json",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            self.assertEqual(json.loads(resolved.stdout)["vault_root"], str(vault.resolve()))

            report = subprocess.run(
                [
                    sys.executable,
                    str(runtime),
                    "doctor",
                    "report",
                    "--root",
                    str(vault),
                    "--format",
                    "json",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("score", json.loads(report.stdout))


if __name__ == "__main__":
    unittest.main()
