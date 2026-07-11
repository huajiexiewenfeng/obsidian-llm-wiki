from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .ingest import PageMutation, _parse_page
from .managed import (
    FRONTMATTER_END,
    FRONTMATTER_START,
    MANAGED_END,
    MANAGED_START,
    ManagedConflict,
    managed_checksum,
    replace_frontmatter_region,
    replace_managed_body,
)
from .state import (
    PageRecord,
    decode_page_registry,
    decode_source_registry,
    casefold_path_key,
    ensure_within,
    stable_record_id,
)
from .writer import (
    VaultLock,
    append_change_event,
    atomic_write_json,
    atomic_write_text,
    begin_operation,
    file_text_checksum,
    read_json_object,
    update_operation,
)


@dataclass(frozen=True)
class PageApplyPayload:
    schema_version: int
    pages: tuple[PageMutation, ...]
    projection_takeovers: tuple[str, ...]


@dataclass(frozen=True)
class PageApplyPlan:
    control_center: Path
    pages: tuple["PagePlan", ...]
    projections: tuple["ProjectionPlan", ...]
    plan_checksum: str
    confirmable: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "control_center": str(self.control_center),
            "pages": [item.to_public_dict() for item in self.pages],
            "projections": [item.to_public_dict() for item in self.projections],
            "plan_checksum": self.plan_checksum,
            "confirmable": self.confirmable,
            "confirmation_required": self.confirmable,
        }


@dataclass(frozen=True)
class PageApplyResult:
    status: str
    operation_id: str


def _plan_checksum(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_page_apply_payload(text: str) -> PageApplyPayload:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("payload must be valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    allowed = {"schema_version", "pages", "projection_takeovers"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"payload has unknown fields: {', '.join(unknown)}")
    if payload.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise ValueError("pages must be a non-empty array")
    pages = tuple(_parse_page(item, index) for index, item in enumerate(raw_pages))
    keys = [casefold_path_key(page.relative_path, windows=True) for page in pages]
    if len(keys) != len(set(keys)):
        raise ValueError("page paths conflict after case folding")
    takeovers = payload.get("projection_takeovers")
    if not isinstance(takeovers, list) or not all(isinstance(item, str) for item in takeovers):
        raise ValueError("projection_takeovers must be a string array")
    valid = {"wiki/index.md", "ingest/index.md", "wiki/log.md"}
    if any(item not in valid for item in takeovers):
        raise ValueError("projection_takeovers contains an invalid path")
    return PageApplyPayload(1, pages, tuple(sorted(set(takeovers))))


@dataclass(frozen=True)
class PagePlan:
    page_id: str
    relative_path: str
    action: str
    expected_file_checksum: str | None
    old_managed_checksum: str | None
    new_managed_checksum: str | None
    rendered_text: str | None
    conflict: Mapping[str, object] | None = None

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "page_id": self.page_id,
            "path": self.relative_path,
            "action": self.action,
            "expected_file_checksum": self.expected_file_checksum,
            "old_managed_checksum": self.old_managed_checksum,
            "new_managed_checksum": self.new_managed_checksum,
        }
        if self.conflict:
            payload.update(self.conflict)
        return payload


def _canonical_body(body: str) -> str:
    return body.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _managed_fields(
    page_id: str,
    mutation: PageMutation,
    source_ids: tuple[str, ...],
    checksum: str | None = None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "llm_wiki_page_id": page_id,
        "llm_wiki_page_type": mutation.page_type,
        "llm_wiki_schema": 1,
        "llm_wiki_source_ids": list(source_ids),
    }
    if checksum is not None:
        fields["llm_wiki_managed_checksum"] = checksum
    return fields


def _new_page(fields: Mapping[str, object], body: str) -> str:
    encoded = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        for key, value in sorted(fields.items())
    )
    return (
        f"---\n{FRONTMATTER_START}\n{encoded}\n{FRONTMATTER_END}\n---\n"
        f"{MANAGED_START}\n{body}\n{MANAGED_END}\n"
    )


def _region(text: str, start: str, end: str, label: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise ManagedConflict(f"{label} markers are missing or duplicate")
    start_index = text.index(start) + len(start)
    end_index = text.index(end)
    if end_index < start_index:
        raise ManagedConflict(f"{label} markers are out of order")
    return text[start_index:end_index].strip("\r\n")


def _read_managed_state(text: str) -> tuple[dict[str, object], str, str]:
    raw_fields = _region(text, FRONTMATTER_START, FRONTMATTER_END, "frontmatter")
    fields: dict[str, object] = {}
    for line in raw_fields.replace("\r\n", "\n").split("\n"):
        if not line:
            continue
        key, separator, raw_value = line.partition(":")
        if not separator or not key.startswith("llm_wiki_"):
            raise ManagedConflict("managed frontmatter is invalid")
        try:
            fields[key] = json.loads(raw_value.strip())
        except json.JSONDecodeError as error:
            raise ManagedConflict("managed frontmatter is invalid") from error
    body = _canonical_body(_region(text, MANAGED_START, MANAGED_END, "managed"))
    return fields, body, managed_checksum(fields, body)


def _record_for_path(
    pages: Mapping[str, PageRecord], relative_path: str
) -> PageRecord | None:
    wanted = casefold_path_key(relative_path, windows=True)
    matches = [
        record
        for record in pages.values()
        if casefold_path_key(record.relative_path, windows=True) == wanted
    ]
    if len(matches) > 1:
        raise ManagedConflict("page registry contains conflicting paths")
    return matches[0] if matches else None


def _conflict(
    *,
    page_id: str,
    mutation: PageMutation,
    expected_file_checksum: str | None,
    current: str | None,
    registry: str | None,
    check: str,
    hint: str,
) -> PagePlan:
    return PagePlan(
        page_id=page_id,
        relative_path=mutation.relative_path,
        action="conflict",
        expected_file_checksum=expected_file_checksum,
        old_managed_checksum=current,
        new_managed_checksum=None,
        rendered_text=None,
        conflict={
            "check": check,
            "current_managed_checksum": current,
            "registry_managed_checksum": registry,
            "resolution_hint": hint,
        },
    )


def plan_page_mutation(
    control_center: Path,
    mutation: PageMutation,
    pages: Mapping[str, PageRecord],
    source_ids: tuple[str, ...],
) -> PagePlan:
    target = ensure_within(control_center / mutation.relative_path, control_center)
    record = _record_for_path(pages, mutation.relative_path)
    page_id = (
        record.page_id
        if record
        else stable_record_id(
            "page", casefold_path_key(mutation.relative_path, windows=True)
        )
    )
    expected_file_checksum = file_text_checksum(target)
    canonical_body = _canonical_body(mutation.managed_body)
    base_fields = _managed_fields(page_id, mutation, source_ids)
    new_checksum = managed_checksum(base_fields, canonical_body)
    fields = _managed_fields(page_id, mutation, source_ids, new_checksum)

    if not target.exists():
        if record is not None:
            return _conflict(
                page_id=page_id,
                mutation=mutation,
                expected_file_checksum=None,
                current=None,
                registry=record.managed_checksum,
                check="missing-managed-page",
                hint="restore the registered page or repair the registry before retrying",
            )
        return PagePlan(
            page_id=page_id,
            relative_path=mutation.relative_path,
            action="create",
            expected_file_checksum=None,
            old_managed_checksum=None,
            new_managed_checksum=new_checksum,
            rendered_text=_new_page(fields, canonical_body),
        )

    with target.open("r", encoding="utf-8", newline="") as stream:
        existing = stream.read()
    try:
        _, _, current_checksum = _read_managed_state(existing)
    except ManagedConflict:
        if not mutation.takeover:
            return _conflict(
                page_id=page_id,
                mutation=mutation,
                expected_file_checksum=expected_file_checksum,
                current=None,
                registry=record.managed_checksum if record else None,
                check="takeover-required",
                hint="set takeover true for this page after reviewing its user content",
            )
        try:
            rendered = replace_frontmatter_region(existing, fields, takeover=True)
            rendered = replace_managed_body(rendered, canonical_body, takeover=True)
        except ManagedConflict as error:
            return _conflict(
                page_id=page_id,
                mutation=mutation,
                expected_file_checksum=expected_file_checksum,
                current=None,
                registry=record.managed_checksum if record else None,
                check="managed-marker-conflict",
                hint=str(error),
            )
        return PagePlan(
            page_id=page_id,
            relative_path=mutation.relative_path,
            action="update" if record else "create",
            expected_file_checksum=expected_file_checksum,
            old_managed_checksum=None,
            new_managed_checksum=new_checksum,
            rendered_text=rendered,
        )

    registry_checksum = record.managed_checksum if record else None
    if record is None:
        return _conflict(
            page_id=page_id,
            mutation=mutation,
            expected_file_checksum=expected_file_checksum,
            current=current_checksum,
            registry=None,
            check="orphan-managed-page",
            hint="repair or explicitly register the managed page before retrying",
        )
    if registry_checksum != current_checksum:
        return _conflict(
            page_id=page_id,
            mutation=mutation,
            expected_file_checksum=expected_file_checksum,
            current=current_checksum,
            registry=registry_checksum,
            check="registry-page-drift",
            hint="reconcile the page registry with the current managed page",
        )
    if mutation.expected_managed_checksum != current_checksum:
        return _conflict(
            page_id=page_id,
            mutation=mutation,
            expected_file_checksum=expected_file_checksum,
            current=current_checksum,
            registry=registry_checksum,
            check="managed-checksum-conflict",
            hint="review the current managed region and refill expected_managed_checksum",
        )
    rendered = replace_frontmatter_region(existing, fields)
    rendered = replace_managed_body(rendered, canonical_body)
    if rendered == existing:
        return PagePlan(
            page_id=page_id,
            relative_path=mutation.relative_path,
            action="unchanged",
            expected_file_checksum=expected_file_checksum,
            old_managed_checksum=current_checksum,
            new_managed_checksum=new_checksum,
            rendered_text=None,
        )
    return PagePlan(
        page_id=page_id,
        relative_path=mutation.relative_path,
        action="update",
        expected_file_checksum=expected_file_checksum,
        old_managed_checksum=current_checksum,
        new_managed_checksum=new_checksum,
        rendered_text=rendered,
    )


def _page_records_after(
    existing: Mapping[str, PageRecord],
    mutations: tuple[PageMutation, ...],
    plans: tuple[PagePlan, ...],
) -> dict[str, PageRecord]:
    records = dict(existing)
    mutation_by_path = {item.relative_path: item for item in mutations}
    for plan in plans:
        if plan.action == "conflict":
            continue
        mutation = mutation_by_path[plan.relative_path]
        previous = records.get(plan.page_id)
        records[plan.page_id] = PageRecord(
            page_id=plan.page_id,
            relative_path=plan.relative_path,
            page_type=mutation.page_type,
            source_ids=previous.source_ids if previous else (),
            managed_checksum=plan.new_managed_checksum,
            revision=(previous.revision + 1 if previous and plan.action == "update" else (previous.revision if previous else 1)),
        )
    return records


def _records_payload(records: Mapping[str, PageRecord]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "records": {key: value.to_dict() for key, value in sorted(records.items())},
    }


def plan_page_apply(control_center: Path, payload: PageApplyPayload) -> PageApplyPlan:
    from .projection import plan_projections, read_change_events

    control_center = control_center.resolve()
    meta = control_center / ".meta"
    sources = decode_source_registry(read_json_object(meta / "sources.json"))
    existing = decode_page_registry(read_json_object(meta / "pages.json"))
    events = read_change_events(meta / "change-log.jsonl")
    plans: list[PagePlan] = []
    for mutation in payload.pages:
        record = _record_for_path(existing, mutation.relative_path)
        plans.append(
            plan_page_mutation(
                control_center,
                mutation,
                existing,
                record.source_ids if record else (),
            )
        )
    page_plans = tuple(plans)
    planned_records = _page_records_after(existing, payload.pages, page_plans)
    prospective = {
        "sequence": max(
            (event.get("sequence", 0) for event in events if isinstance(event.get("sequence"), int)),
            default=0,
        ) + 1,
        "operation_id": "pending-confirmation",
        "kind": "page-apply",
        "record_ids": sorted(item.page_id for item in page_plans),
        "result": "completed",
    }
    projections = plan_projections(
        control_center,
        sources,
        planned_records,
        events,
        payload.projection_takeovers,
        prospective_event=prospective,
    )
    confirmable = all(item.action != "conflict" for item in page_plans) and all(
        item.action != "conflict" for item in projections
    )
    public = {
        "control_center": control_center.as_posix(),
        "pages": [item.to_public_dict() for item in page_plans],
        "projections": [item.to_public_dict() for item in projections],
        "pages_registry_checksum": file_text_checksum(meta / "pages.json"),
        "change_log_checksum": file_text_checksum(meta / "change-log.jsonl"),
        "confirmable": confirmable,
    }
    return PageApplyPlan(
        control_center,
        page_plans,
        projections,
        _plan_checksum(public),
        confirmable,
    )


def apply_pages(
    control_center: Path,
    payload: PageApplyPayload,
    confirmed_plan_checksum: str,
) -> PageApplyResult:
    from .projection import plan_projections, read_change_events

    control_center = control_center.resolve()
    meta = control_center / ".meta"
    operations_path = meta / "operations.json"
    with VaultLock(
        meta / "lock.json",
        allowed_root=control_center,
        command="page apply",
        target=control_center,
    ):
        plan = plan_page_apply(control_center, payload)
        if plan.plan_checksum != confirmed_plan_checksum:
            raise ValueError("plan-conflict: confirmed plan checksum changed")
        if not plan.confirmable:
            raise ValueError("page-conflict: plan is not confirmable")
        existing = decode_page_registry(read_json_object(meta / "pages.json"))
        sources = decode_source_registry(read_json_object(meta / "sources.json"))
        events = read_change_events(meta / "change-log.jsonl")
        planned_records = _page_records_after(existing, payload.pages, plan.pages)
        record_ids = sorted(item.page_id for item in plan.pages)
        operation = begin_operation(
            operations_path,
            allowed_root=control_center,
            kind="page-apply",
            idempotency_key=plan.plan_checksum,
            record_ids=record_ids,
            reuse_completed=False,
        )
        step = "write-pages"
        try:
            update_operation(operations_path, operation.operation_id, allowed_root=control_center, status="running", current_step=step)
            for item in plan.pages:
                if item.action != "unchanged":
                    atomic_write_text(control_center / item.relative_path, item.rendered_text, allowed_root=control_center, expected_checksum=item.expected_file_checksum)
            step = "write-page-registry"
            update_operation(operations_path, operation.operation_id, allowed_root=control_center, status="running", current_step=step)
            atomic_write_json(
                meta / "pages.json",
                _records_payload(planned_records),
                allowed_root=control_center,
                expected_checksum=file_text_checksum(meta / "pages.json"),
            )
            prospective = {
                "sequence": max((event.get("sequence", 0) for event in events if isinstance(event.get("sequence"), int)), default=0) + 1,
                "operation_id": operation.operation_id,
                "kind": "page-apply",
                "record_ids": record_ids,
                "result": "completed",
            }
            projections = plan_projections(control_center, sources, planned_records, events, payload.projection_takeovers, prospective_event=prospective)
            step = "write-projections"
            update_operation(operations_path, operation.operation_id, allowed_root=control_center, status="running", current_step=step)
            for item in projections:
                if item.action != "unchanged":
                    atomic_write_text(control_center / item.relative_path, item.rendered_text, allowed_root=control_center, expected_checksum=item.expected_file_checksum)
            step = "append-change-log"
            append_change_event(
                meta / "change-log.jsonl",
                allowed_root=control_center,
                operation_id=operation.operation_id,
                kind="page-apply",
                record_ids=record_ids,
                old_checksums={},
                new_checksums={"pages.json": file_text_checksum(meta / "pages.json")},
                result="completed",
                idempotency_key=plan.plan_checksum,
            )
            update_operation(operations_path, operation.operation_id, allowed_root=control_center, status="completed", current_step="complete")
            return PageApplyResult("completed", operation.operation_id)
        except BaseException as error:
            update_operation(operations_path, operation.operation_id, allowed_root=control_center, status="failed", current_step=step, error=str(error))
            raise
