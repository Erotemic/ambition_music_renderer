from __future__ import annotations

import json
from pathlib import Path

import mido

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.interchange import (
    export_interchange_bundle,
    read_midi_snapshot,
    write_compiled_midi,
)
from ambition_music_renderer.render.exact_score import ExactTempoMap, ScoreClock


def _instrument():
    return {
        "name": "piano",
        "group": "keys",
        "program": "acoustic_grand_piano",
        "volume": 100,
    }


def _v2_score():
    return {
        "schema": "ambition.musicir.v2",
        "id": "interchange_v2",
        "instruments": [_instrument()],
        "score": {
            "timebase": {"ppq": 480},
            "meter": [
                {"bar": 1, "signature": "4/4"},
                {"bar": 3, "signature": "3/4"},
            ],
            "tempo": [
                {"tick": 0, "bpm": 120},
                {"tick": 1920, "bpm": 90},
            ],
            "form": [
                {"id": "a", "from": {"bar": 1, "beat": 1}, "to": {"bar": 3, "beat": 1}},
                {"id": "b", "from": {"bar": 3, "beat": 1}, "to": {"bar": 4, "beat": 1}},
            ],
            "end": {"bar": 4, "beat": 1},
        },
        "parts": [
            {
                "id": "piano_part",
                "instrument": "piano",
                "controls": [
                    {"tick": 0, "cc": 64, "value": 0},
                    {"tick": 3840, "cc": 64, "value": 127},
                ],
                "voices": [
                    {
                        "id": "right",
                        "events": [
                            [0, 480, "C4", 80],
                            [3840, 480, "E4", 90],
                        ],
                    }
                ],
            }
        ],
    }


def _v3_score():
    return {
        "schema": "ambition.musicir.v3",
        "id": "interchange_v3",
        "timebase": {"ppq": 480},
        "meter": "4/4",
        "tempo": 120,
        "form": [
            {"id": "main", "from": {"bar": 1, "beat": 1}, "to": {"bar": 2, "beat": 1}}
        ],
        "end": {"bar": 2, "beat": 1},
        "instruments": [_instrument()],
        "materials": {
            "hook": {
                "events": [
                    {"id": "first", "at": 0, "dur": "1/4", "pitch": "C4", "velocity": 80},
                    {"id": "second", "at": "1/4", "dur": "1/4", "pitch": "E4", "velocity": 88},
                ]
            }
        },
        "parts": [
            {
                "id": "piano_part",
                "instrument": "piano",
                "voices": [
                    {
                        "id": "right",
                        "clips": [
                            {"id": "hook-clip", "at": {"bar": 1, "beat": 1}, "use": "hook"}
                        ],
                    }
                ],
            }
        ],
    }


def _absolute_meta(track, kind):
    tick = 0
    out = []
    for msg in track:
        tick += int(msg.time)
        if msg.type == kind:
            out.append((tick, msg))
    return out


def test_exact_tempo_time_to_tick_roundtrips_compiler_coordinates():
    score = _v2_score()["score"]
    clock = ScoreClock(score)
    tempo = ExactTempoMap(score, clock).bind_ppq(clock.ppq)
    for tick in [0, 1, 479, 480, 1919, 1920, 3839, 3840, 4319, 4320]:
        assert tempo.time_to_tick(tempo.tick_to_time(tick), hint_max_tick=5000) == tick


def test_compiled_midi_preserves_exact_tempo_meter_and_note_ticks(tmp_path: Path):
    compiled = compile_score(_v2_score())
    midi_path = tmp_path / "score.mid"
    write_compiled_midi(compiled, midi_path)

    mid = mido.MidiFile(str(midi_path))
    assert mid.ticks_per_beat == 480
    signatures = _absolute_meta(mid.tracks[0], "time_signature")
    assert [(tick, msg.numerator, msg.denominator) for tick, msg in signatures] == [
        (0, 4, 4),
        (3840, 3, 4),
    ]
    tempos = _absolute_meta(mid.tracks[0], "set_tempo")
    assert [tick for tick, _msg in tempos] == [0, 1920]
    assert abs(mido.tempo2bpm(tempos[0][1].tempo) - 120.0) < 1e-3
    assert abs(mido.tempo2bpm(tempos[1][1].tempo) - 90.0) < 1e-3

    snapshot = read_midi_snapshot(midi_path)
    piano = next(track for track in snapshot["tracks"] if track["name"] == "piano")
    assert [(row["start_tick"], row["end_tick"], row["pitch"], row["velocity"]) for row in piano["notes"]] == [
        (0, 480, 60, 80),
        (3840, 4320, 64, 90),
    ]
    assert any(row["tick"] == 3840 and row["controller"] == 64 and row["value"] == 127 for row in piano["controls"])


def test_v3_daw_bundle_carries_stable_source_provenance(tmp_path: Path):
    compiled = compile_score(_v3_score())
    paths = export_interchange_bundle(compiled, tmp_path)
    manifest = json.loads(paths["manifest"].read_text())
    assert manifest["schema"] == "ambition.musicir.daw_interchange.v1"
    assert manifest["roundtrip"]["source_mapping"] == "stable"
    assert manifest["authoring_graph_fingerprint"] == compiled.authoring_graph_fingerprint
    notes = manifest["tracks"][0]["notes"]
    assert [row["source_ref"]["clip_id"] for row in notes] == ["hook-clip", "hook-clip"]
    assert [row["source_ref"]["source_event_id"] for row in notes] == ["first", "second"]
    assert all(row["event_id"].startswith("interchange_v3/piano_part/right/hook-clip/") for row in notes)

    snapshot = read_midi_snapshot(paths["midi"])
    piano = next(track for track in snapshot["tracks"] if track["name"] == "piano")
    assert [(row["start_tick"], row["end_tick"], row["pitch"]) for row in piano["notes"]] == [
        (0, 480, 60),
        (480, 960, 64),
    ]
