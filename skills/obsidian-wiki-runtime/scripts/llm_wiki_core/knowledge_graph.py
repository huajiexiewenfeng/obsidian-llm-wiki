from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")


@dataclass(frozen=True)
class KnowledgeGraphAnalysis:
    nodes: frozenset[str]
    reachable_paths: frozenset[str]
    orphan_wiki_pages: tuple[str, ...]
    detached_components: tuple[tuple[str, ...], ...]


def _vault_relative(vault: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(vault).as_posix()
    except (OSError, ValueError):
        return None


def _safe_allowed_path(vault: Path, relative_path: str) -> Path | None:
    candidate = (vault / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(vault)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _markdown_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1:target.index(">")].strip()
    else:
        match = re.match(r"([^\s]+)(?:\s+['\"(].*)?$", target)
        if match:
            target = match.group(1).strip()
    return target.split("#", 1)[0].strip()


def _wikilink_target(raw_target: str) -> str:
    return raw_target.split("|", 1)[0].split("#", 1)[0].strip()


def _candidate_variants(path: Path) -> tuple[Path, ...]:
    candidates = [path]
    if path.suffix == "":
        candidates.append(path.with_suffix(".md"))
    candidates.append(path / "index.md")
    return tuple(candidates)


def _resolve_target(
    source: Path,
    raw_target: str,
    *,
    wikilink: bool,
    vault: Path,
    wiki: Path,
    absolute_nodes: set[Path],
    basename_index: dict[str, tuple[Path, ...]],
) -> Path | None:
    target = _wikilink_target(raw_target) if wikilink else _markdown_target(raw_target)
    if not target or target.startswith("#"):
        return None
    if re.match(r"(?i)^[a-z][a-z0-9+.-]*:", target) or target.startswith("//"):
        return None

    normalized = target.replace("\\", "/")
    target_path = Path(normalized)
    bases = [source.parent]
    if not (normalized.startswith("./") or normalized.startswith("../")):
        bases.extend((vault, wiki))
    for base in bases:
        for candidate in _candidate_variants((base / target_path).resolve()):
            if candidate in absolute_nodes:
                return candidate

    if wikilink and "/" not in normalized:
        expected = target_path.name
        if not expected.casefold().endswith(".md"):
            expected += ".md"
        matches = basename_index.get(expected.casefold(), ())
        exact = tuple(path for path in matches if path.name == expected)
        if len(exact) == 1:
            return exact[0]
        if len(matches) == 1:
            return matches[0]
    return None


def _components(nodes: set[Path], adjacency: dict[Path, set[Path]]) -> list[set[Path]]:
    remaining = set(nodes)
    components: list[set[Path]] = []
    while remaining:
        start = min(remaining, key=lambda path: str(path).casefold())
        component: set[Path] = set()
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current in component:
                continue
            component.add(current)
            remaining.discard(current)
            queue.extend(adjacency[current] - component)
        components.append(component)
    return components


def analyze_knowledge_graph(
    vault_root: Path,
    wiki_root: Path,
    allowed_document_paths: Iterable[str],
) -> KnowledgeGraphAnalysis:
    vault = vault_root.expanduser().resolve()
    wiki = wiki_root.expanduser().resolve()
    allowed = {
        path
        for relative_path in allowed_document_paths
        if (path := _safe_allowed_path(vault, relative_path)) is not None
    }
    wiki_pages = {
        path.resolve()
        for path in wiki.rglob("*.md")
        if path.is_file()
    } if wiki.is_dir() else set()
    absolute_nodes = allowed | wiki_pages
    adjacency = {path: set() for path in absolute_nodes}

    grouped: dict[str, list[Path]] = {}
    for path in absolute_nodes:
        grouped.setdefault(path.name.casefold(), []).append(path)
    basename_index = {
        name: tuple(sorted(paths, key=lambda path: str(path).casefold()))
        for name, paths in grouped.items()
    }

    for source in sorted(absolute_nodes, key=lambda path: str(path).casefold()):
        if source.suffix.casefold() != ".md":
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        raw_targets = ((match.group(1), False) for match in MARKDOWN_LINK_RE.finditer(text))
        wiki_targets = ((match.group(1), True) for match in WIKILINK_RE.finditer(text))
        for raw_target, is_wikilink in (*raw_targets, *wiki_targets):
            target = _resolve_target(
                source,
                raw_target,
                wikilink=is_wikilink,
                vault=vault,
                wiki=wiki,
                absolute_nodes=absolute_nodes,
                basename_index=basename_index,
            )
            if target is None:
                continue
            adjacency[source].add(target)
            adjacency[target].add(source)

    root = (wiki / "index.md").resolve()
    reachable: set[Path] = set()
    queue = deque([root] if root in absolute_nodes else [])
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(adjacency[current] - reachable)

    unreachable = absolute_nodes - reachable
    orphan_wiki = tuple(
        sorted(
            path.relative_to(wiki).as_posix()
            for path in wiki_pages - reachable
            if path != root
        )
    )
    detached: list[tuple[str, ...]] = []
    for component in _components(unreachable, adjacency):
        if not (component & wiki_pages):
            continue
        detached.append(tuple(sorted(
            relative
            for path in component
            if (relative := _vault_relative(vault, path)) is not None
        )))
    detached.sort()

    node_paths = frozenset(
        relative for path in absolute_nodes
        if (relative := _vault_relative(vault, path)) is not None
    )
    reachable_paths = frozenset(
        relative for path in reachable
        if (relative := _vault_relative(vault, path)) is not None
    )
    return KnowledgeGraphAnalysis(
        nodes=node_paths,
        reachable_paths=reachable_paths,
        orphan_wiki_pages=orphan_wiki,
        detached_components=tuple(detached),
    )
