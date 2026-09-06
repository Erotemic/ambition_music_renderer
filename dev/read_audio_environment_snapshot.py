#!/usr/bin/env python3
"""Inspect the checked-in workstation audio snapshot using Python stdlib only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "ambition_music_renderer/data/audio_environment_snapshot.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="summary", help="summary, aliases, plugins, soundfonts, or text to search SFZ paths")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT)
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args()
    data = json.loads(args.snapshot.read_text(encoding="utf8"))
    query = args.query
    if query == "summary":
        reports = data["source_reports"]
        print(f"captured_at: {data.get('captured_at')}")
        print(f"workstation_root: {data.get('workstation_root')}")
        print(f"sfz_programs: {len(data.get('sfz_programs', []))}")
        print(f"discovered_sfz: {reports.get('discovered_sfz_count')}")
        print(f"stable_aliases: {len(data.get('stable_alias_resolutions', {}))}")
        print(f"soundfonts: {len(data.get('soundfonts', []))}")
        print("plugins: " + ", ".join(f"{k}={len(v)}" for k, v in data.get("plugins", {}).items()))
        return 0
    if query == "aliases":
        for key, value in data.get("stable_alias_resolutions", {}).items():
            print(f"{key}: {value}")
        return 0
    if query == "plugins":
        for kind, values in data.get("plugins", {}).items():
            print(f"[{kind}]")
            for value in values:
                print(value)
        return 0
    if query == "soundfonts":
        for value in data.get("soundfonts", []):
            print(value)
        return 0
    needle = query.casefold()
    hits = [row for row in data.get("sfz_programs", []) if needle in str(row.get("relative_path", "")).casefold() or any(needle in str(alias).casefold() for alias in row.get("aliases", []))]
    for row in hits[: args.limit]:
        print(json.dumps(row, sort_keys=True))
    if len(hits) > args.limit:
        print(f"... {len(hits) - args.limit} more")
    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
