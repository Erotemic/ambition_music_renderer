#!/usr/bin/env python3
"""Read the generated source-only instrument authoring index with stdlib only."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "ambition_music_renderer/data/instrument_authoring_index.json"
SNAPSHOT = ROOT / "ambition_music_renderer/data/audio_environment_snapshot.json"


def main(argv: list[str]) -> int:
    data = json.loads(INDEX.read_text(encoding="utf8"))
    instruments = data.get("instruments") or {}
    if not argv or argv[0] == "list":
        family = argv[1] if len(argv) > 1 else None
        for ref in sorted(instruments):
            row = instruments[ref]
            if family and row.get("family") != family:
                continue
            summary = (row.get("usage") or {}).get("summary", "")
            print(f"{ref:34s} {row.get('family',''):10s} {summary}")
        return 0
    if argv[0] == "describe" and len(argv) >= 2:
        ref = argv[1]
        if ref not in instruments:
            print(f"unknown instrument: {ref}", file=sys.stderr)
            return 2
        row = dict(instruments[ref])
        # Join the normative/derived authoring index with the checked-in
        # observational workstation snapshot at read time. This keeps the two
        # authorities distinct while giving a source-only agent one useful
        # description command.
        if SNAPSHOT.exists():
            snapshot = json.loads(SNAPSHOT.read_text(encoding="utf8"))
            rel = (snapshot.get("stable_alias_resolutions") or {}).get(ref)
            if rel:
                observed = next(
                    (item for item in snapshot.get("sfz_programs", []) if item.get("relative_path") == rel),
                    None,
                )
                row["observed_workstation_resolution"] = {"relative_path": rel, "program": observed}
            else:
                row["observed_workstation_resolution"] = None
        print(json.dumps(row, indent=2, sort_keys=True))
        return 0
    if argv[0] == "families":
        print(json.dumps(data.get("family_profiles") or {}, indent=2, sort_keys=True))
        return 0
    print("usage: read_instrument_catalog.py [list [FAMILY] | describe REF | families]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
