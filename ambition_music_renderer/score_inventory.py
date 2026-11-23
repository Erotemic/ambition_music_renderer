"""Export score identities and score-level playback policy without synthesis."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ._paths import scores_root

INVENTORY_SCHEMA = "ambition.music_inventory.v1"


def score_metadata(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Keep score-level one-shot policy separate from section loop policy."""
    if not isinstance(spec, Mapping):
        raise ValueError("score must be a mapping")
    cue_id = spec.get("id")
    if not isinstance(cue_id, str) or not cue_id.strip():
        raise ValueError("score id must be a nonempty string")
    one_shot = spec.get("one_shot", False)
    if not isinstance(one_shot, bool):
        raise ValueError("score one_shot must be true or false")
    return {"cue_id": cue_id, "score_one_shot": one_shot}


def score_inventory(directory: Path | None = None) -> dict[str, Any]:
    """Read source metadata. This export does not verify compiled products."""
    directory = scores_root() / "active" if directory is None else Path(directory)
    paths = sorted({*directory.glob("*.yaml"), *directory.glob("*.yml")})
    if not paths:
        raise ValueError(f"no scores found under {directory}; initialize the music renderer sources")
    scores = []
    identities = set()
    for path in paths:
        try:
            spec = yaml.load(path.read_text(encoding="utf8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
            row = score_metadata(spec)
            if row["cue_id"] in identities:
                raise ValueError(f"duplicate score id {row['cue_id']}")
        except (ValueError, yaml.YAMLError) as error:
            raise ValueError(f"{path}: {error}") from error
        identities.add(row["cue_id"])
        scores.append({**row, "source": path.name})
    return {"schema": INVENTORY_SCHEMA, "scores": sorted(scores, key=lambda row: row["cue_id"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores-dir", type=Path, help="source directory; defaults to scores/active")
    args = parser.parse_args()
    try:
        print(json.dumps(score_inventory(args.scores_dir), indent=2, sort_keys=True))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
