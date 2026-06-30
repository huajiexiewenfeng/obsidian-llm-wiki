#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_CONTROL_CENTER = Path(r"C:\Users\admin\Documents\Obsidian Vault\00-知识库中控")
ENV_ROOT = "OBSIDIAN_LLM_WIKI_ROOT"


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    path: str
    message: str
    line: int | None = None
    hint: str | None = None


@dataclass(frozen=True)
class ResolvedRoot:
    control_center: Path | None
    wiki_root: Path | None
    input_root: Path | None
    source: str
    error: Finding | None = None


@dataclass(frozen=True)
class WikiState:
    init_done: bool
    onboarding_done: bool
    inventory_done: bool
    ingest_started: bool
    generated_pages_exist: bool


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def is_control_center(path: Path) -> bool:
    return path.is_dir() and is_direct_wiki_root(path / "wiki")


def is_direct_wiki_root(path: Path) -> bool:
    return path.is_dir() and (path / "index.md").is_file()


def invalid_root(path: Path, source: str) -> ResolvedRoot:
    return ResolvedRoot(
        control_center=None,
        wiki_root=None,
        input_root=path,
        source=source,
        error=Finding(
            check="invalid-root",
            severity="ERROR",
            path=str(path),
            message=f"{source} root does not point to an Obsidian LLM Wiki control center or wiki root.",
            hint=f"Pass a control-center directory, a wiki directory, or set {ENV_ROOT}.",
        ),
    )


def resolve_explicit_root(root_value: str, source: str = "argument") -> ResolvedRoot:
    input_root = Path(root_value).expanduser()
    try:
        resolved = input_root.resolve()
    except OSError:
        return invalid_root(input_root, source)

    if is_control_center(resolved):
        return ResolvedRoot(
            control_center=resolved,
            wiki_root=(resolved / "wiki").resolve(),
            input_root=resolved,
            source=source,
        )
    if is_direct_wiki_root(resolved):
        control_center = resolved.parent if resolved.name == "wiki" else None
        return ResolvedRoot(
            control_center=control_center.resolve() if control_center else None,
            wiki_root=resolved,
            input_root=resolved,
            source=source,
        )
    return invalid_root(resolved, source)


def resolve_root(root_arg: str | None) -> ResolvedRoot:
    if root_arg:
        return resolve_explicit_root(root_arg, "argument")

    env_root = os.environ.get(ENV_ROOT)
    if env_root:
        return resolve_explicit_root(env_root, "environment")

    if is_control_center(DEFAULT_CONTROL_CENTER):
        resolved_default = DEFAULT_CONTROL_CENTER.resolve()
        return ResolvedRoot(
            control_center=resolved_default,
            wiki_root=(resolved_default / "wiki").resolve(),
            input_root=resolved_default,
            source="default",
        )

    return ResolvedRoot(
        control_center=None,
        wiki_root=None,
        input_root=DEFAULT_CONTROL_CENTER,
        source="default",
        error=Finding(
            check="missing-control-center",
            severity="ERROR",
            path=str(DEFAULT_CONTROL_CENTER),
            message="Default Obsidian LLM Wiki control center was not found.",
            hint=f"Pass --root or set {ENV_ROOT}.",
        ),
    )


def parse_markdown_table_rows(text: str) -> list[dict[str, str]]:
    table_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return []

    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    separator_cells = [cell.strip() for cell in table_lines[1].strip("|").split("|")]
    separator_re = re.compile(r"^:?-{3,}:?$")
    if len(separator_cells) != len(headers) or not all(separator_re.match(cell) for cell in separator_cells):
        return []

    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) == len(headers):
            rows.append(dict(zip(headers, values)))
    return rows


def build_state(root: ResolvedRoot) -> WikiState:
    wiki_root = root.wiki_root
    if wiki_root is None:
        return WikiState(False, False, False, False, False)

    init_done = (wiki_root / "index.md").is_file()
    onboarding_done = any((wiki_root / name).is_file() for name in ("onboarding.md", "README.md", "readme.md"))
    inventory_done = any((wiki_root / name).is_file() for name in ("inventory.md", "sources.md", "source-inventory.md"))
    ingest_started = (wiki_root / "sources").is_dir() or (wiki_root / "log.md").is_file()
    generated_pages_exist = (wiki_root / "topics").is_dir() or any(wiki_root.glob("*.md"))
    return WikiState(init_done, onboarding_done, inventory_done, ingest_started, generated_pages_exist)


def run_checks(root: ResolvedRoot, state: WikiState) -> list[Finding]:
    if root.error is not None:
        return [root.error]

    findings: list[Finding] = []
    wiki_root = root.wiki_root
    if wiki_root is None:
        return [
            Finding(
                check="missing-wiki-root",
                severity="ERROR",
                path="",
                message="Wiki root could not be resolved.",
            )
        ]

    if not state.init_done:
        findings.append(
            Finding(
                check="missing-index",
                severity="ERROR",
                path=str(wiki_root / "index.md"),
                message="Wiki index.md is missing.",
                hint="Initialize the Obsidian LLM Wiki before running doctor checks.",
            )
        )
    return findings


def root_to_dict(root: ResolvedRoot) -> dict[str, object]:
    payload: dict[str, object] = {
        "control_center": str(root.control_center) if root.control_center else None,
        "wiki_root": str(root.wiki_root) if root.wiki_root else None,
        "input_root": str(root.input_root) if root.input_root else None,
        "source": root.source,
    }
    if root.error is not None:
        payload["error"] = asdict(root.error)
    return payload


def calculate_score(state: WikiState, findings: list[Finding]) -> dict[str, object]:
    root_ok = not any(finding.severity == "ERROR" and finding.check in {"invalid-root", "missing-control-center"} for finding in findings)
    dimensions = {
        "root": 25 if root_ok else 0,
        "initialization": 25 if state.init_done else 0,
        "inventory": 20 if state.inventory_done else 0,
        "ingest": 15 if state.ingest_started else 0,
        "generated_pages": 15 if state.generated_pages_exist else 0,
    }
    next_steps = [finding.hint or finding.message for finding in findings if finding.severity == "ERROR"]
    if not next_steps and not state.inventory_done:
        next_steps.append("Add or refresh a source inventory.")
    return {
        "score_version": "0.1",
        "score": sum(dimensions.values()),
        "dimensions": dimensions,
        "signals": asdict(state),
        "next_steps": next_steps,
    }


def emit_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def emit_findings_text(findings: list[Finding]) -> None:
    if not findings:
        print("OK")
        return
    for finding in findings:
        location = finding.path or "<unknown>"
        print(f"{finding.severity}: {finding.check}: {location}: {finding.message}")


def should_fail(findings: list[Finding], fail_on: str) -> bool:
    severities = {finding.severity.upper() for finding in findings}
    if fail_on == "error":
        return "ERROR" in severities
    if fail_on == "warning":
        return bool(severities & {"ERROR", "WARNING"})
    return bool(findings)


def run_validate(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = build_state(root)
    findings = run_checks(root, state)
    if args.format == "json":
        emit_json([asdict(finding) for finding in findings])
    else:
        emit_findings_text(findings)
    return 1 if should_fail(findings, args.fail_on) else 0


def run_score(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = build_state(root)
    findings = run_checks(root, state)
    payload = {"root": root_to_dict(root), **calculate_score(state, findings)}
    if args.format == "json":
        emit_json(payload)
    else:
        print(payload["score"])
    return 1 if any(finding.severity == "ERROR" for finding in findings) else 0


def run_report(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = build_state(root)
    findings = run_checks(root, state)
    score = calculate_score(state, findings)
    payload = {
        "root": root_to_dict(root),
        "state": asdict(state),
        "findings": [asdict(finding) for finding in findings],
        "score": score,
    }
    if args.format == "json":
        emit_json(payload)
    else:
        print(f"Root: {root.wiki_root or root.input_root}")
        emit_findings_text(findings)
        print(f"Score: {score['score']}")
    return 1 if any(finding.severity == "ERROR" for finding in findings) else 0


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="Control-center or wiki root path.")
    parser.add_argument("--format", choices=("text", "json"), default="text")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and score an Obsidian LLM Wiki.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Run doctor checks.")
    add_common_options(validate)
    validate.add_argument("--fail-on", choices=("error", "warning", "any"), default="error")
    validate.set_defaults(func=run_validate)

    score = subparsers.add_parser("score", help="Calculate wiki health score.")
    add_common_options(score)
    score.set_defaults(func=run_score)

    report = subparsers.add_parser("report", help="Print root, state, findings, and score.")
    add_common_options(report)
    report.set_defaults(func=run_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
