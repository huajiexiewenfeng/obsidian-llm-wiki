#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from llm_wiki_core.root import (
    ConfigureResult,
    DiscoveryResult,
    ResolvedRoot,
    configure_user_default,
    default_obsidian_metadata_path,
    default_user_config_path,
    discover_recent_vaults,
    resolve_root,
)
from llm_wiki_core.state import StateValidationError, plan_state_init
from llm_wiki_core.writer import (
    LockTimeout,
    SnapshotConflict,
    WriterError,
    apply_state_init,
)
import obsidian_wiki_doctor
from llm_wiki_core.archive import ArchiveConflict, ArchiveWriteError
from llm_wiki_core.ingest import (
    IngestPlanConflict,
    IngestValidationError,
    IngestWriteError,
    apply_ingest,
    load_payload_file,
    plan_ingest,
)
from llm_wiki_core.inventory import (
    InventoryLoadError,
    InventoryPlanConflict,
    InventoryValidationError,
    InventoryWriteError,
    SensitiveScope,
    apply_inventory_initialize,
    default_inventory_scope,
    inspect_inventory,
    plan_inventory_initialize,
)
from llm_wiki_core.page import apply_pages, load_page_apply_payload, plan_page_apply
from llm_wiki_core.projection import (
    apply_projection_rebuild,
    load_projection_rebuild_payload,
    plan_projection_rebuild,
)


def root_to_dict(root: ResolvedRoot) -> dict[str, object]:
    payload: dict[str, object] = {
        "vault_root": str(root.vault_root) if root.vault_root else None,
        "control_center": str(root.control_center) if root.control_center else None,
        "wiki_root": str(root.wiki_root) if root.wiki_root else None,
        "input_root": str(root.input_root) if root.input_root else None,
        "source": root.source,
    }
    if root.error is not None:
        payload["error"] = {
            "check": root.error.check,
            "severity": root.error.severity,
            "path": root.error.path,
            "message": root.error.message,
            "hint": root.error.hint,
            "candidates": list(root.error.candidates),
        }
    return payload


def root_exit_code(root: ResolvedRoot) -> int:
    if root.error is None:
        return 0
    if root.error.check in {"missing-config", "disabled-config", "multiple-roots"}:
        return 1
    return 2


def run_root_resolve(args: argparse.Namespace) -> int:
    root = resolve_root(
        root_arg=args.root,
        cwd=args.cwd,
        user_config_path=args.user_config,
    )
    payload = root_to_dict(root)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"source: {payload['source']}")
        print(f"vault_root: {payload['vault_root']}")
        print(f"control_center: {payload['control_center']}")
        print(f"wiki_root: {payload['wiki_root']}")
        if "error" in payload:
            print(f"error: {payload['error']['check']}")
    return root_exit_code(root)


def run_root_discover(args: argparse.Namespace) -> int:
    result: DiscoveryResult = discover_recent_vaults(default_obsidian_metadata_path())
    payload = {
        "candidates": [str(path) for path in result.candidates],
        "source": result.source,
        "status": result.status,
        "message": result.message,
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for index, path in enumerate(payload["candidates"], start=1):
            print(f"{index}. {path}")
        if not payload["candidates"]:
            print(f"No recent Vault candidates ({result.status}).")
    return 0


def run_root_configure(args: argparse.Namespace) -> int:
    result: ConfigureResult = configure_user_default(
        args.root,
        Path(args.user_config) if args.user_config else default_user_config_path(),
        args.confirm,
    )
    payload = root_to_dict(result.root)
    payload.update({
        "user_config": str(result.config_path),
        "confirmation_required": result.confirmation_required,
        "configured": result.configured,
    })
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"vault_root: {payload['vault_root']}")
        print(f"user_config: {payload['user_config']}")
        print(f"configured: {payload['configured']}")
    if result.root.error is not None:
        return 2
    return 1 if result.confirmation_required else 0


def state_plan_to_dict(
    plan,
    *,
    confirmation_required: bool,
    initialized: bool,
    create: tuple[str, ...] | None = None,
) -> dict[str, object]:
    return {
        "control_center": str(plan.control_center),
        "meta_root": str(plan.meta_root),
        "confirmation_required": confirmation_required,
        "initialized": initialized,
        "create": list(plan.create if create is None else create),
        "unchanged": list(plan.unchanged),
    }


def print_state_payload(payload: dict[str, object], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if "error" in payload:
        error = payload["error"]
        print(f"error: {error['check']}")
        print(f"message: {error['message']}")
        return
    print(f"initialized: {payload.get('initialized', False)}")
    print(f"create: {', '.join(payload.get('create', []))}")


def run_state_init(args: argparse.Namespace) -> int:
    root = resolve_root(
        root_arg=args.root,
        cwd=args.cwd,
        user_config_path=args.user_config,
    )
    if root.error is not None or root.control_center is None:
        payload = root_to_dict(root)
        print_state_payload(payload, args.format)
        return root_exit_code(root)
    try:
        plan = plan_state_init(root.control_center)
        if plan.create and not args.confirm:
            payload = state_plan_to_dict(
                plan,
                confirmation_required=True,
                initialized=False,
            )
            code = 1
        else:
            original_create = plan.create
            result = apply_state_init(plan) if plan.create else plan
            payload = state_plan_to_dict(
                result,
                confirmation_required=False,
                initialized=True,
                create=original_create,
            )
            code = 0
    except (StateValidationError, SnapshotConflict) as error:
        payload = {"error": {"check": "invalid-state", "message": str(error)}}
        code = 2
    except (LockTimeout, WriterError, OSError) as error:
        payload = {"error": {"check": "state-write-failed", "message": str(error)}}
        code = 3
    print_state_payload(payload, args.format)
    return code


def print_apply_payload(payload: dict[str, object], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if "error" in payload:
        error = payload["error"]
        print(f"error: {error['check']}")
        print(f"message: {error['message']}")
        return
    print(f"status: {payload.get('status')}")
    if payload.get("plan_checksum"):
        print(f"plan_checksum: {payload['plan_checksum']}")


def run_ingest_apply(args: argparse.Namespace) -> int:
    root = resolve_root(
        root_arg=args.root,
        cwd=args.cwd,
        user_config_path=args.user_config,
    )
    if root.error is not None or root.control_center is None:
        payload = root_to_dict(root)
        print_apply_payload(payload, args.format)
        return root_exit_code(root)
    try:
        ingest_payload = load_payload_file(args.payload, sys.stdin)
        plan = plan_ingest(root.control_center, ingest_payload)
        if not args.confirm:
            payload = plan.to_public_dict()
            payload["status"] = (
                "confirmation-required" if plan.confirmable else "conflict"
            )
            code = 1 if plan.confirmable else 2
        elif not args.plan_checksum:
            payload = {
                "error": {
                    "check": "missing-plan-checksum",
                    "message": "--plan-checksum is required with --confirm",
                }
            }
            code = 2
        else:
            result = apply_ingest(
                root.control_center,
                ingest_payload,
                args.plan_checksum,
            )
            payload = {
                "status": result.status,
                "operation_id": result.operation_id,
                "idempotency_key": result.idempotency_key,
                "source_id": result.source_id,
                "record_ids": list(result.record_ids),
                "idempotent": result.idempotent,
                "confirmation_required": False,
            }
            if result.archive_relative_path is not None:
                payload["archive_target"] = result.archive_relative_path
            code = 0
    except (
        IngestValidationError,
        IngestPlanConflict,
        ArchiveConflict,
        StateValidationError,
        SnapshotConflict,
    ) as error:
        payload = {
            "error": {
                "check": getattr(error, "check", "ingest-conflict"),
                "message": str(error),
            }
        }
        hint = getattr(error, "hint", None)
        if hint:
            payload["error"]["hint"] = hint
        code = 2
    except (IngestWriteError, ArchiveWriteError, LockTimeout, WriterError, OSError) as error:
        payload = {
            "error": {
                "check": getattr(error, "check", "ingest-write-failed"),
                "message": str(error),
            }
        }
        hint = getattr(error, "hint", None)
        if hint:
            payload["error"]["hint"] = hint
        if isinstance(error, IngestWriteError):
            payload["error"]["current_step"] = error.current_step
            payload["error"]["completed_targets"] = list(error.completed_targets)
        code = 3
    except Exception:
        payload = {
            "error": {
                "check": "internal-error",
                "message": "unexpected internal error",
            }
        }
        code = 4
    print_apply_payload(payload, args.format)
    return code


def add_apply_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root")
    parser.add_argument("--cwd", default=str(Path.cwd()))
    parser.add_argument("--user-config")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--plan-checksum")
    parser.add_argument("--format", choices=("text", "json"), default="json")


def read_payload_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8-sig")


def run_simple_apply(args: argparse.Namespace, *, loader, planner, applier) -> int:
    root = resolve_root(root_arg=args.root, cwd=args.cwd, user_config_path=args.user_config)
    if root.error is not None or root.control_center is None:
        payload = root_to_dict(root)
        print_apply_payload(payload, args.format)
        return root_exit_code(root)
    try:
        command_payload = loader(read_payload_text(args.payload))
        plan = planner(root.control_center, command_payload)
        if not args.confirm:
            payload = plan.to_public_dict()
            payload["status"] = "confirmation-required" if plan.confirmable else "conflict"
            code = 1 if plan.confirmable else 2
        elif not args.plan_checksum:
            payload = {"error": {"check": "missing-plan-checksum", "message": "--plan-checksum is required with --confirm"}}
            code = 2
        else:
            result = applier(root.control_center, command_payload, args.plan_checksum)
            payload = {
                "status": result.status,
                "operation_id": result.operation_id,
                "confirmation_required": False,
            }
            code = 0
    except ValueError as error:
        message = str(error)
        check = message.split(":", 1)[0] if "-conflict" in message else "invalid-payload"
        payload = {"error": {"check": check, "message": message}}
        code = 2
    except (LockTimeout, WriterError, OSError) as error:
        payload = {"error": {"check": "write-failed", "message": str(error)}}
        code = 3
    except Exception:
        payload = {"error": {"check": "internal-error", "message": "unexpected internal error"}}
        code = 4
    print_apply_payload(payload, args.format)
    return code


def run_page_apply(args: argparse.Namespace) -> int:
    return run_simple_apply(
        args,
        loader=load_page_apply_payload,
        planner=plan_page_apply,
        applier=apply_pages,
    )


def run_projection_rebuild(args: argparse.Namespace) -> int:
    return run_simple_apply(
        args,
        loader=load_projection_rebuild_payload,
        planner=plan_projection_rebuild,
        applier=apply_projection_rebuild,
    )


def run_inventory_inspect(args: argparse.Namespace) -> int:
    root = resolve_root(root_arg=args.root, cwd=args.cwd, user_config_path=args.user_config)
    if root.error is not None or root.vault_root is None or root.control_center is None:
        payload = root_to_dict(root)
        print_apply_payload(payload, args.format)
        return root_exit_code(root)
    try:
        scope = inventory_scope_from_args(
            root.vault_root,
            root.control_center,
            args,
            optional=True,
        )
        result = inspect_inventory(
            root.vault_root,
            root.control_center,
            scope_override=scope,
            verify_content=args.verify_content,
        )
        payload = result.to_public_dict()
        code = 0
    except (InventoryValidationError, InventoryLoadError, OSError) as error:
        payload = {"error": {"check": "inventory-inspect-failed", "message": str(error)}}
        code = 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif "error" in payload:
        print(f"error: {payload['error']['check']}")
        print(f"message: {payload['error']['message']}")
    else:
        print(f"complete: {payload['complete']}")
        for finding in payload["findings"]:
            print(f"{finding['severity']}: {finding['check']}: {finding.get('path') or '<unknown>'}")
    return code


def run_inventory_initialize(args: argparse.Namespace) -> int:
    root = resolve_root(root_arg=args.root, cwd=args.cwd, user_config_path=args.user_config)
    if root.error is not None or root.vault_root is None or root.control_center is None:
        payload = root_to_dict(root)
        print_apply_payload(payload, args.format)
        return root_exit_code(root)
    try:
        scope = inventory_scope_from_args(root.vault_root, root.control_center, args)
        if not args.confirm:
            plan = plan_inventory_initialize(root.vault_root, root.control_center, scope=scope)
            payload = plan.to_public_dict()
            payload["status"] = "confirmation-required"
            code = 1
        elif not args.plan_checksum:
            payload = {
                "error": {
                    "check": "missing-plan-checksum",
                    "message": "--plan-checksum is required with --confirm",
                }
            }
            code = 2
        else:
            result = apply_inventory_initialize(
                root.vault_root,
                root.control_center,
                args.plan_checksum,
                scope=scope,
            )
            payload = {
                "status": result.status,
                "operation_id": result.operation_id,
                "idempotency_key": result.idempotency_key,
                "idempotent": result.idempotent,
                "confirmation_required": False,
            }
            code = 0
    except (InventoryValidationError, InventoryLoadError, InventoryPlanConflict, SnapshotConflict) as error:
        payload = {"error": {"check": "inventory-conflict", "message": str(error)}}
        code = 2
    except (InventoryWriteError, LockTimeout, WriterError, OSError) as error:
        payload = {"error": {"check": "inventory-write-failed", "message": str(error)}}
        code = 3
    print_apply_payload(payload, args.format)
    return code


def inventory_scope_from_args(
    vault_root: Path,
    control_center: Path,
    args: argparse.Namespace,
    *,
    optional: bool = False,
):
    includes = tuple(args.include or ())
    excludes = tuple(args.exclude or ())
    sensitive_values = tuple(args.sensitive_scope or ())
    if optional and not includes and not excludes and not sensitive_values:
        return None
    control_relative = control_center.resolve().relative_to(vault_root.resolve()).as_posix()
    scope = default_inventory_scope(control_relative)
    sensitive: list[SensitiveScope] = []
    for value in sensitive_values:
        alias, separator, pattern = value.partition("=")
        if not separator:
            raise InventoryValidationError(
                "--sensitive-scope must use alias=vault-relative-glob"
            )
        sensitive.append(SensitiveScope(alias, pattern))
    return replace(
        scope,
        include=includes or scope.include,
        exclude=scope.exclude + excludes,
        sensitive=tuple(sensitive),
    )


def add_inventory_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--include", action="append")
    parser.add_argument("--exclude", action="append")
    parser.add_argument("--sensitive-scope", action="append")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-wiki")
    groups = parser.add_subparsers(dest="group", required=True)
    root = groups.add_parser("root")
    root_commands = root.add_subparsers(dest="command", required=True)
    resolve = root_commands.add_parser("resolve")
    resolve.add_argument("--root")
    resolve.add_argument("--cwd", default=str(Path.cwd()))
    resolve.add_argument("--user-config")
    resolve.add_argument("--format", choices=("text", "json"), default="json")
    resolve.set_defaults(handler=run_root_resolve)
    discover = root_commands.add_parser("discover")
    discover.add_argument("--format", choices=("text", "json"), default="json")
    discover.set_defaults(handler=run_root_discover)
    configure = root_commands.add_parser("configure")
    configure.add_argument("--root", required=True)
    configure.add_argument("--activate", action="store_true", required=True)
    configure.add_argument("--confirm", action="store_true")
    configure.add_argument("--user-config")
    configure.add_argument("--format", choices=("text", "json"), default="json")
    configure.set_defaults(handler=run_root_configure)
    state = groups.add_parser("state")
    state_commands = state.add_subparsers(dest="command", required=True)
    state_init = state_commands.add_parser("init")
    state_init.add_argument("--root")
    state_init.add_argument("--cwd", default=str(Path.cwd()))
    state_init.add_argument("--user-config")
    state_init.add_argument("--confirm", action="store_true")
    state_init.add_argument("--format", choices=("text", "json"), default="json")
    state_init.set_defaults(handler=run_state_init)
    ingest = groups.add_parser("ingest")
    ingest_commands = ingest.add_subparsers(dest="command", required=True)
    ingest_apply = ingest_commands.add_parser("apply")
    add_apply_arguments(ingest_apply)
    ingest_apply.set_defaults(handler=run_ingest_apply)
    page = groups.add_parser("page")
    page_commands = page.add_subparsers(dest="command", required=True)
    page_apply = page_commands.add_parser("apply")
    add_apply_arguments(page_apply)
    page_apply.set_defaults(handler=run_page_apply)
    projection = groups.add_parser("projection")
    projection_commands = projection.add_subparsers(dest="command", required=True)
    projection_rebuild = projection_commands.add_parser("rebuild")
    add_apply_arguments(projection_rebuild)
    projection_rebuild.set_defaults(handler=run_projection_rebuild)
    inventory = groups.add_parser("inventory")
    inventory_commands = inventory.add_subparsers(dest="command", required=True)
    inventory_inspect = inventory_commands.add_parser("inspect")
    inventory_inspect.add_argument("--root")
    inventory_inspect.add_argument("--cwd", default=str(Path.cwd()))
    inventory_inspect.add_argument("--user-config")
    inventory_inspect.add_argument("--verify-content", action="store_true")
    add_inventory_scope_arguments(inventory_inspect)
    inventory_inspect.add_argument("--format", choices=("text", "json"), default="json")
    inventory_inspect.set_defaults(handler=run_inventory_inspect)
    inventory_initialize = inventory_commands.add_parser("initialize")
    inventory_initialize.add_argument("--root")
    inventory_initialize.add_argument("--cwd", default=str(Path.cwd()))
    inventory_initialize.add_argument("--user-config")
    inventory_initialize.add_argument("--confirm", action="store_true")
    inventory_initialize.add_argument("--plan-checksum")
    add_inventory_scope_arguments(inventory_initialize)
    inventory_initialize.add_argument("--format", choices=("text", "json"), default="json")
    inventory_initialize.set_defaults(handler=run_inventory_initialize)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["doctor"]:
        return obsidian_wiki_doctor.main(arguments[1:])
    args = build_parser().parse_args(arguments)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
