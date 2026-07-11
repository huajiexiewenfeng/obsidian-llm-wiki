from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .ingest import PageMutation
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
from .state import PageRecord, casefold_path_key, ensure_within, stable_record_id
from .writer import file_text_checksum


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
