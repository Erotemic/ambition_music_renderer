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
from ..musicir.normalize import MUSICIR_V2_SCHEMA, MUSICIR_V3_SCHEMA, normalize_musicir_spec
from .exact_score import find_external_score_dependencies
from .diagnostics import (
    MusicIRValidationError,
    diagnostic,
    yaml_location_map,
)
from .v3 import diagnose_v3_spec


def validate_musicir_spec(
    spec: Mapping[str, Any],
    *,
    source: str | Path | None = None,
    strict_schema: bool = False,
    require_self_contained: bool = True,
    source_locations=None,
) -> dict[str, Any]:
    """Compile and summarize any supported MusicIR score.

    ``strict_schema=False`` mirrors production compatibility behavior while
    reporting normalization warnings.  Set it true in CI to reject missing,
    deprecated, or unknown schema spellings once a caller is ready to migrate.
    """

    normalized = normalize_musicir_spec(spec, strict_schema=strict_schema)
    source_diagnostics = []
    if normalized.canonical_schema == MUSICIR_V3_SCHEMA:
        source_diagnostics = diagnose_v3_spec(
            normalized.spec, locations=source_locations or {}
        )
        errors = [item for item in source_diagnostics if item.severity == "error"]
        if errors:
            raise MusicIRValidationError(errors, source=source)

    dependencies: list[dict[str, Any]] = []
    if normalized.canonical_schema == MUSICIR_V2_SCHEMA:
        dependencies = find_external_score_dependencies(normalized.spec)
        if require_self_contained and dependencies:
            paths = ", ".join(item["path"] for item in dependencies)
            raise ValueError(
                f"exact score has external symbolic-score dependencies: {paths}"
            )

    try:
        compiled = compile_score(spec, strict_schema=strict_schema)
    except MusicIRValidationError:
        raise
    except Exception as ex:
        if normalized.canonical_schema == MUSICIR_V3_SCHEMA:
            raise MusicIRValidationError(
                [
                    diagnostic(
                        "V3_COMPILE",
                        f"canonical compilation failed: {ex}",
                        locations=source_locations or {},
                        hint="run `cue expand --json` after fixing validation errors to inspect the lowered events",
                    )
                ],
                source=source,
            ) from ex
        raise
    musical_events = [
        event
        for event in compiled.note_events
        if str(event.get("event_type", "note")) == "note"
    ]
    v3_summary: dict[str, Any] | None = None
    if compiled.canonical_schema == MUSICIR_V3_SCHEMA and compiled.authoring_graph:
        graph = compiled.authoring_graph
        v3_summary = {
            "authoring_graph_fingerprint": compiled.authoring_graph_fingerprint,
            "materials": len(graph.get("materials") or {}),
            "parts": len(graph.get("parts") or []),
            "clips": sum(
                len(voice.get("clips") or [])
                for part in graph.get("parts") or []
                for voice in part.get("voices") or []
            ),
            "generator_clips": sum(
                1
                for part in graph.get("parts") or []
                for voice in part.get("voices") or []
                for clip in voice.get("clips") or []
                if "generate" in clip
            ),
            "automation_points": sum(
                len(clip.get("automation") or [])
                for part in graph.get("parts") or []
                for voice in part.get("voices") or []
                for clip in voice.get("clips") or []
            ),
        }

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
        "control_events": (
            len(compiled.note_events) - len(musical_events) + len(compiled.controller_events)
        ),
        "duration_seconds": compiled.duration_seconds,
        "midi_resolution": int(compiled.pm.resolution),
        "exact": dict(compiled.exact_metadata or {}),
        "v3": v3_summary,
        "diagnostics": [item.as_dict() for item in source_diagnostics],
    }


def validate_musicir_file(
    path: str | Path,
    *,
    strict_schema: bool = False,
    require_self_contained: bool = True,
) -> dict[str, Any]:
    score_path = Path(path)
    text = score_path.read_text(encoding="utf8")
    try:
        spec = yaml.safe_load(text) or {}
        locations = yaml_location_map(text)
    except yaml.YAMLError as ex:
        mark = getattr(ex, "problem_mark", None)
        message = getattr(ex, "problem", None) or str(ex)
        item = diagnostic("YAML_PARSE", message)
        if mark is not None:
            from .diagnostics import SourceLocation, Diagnostic

            item = Diagnostic(
                code=item.code,
                severity=item.severity,
                message=item.message,
                path=item.path,
                location=SourceLocation(mark.line + 1, mark.column + 1),
                hint="fix the YAML syntax before MusicIR validation can continue",
            )
        raise MusicIRValidationError([item], source=score_path) from ex
    if not isinstance(spec, Mapping):
        raise MusicIRValidationError(
            [diagnostic("MUSICIR_ROOT", "score document must be a YAML mapping", locations=locations)],
            source=score_path,
        )
    return validate_musicir_spec(
        spec,
        source=score_path,
        strict_schema=strict_schema,
        require_self_contained=require_self_contained,
        source_locations=locations,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path)
    parser.add_argument("--strict-schema", action="store_true")
    parser.add_argument("--allow-external-score", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = validate_musicir_file(
            args.score,
            strict_schema=bool(args.strict_schema),
            require_self_contained=not bool(args.allow_external_score),
        )
    except MusicIRValidationError as ex:
        print(ex.format())
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
