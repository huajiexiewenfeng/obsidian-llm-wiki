#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
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
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["doctor"]:
        return obsidian_wiki_doctor.main(arguments[1:])
    args = build_parser().parse_args(arguments)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
