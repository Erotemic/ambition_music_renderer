from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.generators import (
    generator_json_schema,
    generator_specs,
    public_generator_names,
)
from ambition_music_renderer.musicir.interchange import build_interchange_manifest
from ambition_music_renderer.musicir.model import compiled_score_fingerprint
from ambition_music_renderer.musicir.pitch import pitch_syntax_reference
from ambition_music_renderer.render.score_layers import LAYER_RENDERERS


ROOT = Path(__file__).resolve().parents[1]


def _instrument(name="keys", *, is_drum=False):
    row = {
        "name": name,
        "group": "music",
        "program": "acoustic_grand_piano",
        "volume": 100,
        "pan": 64,
    }
    if is_drum:
        row.pop("program")
        row["is_drum"] = True
    return row


def _base_score(*, clips, materials=None, harmony=None, end_bar=3):
    return {
        "schema": "ambition.musicir.v3",
        "id": "v3_authoring_semantics",
        "seed": 13,
        "timebase": {"ppq": 480},
        "meter": "4/4",
        "tempo": 120,
        "end": {"bar": end_bar, "beat": 1},
        "harmony": harmony or ["C"],
        "instruments": [_instrument()],
        "materials": materials or {},
        "parts": [
            {
                "id": "keys_part",
                "instrument": "keys",
                "voices": [{"id": "voice", "clips": clips}],
            }
        ],
    }


def _notes(compiled):
    return [
        (
            int(round(compiled.pm.time_to_tick(note.start))),
            int(round(compiled.pm.time_to_tick(note.end))),
            int(note.pitch),
            int(note.velocity),
        )
        for note in compiled.pm.instruments[0].notes
    ]


def test_common_clip_transforms_apply_to_reused_exact_material():
    spec = _base_score(
        materials={"hit": {"events": [[0, "1/4", "C4", 80]]}},
        clips=[
            {
                "id": "transformed",
                "at": {"bar": 1, "beat": 1},
                "use": "hit",
                "transpose": 2,
                "octave": 1,
                "velocity_scale": 0.5,
                "velocity_offset": 10,
                "time_scale": 2,
                "gate": 0.5,
                "repeat": 2,
            }
        ],
    )
    compiled = compile_score(spec)
    # Source duration is one quarter note (480 ticks). time_scale doubles the
    # nominal clip span to 960, while gate=0.5 returns sounding duration to 480.
    assert _notes(compiled) == [
        (0, 480, 74, 50),
        (960, 1440, 74, 50),
    ]
    assert [event["duration_ticks"] for event in compiled.note_events] == [960, 960]


def test_common_clip_transforms_apply_after_generator_expansion():
    base_clip = {
        "id": "arp",
        "at": {"bar": 1, "beat": 1},
        "duration": {"bars": 1},
        "generate": {
            "kind": "harmony.arpeggio",
            "pattern": [0, 2, 1, 2],
            "step": 0.5,
            "duration_beats": 0.5,
            "octave": 4,
            "velocity": 80,
            "humanize_ms": 0,
        },
    }
    baseline = compile_score(_base_score(clips=[copy.deepcopy(base_clip)], end_bar=2))
    transformed_clip = copy.deepcopy(base_clip)
    transformed_clip.update(
        {
            "transpose": 12,
            "velocity_scale": 0.5,
            "velocity_offset": 10,
            "time_scale": 0.5,
            "gate": 0.5,
        }
    )
    transformed = compile_score(_base_score(clips=[transformed_clip], end_bar=2))
    a = _notes(baseline)
    b = _notes(transformed)
    assert len(a) == len(b)
    for source, target in zip(a, b):
        source_start, source_end, source_pitch, source_velocity = source
        target_start, target_end, target_pitch, target_velocity = target
        assert target_pitch == source_pitch + 12
        assert target_velocity == round(source_velocity * 0.5 + 10)
        assert target_start == round(source_start * 0.5)
        source_duration = source_end - source_start
        assert target_end - target_start == max(1, round(max(1, round(source_duration * 0.5)) * 0.5))


def test_explicit_pitch_semantics_resolve_against_exact_harmony_clock():
    spec = _base_score(
        harmony={
            "events": [
                {"at": {"bar": 1, "beat": 1}, "chord": "Em"},
                {"at": {"bar": 1, "beat": 3}, "chord": "C"},
            ]
        },
        clips=[
            {
                "id": "semantic-pitches",
                "at": {"bar": 1, "beat": 1},
                "events": [
                    {"at": 0, "dur": "1/8", "pitch": {"kind": "harmony_root", "octave": 3}, "velocity": 80},
                    {"at": "1/8", "dur": "1/8", "pitch": {"kind": "chord_tone", "degree": 3, "octave": 4}, "velocity": 80},
                    # 1/2 of a whole note is beat 3 in 4/4, where harmony has changed to C.
                    {"at": "1/2", "dur": "1/8", "pitch": {"kind": "harmony_root", "octave": 4}, "velocity": 80},
                    {"at": "5/8", "dur": "1/8", "pitch": {"kind": "scale_degree", "tonic": "E", "mode": "minor", "degree": 6, "octave": 4}, "velocity": 80},
                    {"at": "3/4", "dur": "1/8", "pitch": {"kind": "drum", "name": "snare"}, "velocity": 80},
                    {"at": "7/8", "dur": "1/8", "pitch": {"kind": "guitar_fret", "string": "A2", "fret": 7}, "velocity": 80},
                ],
            }
        ],
    )
    compiled = compile_score(spec)
    assert [note[2] for note in _notes(compiled)] == [52, 71, 60, 72, 38, 52]
    reference = pitch_syntax_reference()
    assert set(reference["explicit"]) >= {
        "note",
        "midi",
        "relative",
        "harmony_root",
        "chord_tone",
        "scale_degree",
        "drum",
        "guitar_fret",
    }


def test_clip_automation_repeats_scales_time_and_keeps_source_provenance():
    spec = _base_score(
        materials={"hit": {"events": [[0, "1/4", "C4", 80]]}},
        clips=[
            {
                "id": "automated",
                "at": {"bar": 1, "beat": 1},
                "use": "hit",
                "time_scale": 0.5,
                "repeat": {"count": 2, "every": {"bars": 1}},
                "automation": [
                    {"id": "swell", "at": "1/4", "cc": "expression", "value": 109},
                    {"id": "bend", "at": "1/2", "pitch_bend": 2048},
                ],
            }
        ],
    )
    compiled = compile_score(spec)
    authored = [event for event in compiled.controller_events if event.get("source_ref")]
    assert [(event["event_type"], event["tick"]) for event in authored] == [
        ("control_change", 240),
        ("pitch_bend", 480),
        ("control_change", 2160),
        ("pitch_bend", 2400),
    ]
    assert all(event["source_ref"]["clip_id"] == "automated" for event in authored)
    assert all(event["source_ref"]["source_kind"] == "automation" for event in authored)
    assert len({event["event_id"] for event in authored}) == 4

    manifest = build_interchange_manifest(compiled, midi_filename="score.mid")
    assert manifest["roundtrip"]["controller_source_mapping"] == "stable"
    track = manifest["tracks"][0]
    assert any(row.get("source_ref", {}).get("source_event_id") == "swell" for row in track["controls"])
    assert any(row.get("source_ref", {}).get("source_event_id") == "bend" for row in track["pitch_bends"])


def test_clip_automation_works_on_generator_clips_too():
    spec = _base_score(
        harmony=["C"],
        clips=[
            {
                "id": "generated",
                "at": {"bar": 1, "beat": 1},
                "duration": {"bars": 1},
                "generate": {
                    "kind": "harmony.arpeggio",
                    "pattern": [0, 2, 1, 2],
                    "step": 0.5,
                    "duration_beats": 0.45,
                    "octave": 4,
                    "velocity": 72,
                    "humanize_ms": 0,
                },
                "automation": [
                    {"id": "expression-up", "at": "1/2", "cc": "expression", "value": 120}
                ],
            }
        ],
        end_bar=2,
    )
    compiled = compile_score(spec)
    authored = [event for event in compiled.controller_events if event.get("source_ref")]
    assert len(authored) == 1
    assert authored[0]["tick"] == 960
    assert authored[0]["controller"] == 11
    assert authored[0]["source_ref"]["clip_id"] == "generated"


def test_generator_catalog_is_the_public_bridge_authority():
    specs = generator_specs()
    assert tuple(sorted(specs)) == public_generator_names()
    assert len(specs) >= 16
    assert {spec.bridge_kind for spec in specs.values()} <= set(LAYER_RENDERERS)
    for name, spec in specs.items():
        schema = generator_json_schema(name)
        assert schema["properties"]["kind"]["const"] == name
        assert schema["additionalProperties"] is False
        assert spec.example["kind"] == name


def test_every_generator_catalog_example_compiles():
    instrument = {
        "name": "voice",
        "group": "music",
        "program": "acoustic_grand_piano",
    }
    motif = {
        "kind": "motif",
        "root": "C4",
        "intervals": [0, 4, 7],
        "rhythm": [0.5, 0.5, 1.0],
        "durations": [0.45, 0.45, 0.9],
        "velocities": [1.0, 1.0, 1.0],
    }
    for name, generator in generator_specs().items():
        spec = {
            "schema": "ambition.musicir.v3",
            "id": f"generator_contract_{name.replace('.', '_')}",
            "seed": 1,
            "timebase": {"ppq": 960},
            "meter": "4/4",
            "tempo": 120,
            "harmony": ["C"],
            "end": {"bar": 2, "beat": 1},
            "instruments": [instrument],
            "materials": {"hero_motif": motif},
            "parts": [
                {
                    "id": "part",
                    "instrument": "voice",
                    "voices": [
                        {
                            "id": "voice",
                            "clips": [
                                {
                                    "id": "generator",
                                    "at": {"bar": 1, "beat": 1},
                                    "duration": {"bars": 1},
                                    "generate": copy.deepcopy(generator.example),
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        compiled = compile_score(spec)
        compiled.assert_internal_consistency()


def test_generator_catalog_is_source_readable_without_site_packages():
    script = ROOT / "dev" / "read_generator_catalog.py"
    result = subprocess.run(
        [sys.executable, "-S", str(script), "describe", "harmony.arpeggio"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert "harmony.arpeggio" in result.stdout
    assert "pattern" in result.stdout
    assert "bridge_kind" in result.stdout


def test_checked_in_audio_environment_snapshot_is_source_readable_without_site_packages():
    snapshot_path = ROOT / "ambition_music_renderer" / "data" / "audio_environment_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf8"))
    assert snapshot["schema"] == "ambition.audio_environment_snapshot.v1"
    assert len(snapshot["sfz_programs"]) == 2403
    assert len(snapshot["stable_alias_resolutions"]) == 70
    assert snapshot["soundfonts"] == ["soundfonts/GeneralUser-GS.sf2"]
    assert {key: len(value) for key, value in snapshot["plugins"].items()} == {
        "clap": 28,
        "lv2": 22,
        "vst3": 25,
    }
    # Workstation-root provenance is allowed, but recorded resources themselves
    # must be portable paths so a remote agent can reason about them.
    payload = json.dumps({key: value for key, value in snapshot.items() if key != "workstation_root"})
    assert "/data/audio-tools" not in payload

    script = ROOT / "dev" / "read_audio_environment_snapshot.py"
    result = subprocess.run(
        [sys.executable, "-S", str(script), "summary"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert "sfz_programs: 2403" in result.stdout
    assert "stable_aliases: 70" in result.stdout


def test_instrument_candidate_bank_is_inert_until_a_scratch_variant_selects_it():
    spec = _base_score(
        clips=[{
            "id": "note",
            "at": {"bar": 1, "beat": 1},
            "events": [[0, "1/4", "C4", 80]],
        }],
        end_bar=2,
    )
    baseline = compile_score(copy.deepcopy(spec))
    spec["authoring"] = {
        "instrument_candidates": {
            "keys": {
                "primary": "gm_piano",
                "candidates": [
                    {"id": "gm_piano", "label": "GM Piano", "program": "acoustic_grand_piano"},
                    {"id": "electric", "label": "Electric Piano", "program": "electric_piano_1"},
                ],
            }
        }
    }
    with_candidates = compile_score(spec)
    assert compiled_score_fingerprint(with_candidates) == compiled_score_fingerprint(baseline)
    assert _notes(with_candidates) == _notes(baseline)
