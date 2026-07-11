#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

RUNTIME = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "obsidian-wiki-runtime"
    / "scripts"
    / "llm_wiki.py"
)

if not RUNTIME.is_file():
    raise SystemExit(f"missing-runtime: {RUNTIME}")

runpy.run_path(str(RUNTIME), run_name="__main__")
