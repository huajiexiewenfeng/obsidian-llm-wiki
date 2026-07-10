from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping
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


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: tuple[Path, ...]
    source: str
    status: str
    message: str | None = None


@dataclass(frozen=True)
class ConfigureResult:
    root: ResolvedRoot
    config_path: Path
    confirmation_required: bool
    configured: bool


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


def config_issue(
    check: str,
    path: Path,
    message: str,
    source: str,
    candidates: tuple[str, ...] = (),
) -> ResolvedRoot:
    return ResolvedRoot(
        control_center=None,
        wiki_root=None,
        input_root=path,
        source=source,
        error=RootIssue(
            check=check,
            path=str(path),
            message=message,
            hint="Fix or remove the invalid configuration before continuing.",
            candidates=candidates,
        ),
    )


def find_project_config(cwd: Path) -> Path | None:
    current = cwd.expanduser().resolve()
    for candidate in (current, *current.parents):
        config = candidate / PROJECT_CONFIG_NAME
        if config.is_file():
            return config
    return None


def load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("configuration root must be a JSON object")
    return payload


def resolve_config_record(
    record: Mapping[str, object],
    config_path: Path,
    source: str,
) -> ResolvedRoot:
    if record.get("schema_version") != 1:
        return config_issue("invalid-config", config_path, "schema_version must be 1", source)
    if record.get("active") is not True:
        return config_issue("disabled-config", config_path, "configuration is not active", source)

    vault_value = record.get("vault_root")
    control_value = record.get("control_center", DEFAULT_CONTROL_CENTER_NAME)
    if not isinstance(vault_value, str) or not vault_value.strip():
        return config_issue("invalid-config", config_path, "vault_root must be a non-empty string", source)
    control_path = Path(control_value) if isinstance(control_value, str) else None
    if (
        control_path is None
        or not control_value.strip()
        or control_path.is_absolute()
        or ".." in control_path.parts
    ):
        return config_issue(
            "invalid-config",
            config_path,
            "control_center must be a non-empty relative path contained by the Vault",
            source,
        )

    vault_path = Path(vault_value).expanduser()
    if not vault_path.is_absolute():
        vault_path = config_path.parent / vault_path
    return resolve_explicit_root(str(vault_path), source=source, control_center_name=control_value)


def resolve_root(
    root_arg: str | None = None,
    cwd: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    user_config_path: str | Path | None = None,
) -> ResolvedRoot:
    if root_arg:
        return resolve_explicit_root(root_arg, source="argument")

    current = Path(cwd) if cwd is not None else Path.cwd()
    project_config = find_project_config(current)
    if project_config is not None:
        try:
            return resolve_config_record(load_json_object(project_config), project_config, "project-config")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return config_issue("invalid-config", project_config, str(exc), "project-config")

    environment = os.environ if environ is None else environ
    env_root = environment.get(ENV_ROOT)
    if env_root:
        return resolve_explicit_root(env_root, source="environment")

    config_path = Path(user_config_path) if user_config_path is not None else default_user_config_path(environ=environment)
    return resolve_user_config(config_path)


def default_user_config_path(
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_value = sys.platform if platform_name is None else platform_name
    environment = os.environ if environ is None else environ
    home_path = Path.home() if home is None else home
    if platform_value.startswith("win"):
        appdata = environment.get("APPDATA")
        base = Path(appdata) if appdata else home_path / "AppData" / "Roaming"
        return base / "obsidian-llm-wiki" / "config.json"
    if platform_value == "darwin":
        return home_path / "Library" / "Application Support" / "obsidian-llm-wiki" / "config.json"
    return home_path / ".config" / "obsidian-llm-wiki" / "config.json"


def default_obsidian_metadata_path(
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_value = sys.platform if platform_name is None else platform_name
    environment = os.environ if environ is None else environ
    home_path = Path.home() if home is None else home
    if platform_value.startswith("win"):
        base = Path(environment.get("APPDATA", home_path / "AppData" / "Roaming"))
        return base / "obsidian" / "obsidian.json"
    if platform_value == "darwin":
        return home_path / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    return home_path / ".config" / "obsidian" / "obsidian.json"


def discover_recent_vaults(metadata_path: Path) -> DiscoveryResult:
    try:
        payload = load_json_object(metadata_path)
    except FileNotFoundError:
        return DiscoveryResult((), "obsidian-recent", "missing-metadata")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return DiscoveryResult((), "obsidian-recent", "invalid-metadata", str(exc))

    vaults = payload.get("vaults")
    if not isinstance(vaults, dict):
        return DiscoveryResult((), "obsidian-recent", "unsupported-metadata")

    candidates: list[Path] = []
    seen: set[Path] = set()
    for record in vaults.values():
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            continue
        candidate = Path(record["path"]).expanduser()
        if not candidate.is_absolute() or not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)
    return DiscoveryResult(tuple(candidates), "obsidian-recent", "ok")


def update_active_vault(payload: dict[str, object], root: ResolvedRoot) -> dict[str, object]:
    assert root.vault_root is not None and root.control_center is not None
    target = {"vault_root": str(root.vault_root), "control_center": root.control_center.name, "active": True}
    updated: list[dict[str, object]] = []
    found = False
    for item in payload["vaults"]:
        if not isinstance(item, dict):
            continue
        record = dict(item)
        if record.get("vault_root") == target["vault_root"] and record.get("control_center", DEFAULT_CONTROL_CENTER_NAME) == target["control_center"]:
            record.update(target)
            found = True
        else:
            record["active"] = False
        updated.append(record)
    if not found:
        updated.append(target)
    next_payload = dict(payload)
    next_payload["schema_version"] = 1
    next_payload["vaults"] = updated
    return next_payload


def write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def configure_user_default(root_value: str, user_config_path: Path, confirm: bool) -> ConfigureResult:
    root = resolve_explicit_root(root_value, source="configure")
    if root.error is not None:
        return ConfigureResult(root, user_config_path, False, False)
    try:
        payload = load_json_object(user_config_path) if user_config_path.exists() else {"schema_version": 1, "vaults": []}
        if payload.get("schema_version") != 1 or not isinstance(payload.get("vaults"), list):
            raise ValueError("User configuration requires schema_version 1 and a vaults array.")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return ConfigureResult(config_issue("invalid-config", user_config_path, str(exc), "configure"), user_config_path, False, False)
    if not confirm:
        return ConfigureResult(root, user_config_path, True, False)
    try:
        write_json_atomically(user_config_path, update_active_vault(payload, root))
    except OSError as exc:
        return ConfigureResult(config_issue("invalid-config", user_config_path, str(exc), "configure"), user_config_path, False, False)
    return ConfigureResult(root, user_config_path, False, True)


def resolve_user_config(path: Path) -> ResolvedRoot:
    try:
        payload = load_json_object(path)
    except FileNotFoundError:
        return config_issue("missing-config", path, "User configuration was not found.", "user-config")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return config_issue("invalid-config", path, str(exc), "user-config")

    if payload.get("schema_version") != 1 or not isinstance(payload.get("vaults"), list):
        return config_issue(
            "invalid-config",
            path,
            "User configuration requires schema_version 1 and a vaults array.",
            "user-config",
        )
    active = [item for item in payload["vaults"] if isinstance(item, dict) and item.get("active") is True]
    if not active:
        return config_issue("missing-config", path, "No active Vault is configured.", "user-config")
    if len(active) > 1:
        candidates = tuple(
            str(Path(item["vault_root"]).expanduser())
            for item in active
            if isinstance(item.get("vault_root"), str)
        )
        return config_issue(
            "multiple-roots",
            path,
            "More than one active Vault is configured.",
            "user-config",
            candidates=candidates,
        )
    record = dict(active[0])
    record["schema_version"] = payload["schema_version"]
    return resolve_config_record(record, path, "user-config")
