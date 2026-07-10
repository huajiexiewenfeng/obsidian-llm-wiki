from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONTROL_CENTER_NAME = "00-知识库中控"
ENV_ROOT = "OBSIDIAN_LLM_WIKI_ROOT"
PROJECT_CONFIG_NAME = ".obsidian-llm-wiki.json"


@dataclass(frozen=True)
class RootIssue:
    check: str
    path: str
    message: str
    hint: str
    severity: str = "ERROR"
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedRoot:
    control_center: Path | None
    wiki_root: Path | None
    input_root: Path | None
    source: str
    error: RootIssue | None = None
    vault_root: Path | None = None


def has_wiki_marker(path: Path) -> bool:
    return (path / "index.md").is_file() or (path / "log.md").is_file()


def is_control_center(path: Path) -> bool:
    return path.is_dir() and ((path / "wiki").is_dir() or has_wiki_marker(path / "wiki"))


def is_direct_wiki_root(path: Path) -> bool:
    return path.is_dir() and has_wiki_marker(path)


def invalid_root(path: Path, source: str) -> ResolvedRoot:
    return ResolvedRoot(
        control_center=None,
        wiki_root=None,
        input_root=path,
        source=source,
        error=RootIssue(
            check="invalid-root",
            path=str(path),
            message=f"{source} root does not point to an Obsidian LLM Wiki vault, control center, or wiki root.",
            hint=f"Pass --root, create {PROJECT_CONFIG_NAME}, or set {ENV_ROOT}.",
        ),
    )


def resolve_explicit_root(
    root_value: str,
    source: str = "argument",
    control_center_name: str = DEFAULT_CONTROL_CENTER_NAME,
) -> ResolvedRoot:
    input_root = Path(root_value).expanduser()
    try:
        resolved = input_root.resolve()
    except OSError:
        return invalid_root(input_root, source)

    vault_control = resolved / control_center_name
    if is_control_center(vault_control):
        return ResolvedRoot(
            control_center=vault_control.resolve(),
            wiki_root=(vault_control / "wiki").resolve(),
            input_root=resolved,
            source=source,
            vault_root=resolved,
        )

    if is_control_center(resolved):
        return ResolvedRoot(
            control_center=resolved,
            wiki_root=(resolved / "wiki").resolve(),
            input_root=resolved,
            source=source,
            vault_root=resolved.parent,
        )

    if is_direct_wiki_root(resolved):
        control_center = resolved.parent if resolved.name == "wiki" else None
        vault_root = control_center.parent if control_center is not None else None
        return ResolvedRoot(
            control_center=control_center.resolve() if control_center else None,
            wiki_root=resolved,
            input_root=resolved,
            source=source,
            vault_root=vault_root.resolve() if vault_root else None,
        )

    return invalid_root(resolved, source)


def resolve_root(*args: object, **kwargs: object) -> ResolvedRoot:
    raise NotImplementedError("configuration resolution is added in Task 2")
