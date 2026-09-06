from __future__ import annotations

import copy
from pathlib import Path

import yaml

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.graph import authoring_graph_fingerprint, normalize_v3_score_graph
from ambition_music_renderer.musicir.model import compiled_score_fingerprint
from ambition_music_renderer.musicir.normalize import MUSICIR_V2_SCHEMA, MUSICIR_V3_SCHEMA


def _instrument():
    return {
        "name": "keys",
        "group": "harmony",
        "program": "acoustic_grand_piano",
        "volume": 100,
        "pan": 64,
    }


def _exact_v3():
    return {
        "schema": MUSICIR_V3_SCHEMA,
        "id": "v3_exact_contract",
        "timebase": {"ppq": 480},
        "meter": "4/4",
        "tempo": 120,
        "form": [
            {"id": "main", "from": {"bar": 1, "beat": 1}, "to": {"bar": 3, "beat": 1}}
        ],
        "end": {"bar": 3, "beat": 1},
        "instruments": [_instrument()],
        "materials": {
            "hook": {
                "events": [
                    [0, "1/4", "C4", 80],
                    ["1/4", "1/4", "E4", 84],
                ]
            }
        },
        "parts": [
            {
                "id": "keys_part",
                "instrument": "keys",
                "voices": [
                    {
                        "id": "right",
                        "clips": [
                            {
                                "id": "hook-a",
                                "at": {"bar": 1, "beat": 1},
                                "use": "hook",
                                "repeat": {"count": 2, "every": {"bars": 1}},
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _equivalent_v2():
    return {
        "schema": MUSICIR_V2_SCHEMA,
        "id": "v2_exact_contract",
        "instruments": [_instrument()],
        "score": {
            "timebase": {"ppq": 480},
            "meter": [{"bar": 1, "signature": "4/4"}],
            "tempo": [{"tick": 0, "bpm": 120.0}],
            "form": [
                {"id": "main", "from": {"bar": 1, "beat": 1}, "to": {"bar": 3, "beat": 1}}
            ],
            "end": {"bar": 3, "beat": 1},
        },
        "parts": [
            {
                "id": "keys_part",
                "instrument": "keys",
                "voices": [
                    {
                        "id": "right",
                        "events": [
                            [0, 480, "C4", 80],
                            [480, 480, "E4", 84],
                            [1920, 480, "C4", 80],
                            [2400, 480, "E4", 84],
                        ],
                    }
                ],
            }
        ],
    }


def _note_contract(compiled):
    inst = compiled.pm.instruments[0]
    return [
        (round(note.start, 9), round(note.end, 9), note.pitch, note.velocity)
        for note in inst.notes
    ]


def test_v3_exact_material_matches_v2_compiled_music():
    v3 = compile_score(_exact_v3())
    v2 = compile_score(_equivalent_v2())
    assert _note_contract(v3) == _note_contract(v2)
    assert v3.sections == v2.sections
    assert v3.exact_metadata == v2.exact_metadata
    assert compiled_score_fingerprint(v3) == compiled_score_fingerprint(v2)


def test_v3_source_ids_are_provenance_not_music():
    spec1 = _exact_v3()
    spec2 = copy.deepcopy(spec1)
    spec2["parts"][0]["voices"][0]["clips"][0]["id"] = "renamed-hook"
    a = compile_score(spec1)
    b = compile_score(spec2)
    assert compiled_score_fingerprint(a) == compiled_score_fingerprint(b)
    assert a.authoring_graph_fingerprint != b.authoring_graph_fingerprint
    assert a.note_events[0]["event_id"] != b.note_events[0]["event_id"]


def test_v3_source_id_rename_does_not_invalidate_audio_dependency(tmp_path):
    from ambition_music_renderer.render.dependencies import build_render_dependency_fingerprint

    spec1 = _exact_v3()
    spec2 = copy.deepcopy(spec1)
    spec2["parts"][0]["voices"][0]["clips"][0]["id"] = "renamed-hook"
    a = compile_score(spec1)
    b = compile_score(spec2)
    spec_path = tmp_path / "score.music.yaml"
    spec_path.write_text("# dependency base only\n", encoding="utf8")
    package_root = Path(__file__).resolve().parents[1] / "ambition_music_renderer"
    fa = build_render_dependency_fingerprint(
        spec_path=spec_path,
        spec=spec1,
        compiled=a,
        backend="pretty-midi",
        soundfont="",
        package_root=package_root,
    )
    fb = build_render_dependency_fingerprint(
        spec_path=spec_path,
        spec=spec2,
        compiled=b,
        backend="pretty-midi",
        soundfont="",
        package_root=package_root,
    )
    assert fa.fingerprint == fb.fingerprint


def test_v3_event_ids_are_unique_and_trace_to_clip():
    compiled = compile_score(_exact_v3())
    event_ids = [event["event_id"] for event in compiled.note_events]
    assert len(event_ids) == len(set(event_ids))
    assert all("hook-a" in event_id for event_id in event_ids)
    assert all(event["source_ref"]["clip_id"] == "hook-a" for event in compiled.note_events)


def test_v3_authoring_graph_requires_stable_clip_ids():
    spec = _exact_v3()
    del spec["parts"][0]["voices"][0]["clips"][0]["id"]
    try:
        normalize_v3_score_graph(spec)
    except ValueError as ex:
        assert "stable `id`" in str(ex)
    else:
        raise AssertionError("expected missing v3 clip id to fail")


def _generator_v3(clip_id="arp-a"):
    return {
        "schema": MUSICIR_V3_SCHEMA,
        "id": "v3_generator_contract",
        "seed": 7,
        "timebase": {"ppq": 960},
        "meter": "4/4",
        "tempo": 120,
        "harmony": ["C"],
        "end": {"bar": 2, "beat": 1},
        "instruments": [_instrument()],
        "parts": [
            {
                "id": "keys_part",
                "instrument": "keys",
                "voices": [
                    {
                        "id": "right",
                        "clips": [
                            {
                                "id": clip_id,
                                "at": {"bar": 1, "beat": 1},
                                "duration": {"bars": 1},
                                "generate": {
                                    "kind": "harmony.arpeggio",
                                    "pattern": [0, 2, 1, 2],
                                    "step": 0.5,
                                    "duration_beats": 0.5,
                                    "octave": 4,
                                    "velocity": 72,
                                    "humanize_ms": 0,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _generator_v1():
    return {
        "schema": "ambition.musicir.v1",
        "id": "v1_generator_contract",
        "seed": 999,
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [_instrument()],
        "sections": [
            {
                "id": "arp-a",
                "bars": 1,
                "harmony": ["C"],
                "layers": [
                    {
                        "kind": "arpeggio",
                        "instrument": "keys",
                        "pattern": [0, 2, 1, 2],
                        "step": 0.5,
                        "duration_beats": 0.5,
                        "octave": 4,
                        "velocity": 72,
                        "humanize_ms": 0,
                    }
                ],
            }
        ],
    }


def test_v3_generator_bridge_preserves_existing_arpeggio_behavior():
    v3 = compile_score(_generator_v3())
    v1 = compile_score(_generator_v1())
    assert _note_contract(v3) == _note_contract(v1)
    assert all(event.get("source_ref", {}).get("generator_kind") == "harmony.arpeggio" for event in v3.note_events)


def test_v3_generator_clip_rename_does_not_change_music_or_random_seed():
    a = compile_score(_generator_v3("arp-a"))
    b = compile_score(_generator_v3("renamed-arp"))
    assert _note_contract(a) == _note_contract(b)
    assert compiled_score_fingerprint(a) == compiled_score_fingerprint(b)
    assert a.authoring_graph_fingerprint != b.authoring_graph_fingerprint


def test_v3_generator_bridge_preserves_post_sanitization_note_lengths():
    v1_spec = {
        "schema": "ambition.musicir.v1",
        "id": "overlap_v1",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [_instrument()],
        "sections": [
            {
                "id": "main",
                "bars": 2,
                "harmony": ["C", "C"],
                "layers": [
                    {
                        "kind": "pad_chords",
                        "instrument": "keys",
                        "every_bars": 1,
                        "duration_beats": 5,
                        "octave": 4,
                        "velocity": 72,
                        "humanize_ms": 0,
                    }
                ],
            }
        ],
    }
    v3_spec = {
        "schema": MUSICIR_V3_SCHEMA,
        "id": "overlap_v3",
        "timebase": {"ppq": 960},
        "meter": "4/4",
        "tempo": 120,
        "harmony": ["C", "C"],
        "end": {"bar": 3, "beat": 1},
        "instruments": [_instrument()],
        "parts": [
            {
                "id": "keys_part",
                "instrument": "keys",
                "voices": [
                    {
                        "id": "pad",
                        "clips": [
                            {
                                "id": "long-pad",
                                "at": {"bar": 1, "beat": 1},
                                "duration": {"bars": 2},
                                "generate": {
                                    "kind": "harmony.pad",
                                    "every_bars": 1,
                                    "duration_beats": 5,
                                    "octave": 4,
                                    "velocity": 72,
                                    "humanize_ms": 0,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
    v1 = compile_score(v1_spec)
    v3 = compile_score(v3_spec)
    assert _note_contract(v3) == _note_contract(v1)
    # The first voicing overlaps the repeated chord nominally and is shortened
    # by the existing v1 sanitizer.  The v3 bridge must copy that sounding MIDI.
    assert any(note.end < 2.5 for note in v1.pm.instruments[0].notes)


def test_v3_exact_and_generator_clips_can_coexist():
    spec = _generator_v3()
    spec["materials"] = {"hit": {"events": [[0, "1/4", "C5", 100]]}}
    spec["parts"][0]["voices"][0]["clips"].append(
        {"id": "literal-hit", "at": {"bar": 1, "beat": 3}, "use": "hit"}
    )
    compiled = compile_score(spec)
    assert any(event.get("source_ref", {}).get("clip_id") == "literal-hit" for event in compiled.note_events)
    assert any(event.get("source_ref", {}).get("generator_kind") == "harmony.arpeggio" for event in compiled.note_events)
    assert len(compiled.pm.instruments[0].notes) > len(compile_score(_generator_v3()).pm.instruments[0].notes)


def test_v3_generator_registry_targets_existing_v1_implementations():
    from ambition_music_renderer.musicir.v3 import GENERATOR_KINDS
    from ambition_music_renderer.render.score_layers import LAYER_RENDERERS

    assert set(GENERATOR_KINDS.values()) <= set(LAYER_RENDERERS)


def test_v3_exact_clips_can_cross_clock_changes_but_generator_bridge_requires_split():
    exact = _exact_v3()
    exact["tempo"] = [
        {"tick": 0, "bpm": 120},
        {"tick": 960, "bpm": 90},
    ]
    exact["meter"] = [
        {"bar": 1, "signature": "4/4"},
        {"bar": 2, "signature": "3/4"},
    ]
    # Exact material remains valid because it is lowered directly onto v3's exact clock.
    compile_score(exact)

    generated = _generator_v3()
    generated["tempo"] = [
        {"tick": 0, "bpm": 120},
        {"tick": 960, "bpm": 90},
    ]
    try:
        compile_score(generated)
    except ValueError as ex:
        assert "tempo change/ramp" in str(ex)
        assert "split" in str(ex)
    else:
        raise AssertionError("generator bridge should reject a clip spanning a tempo change")


def test_v3_validation_reports_authoring_graph_and_clip_counts():
    from ambition_music_renderer.validation.musicir import validate_musicir_spec

    report = validate_musicir_spec(_generator_v3(), strict_schema=True)
    assert report["canonical_schema"] == "ambition.musicir.v3"
    assert report["v3"]["clips"] == 1
    assert report["v3"]["generator_clips"] == 1
    assert report["v3"]["authoring_graph_fingerprint"]


def test_checked_in_v3_authoring_example_compiles():
    path = Path(__file__).resolve().parents[1] / "scores" / "examples" / "musicir_v3_authoring.music.yaml"
    spec = yaml.safe_load(path.read_text(encoding="utf8"))
    compiled = compile_score(spec)
    assert compiled.canonical_schema == MUSICIR_V3_SCHEMA
    assert compiled.authoring_graph_fingerprint
    assert len(compiled.pm.instruments[0].notes) > 3
    compiled.assert_internal_consistency()


def test_v3_guitar_lead_preserves_authored_pitch_octaves():
    """V3 pitch intent survives the legacy guitar fretboard helper exactly."""
    spec = {
        "schema": MUSICIR_V3_SCHEMA,
        "id": "v3_guitar_lead_pitch_contract",
        "seed": 1,
        "timebase": {"ppq": 960},
        "meter": "4/4",
        "tempo": 120,
        "harmony": ["C"],
        "end": {"bar": 2, "beat": 1},
        "instruments": [
            {
                "name": "lead",
                "group": "lead",
                "program": "overdrive_guitar",
            }
        ],
        "materials": {
            "tread": {
                "kind": "motif",
                "root": "B3",
                "intervals": [0, -2, -4, -7],
                "rhythm": [1.0, 1.0, 1.0, 1.0],
                "durations": [0.75, 0.75, 0.75, 0.75],
                "velocities": [1.0, 1.0, 1.0, 1.0],
            }
        },
        "parts": [
            {
                "id": "lead_part",
                "instrument": "lead",
                "voices": [
                    {
                        "id": "voice",
                        "clips": [
                            {
                                "id": "tread_clip",
                                "at": {"bar": 1, "beat": 1},
                                "duration": {"bars": 1},
                                "transpose": -12,
                                "generate": {
                                    "kind": "guitar.lead",
                                    "material": "tread",
                                    "starts": [[0, 0.0]],
                                    "repeats": 1,
                                    "every_bars": 1,
                                    "velocity": 80,
                                    "pitch_scoop_cents": 0,
                                    "position_scoop_scale": 0,
                                    "humanize_ms": 0,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
    compiled = compile_score(spec)
    pitches = [note.pitch for note in compiled.pm.instruments[0].notes]
    assert pitches == [47, 45, 43, 40]
