"""Schema-aware validation for both MusicIR authoring frontends.

Validation deliberately compiles through the same canonical pipeline used by
rendering.  It can run in compatibility mode during migration or in strict
schema mode for CI/authoring checks without changing production behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..musicir.compile import compile_score
from ..musicir.model import compiled_score_fingerprint
from ..musicir.normalize import MUSICIR_V2_SCHEMA, normalize_musicir_spec
from .exact_score import find_external_score_dependencies


def validate_musicir_spec(
    spec: Mapping[str, Any],
    *,
    source: str | Path | None = None,
    strict_schema: bool = False,
    require_self_contained: bool = True,
) -> dict[str, Any]:
    """Compile and summarize any supported MusicIR score.

    ``strict_schema=False`` mirrors production compatibility behavior while
    reporting normalization warnings.  Set it true in CI to reject missing,
    deprecated, or unknown schema spellings once a caller is ready to migrate.
    """

    normalized = normalize_musicir_spec(spec, strict_schema=strict_schema)
    dependencies: list[dict[str, Any]] = []
    if normalized.canonical_schema == MUSICIR_V2_SCHEMA:
        dependencies = find_external_score_dependencies(normalized.spec)
        if require_self_contained and dependencies:
            paths = ", ".join(item["path"] for item in dependencies)
            raise ValueError(
                f"exact score has external symbolic-score dependencies: {paths}"
            )

    compiled = compile_score(spec, strict_schema=strict_schema)
    musical_events = [
        event
        for event in compiled.note_events
        if str(event.get("event_type", "note")) == "note"
    ]
    return {
        "schema": "ambition.musicir_validation.v1",
        "score_id": str(compiled.normalized_spec.get("id", "")),
        "score_path": str(source) if source is not None else None,
        "source_schema": compiled.source_schema,
        "canonical_schema": compiled.canonical_schema,
        "compiled_score_schema": "ambition.compiled_score.v1",
        "compiled_score_fingerprint": compiled_score_fingerprint(compiled),
        "normalization_warnings": list(compiled.normalization_warnings),
        "strict_schema": bool(strict_schema),
        "self_contained": not dependencies,
        "external_score_dependencies": len(dependencies),
        "external_score_dependency_fields": dependencies,
        "instruments": len(compiled.pm.instruments),
        "groups": list(compiled.group_names),
        "sections": len(compiled.sections),
        "note_events": len(musical_events),
        "control_events": len(compiled.note_events) - len(musical_events),
        "duration_seconds": compiled.duration_seconds,
        "midi_resolution": int(compiled.pm.resolution),
        "exact": dict(compiled.exact_metadata or {}),
    }


def validate_musicir_file(
    path: str | Path,
    *,
    strict_schema: bool = False,
    require_self_contained: bool = True,
) -> dict[str, Any]:
    score_path = Path(path)
    spec = yaml.safe_load(score_path.read_text(encoding="utf8")) or {}
    if not isinstance(spec, Mapping):
        raise ValueError(f"{score_path} does not contain a MusicIR mapping")
    return validate_musicir_spec(
        spec,
        source=score_path,
        strict_schema=strict_schema,
        require_self_contained=require_self_contained,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path)
    parser.add_argument("--strict-schema", action="store_true")
    parser.add_argument("--allow-external-score", action="store_true")
    args = parser.parse_args(argv)
    report = validate_musicir_file(
        args.score,
        strict_schema=bool(args.strict_schema),
        require_self_contained=not bool(args.allow_external_score),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
