#!/usr/bin/env python3
"""Inspect the checked-in MusicIR v3 generator catalog using stdlib only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[1]
    / "ambition_music_renderer"
    / "data"
    / "generator_catalog.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "describe", "schema"], nargs="?", default="list")
    parser.add_argument("name", nargs="?")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    data = json.loads(args.catalog.read_text(encoding="utf8"))
    generators = data.get("generators", {})
    if args.command == "list":
        for name in sorted(generators):
            row = generators[name]
            print(f"{name}: {row.get('summary', '')}")
        return 0
    if not args.name:
        parser.error(f"{args.command} requires a generator name")
    if args.name not in generators:
        parser.error(f"unknown generator {args.name!r}; expected one of {sorted(generators)}")
    row = {"name": args.name, **generators[args.name]}
    if args.command == "describe":
        print(json.dumps(row, indent=2, sort_keys=True))
        return 0
    # Dependency-free approximate JSON Schema view. The package CLI emits the
    # same public parameter set with richer inferred types/defaults.
    properties = {"kind": {"const": args.name}}
    required = ["kind"]
    for key, meta in row.get("parameters", {}).items():
        item = {}
        if meta.get("description"):
            item["description"] = meta["description"]
        if meta.get("default") != "derived" and "default" in meta:
            item["default"] = meta["default"]
        for field in ("type", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "enum", "items"):
            if field in meta:
                item[field] = meta[field]
        if meta.get("required"):
            required.append(key)
        properties[key] = item
    print(json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"MusicIR v3 generator: {args.name}",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
        "x-ambition-capabilities": row.get("capabilities", {}),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
