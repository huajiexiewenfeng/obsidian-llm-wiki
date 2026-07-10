#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from llm_wiki_core.root import ResolvedRoot, resolve_root
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
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["doctor"]:
        return obsidian_wiki_doctor.main(arguments[1:])
    args = build_parser().parse_args(arguments)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
