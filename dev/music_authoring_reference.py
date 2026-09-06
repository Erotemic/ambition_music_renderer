#!/usr/bin/env python3
"""Dependency-free source checkout reference for MusicIR v3 authoring.

This intentionally uses only Python's standard library so a remote agent with
nothing except the repository can discover the public authoring vocabulary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ambition_music_renderer" / "data"


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf8"))


def _entries(payload, key):
    value = payload.get(key, {})
    if isinstance(value, dict):
        return value
    raise SystemExit(f"invalid {key} registry shape")


def _registries():
    instruments = _load("instrument_authoring_index.json")
    generators = _load("generator_catalog.json")
    processors = _load("processing_catalog.json")
    techniques = _load("technique_catalog.json")
    environment = _load("audio_environment_snapshot.json")
    return {
        "instruments": _entries(instruments, "instruments"),
        "generators": _entries(generators, "generators"),
        "processors": _entries(processors, "processors"),
        "techniques": _entries(techniques, "techniques"),
        "environment": environment,
    }


def _text(value) -> str:
    return json.dumps(value, sort_keys=True).lower()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary")
    search = sub.add_parser("search")
    search.add_argument("query")
    describe = sub.add_parser("describe")
    describe.add_argument("name")
    args = parser.parse_args(argv)

    regs = _registries()
    if args.command == "summary":
        observed = regs["environment"]
        print(f"instruments: {len(regs['instruments'])}")
        print(f"generators: {len(regs['generators'])}")
        print(f"processors: {len(regs['processors'])}")
        print(f"techniques: {len(regs['techniques'])}")
        print(f"observed SFZ programs: {len(observed.get('sfz_programs', []))}")
        print("v1/v2: supported legacy regeneration formats")
        print("v3: default format for new composition")
        return 0

    if args.command == "describe":
        name = args.name
        hits = []
        for category in ("instruments", "generators", "processors", "techniques"):
            entry = regs[category].get(name)
            if entry is not None:
                hits.append((category, entry))
        if not hits:
            raise SystemExit(f"no public authoring entry named {name!r}")
        for category, entry in hits:
            print(json.dumps({"category": category, "name": name, "entry": entry}, indent=2, sort_keys=True))
        return 0

    query = args.query.lower()
    matches = []
    for category in ("instruments", "generators", "processors", "techniques"):
        for name, entry in regs[category].items():
            if query in name.lower() or query in _text(entry):
                matches.append((category, name, entry.get("summary", entry.get("description", ""))))
    for category, name, summary in sorted(matches):
        print(f"{category[:-1]}\t{name}\t{summary}")
    if not matches:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
