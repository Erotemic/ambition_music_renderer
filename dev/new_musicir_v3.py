#!/usr/bin/env python3
"""Create a new MusicIR v3 score from the checked-in dependency-free starter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ambition_music_renderer/data/musicir_v3_new.music.yaml"


def slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").lower()
    if not text:
        raise ValueError("cue name must contain at least one letter or number")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="new stable cue id or human-readable name")
    parser.add_argument("output", nargs="?", type=Path, help="output path (default: <id>.music.yaml)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    cue_id = slug(args.name)
    output = args.output or Path(f"{cue_id}.music.yaml")
    if output.exists() and not args.force:
        parser.error(f"refusing to overwrite {output}; pass --force")
    text = TEMPLATE.read_text(encoding="utf8")
    text = text.replace("id: new_v3_cue", f"id: {cue_id}")
    text = text.replace("title: New MusicIR v3 cue", f"title: {json.dumps(args.name)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
