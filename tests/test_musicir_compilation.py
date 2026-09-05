"""Migration-safety tests for canonical MusicIR compilation.

These are renderer-contract fixtures, not song tests.  The frozen snapshots were
captured from the pre-CompiledScore renderer and cover both authoring frontends.
They intentionally compare the synthesis/form inputs that determine audible
music: notes, velocities, timing, controllers, pitch bends, groups, section
boundaries, MIDI resolution, and exact-score clock metadata.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.model import CompiledScore, compiled_score_fingerprint
from ambition_music_renderer.musicir.normalize import (
    LEGACY_V1_SCHEMA,
    MUSICIR_V1_SCHEMA,
    MUSICIR_V2_SCHEMA,
    normalize_musicir_spec,
)
from ambition_music_renderer.validation.musicir import validate_musicir_spec
from ambition_music_renderer.render.group import build_manifest, render_group_audio
from ambition_music_renderer.render.score_layers import build_score


DATA_DPATH = Path(__file__).parent / "data"


def _v1_contract_spec() -> dict:
    return {
        "schema": MUSICIR_V1_SCHEMA,
        "id": "renderer_migration_v1_contract",
        "seed": 13,
        "tempo": {"bpm": 120, "map": [{"bar": 1, "bpm": 90, "ramp_bars": 1}]},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {
                "name": "keys",
                "group": "harmony",
                "program": "acoustic_grand_piano",
                "volume": 103,
                "pan": 58,
                "expression": 109,
                "controls": {64: 0},
            },
            {
                "name": "bass",
                "group": "bass",
                "program": "fingered_bass",
                "volume": 97,
                "pan": 64,
            },
            {"name": "kit", "group": "drums", "is_drum": True, "volume": 105},
        ],
        "motifs": [
            {
                "id": "figure",
                "root": "C4",
                "intervals": [0, 2, 4],
                "rhythm": [0.5, 0.5, 1.0],
                "durations": [0.45, 0.45, 0.9],
                "velocities": [1.0, 0.9, 1.05],
            },
        ],
        "sections": [
            {
                "id": "main",
                "bars": 2,
                "harmony": ["C", "Am"],
                "layers": [
                    {
                        "kind": "motif",
                        "instrument": "keys",
                        "motif": "figure",
                        "starts": [[0, 0.0]],
                        "repeats": 2,
                        "every_bars": 1,
                        "velocity": 82,
                        "humanize_ms": 0,
                    },
                    {
                        "kind": "notes",
                        "instrument": "keys",
                        "notes": [
                            [0, 2.0, ["C4", "E4", "G4"], 1.5, 68],
                            {
                                "bar": 1,
                                "beat": 2.0,
                                "note": "E5",
                                "dur": 1.25,
                                "vel": 88,
                                "gate": 0.9,
                                "bend": [[0.0, 0], [0.5, 80], [1.0, 0]],
                            },
                        ],
                        "humanize_ms": 0,
                    },
                    {
                        "kind": "bassline",
                        "instrument": "bass",
                        "pattern": [[0, 0.0, 0.75], [7, 2.0, 0.5]],
                        "octave": 2,
                        "velocity": 76,
                        "humanize_ms": 0,
                    },
                    {
                        "kind": "drums",
                        "instrument": "kit",
                        "humanize_ms": 0,
                        "events": [
                            {"drum": "kick", "beats": [0.0, 2.0], "velocity": 94},
                            {"drum": "snare", "beats": [1.0, 3.0], "velocity": 86},
                        ],
                    },
                    {
                        "kind": "automation",
                        "instrument": "keys",
                        "automation": [
                            {
                                "cc": "brightness",
                                "from": 25,
                                "to": 95,
                                "curve": "smooth",
                                "points": 5,
                            },
                        ],
                    },
                ],
            }
        ],
    }


def _v2_contract_spec() -> dict:
    return {
        "schema": MUSICIR_V2_SCHEMA,
        "id": "renderer_migration_v2_contract",
        "instruments": [
            {
                "name": "piano",
                "group": "keys",
                "program": "acoustic_grand_piano",
                "volume": 101,
                "pan": 66,
                "expression": 111,
                "controls": {64: 0},
            },
        ],
        "score": {
            "timebase": {"ppq": 480},
            "meter": [
                {"bar": 1, "signature": "4/4"},
                {"bar": 3, "signature": "3/4"},
            ],
            "tempo": [
                {"tick": 0, "bpm": 120.0},
                {"tick": 960, "bpm": 96.0},
            ],
            "phrases": [
                {
                    "id": "figure",
                    "events": [
                        [0, 240, "C4", 80],
                        [240, 240, "E4", 84],
                        [480, 480, "G4", 88],
                    ],
                },
            ],
            "form": [
                {
                    "id": "a",
                    "from": {"bar": 1, "beat": 1},
                    "to": {"bar": 2, "beat": 1},
                },
                {
                    "id": "b",
                    "from": {"bar": 2, "beat": 1},
                    "to": {"bar": 4, "beat": 1},
                },
            ],
            "end": {"bar": 4, "beat": 1},
        },
        "parts": [
            {
                "id": "piano_part",
                "instrument": "piano",
                "controls": [
                    {"tick": 0, "cc": "sustain", "value": 0},
                    {"tick": 720, "cc": 64, "value": 127},
                    {"tick": 1440, "cc": 64, "value": 0},
                ],
                "voices": [
                    {
                        "id": "right",
                        "sequence": [
                            {"phrase": "figure", "at": {"bar": 1, "beat": 1}},
                            {
                                "phrase": "figure",
                                "at": {"bar": 2, "beat": 1},
                                "transpose": 2,
                                "velocity_scale": 0.9,
                            },
                        ],
                        "events": [
                            {
                                "at": {"bar": 3, "beat": 1},
                                "dur": "1/2",
                                "pitches": ["C4", "E4", "A4"],
                                "velocity": 76,
                                "gate": 0.95,
                            },
                        ],
                    },
                ],
            }
        ],
    }


def _round(value: float) -> float:
    return round(float(value), 9)


def _render_contract(compiled: CompiledScore) -> dict:
    return {
        "resolution": int(compiled.pm.resolution),
        "instruments": [
            {
                "name": str(inst.name),
                "program": int(inst.program),
                "is_drum": bool(inst.is_drum),
                "notes": sorted(
                    [
                        _round(note.start),
                        _round(note.end),
                        int(note.pitch),
                        int(note.velocity),
                    ]
                    for note in inst.notes
                ),
                "control_changes": sorted(
                    [_round(cc.time), int(cc.number), int(cc.value)]
                    for cc in inst.control_changes
                ),
                "pitch_bends": sorted(
                    [_round(pb.time), int(pb.pitch)] for pb in inst.pitch_bends
                ),
            }
            for inst in compiled.pm.instruments
        ],
        "groups": compiled.groups,
        "sections": compiled.sections,
        "exact_metadata": compiled.exact_metadata,
    }


def test_compiled_v1_matches_pre_refactor_synthesis_contract():
    expected = json.loads(
        (DATA_DPATH / "generic_musicir_migration_contract.json").read_text()
    )["v1"]
    compiled = compile_score(_v1_contract_spec())
    assert _render_contract(compiled) == expected


def test_compiled_v2_matches_pre_refactor_synthesis_contract():
    expected = json.loads(
        (DATA_DPATH / "generic_musicir_migration_contract.json").read_text()
    )["v2"]
    compiled = compile_score(_v2_contract_spec())
    assert _render_contract(compiled) == expected


def test_build_score_compatibility_metadata_is_derived_from_compiled_score():
    spec = _v1_contract_spec()
    compiled = compile_score(spec)
    pm, groups, sections = build_score(spec)
    assert groups == compiled.groups
    assert sections == compiled.sections
    assert list(pm._ambition_note_events) == compiled.note_events  # type: ignore[attr-defined]
    assert dict(pm._ambition_instrument_specs) == compiled.instrument_specs  # type: ignore[attr-defined]


def test_exact_events_have_canonical_note_event_type():
    compiled = compile_score(_v2_contract_spec())
    assert compiled.note_events
    assert {event["event_type"] for event in compiled.note_events} == {"note"}


def test_legacy_and_missing_schema_are_compatible_but_visible():
    old = _v1_contract_spec()
    old["schema"] = LEGACY_V1_SCHEMA
    compiled = compile_score(old)
    assert compiled.canonical_schema == MUSICIR_V1_SCHEMA
    assert compiled.source_schema == LEGACY_V1_SCHEMA
    assert compiled.normalization_warnings

    missing = _v1_contract_spec()
    missing.pop("schema")
    compiled_missing = compile_score(missing)
    assert compiled_missing.canonical_schema == MUSICIR_V1_SCHEMA
    assert compiled_missing.source_schema is None
    assert compiled_missing.normalization_warnings


def test_strict_validation_rejects_schema_compatibility_fallbacks():
    old = _v1_contract_spec()
    old["schema"] = LEGACY_V1_SCHEMA
    with pytest.raises(ValueError, match="unsupported|deprecated|expected"):
        validate_musicir_spec(old, strict_schema=True)

    missing = _v1_contract_spec()
    missing.pop("schema")
    with pytest.raises(ValueError, match="missing schema"):
        validate_musicir_spec(missing, strict_schema=True)

    unknown = _v1_contract_spec()
    unknown["schema"] = "ambition.musicir.v999"
    with pytest.raises(ValueError, match="unsupported MusicIR schema"):
        validate_musicir_spec(unknown, strict_schema=True)


def test_instrument_backend_aliases_normalize_once_without_mutating_source():
    spec = _v1_contract_spec()
    spec["instruments"][0]["backend"] = {
        "type": "sfizz",
        "library": "freepats.salamander_grand",
        "prefer_keywords": "piano",
    }
    original = copy.deepcopy(spec)
    normalized = normalize_musicir_spec(spec)
    assert spec == original
    backend = normalized.spec["instruments"][0]["instrument_backend"]
    assert backend["kind"] == "sfizz"
    assert backend["library_ref"] == "freepats.salamander_grand"
    assert backend["prefer"] == ["piano"]


def test_initial_controller_precedence_is_shared_between_v1_and_v2():
    v1 = _v1_contract_spec()
    v1["instruments"] = [
        {
            "name": "piano",
            "group": "keys",
            "program": "acoustic_grand_piano",
            "expression": 20,
            "controls": {11: 91},
        }
    ]
    v1["motifs"] = []
    v1["sections"] = [
        {
            "id": "a",
            "bars": 1,
            "harmony": ["C"],
            "layers": [
                {
                    "kind": "notes",
                    "instrument": "piano",
                    "notes": [[0, 0, "C4", 1, 80]],
                }
            ],
        }
    ]

    v2 = _v2_contract_spec()
    v2["instruments"] = copy.deepcopy(v1["instruments"])
    v2["parts"][0]["instrument"] = "piano"

    for compiled in (compile_score(v1), compile_score(v2)):
        values = [
            cc.value
            for cc in compiled.pm.instruments[0].control_changes
            if cc.time == 0.0 and cc.number == 11
        ]
        assert values == [91]


def test_validation_report_reads_compiled_semantics_directly():
    report = validate_musicir_spec(_v2_contract_spec(), strict_schema=True)
    assert report["canonical_schema"] == MUSICIR_V2_SCHEMA
    assert report["source_schema"] == MUSICIR_V2_SCHEMA
    assert report["note_events"] == 9
    assert report["sections"] == 2
    assert report["exact"]["ppq"] == 480
    assert report["normalization_warnings"] == []



def _procedural_audio_contract_spec() -> dict:
    return {
        "schema": MUSICIR_V1_SCHEMA,
        "id": "renderer_audio_migration_contract",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {
                "name": "lead",
                "group": "melody",
                "program": 80,
                "instrument_backend": {
                    "kind": "procedural_fm",
                    "carrier": {"waveform": "square", "harmonics": 9},
                    "fm": {"waveform": "sine", "ratio": 0.5, "index": 0.12},
                    "envelope": {
                        "attack_ms": 3,
                        "decay_ms": 25,
                        "sustain": 0.85,
                        "release_ms": 20,
                    },
                    "saturation_drive": 1.05,
                    "output_gain_db": -8,
                },
            }
        ],
        "sections": [
            {
                "id": "main",
                "bars": 1,
                "harmony": ["C"],
                "layers": [
                    {
                        "kind": "notes",
                        "instrument": "lead",
                        "humanize_ms": 0,
                        "notes": [
                            [0, 0.0, "A4", 0.5, 90],
                            [0, 1.0, "C5", 0.5, 82],
                        ],
                    }
                ],
            }
        ],
    }


def test_compiled_score_audio_path_matches_legacy_facade(tmp_path: Path):
    """Migration wiring must not change audio for the same compiled semantics."""
    spec = _procedural_audio_contract_spec()
    compiled = compile_score(spec)
    legacy_pm, legacy_groups, _ = build_score(spec)
    duration = compiled.sections[-1]["end_seconds"]

    legacy_audio = render_group_audio(
        legacy_pm,
        legacy_groups,
        "melody",
        "pretty-midi",
        "",
        24_000,
        tmp_path / "legacy",
        duration,
        120.0,
        render_cfg={},
    )
    compiled_audio = render_group_audio(
        compiled.pm,
        compiled.groups,
        "melody",
        "pretty-midi",
        "",
        24_000,
        tmp_path / "compiled",
        duration,
        120.0,
        render_cfg={},
        instrument_specs=compiled.instrument_specs,
    )

    assert legacy_audio.shape == compiled_audio.shape
    assert np.array_equal(legacy_audio, compiled_audio)
    assert float(np.max(np.abs(compiled_audio))) > 1e-3


def test_compiled_score_fingerprint_tracks_music_not_schema_spelling():
    canonical = compile_score(_v1_contract_spec())
    legacy_spec = _v1_contract_spec()
    legacy_spec["schema"] = LEGACY_V1_SCHEMA
    legacy = compile_score(legacy_spec)
    assert compiled_score_fingerprint(canonical) == compiled_score_fingerprint(legacy)

    changed_spec = _v1_contract_spec()
    changed_spec["sections"][0]["layers"][1]["notes"][0][4] += 1
    changed = compile_score(changed_spec)
    assert compiled_score_fingerprint(changed) != compiled_score_fingerprint(canonical)


def test_validation_reports_the_same_compiled_score_fingerprint():
    compiled = compile_score(_v2_contract_spec(), strict_schema=True)
    report = validate_musicir_spec(_v2_contract_spec(), strict_schema=True)
    assert report["compiled_score_schema"] == "ambition.compiled_score.v1"
    assert report["compiled_score_fingerprint"] == compiled_score_fingerprint(compiled)



def test_render_manifest_can_record_compiled_semantic_provenance():
    compiled = compile_score(_v1_contract_spec())
    fingerprint = compiled_score_fingerprint(compiled)
    provenance = {
        "schema": "ambition.compiled_score.v1",
        "fingerprint": fingerprint,
        "source_schema": compiled.source_schema,
        "canonical_schema": compiled.canonical_schema,
        "normalization_warnings": list(compiled.normalization_warnings),
    }
    manifest = build_manifest(
        compiled.normalized_spec,
        "render-hash",
        compiled.sections,
        list(compiled.group_names),
        {},
        48_000,
        compiled_score=provenance,
    )
    assert manifest["compiled_score"] == provenance
