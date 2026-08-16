"""Generic offline validation for self-contained MusicIR v2 exact scores.

The validator knows nothing about individual compositions.  It verifies the
MusicIR contract, rejects symbolic-score dependencies that would make a score
non-self-contained, compiles the YAML through the normal renderer path, and
reports structural metrics useful to acceptance tests and authoring tools.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from ambition_music_renderer.render.exact_score import EXACT_SCHEMA
from ambition_music_renderer.render.score_layers import build_score


_EXTERNAL_SCORE_KEYS = frozenset(
    {
        "download_url",
        "external_score",
        "external_score_path",
        "external_score_url",
        "midi_path",
        "musicxml_path",
        "mxl_path",
        "score_file",
        "score_path",
        "score_url",
        "source_midi",
        "source_musicxml",
        "source_mxl",
        "source_score",
        "source_score_path",
        "source_score_url",
        "source_url",
    }
)


def find_external_score_dependencies(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return render-time symbolic-score dependency fields found in ``spec``.

    Instrument/sample library references are deliberately not considered score
    dependencies: installed sound libraries are part of the renderer runtime.
    This check targets external symbolic composition data such as MIDI,
    MusicXML, downloaded score files, or URLs that a score would need in order
    to reconstruct its notes.
    """

    found: list[dict[str, Any]] = []

    def walk(value: Any, path: tuple[str, ...], *, metadata_only: bool = False) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key)
                child_path = (*path, key)
                child_metadata_only = metadata_only or key.lower() in {"provenance", "authoring"}
                if (
                    not child_metadata_only
                    and key.lower() in _EXTERNAL_SCORE_KEYS
                    and child not in (None, "", [], {})
                ):
                    found.append({"path": ".".join(child_path), "value": child})
                walk(child, child_path, metadata_only=child_metadata_only)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*path, str(index)), metadata_only=metadata_only)

    walk(spec, ())
    return found


def validate_exact_score_spec(
    spec: dict[str, Any],
    *,
    source: str | Path | None = None,
    require_self_contained: bool = True,
) -> dict[str, Any]:
    """Compile and summarize an arbitrary MusicIR v2 exact score.

    ``require_self_contained`` is true by default because a committed exact
    score is expected to contain all symbolic composition data needed to
    render.  Validation uses the same ``build_score`` path as production
    rendering rather than a parallel parser.
    """

    if spec.get("schema") != EXACT_SCHEMA:
        raise ValueError(f"expected {EXACT_SCHEMA!r}, got {spec.get('schema')!r}")

    dependencies = find_external_score_dependencies(spec)
    if require_self_contained and dependencies:
        paths = ", ".join(item["path"] for item in dependencies)
        raise ValueError(f"exact score has external symbolic-score dependencies: {paths}")

    pm, groups, sections = build_score(spec)
    events = list(pm._ambition_note_events)  # type: ignore[attr-defined]
    exact = dict(pm._ambition_exact_score)  # type: ignore[attr-defined]
    end_tick = int(exact["end_tick"])
    duration_seconds = max((float(event["end_time"]) for event in events), default=0.0)

    return {
        "score_id": str(spec.get("id", "")),
        "score_path": str(source) if source is not None else None,
        "schema": str(spec["schema"]),
        "self_contained": not dependencies,
        "external_score_dependencies": len(dependencies),
        "external_score_dependency_fields": dependencies,
        "ppq": int(exact["ppq"]),
        "end_tick": end_tick,
        "duration_seconds": duration_seconds,
        "note_events": len(events),
        "instruments": len(pm.instruments),
        "groups": sorted(set(groups.values())),
        "parts": len(spec.get("parts") or []),
        "voices": sum(len(part.get("voices") or []) for part in spec.get("parts") or []),
        "form_regions": [section["id"] for section in sections],
        "meter_changes": len(exact.get("meter_changes") or []),
        "tempo_segments": len(exact.get("tempo_segments") or []),
        "holds": len(exact.get("holds") or []),
    }


def validate_exact_score_file(
    path: str | Path,
    *,
    require_self_contained: bool = True,
) -> dict[str, Any]:
    """Load and validate a MusicIR v2 YAML file."""

    score_path = Path(path)
    spec = yaml.safe_load(score_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"{score_path} does not contain a MusicIR mapping")
    return validate_exact_score_spec(
        spec,
        source=score_path,
        require_self_contained=require_self_contained,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path, help="self-contained MusicIR v2 YAML to validate")
    args = parser.parse_args(argv)
    report = validate_exact_score_file(args.score)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
