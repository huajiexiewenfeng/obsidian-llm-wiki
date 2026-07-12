from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .managed import ManagedConflict, replace_projection_region
from .state import (
    PageRecord,
    SourceRecord,
    decode_page_registry,
    decode_source_registry,
    ensure_within,
)
from .writer import (
    VaultLock,
    atomic_write_text,
    begin_operation,
    file_text_checksum,
    read_json_object,
    update_operation,
)

PROJECTION_PATHS = ("wiki/index.md", "ingest/index.md", "wiki/log.md")


@dataclass(frozen=True)
class ProjectionRebuildPayload:
    schema_version: int
    projection_takeovers: tuple[str, ...]


@dataclass(frozen=True)
class ProjectionRebuildPlan:
    control_center: Path
    projections: tuple["ProjectionPlan", ...]
    plan_checksum: str
    confirmable: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "control_center": str(self.control_center),
            "projections": [item.to_public_dict() for item in self.projections],
            "plan_checksum": self.plan_checksum,
            "confirmable": self.confirmable,
            "confirmation_required": self.confirmable,
        }


@dataclass(frozen=True)
class ProjectionRebuildResult:
    status: str
    operation_id: str


def _checksum(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_projection_rebuild_payload(text: str) -> ProjectionRebuildPayload:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("payload must be valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    unknown = sorted(set(payload) - {"schema_version", "projection_takeovers"})
    if unknown:
        raise ValueError(f"payload has unknown fields: {', '.join(unknown)}")
    if payload.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    takeovers = payload.get("projection_takeovers")
    if not isinstance(takeovers, list) or not all(isinstance(item, str) for item in takeovers):
        raise ValueError("projection_takeovers must be a string array")
    if any(item not in PROJECTION_PATHS for item in takeovers):
        raise ValueError("projection_takeovers contains an invalid path")
    return ProjectionRebuildPayload(1, tuple(sorted(set(takeovers))))


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


def plan_projection_rebuild(
    control_center: Path, payload: ProjectionRebuildPayload
) -> ProjectionRebuildPlan:
    control_center = control_center.resolve()
    meta = control_center / ".meta"
    sources = decode_source_registry(read_json_object(meta / "sources.json"))
    pages = decode_page_registry(read_json_object(meta / "pages.json"))
    events = read_change_events(meta / "change-log.jsonl")
    projections = plan_projections(
        control_center,
        sources,
        pages,
        events,
        payload.projection_takeovers,
    )
    public = [item.to_public_dict() for item in projections]
    confirmable = all(item.action != "conflict" for item in projections)
    plan_checksum = _checksum(
        {
            "control_center": control_center.as_posix(),
            "projections": public,
            "confirmable": confirmable,
        }
    )
    return ProjectionRebuildPlan(control_center, projections, plan_checksum, confirmable)


def apply_projection_rebuild(
    control_center: Path,
    payload: ProjectionRebuildPayload,
    confirmed_plan_checksum: str,
) -> ProjectionRebuildResult:
    control_center = control_center.resolve()
    meta = control_center / ".meta"
    operations_path = meta / "operations.json"
    with VaultLock(
        meta / "lock.json",
        allowed_root=control_center,
        command="projection rebuild",
        target=control_center,
    ):
        plan = plan_projection_rebuild(control_center, payload)
        if plan.plan_checksum != confirmed_plan_checksum:
            raise ValueError("plan-conflict: confirmed plan checksum changed")
        if not plan.confirmable:
            raise ValueError("projection-conflict: plan is not confirmable")
        operation = begin_operation(
            operations_path,
            allowed_root=control_center,
            kind="projection-rebuild",
            idempotency_key=plan.plan_checksum,
            record_ids=[],
            reuse_completed=False,
        )
        try:
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=control_center,
                status="running",
                current_step="write-projections",
            )
            for projection in plan.projections:
                if projection.action == "unchanged":
                    continue
                atomic_write_text(
                    control_center / projection.relative_path,
                    projection.rendered_text,
                    allowed_root=control_center,
                    expected_checksum=projection.expected_file_checksum,
                )
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=control_center,
                status="completed",
                current_step="complete",
            )
            return ProjectionRebuildResult("completed", operation.operation_id)
        except BaseException as error:
            update_operation(
                operations_path,
                operation.operation_id,
                allowed_root=control_center,
                status="failed",
                current_step="write-projections",
                error=str(error),
            )
            raise
