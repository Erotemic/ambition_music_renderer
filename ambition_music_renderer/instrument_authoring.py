"""Agent-facing instrument-family guidance and canonical audition material."""
from __future__ import annotations

import copy
import functools
import hashlib
import json
from fractions import Fraction
from importlib import resources
from pathlib import Path
from typing import Any

from .instrument_catalog import describe_instrument, instrument_catalog, load_instrument_catalog_document
from .render.score_theory import note_to_midi

FAMILY_PROFILE_SCHEMA = "ambition.instrument_family_profiles.v1"
INSTRUMENT_INDEX_SCHEMA = "ambition.instrument_authoring_index.v1"


def _profile_resource():
    return resources.files("ambition_music_renderer").joinpath("data/instrument_family_profiles.json")


@functools.lru_cache(maxsize=1)
def instrument_family_profiles() -> dict[str, dict[str, Any]]:
    data = json.loads(_profile_resource().read_text(encoding="utf8"))
    if data.get("schema") != FAMILY_PROFILE_SCHEMA:
        raise ValueError("instrument family profile schema mismatch")
    return {str(k): copy.deepcopy(dict(v)) for k, v in (data.get("families") or {}).items()}


def instrument_authoring_description(ref: str) -> dict[str, Any]:
    result = describe_instrument(ref)
    family = str(result.get("family") or "other")
    profile = instrument_family_profiles().get(family)
    if profile:
        result["family_profile"] = copy.deepcopy(profile)
    return result


def canonical_audition_score(ref: str) -> dict[str, Any]:
    """Build a small v3 score that compares one catalog instrument consistently."""

    entry = instrument_catalog().get(ref)
    if entry is None:
        raise KeyError(ref)
    profile = instrument_family_profiles().get(entry.family)
    if profile is None:
        raise ValueError(f"instrument family {entry.family!r} has no canonical audition profile")
    instrument: dict[str, Any] = {
        "name": "audition",
        "group": "audition",
        "program": "acoustic_grand_piano",
        **entry.authoring_snippet(),
    }
    clips: list[dict[str, Any]] = []
    audition = profile.get("audition") or {}
    if entry.is_drum or audition.get("drums"):
        events = []
        drum_phrase = audition.get("drums") or [
            [0.0, "kick", 92], [1.0, "snare", 88], [2.0, "kick", 96], [3.0, "snare", 92],
            [4.0, "kick", 98], [5.0, "snare", 94], [6.0, "kick", 102], [7.0, "snare", 100],
        ]
        for index, (beat, drum, velocity) in enumerate(drum_phrase):
            events.append({
                "id": f"drum_{index:02d}",
                "at": {"beats": float(beat)},
                "dur": "1/16",
                "pitch": {"kind": "drum", "name": str(drum)},
                "velocity": int(velocity),
            })
        clips.append({"id": "canonical_drum_phrase", "at": {"bar": 1, "beat": 1}, "events": events})
        end = {"bar": 3, "beat": 1}
    else:
        base = note_to_midi(str(audition.get("base", "C4")))
        intervals = list(audition.get("intervals") or [0, 2, 4, 5, 7, 9, 11, 12])
        durations = list(audition.get("durations") or [0.25] * len(intervals))
        events = []
        beat = Fraction(0)
        for index, interval in enumerate(intervals):
            duration = Fraction(str(durations[index % len(durations)]))
            events.append({
                "id": f"phrase_{index:02d}",
                "at": {"beats": str(beat)},
                "dur": {"beats": str(duration)},
                "pitch": int(base + int(interval)),
                "velocity": 72 + (index % 4) * 5,
            })
            beat += duration
        chord = [int(base + int(interval)) for interval in audition.get("chord", [0, 4, 7, 12])]
        events.append({
            "id": "closing_chord", "at": {"beats": str(beat + Fraction(1, 2))}, "dur": {"beats": 2},
            "pitches": chord, "velocity": 82,
        })
        clips.append({
            "id": "canonical_phrase", "at": {"bar": 1, "beat": 1}, "events": events,
            "automation": [{
                "id": "expression_shape", "cc": "expression", "points": [[0, 82], [{"beats": str(max(Fraction(1), beat / 2))}, 108], [{"beats": str(beat + Fraction(5, 2))}, 88]],
                "interpolation": "smooth", "resolution": "1/16",
            }],
        })
        end = {"bar": 4, "beat": 1}
    return {
        "schema": "ambition.musicir.v3",
        "id": f"audition_{ref.replace('.', '_')}",
        "title": f"Canonical audition: {ref}",
        "timebase": {"ppq": 480},
        "meter": "4/4",
        "tempo": 108,
        "end": end,
        "instruments": [instrument],
        "parts": [{"id": "audition_part", "instrument": "audition", "voices": [{"id": "main", "clips": clips}]}],
    }


def build_instrument_authoring_index() -> dict[str, Any]:
    """Build the dependency-free JSON mirror from the normative YAML catalog."""

    doc = load_instrument_catalog_document()
    # Hash semantic JSON rather than YAML formatting so harmless reflow does not
    # force the derived source-only index to change.
    catalog_hash = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    rows = {}
    for ref in sorted(instrument_catalog()):
        rows[ref] = instrument_authoring_description(ref)
    return {
        "schema": INSTRUMENT_INDEX_SCHEMA,
        "generated_from": "instrument_catalog.yaml + instrument_family_profiles.json",
        "catalog_semantic_sha256": catalog_hash,
        "instrument_count": len(rows),
        "instruments": rows,
        "family_profiles": instrument_family_profiles(),
    }
