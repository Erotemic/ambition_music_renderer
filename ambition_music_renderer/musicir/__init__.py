"""Canonical MusicIR normalization and compilation interfaces."""

from .compile import compile_score
from .model import CompiledScore, compiled_score_payload, compiled_score_fingerprint
from .normalize import (
    LEGACY_V1_SCHEMA,
    MUSICIR_V1_SCHEMA,
    MUSICIR_V2_SCHEMA,
    NormalizedMusicIR,
    normalize_musicir_spec,
)

__all__ = [
    "CompiledScore",
    "LEGACY_V1_SCHEMA",
    "MUSICIR_V1_SCHEMA",
    "MUSICIR_V2_SCHEMA",
    "NormalizedMusicIR",
    "compile_score",
    "compiled_score_fingerprint",
    "compiled_score_payload",
    "normalize_musicir_spec",
]
