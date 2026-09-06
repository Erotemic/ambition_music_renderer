#!/usr/bin/env python3
"""Compile every committed legacy MusicIR score as a regeneration smoke gate.

This is a corpus *regeneration* gate, not a per-song acceptance snapshot.  It
ensures all durable v1/v2/implicit-v1 sources still compile through the current
canonical boundary. Pass ``--rounds >1`` for an optional heavier determinism
sweep. When a broad
compiler refactor needs exact semantic drift evidence, compare this report
against a report generated from the pre-change tree rather than checking named
song fingerprints into the test suite.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.model import compiled_score_fingerprint

SCHEMA = "ambition.legacy_regeneration_check.v2"
LEGACY_SCHEMAS = {None, "ambition.musicir.v1", "ambition.music.v1", "ambition.musicir.v2"}


def repo_root() -> Path:
    return ROOT


def score_paths() -> list[Path]:
    root = repo_root() / "scores"
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and (p.name.endswith(".music.yaml") or p.name.endswith(".music.yml"))
    )


def check_legacy_scores(*, rounds: int = 1) -> dict:
    if rounds < 1:
        raise ValueError("rounds must be >= 1")
    rows = []
    failures = []
    for path in score_paths():
        spec = yaml.safe_load(path.read_text(encoding="utf8"))
        schema = spec.get("schema") if isinstance(spec, dict) else None
        if schema not in LEGACY_SCHEMAS:
            continue
        fingerprints = []
        first_notes = None
        first_controls = None
        try:
            for _ in range(rounds):
                compiled = compile_score(copy.deepcopy(spec))
                fingerprints.append(compiled_score_fingerprint(compiled))
                if first_notes is None:
                    first_notes = compiled.note_events
                    first_controls = compiled.controller_events
                elif compiled.note_events != first_notes or compiled.controller_events != first_controls:
                    raise AssertionError("canonical events changed between compilation rounds")
            if len(set(fingerprints)) != 1:
                raise AssertionError(f"compiled fingerprints changed between rounds: {fingerprints}")
        except Exception as ex:
            failures.append({
                "path": path.relative_to(repo_root()).as_posix(),
                "id": str((spec or {}).get("id") or path.stem),
                "source_schema": schema,
                "error": f"{type(ex).__name__}: {ex}",
            })
            continue
        rows.append({
            "path": path.relative_to(repo_root()).as_posix(),
            "id": str(spec.get("id") or path.stem),
            "source_schema": schema,
            # Included in an optional ephemeral report for explicit pre/post
            # comparison. This value is not a checked-in named-song fixture.
            "compiled_score_sha256": fingerprints[0],
        })
    return {
        "schema": SCHEMA,
        "rounds": rounds,
        "score_count": len(rows) + len(failures),
        "passed": len(rows),
        "failed": len(failures),
        "scores": rows,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=1, help="compile rounds per score; use >1 for a heavier determinism sweep")
    parser.add_argument(
        "--json-out", type=Path,
        help="optional ephemeral report for an explicit pre/post refactor comparison",
    )
    args = parser.parse_args()
    report = check_legacy_scores(rounds=args.rounds)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8")
    if report["failures"]:
        for row in report["failures"]:
            print(f"{row['path']}: {row['error']}", file=sys.stderr)
        return 1
    print(
        f"legacy regeneration OK: {report['passed']} scores compiled "
        f"across {report['rounds']} round(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
