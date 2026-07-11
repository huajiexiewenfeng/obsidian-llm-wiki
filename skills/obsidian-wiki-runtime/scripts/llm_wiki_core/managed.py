from __future__ import annotations

import hashlib
import json
from typing import Mapping

PROJECTION_START = "<!-- llm-wiki:projection:start -->"
PROJECTION_END = "<!-- llm-wiki:projection:end -->"
MANAGED_START = "<!-- llm-wiki:managed:start -->"
MANAGED_END = "<!-- llm-wiki:managed:end -->"
FRONTMATTER_START = "# llm-wiki:frontmatter:start"
FRONTMATTER_END = "# llm-wiki:frontmatter:end"


class ManagedConflict(ValueError):
    pass


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def normalize_content_newlines(content: str, newline: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)


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
