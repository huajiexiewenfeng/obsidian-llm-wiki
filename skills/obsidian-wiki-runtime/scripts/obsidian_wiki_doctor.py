#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from llm_wiki_core.doctor_state import ConsistencyIssue, inspect_state_consistency
from llm_wiki_core.root import ResolvedRoot, RootIssue, resolve_root

MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
SENSITIVE_PATTERNS = [
    ("password", re.compile(r"(?i)\bpassword\s*[:=]")),
    ("token", re.compile(r"(?i)\btoken\s*[:=]")),
    ("secret", re.compile(r"(?i)\bsecret\s*[:=]")),
    ("ak-sk", re.compile(r"(?i)\bAK/SK\b|access[_-]?key|secret[_-]?key")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("cookie", re.compile(r"(?i)\bcookie\s*[:=]")),
    ("credentialed-rtsp", re.compile(r"(?i)rtsp://[^\s/@:]+:[^\s/@]+@")),
    ("connection-string", re.compile(r"(?i)(jdbc:|mongodb://|postgres://|mysql://)")),
    ("internal-endpoint", re.compile(r"(?i)https?://(?:10\.|172\.(?:1[6-9]|2\d|3[0-1])\.|192\.168\.|localhost|127\.0\.0\.1)")),
]



@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    path: str
    message: str
    line: int | None = None
    hint: str | None = None


def finding_from_root_issue(issue: RootIssue) -> Finding:
    return Finding(
        check=issue.check,
        severity=issue.severity,
        path=issue.path,
        message=issue.message,
        hint=issue.hint,
    )


def finding_from_consistency_issue(issue: ConsistencyIssue) -> Finding:
    return Finding(
        check=issue.check,
        severity=issue.severity,
        path=issue.relative_path,
        message=issue.message,
        line=issue.line,
        hint=issue.recovery_hint,
    )


@dataclass(frozen=True)
class WikiState:
    init_done: bool
    onboarding_done: bool
    inventory_done: bool
    ingest_started: bool
    generated_pages_exist: bool


@dataclass(frozen=True)
class ScoreDimension:
    name: str
    weight: int
    score: int | None
    applicability: str
    message: str


@dataclass(frozen=True)
class ScoreReport:
    score_version: int
    score: int
    level: str
    dimensions: list[ScoreDimension]
    signals: dict[str, object]
    next_steps: list[str]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def canonical_table_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def parse_markdown_table_rows(text: str) -> list[dict[str, str]]:
    table_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return []

    headers = [canonical_table_header(cell) for cell in table_lines[0].strip("|").split("|")]
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



def iter_markdown_files(wiki_root: Path) -> list[Path]:
    if not wiki_root.is_dir():
        return []
    return sorted(path for path in wiki_root.rglob("*.md") if path.is_file())


def repo_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def redact_sensitive_text(value: str) -> str:
    redacted = re.sub(
        r"(?i)\b(password|token|secret|access[_-]?key|secret[_-]?key|cookie)\s*([:=_-])\s*[^\\/\s)]+",
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        value,
    )
    return re.sub(
        r"(?i)(?<![A-Za-z0-9])(?:ak|sk)-[A-Za-z0-9_-]{16,}",
        "<redacted>",
        redacted,
    )


def safe_text(value: object | None) -> str | None:
    if value is None:
        return None
    return redact_sensitive_text(str(value))


def safe_finding(finding: Finding) -> Finding:
    return Finding(
        check=finding.check,
        severity=finding.severity,
        path=safe_text(finding.path) or "",
        message=safe_text(finding.message) or "",
        line=finding.line,
        hint=safe_text(finding.hint),
    )


def safe_finding_dict(finding: Finding) -> dict[str, object]:
    return asdict(safe_finding(finding))

def markdown_link_target(target: str) -> str:
    target = target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1:target.index(">")].strip()
    else:
        title_match = re.match(r"([^\s]+)(?:\s+['\"(].*)?$", target)
        if title_match:
            target = title_match.group(1).strip()
    return target.split("#", 1)[0].strip()


def obsidian_link_target(target: str) -> str:
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    return target


def resolve_link_candidate(source: Path, target: str) -> Path | None:
    if not target or target.startswith("#"):
        return None
    if re.match(r"(?i)^[a-z][a-z0-9+.-]*:", target) or target.startswith("//"):
        return None

    candidate = (source.parent / target).resolve()
    candidates = [candidate]
    if candidate.suffix == "":
        candidates.append(candidate.with_suffix(".md"))
    candidates.append(candidate / "index.md")

    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def resolve_markdown_link(source: Path, target: str) -> Path | None:
    return resolve_link_candidate(source, markdown_link_target(target))


def wikilink_candidate_paths(base: Path) -> list[Path]:
    candidates = [base]
    if not base.name.lower().endswith(".md"):
        candidates.append(Path(f"{base}.md"))
    candidates.append(base / "index.md")
    return candidates


def resolve_wikilink_base(base: Path) -> Path:
    candidates = wikilink_candidate_paths(base.resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def build_markdown_name_index(root: Path | None) -> dict[str, tuple[Path, ...]]:
    if root is None or not root.is_dir():
        return {}
    grouped: dict[str, list[Path]] = {}
    for path in iter_markdown_files(root):
        grouped.setdefault(path.name.casefold(), []).append(path.resolve())
    return {name: tuple(sorted(paths)) for name, paths in grouped.items()}


def resolve_wikilink(
    source: Path,
    target: str,
    vault_root: Path | None = None,
    wiki_root: Path | None = None,
    control_center: Path | None = None,
    basename_index: dict[str, tuple[Path, ...]] | None = None,
) -> Path | None:
    link_target = obsidian_link_target(target)
    if not link_target or link_target.startswith("#"):
        return None
    if re.match(r"(?i)^[a-z][a-z0-9+.-]*:", link_target) or link_target.startswith("//"):
        return None

    normalized_target = link_target.replace("\\", "/")
    target_path = Path(normalized_target)
    explicit_relative = normalized_target.startswith("./") or normalized_target.startswith("../")
    has_directory = "/" in normalized_target

    if explicit_relative:
        return resolve_wikilink_base(source.parent / target_path)

    if has_directory:
        roots: list[Path] = []
        for root in (control_center, vault_root, wiki_root):
            if root is not None and root not in roots:
                roots.append(root)
        unresolved: Path | None = None
        for root in roots:
            candidate = resolve_wikilink_base(root / target_path)
            if candidate.exists():
                return candidate
            if unresolved is None:
                unresolved = candidate
        return unresolved or resolve_wikilink_base(source.parent / target_path)

    source_candidate = resolve_wikilink_base(source.parent / target_path)
    if source_candidate.exists():
        return source_candidate

    expected_name = target_path.name
    if not expected_name.lower().endswith(".md"):
        expected_name = f"{expected_name}.md"
    lookup = basename_index if basename_index is not None else build_markdown_name_index(vault_root or wiki_root)
    matches = lookup.get(expected_name.casefold(), ())
    exact_matches = tuple(path for path in matches if path.name == expected_name)
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(matches) == 1:
        return matches[0]
    return source_candidate


def table_dicts(text: str) -> list[dict[str, str]]:
    return parse_markdown_table_rows(text)


def check_required_structure(root: ResolvedRoot, state: WikiState) -> list[Finding]:
    if root.wiki_root is None:
        return []

    findings: list[Finding] = []
    index = root.wiki_root / "index.md"
    log = root.wiki_root / "log.md"
    index_exists = index.is_file()
    log_exists = log.is_file()
    if not index_exists:
        findings.append(Finding(
            check="missing-wiki-index",
            severity="ERROR",
            path=repo_path(root.wiki_root, index),
            message="wiki/index.md is missing.",
            hint="Create wiki/index.md or rerun wiki initialization.",
        ))
    if not log_exists:
        findings.append(Finding(
            check="missing-wiki-log",
            severity="ERROR",
            path=repo_path(root.wiki_root, log),
            message="wiki/log.md is missing.",
            hint="Create wiki/log.md or rerun wiki initialization.",
        ))

    if state.init_done and root.control_center is not None:
        roadmap = root.control_center / "00.LLM Wiki \u5efa\u8bbe\u8def\u7ebf\u56fe.md"
        knowledge_map = root.control_center / "00.\u77e5\u8bc6\u5e93\u5730\u56fe.md"
        if not roadmap.is_file():
            findings.append(Finding(
                check="missing-roadmap",
                severity="WARN",
                path=repo_path(root.control_center, roadmap),
                message="Control-center roadmap is missing.",
            ))
        if not knowledge_map.is_file():
            findings.append(Finding(
                check="missing-knowledge-map",
                severity="WARN",
                path=repo_path(root.control_center, knowledge_map),
                message="Control-center knowledge map is missing.",
            ))
    return findings


def check_links(root: ResolvedRoot) -> list[Finding]:
    if root.wiki_root is None:
        return []

    basename_index = build_markdown_name_index(root.vault_root or root.wiki_root)
    findings: list[Finding] = []
    for markdown_file in iter_markdown_files(root.wiki_root):
        text = read_text(markdown_file)
        link_targets = [(match.group(1), resolve_markdown_link(markdown_file, match.group(1))) for match in MARKDOWN_LINK_RE.finditer(text)]
        link_targets.extend(
            (
                match.group(1),
                resolve_wikilink(
                    markdown_file,
                    match.group(1),
                    vault_root=root.vault_root,
                    wiki_root=root.wiki_root,
                    control_center=root.control_center,
                    basename_index=basename_index,
                ),
            )
            for match in WIKILINK_RE.finditer(text)
        )
        for target, resolved in link_targets:
            if resolved is None or resolved.exists():
                continue
            is_root_index = markdown_file == root.wiki_root / "index.md"
            check = "broken-index-link" if is_root_index else "broken-internal-link"
            severity = "ERROR" if is_root_index else "WARN"
            findings.append(Finding(
                check=check,
                severity=severity,
                path=repo_path(root.wiki_root, markdown_file),
                message=f"Markdown link target does not exist: {target}",
            ))
    return findings


def check_ingest(root: ResolvedRoot, state: WikiState) -> list[Finding]:
    if not state.ingest_started or root.control_center is None or root.wiki_root is None:
        return []

    ingest_index = root.control_center / "ingest" / "index.md"
    if not ingest_index.is_file():
        return []

    findings: list[Finding] = []
    for row in table_dicts(read_text(ingest_index)):
        status = row.get("status", "").strip().lower()
        proxy = (row.get("proxy") or row.get("source_proxy") or "").strip()
        if status == "processed" and proxy and not (root.wiki_root / proxy).is_file():
            findings.append(Finding(
                check="missing-source-proxy",
                severity="ERROR",
                path=repo_path(root.control_center, ingest_index),
                message=f"Processed ingest row references missing source proxy: {proxy}",
            ))
    return findings


def check_safety(root: ResolvedRoot) -> list[Finding]:
    if root.wiki_root is None:
        return []

    findings: list[Finding] = []
    for markdown_file in iter_markdown_files(root.wiki_root):
        for line_number, line in enumerate(read_text(markdown_file).splitlines(), start=1):
            for category, pattern in SENSITIVE_PATTERNS:
                if pattern.search(line):
                    redacted_path = redact_sensitive_text(repo_path(root.wiki_root, markdown_file))
                    findings.append(Finding(
                        check="sensitive-pattern",
                        severity="ERROR",
                        path=redacted_path,
                        line=line_number,
                        message=f"Sensitive pattern '{category}' found in {redacted_path} at line {line_number}.",
                    ))
                    break
    return findings


def build_state(root: ResolvedRoot) -> WikiState:
    wiki_root = root.wiki_root
    control_center = root.control_center
    if wiki_root is None:
        return WikiState(False, False, False, False, False)

    init_done = (wiki_root / "index.md").is_file() and (wiki_root / "log.md").is_file()
    onboarding_done = control_center is not None and (control_center / "00.LLM Wiki 建设路线图.md").is_file()
    inventory_done = control_center is not None and (control_center / "00.知识库地图.md").is_file()

    ingest_started = False
    if control_center is not None:
        ingest_index = control_center / "ingest" / "index.md"
        if ingest_index.is_file():
            ingest_started = bool(table_dicts(read_text(ingest_index)))

    generated_pages_exist = any(wiki_root.rglob("*.md"))
    return WikiState(init_done, onboarding_done, inventory_done, ingest_started, generated_pages_exist)


def run_checks(root: ResolvedRoot, state: WikiState) -> list[Finding]:
    if root.error is not None:
        return [finding_from_root_issue(root.error)]

    findings: list[Finding] = []
    findings.extend(check_required_structure(root, state))
    findings.extend(check_links(root))
    findings.extend(check_ingest(root, state))
    findings.extend(check_safety(root))
    if root.control_center is not None:
        findings.extend(
            finding_from_consistency_issue(issue)
            for issue in inspect_state_consistency(root.control_center)
        )
    return findings


def root_to_dict(root: ResolvedRoot) -> dict[str, object]:
    payload: dict[str, object] = {
        "control_center": safe_text(root.control_center) if root.control_center else None,
        "wiki_root": safe_text(root.wiki_root) if root.wiki_root else None,
        "input_root": safe_text(root.input_root) if root.input_root else None,
        "source": root.source,
    }
    if root.error is not None:
        payload["error"] = safe_finding_dict(finding_from_root_issue(root.error))
    return payload

def score_level(score: int) -> str:
    if score >= 90:
        return "healthy"
    if score >= 70:
        return "usable"
    if score >= 50:
        return "needs-attention"
    return "at-risk"


def has_error(findings: list[Finding], *checks: str) -> bool:
    wanted = set(checks)
    return any(finding.severity == "ERROR" and finding.check in wanted for finding in findings)


def has_warning(findings: list[Finding], *checks: str) -> bool:
    wanted = set(checks)
    return any(finding.severity == "WARN" and finding.check in wanted for finding in findings)


def build_score_report(root: ResolvedRoot, state: WikiState, findings: list[Finding]) -> ScoreReport:
    dimensions: list[ScoreDimension] = []

    root_score = 0 if root.error is not None else 20
    dimensions.append(ScoreDimension(
        name="Control center resolution",
        weight=20,
        score=root_score,
        applicability="applicable",
        message="Root could not be resolved." if root.error is not None else "Root resolves to a wiki control center.",
    ))

    if root.error is not None:
        blocked_message = "Not evaluated because the root did not resolve."
        dimensions.extend([
            ScoreDimension(
                name="Navigation and discoverability",
                weight=25,
                score=None,
                applicability="not-applicable",
                message=blocked_message,
            ),
            ScoreDimension(
                name="Ingest traceability",
                weight=20,
                score=None,
                applicability="not-applicable",
                message=blocked_message,
            ),
            ScoreDimension(
                name="Safety hygiene",
                weight=20,
                score=None,
                applicability="not-applicable",
                message=blocked_message,
            ),
            ScoreDimension(
                name="Query readiness",
                weight=15,
                score=None,
                applicability="not-applicable",
                message=blocked_message,
            ),
        ])
    else:
        navigation_error = has_error(findings, "missing-wiki-index", "missing-wiki-log", "broken-index-link")
        navigation_warning = has_warning(findings, "missing-roadmap", "missing-knowledge-map", "broken-internal-link")
        if navigation_error:
            navigation_score = 0
            navigation_message = "Index, log, or root navigation has blocking errors."
        elif navigation_warning:
            navigation_score = 15
            navigation_message = "Navigation works but discoverability warnings remain."
        else:
            navigation_score = 25
            navigation_message = "Index, log, and internal navigation are discoverable."
        dimensions.append(ScoreDimension(
            name="Navigation and discoverability",
            weight=25,
            score=navigation_score,
            applicability="applicable",
            message=navigation_message,
        ))

        if state.ingest_started:
            ingest_error = has_error(findings, "missing-source-proxy")
            dimensions.append(ScoreDimension(
                name="Ingest traceability",
                weight=20,
                score=0 if ingest_error else 20,
                applicability="applicable",
                message="Processed ingest rows have missing source proxies." if ingest_error else "Ingest rows are traceable to source proxies.",
            ))
        else:
            dimensions.append(ScoreDimension(
                name="Ingest traceability",
                weight=20,
                score=None,
                applicability="not-applicable",
                message="No ingest rows are present yet.",
            ))

        safety_error = has_error(findings, "sensitive-pattern")
        dimensions.append(ScoreDimension(
            name="Safety hygiene",
            weight=20,
            score=0 if safety_error else 20,
            applicability="applicable",
            message="Sensitive patterns require cleanup." if safety_error else "No sensitive patterns were detected.",
        ))

        query_ready = state.generated_pages_exist
        dimensions.append(ScoreDimension(
            name="Query readiness",
            weight=15,
            score=15 if query_ready else 0,
            applicability="applicable",
            message="Generated wiki pages are available for queries." if query_ready else "Generated wiki pages are not ready for queries.",
        ))

    applicable = [dimension for dimension in dimensions if dimension.applicability == "applicable"]
    earned = sum(dimension.score or 0 for dimension in applicable)
    possible = sum(dimension.weight for dimension in applicable)
    score = round((earned / possible) * 100) if possible else 0

    safe_findings = [safe_finding(finding) for finding in findings]
    next_steps = [
        f"修复 {finding.severity} finding: {finding.check} ({finding.path})"
        for finding in safe_findings
        if finding.severity == "ERROR"
    ]
    if not next_steps:
        next_steps = ["保持 wiki/index.md、wiki/log.md 和来源追踪持续更新。"]

    return ScoreReport(
        score_version=1,
        score=score,
        level=score_level(score),
        dimensions=dimensions,
        signals=asdict(state),
        next_steps=next_steps,
    )

def score_to_dict(report: ScoreReport, root: ResolvedRoot) -> dict[str, object]:
    return {
        "root": root_to_dict(root),
        "score_version": report.score_version,
        "score": report.score,
        "level": report.level,
        "dimensions": [asdict(dimension) for dimension in report.dimensions],
        "signals": report.signals,
        "next_steps": report.next_steps,
    }


def calculate_score(state: WikiState, findings: list[Finding]) -> dict[str, object]:
    compatibility_root = ResolvedRoot(None, None, None, "unknown")
    report = build_score_report(compatibility_root, state, findings)
    payload = score_to_dict(report, compatibility_root)
    payload.pop("root")
    return payload


def format_report_text(root: ResolvedRoot, state: WikiState, findings: list[Finding]) -> str:
    report = build_score_report(root, state, findings)
    root_payload = root_to_dict(root)
    root_path = root_payload["wiki_root"] or root_payload["input_root"] or root_payload["control_center"]
    safe_findings = [safe_finding(finding) for finding in findings]
    finding_lines = [
        f"- {finding.severity} {finding.check}: {finding.path}: {finding.message}"
        for finding in safe_findings
    ] or ["- OK: 未发现阻断性 findings。"]
    dimension_lines = [
        f"- {dimension.name}: {dimension.score if dimension.score is not None else 'N/A'}/{dimension.weight} ({dimension.applicability}) - {dimension.message}"
        for dimension in report.dimensions
    ]
    next_step_lines = [f"- {safe_text(step)}" for step in report.next_steps]
    state_lines = [f"- {key}: {value}" for key, value in asdict(state).items()]

    sections = [
        "# Obsidian Wiki Doctor 报告",
        "## 关键结论",
        f"- 当前成熟度评分：{report.score}/100（{report.level}）。",
        f"- 根目录来源：{root.source}。",
        "## 建议行动计划",
        *next_step_lines,
        "## 总体评分",
        f"- score_version: {report.score_version}",
        f"- score: {report.score}",
        f"- level: {report.level}",
        "## 成熟度维度",
        *dimension_lines,
        "## Doctor Findings",
        *finding_lines,
        "## 证据与路径",
        f"- control_center: {root_payload['control_center']}",
        f"- wiki_root: {root_payload['wiki_root']}",
        f"- input_root: {root_payload['input_root']}",
        f"- report_root: {root_path}",
        *state_lines,
        "## Repair Handoff",
        "- validate 命令仍按 --fail-on 返回失败码；score/report 用于诊断展示并始终返回 0。",
    ]
    return "\n".join(sections) + "\n"

def emit_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def emit_findings_text(findings: list[Finding]) -> None:
    safe_findings = [safe_finding(finding) for finding in findings]
    if not safe_findings:
        print("OK")
        return
    for finding in safe_findings:
        location = finding.path or "<unknown>"
        print(f"{finding.severity}: {finding.check}: {location}: {finding.message}")

def should_fail(findings: list[Finding], fail_on: str) -> bool:
    if fail_on == "none":
        return False
    return fail_on == "error" and any(finding.severity == "ERROR" for finding in findings)


def run_validate(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = build_state(root)
    findings = run_checks(root, state)
    if args.format == "json":
        emit_json([safe_finding_dict(finding) for finding in findings])
    else:
        emit_findings_text(findings)
    return 1 if should_fail(findings, args.fail_on) else 0


def run_score(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = build_state(root)
    findings = run_checks(root, state)
    report = build_score_report(root, state, findings)
    payload = score_to_dict(report, root)
    if args.format == "json":
        emit_json(payload)
    else:
        print(payload["score"])
    return 0

def run_report(args: argparse.Namespace) -> int:
    root = resolve_root(args.root)
    state = build_state(root)
    findings = run_checks(root, state)
    report = build_score_report(root, state, findings)
    payload = {
        "root": root_to_dict(root),
        "state": asdict(state),
        "findings": [safe_finding_dict(finding) for finding in findings],
        "score": score_to_dict(report, root),
    }
    if args.format == "json":
        emit_json(payload)
    else:
        print(format_report_text(root, state, findings), end="")
    return 0

def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="Control-center or wiki root path.")
    parser.add_argument("--format", choices=("text", "json"), default="text")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and score an Obsidian LLM Wiki.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Run doctor checks.")
    add_common_options(validate)
    validate.add_argument("--fail-on", choices=("error", "none"), default="error")
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
