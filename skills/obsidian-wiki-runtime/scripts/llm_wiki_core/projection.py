from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .managed import ManagedConflict, replace_projection_region
from .state import PageRecord, SourceRecord, ensure_within
from .writer import file_text_checksum

PROJECTION_PATHS = ("wiki/index.md", "ingest/index.md", "wiki/log.md")


def read_change_events(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    events: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"change log line {line_number} is invalid JSON") from error
            if not isinstance(event, dict):
                raise ValueError(f"change log line {line_number} must be a JSON object")
            events.append(event)
    return tuple(events)


@dataclass(frozen=True)
class ProjectionPlan:
    relative_path: str
    action: str
    expected_file_checksum: str | None
    rendered_text: str | None
    conflict: Mapping[str, object] | None = None

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": self.relative_path,
            "action": self.action,
            "expected_file_checksum": self.expected_file_checksum,
        }
        if self.conflict:
            payload.update(self.conflict)
        return payload


def _link(relative_path: str) -> str:
    return relative_path[:-3] if relative_path.endswith(".md") else relative_path


def render_wiki_index(pages: Mapping[str, PageRecord]) -> str:
    lines = ["## Wiki pages", ""]
    for page in sorted(
        pages.values(), key=lambda item: (item.page_type, item.relative_path.casefold(), item.page_id)
    ):
        lines.append(f"- {page.page_type}: [[{_link(page.relative_path)}]]")
    return "\n".join(lines).rstrip() + "\n"


def render_ingest_index(
    sources: Mapping[str, SourceRecord], pages: Mapping[str, PageRecord]
) -> str:
    lines = ["## Ingest sources", ""]
    for source in sorted(
        sources.values(), key=lambda item: (item.canonical_path.casefold(), item.source_id)
    ):
        proxy = pages.get(source.proxy_page_id or "")
        proxy_text = f"[[{_link(proxy.relative_path)}]]" if proxy else "(missing proxy)"
        lines.append(
            f"- `{source.canonical_path}` | {source.status} | {source.mode} | {proxy_text}"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_wiki_log(events: Sequence[Mapping[str, object]]) -> str:
    lines = ["## Change log", ""]
    for event in sorted(
        events,
        key=lambda item: (
            item.get("sequence") if isinstance(item.get("sequence"), int) else 0,
            str(item.get("operation_id", "")),
        ),
    ):
        lines.append(
            f"- {event.get('sequence', '?')} | {event.get('kind', 'unknown')} | "
            f"{event.get('operation_id', 'unknown')} | {event.get('result', 'unknown')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _new_projection(content: str) -> str:
    return (
        "<!-- llm-wiki:projection:start -->\n"
        f"{content.rstrip()}\n"
        "<!-- llm-wiki:projection:end -->\n"
    )


def plan_projections(
    control_center: Path,
    sources: Mapping[str, SourceRecord],
    pages: Mapping[str, PageRecord],
    events: Sequence[Mapping[str, object]],
    takeovers: Sequence[str],
    prospective_event: Mapping[str, object] | None = None,
) -> tuple[ProjectionPlan, ...]:
    log_events = list(events)
    if prospective_event is not None:
        log_events.append(prospective_event)
    contents = {
        "wiki/index.md": render_wiki_index(pages),
        "ingest/index.md": render_ingest_index(sources, pages),
        "wiki/log.md": render_wiki_log(log_events),
    }
    takeover_set = set(takeovers)
    plans: list[ProjectionPlan] = []
    for relative_path in PROJECTION_PATHS:
        target = ensure_within(control_center / relative_path, control_center)
        expected = file_text_checksum(target)
        if not target.exists():
            plans.append(
                ProjectionPlan(relative_path, "create", None, _new_projection(contents[relative_path]))
            )
            continue
        with target.open("r", encoding="utf-8", newline="") as stream:
            existing = stream.read()
        try:
            rendered = replace_projection_region(
                existing,
                contents[relative_path],
                takeover=relative_path in takeover_set,
            )
        except ManagedConflict as error:
            plans.append(
                ProjectionPlan(
                    relative_path,
                    "conflict",
                    expected,
                    None,
                    {
                        "check": "projection-conflict",
                        "resolution_hint": str(error),
                    },
                )
            )
            continue
        plans.append(
            ProjectionPlan(
                relative_path,
                "unchanged" if rendered == existing else "update",
                expected,
                None if rendered == existing else rendered,
            )
        )
    return tuple(plans)
