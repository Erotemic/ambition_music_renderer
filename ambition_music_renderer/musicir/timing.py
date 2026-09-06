"""Shared source-timing accessors for MusicIR compatibility consumers.

These helpers exist for code that still needs one representative tempo or
bar-width scalar (manifests, legacy-style audits, cache metadata, transition
windows). They preserve historical v1 mapping behavior while accepting v2/v3
source spellings. Exact-score consumers should continue using ``ScoreClock``
and ``ExactTempoMap`` for time-varying meter/tempo semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .normalize import MUSICIR_V3_SCHEMA, normalize_musicir_spec


def _signature_quarter_beats(signature: str) -> float:
    text = str(signature).strip()
    if "/" not in text:
        raise ValueError(f"invalid meter signature {signature!r}; expected N/D")
    numerator_text, denominator_text = text.split("/", 1)
    numerator = int(numerator_text)
    denominator = int(denominator_text)
    if numerator <= 0 or denominator <= 0:
        raise ValueError(f"invalid meter signature {signature!r}")
    return float(numerator) * 4.0 / float(denominator)


def initial_bpm(spec: Mapping[str, Any], default: float = 120.0) -> float:
    """Return the score's initial BPM without assuming a v1 tempo mapping."""

    normalized = normalize_musicir_spec(spec).spec
    tempo = normalized.get("tempo")
    if isinstance(tempo, (int, float)):
        return float(tempo)
    if isinstance(tempo, Mapping):
        for key in ("bpm", "initial"):
            if tempo.get(key) is not None:
                return float(tempo[key])
        events = tempo.get("events") or tempo.get("map") or []
        if isinstance(events, Sequence) and not isinstance(events, (str, bytes)):
            for row in events:
                if isinstance(row, Mapping) and row.get("bpm") is not None:
                    return float(row["bpm"])
    if isinstance(tempo, Sequence) and not isinstance(tempo, (str, bytes)):
        for row in tempo:
            if isinstance(row, Mapping) and row.get("bpm") is not None:
                return float(row["bpm"])
    if normalized.get("bpm") is not None:
        return float(normalized["bpm"])
    return float(default)


def initial_beats_per_bar(spec: Mapping[str, Any], default: float = 4.0) -> float:
    """Return initial bar width in the score's quarter-note beat coordinate.

    Historical v1 mappings keep their exact ``beats_per_bar`` value so legacy
    audits/manifests do not change. V3 signatures are converted to quarter-note
    beats because v2/v3 compiled ``start_beat`` coordinates use quarter notes.
    """

    normalized = normalize_musicir_spec(spec).spec
    meter = normalized.get("meter")
    if isinstance(meter, Mapping) and meter.get("beats_per_bar") is not None:
        return float(meter["beats_per_bar"])
    if isinstance(meter, str):
        return _signature_quarter_beats(meter)
    if isinstance(meter, Mapping):
        if meter.get("signature") is not None:
            return _signature_quarter_beats(str(meter["signature"]))
        rows = meter.get("map") or []
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                if row.get("beats_per_bar") is not None:
                    beats = float(row["beats_per_bar"])
                    if normalized.get("schema") == MUSICIR_V3_SCHEMA:
                        denominator = float(row.get("beat_unit", 4))
                        return beats * 4.0 / denominator
                    return beats
                if row.get("signature") is not None:
                    return _signature_quarter_beats(str(row["signature"]))
    if isinstance(meter, Sequence) and not isinstance(meter, (str, bytes)):
        for row in meter:
            if isinstance(row, Mapping):
                if row.get("signature") is not None:
                    return _signature_quarter_beats(str(row["signature"]))
                if row.get("beats_per_bar") is not None:
                    beats = float(row["beats_per_bar"])
                    denominator = float(row.get("beat_unit", 4))
                    return beats * 4.0 / denominator
    return float(default)
