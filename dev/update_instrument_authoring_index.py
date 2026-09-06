#!/usr/bin/env python3
"""Regenerate or verify the checked-in instrument authoring index."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ambition_music_renderer.instrument_authoring import build_instrument_authoring_index

OUT = ROOT / "ambition_music_renderer/data/instrument_authoring_index.json"


def rendered_index() -> str:
    return json.dumps(build_instrument_authoring_index(), indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the checked-in index is current instead of rewriting it",
    )
    args = parser.parse_args(argv)
    rendered = rendered_index()
    if args.check:
        actual = OUT.read_text(encoding="utf8")
        if actual != rendered:
            print(
                f"instrument authoring index is stale: run {Path(__file__).name}",
                file=sys.stderr,
            )
            return 1
        print(f"instrument authoring index is current: {OUT}")
        return 0
    OUT.write_text(rendered, encoding="utf8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
