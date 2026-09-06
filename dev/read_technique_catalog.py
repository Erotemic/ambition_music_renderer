#!/usr/bin/env python3
"""Inspect the checked-in MusicIR technique catalog using Python stdlib only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "ambition_music_renderer/data/technique_catalog.json"


def main(argv: list[str]) -> int:
    data = json.loads(CATALOG.read_text(encoding="utf8"))
    techniques = data.get("techniques") or {}
    if not argv or argv[0] == "list":
        for name in sorted(techniques):
            row = techniques[name]
            print(f"{name:14s} gate={float(row.get('default_gate', 0.86)):0.2f}  {row.get('summary','')}")
        return 0
    if argv[0] == "describe" and len(argv) >= 2:
        name = argv[1]
        aliases = {alias: key for key, row in techniques.items() for alias in row.get("aliases") or []}
        name = name if name in techniques else aliases.get(name, name)
        if name not in techniques:
            print(f"unknown technique: {argv[1]}", file=sys.stderr)
            return 2
        print(json.dumps({"name": name, **techniques[name]}, indent=2, sort_keys=True))
        return 0
    print("usage: read_technique_catalog.py [list | describe NAME]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
