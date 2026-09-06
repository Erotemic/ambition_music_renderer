#!/usr/bin/env python3
"""Read the checked-in processing catalog using only the Python stdlib."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "ambition_music_renderer" / "data" / "processing_catalog.json"


def main(argv: list[str]) -> int:
    data = json.loads(CATALOG.read_text(encoding="utf8"))
    processors = data.get("processors") or {}
    if not argv or argv[0] == "list":
        for name in sorted(processors):
            row = processors[name]
            print(f"{name:18s} {row.get('backend',''):12s} {row.get('summary','')}")
        return 0
    if argv[0] == "describe" and len(argv) >= 2:
        name = argv[1]
        aliases = {alias: key for key, row in processors.items() for alias in row.get("aliases") or []}
        name = name if name in processors else aliases.get(name, name)
        if name not in processors:
            print(f"unknown processor: {argv[1]}", file=sys.stderr)
            return 2
        print(json.dumps({"name": name, **processors[name]}, indent=2, sort_keys=True))
        return 0
    if argv[0] == "templates":
        print(json.dumps(data.get("inspector_templates") or {}, indent=2, sort_keys=True))
        return 0
    print("usage: read_processing_catalog.py [list | describe NAME | templates]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
