"""Normalize MusicIR compatibility spellings at one source boundary.

The renderer historically accepted a loose collection of schema spellings and
instrument-backend aliases.  Consumers then reinterpreted those aliases in
several places.  This module is the compatibility firewall: production
compilation receives a canonical schema and canonical backend mapping while the
original source remains available for diagnostics/provenance.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from ..instrument_resolution import normalize_backend_spec


MUSICIR_V1_SCHEMA = "ambition.musicir.v1"
MUSICIR_V2_SCHEMA = "ambition.musicir.v2"
LEGACY_V1_SCHEMA = "ambition.music.v1"
SUPPORTED_SCHEMAS = frozenset({MUSICIR_V1_SCHEMA, MUSICIR_V2_SCHEMA})


@dataclass(frozen=True)
class NormalizedMusicIR:
    """One source score after compatibility normalization."""

    spec: dict[str, Any]
    source_schema: str | None
    canonical_schema: str
    warnings: tuple[str, ...] = ()


def _normalize_instrument(instrument: Mapping[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(dict(instrument))
    raw_backend = row.get("instrument_backend", row.get("backend"))
    if raw_backend is None and row.get("sfz"):
        raw_backend = {"kind": "sfz", "sfz": row.get("sfz")}
    if raw_backend is not None:
        # Keep compatibility keys in the normalized row for now because a few
        # non-render authoring tools still display them.  All semantic consumers
        # should use instrument_backend from this point onward.
        row["instrument_backend"] = normalize_backend_spec(raw_backend)
    return row


def normalize_musicir_spec(
    spec: Mapping[str, Any],
    *,
    strict_schema: bool = False,
) -> NormalizedMusicIR:
    """Return a canonical copy of one MusicIR mapping.

    Compatibility behavior is intentionally non-destructive during this
    migration.  Missing/unknown schemas retain the historical v1 fallback when
    ``strict_schema`` is false, but the result carries a warning.  Validation
    and CI can opt into strict schema rejection before production compilation
    changes behavior.
    """

    if not isinstance(spec, Mapping):
        raise TypeError(f"MusicIR score must be a mapping, got {type(spec).__name__}")
    out = copy.deepcopy(dict(spec))
    source_schema_raw = out.get("schema")
    source_schema = None if source_schema_raw is None else str(source_schema_raw)
    warnings: list[str] = []

    if source_schema == MUSICIR_V2_SCHEMA:
        canonical_schema = MUSICIR_V2_SCHEMA
    elif source_schema == MUSICIR_V1_SCHEMA:
        canonical_schema = MUSICIR_V1_SCHEMA
    elif source_schema == LEGACY_V1_SCHEMA:
        if strict_schema:
            raise ValueError(
                f"deprecated MusicIR schema {LEGACY_V1_SCHEMA!r}; use "
                f"{MUSICIR_V1_SCHEMA!r}"
            )
        canonical_schema = MUSICIR_V1_SCHEMA
        warnings.append(
            f"deprecated schema {LEGACY_V1_SCHEMA!r}; use {MUSICIR_V1_SCHEMA!r}"
        )
    elif source_schema is None:
        if strict_schema:
            raise ValueError(
                f"MusicIR score is missing schema; expected one of {sorted(SUPPORTED_SCHEMAS)}"
            )
        canonical_schema = MUSICIR_V1_SCHEMA
        warnings.append(
            f"missing schema interpreted as {MUSICIR_V1_SCHEMA!r} for compatibility"
        )
    else:
        if strict_schema:
            raise ValueError(
                f"unsupported MusicIR schema {source_schema!r}; expected one of "
                f"{sorted(SUPPORTED_SCHEMAS)}"
            )
        # Preserve the historical build_score contract while making the
        # fallback visible.  This branch can be removed after the corpus and
        # external score producers pass strict validation.
        canonical_schema = MUSICIR_V1_SCHEMA
        warnings.append(
            f"unknown schema {source_schema!r} interpreted as {MUSICIR_V1_SCHEMA!r} "
            "for compatibility"
        )

    out["schema"] = canonical_schema
    instruments = out.get("instruments") or []
    if not isinstance(instruments, list):
        raise TypeError("MusicIR instruments must be a list")
    out["instruments"] = [
        _normalize_instrument(item) if isinstance(item, Mapping) else copy.deepcopy(item)
        for item in instruments
    ]
    return NormalizedMusicIR(
        spec=out,
        source_schema=source_schema,
        canonical_schema=canonical_schema,
        warnings=tuple(warnings),
    )
