from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

PROJECTION_START = "<!-- llm-wiki:projection:start -->"
PROJECTION_END = "<!-- llm-wiki:projection:end -->"
MANAGED_START = "<!-- llm-wiki:managed:start -->"
MANAGED_END = "<!-- llm-wiki:managed:end -->"
FRONTMATTER_START = "# llm-wiki:frontmatter:start"
FRONTMATTER_END = "# llm-wiki:frontmatter:end"


class ManagedConflict(ValueError):
    pass


@dataclass(frozen=True)
class ManagedPageSnapshot:
    fields: Mapping[str, object]
    managed_body: str
    computed_checksum: str


@dataclass(frozen=True)
class ProjectionSnapshot:
    managed_body: str


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def normalize_content_newlines(content: str, newline: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)


def canonical_managed_body(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def extract_single_region(
    text: str,
    start: str,
    end: str,
    label: str,
) -> str:
    start_count = text.count(start)
    end_count = text.count(end)
    if start_count != 1 or end_count != 1:
        raise ManagedConflict(f"{label} markers are missing, duplicate, or unbalanced")
    start_index = text.index(start) + len(start)
    end_index = text.index(end)
    if end_index < start_index:
        raise ManagedConflict(f"{label} markers are out of order")
    content = text[start_index:end_index]
    if content.startswith("\r\n"):
        content = content[2:]
    elif content.startswith(("\r", "\n")):
        content = content[1:]
    return canonical_managed_body(content)


def parse_managed_frontmatter(text: str) -> dict[str, object]:
    raw_fields = extract_single_region(
        text,
        FRONTMATTER_START,
        FRONTMATTER_END,
        "frontmatter",
    )
    fields: dict[str, object] = {}
    for line in raw_fields.split("\n"):
        if not line:
            continue
        key, separator, raw_value = line.partition(":")
        if not separator or not key.startswith("llm_wiki_") or key in fields:
            raise ManagedConflict("managed frontmatter is invalid")
        try:
            fields[key] = json.loads(raw_value.strip())
        except json.JSONDecodeError as error:
            raise ManagedConflict("managed frontmatter is invalid") from error
    return fields


def inspect_managed_page(text: str) -> ManagedPageSnapshot:
    frontmatter, body, _ = split_frontmatter(text)
    fields = parse_managed_frontmatter(frontmatter)
    managed_body = extract_single_region(
        body,
        MANAGED_START,
        MANAGED_END,
        "managed",
    )
    return ManagedPageSnapshot(
        fields=fields,
        managed_body=managed_body,
        computed_checksum=managed_checksum(fields, managed_body),
    )


def inspect_projection_region(text: str) -> ProjectionSnapshot:
    return ProjectionSnapshot(
        managed_body=extract_single_region(
            text,
            PROJECTION_START,
            PROJECTION_END,
            "projection",
        )
    )


def replace_region(
    text: str,
    content: str,
    start: str,
    end: str,
    label: str,
    *,
    takeover: bool = False,
) -> str:
    start_count = text.count(start)
    end_count = text.count(end)
    if start_count != end_count or start_count > 1:
        raise ManagedConflict(f"{label} markers are duplicate or unbalanced")
    newline = detect_newline(text)
    managed_content = normalize_content_newlines(content, newline).rstrip("\r\n")
    if start_count == 0:
        if not takeover:
            raise ManagedConflict(f"{label} markers are missing")
        separator = "" if not text or text.endswith(newline) else newline
        return f"{text}{separator}{start}{newline}{managed_content}{newline}{end}{newline}"
    start_index = text.index(start)
    end_index = text.index(end)
    if end_index < start_index:
        raise ManagedConflict(f"{label} markers are out of order")
    prefix = text[: start_index + len(start)]
    suffix = text[end_index:]
    return f"{prefix}{newline}{managed_content}{newline}{suffix}"


def replace_projection_region(text: str, content: str, *, takeover: bool = False) -> str:
    return replace_region(
        text,
        content,
        PROJECTION_START,
        PROJECTION_END,
        "projection",
        takeover=takeover,
    )


def replace_managed_body(text: str, content: str, *, takeover: bool = False) -> str:
    return replace_region(
        text,
        content,
        MANAGED_START,
        MANAGED_END,
        "managed",
        takeover=takeover,
    )


def split_frontmatter(text: str) -> tuple[str, str, str]:
    newline = detect_newline(text)
    opening = f"---{newline}"
    closing = f"{newline}---{newline}"
    if not text.startswith(opening):
        raise ManagedConflict("YAML frontmatter is missing")
    closing_index = text.find(closing, len(opening))
    if closing_index < 0:
        raise ManagedConflict("YAML frontmatter is unclosed")
    return (
        text[len(opening) : closing_index],
        text[closing_index + len(closing) :],
        newline,
    )


def encode_frontmatter_fields(fields: Mapping[str, object], newline: str) -> str:
    lines: list[str] = []
    for key, value in sorted(fields.items()):
        if not key.startswith("llm_wiki_"):
            raise ManagedConflict("managed frontmatter keys must start with llm_wiki_")
        lines.append(
            f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        )
    return newline.join(lines) + newline


def replace_frontmatter_region(
    text: str,
    fields: Mapping[str, object],
    *,
    takeover: bool = False,
) -> str:
    try:
        frontmatter, body, newline = split_frontmatter(text)
    except ManagedConflict:
        if not takeover or text.startswith("---"):
            raise
        newline = detect_newline(text)
        managed_fields = encode_frontmatter_fields(fields, newline)
        return (
            f"---{newline}{FRONTMATTER_START}{newline}{managed_fields}"
            f"{FRONTMATTER_END}{newline}---{newline}{text}"
        )
    updated = replace_region(
        frontmatter + newline,
        encode_frontmatter_fields(fields, newline),
        FRONTMATTER_START,
        FRONTMATTER_END,
        "frontmatter",
        takeover=takeover,
    )
    if not updated.endswith(newline):
        updated += newline
    return f"---{newline}{updated}---{newline}{body}"


def managed_checksum(fields: Mapping[str, object], managed_body: str) -> str:
    filtered = {
        key: value
        for key, value in fields.items()
        if key != "llm_wiki_managed_checksum"
    }
    payload = (
        json.dumps(
            filtered,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        + managed_body
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
