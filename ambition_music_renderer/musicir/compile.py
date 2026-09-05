"""Single dispatch point from authored MusicIR to :class:`CompiledScore`."""

from __future__ import annotations

from typing import Any, Mapping

from ..profiler import profile
from .model import CompiledScore
from .normalize import MUSICIR_V1_SCHEMA, MUSICIR_V2_SCHEMA, normalize_musicir_spec


@profile
def compile_score(
    spec: Mapping[str, Any],
    *,
    strict_schema: bool = False,
) -> CompiledScore:
    """Normalize, compile, and consistency-check one MusicIR score."""

    normalized = normalize_musicir_spec(spec, strict_schema=strict_schema)
    if normalized.canonical_schema == MUSICIR_V2_SCHEMA:
        from ..render.exact_score import compile_exact_score

        compiled = compile_exact_score(
            normalized.spec,
            source_schema=normalized.source_schema,
            normalization_warnings=normalized.warnings,
        )
    elif normalized.canonical_schema == MUSICIR_V1_SCHEMA:
        from ..render.score_layers import compile_procedural_score

        compiled = compile_procedural_score(
            normalized.spec,
            source_schema=normalized.source_schema,
            normalization_warnings=normalized.warnings,
        )
    else:  # pragma: no cover - normalization owns the supported schema set.
        raise AssertionError(f"unhandled canonical schema {normalized.canonical_schema!r}")
    compiled.assert_internal_consistency()
    compiled.attach_legacy_metadata()
    return compiled
