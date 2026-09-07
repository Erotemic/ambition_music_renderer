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
from ambition_music_renderer.musicir.interchange_reconcile import (
    DawRoundtripError,
    lower_reconciled_clips,
    reconcile_edited_midi,
    verify_compiled_matches_edited_midi,
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



def _write_track_midi(path: Path, *, ppq: int, name: str, notes):
    mid = mido.MidiFile(type=1, ticks_per_beat=ppq)
    conductor = mido.MidiTrack()
    conductor.extend(
        [
            mido.MetaMessage("track_name", name="MusicIR conductor", time=0),
            mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0),
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0),
            mido.MetaMessage("marker", text="main", time=0),
            mido.MetaMessage("end_of_track", time=ppq * 4),
        ]
    )
    mid.tracks.append(conductor)
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name=name, time=0))
    track.append(mido.Message("program_change", channel=0, program=0, time=0))
    events = []
    for start, end, pitch, velocity in notes:
        events.append((start, 1, mido.Message("note_on", channel=0, note=pitch, velocity=velocity, time=0)))
        events.append((end, 0, mido.Message("note_off", channel=0, note=pitch, velocity=0, time=0)))
    previous = 0
    for tick, _priority, msg in sorted(events, key=lambda row: (row[0], row[1])):
        track.append(msg.copy(time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=max(0, ppq * 4 - previous)))
    mid.tracks.append(track)
    mid.save(str(path))


def _generator_v3_score():
    return {
        "schema": "ambition.musicir.v3",
        "id": "interchange_generator",
        "seed": 7,
        "timebase": {"ppq": 960},
        "meter": "4/4",
        "tempo": 120,
        "harmony": ["C"],
        "form": [{"id": "main", "from": {"bar": 1, "beat": 1}, "to": {"bar": 2, "beat": 1}}],
        "end": {"bar": 2, "beat": 1},
        "instruments": [
            {"name": "keys", "group": "keys", "program": "acoustic_grand_piano", "volume": 100}
        ],
        "parts": [
            {
                "id": "keys_part",
                "instrument": "keys",
                "voices": [
                    {
                        "id": "right",
                        "clips": [
                            {
                                "id": "generated",
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


def test_daw_reconcile_rescales_ppq_and_lowers_only_edited_material_clip(tmp_path: Path):
    source = _v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    assert manifest["source_regions"] == [
        {
            "clip_id": "hook-clip",
            "end_tick": 960,
            "instrument": "piano",
            "part_id": "piano_part",
            "source_kind": "material",
            "start_tick": 0,
            "voice_id": "right",
        }
    ]

    edited_path = tmp_path / "edited.mid"
    # The DAW changed PPQ from 480 to 960. First note is unchanged, one new
    # note is inserted, and the old E4 is moved/resized/repitched/re-velocitized.
    _write_track_midi(
        edited_path,
        ppq=960,
        name="piano",
        notes=[
            (0, 960, 60, 80),
            (480, 960, 62, 70),
            (1200, 2400, 67, 100),
        ],
    )
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["edited_midi"]["source_ppq"] == 960
    assert report["edited_midi"]["normalized_ppq"] == 480
    assert report["summary"]["note_changes"] == 2
    assert report["apply"]["supported"] is True
    modified = [row for row in report["tracks"][0]["notes"]["matches"] if row["status"] == "modified"]
    assert modified[0]["changes"] == ["moved", "resized", "repitched", "velocity"]
    assert report["tracks"][0]["notes"]["added"][0]["source_region"]["clip_id"] == "hook-clip"

    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    # Reusable material remains source material; only this clip is literalized.
    assert updated["materials"] == source["materials"]
    clip = updated["parts"][0]["voices"][0]["clips"][0]
    assert "use" not in clip
    assert len(clip["events"]) == 3
    assert apply_report["clips_lowered"][0]["from"] == "material"
    assert verify_compiled_matches_edited_midi(compile_score(updated), manifest, snapshot)["ok"] is True


def test_daw_apply_can_lower_one_generated_clip_after_performance_edit(tmp_path: Path):
    source = _generator_v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    changed = False
    for track in edited.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                msg.velocity += 7
                changed = True
                break
        if changed:
            break
    assert changed
    edited_path = tmp_path / "generator-edited.mid"
    edited.save(str(edited_path))
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["summary"]["note_changes"] == 1
    assert report["apply"]["supported"] is True

    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    clip = updated["parts"][0]["voices"][0]["clips"][0]
    assert "generate" not in clip
    assert "duration" not in clip
    assert len(clip["events"]) == len(compiled.pm.instruments[0].notes)
    assert apply_report["clips_lowered"] == [
        {
            "part_id": "keys_part",
            "voice_id": "right",
            "clip_id": "generated",
            "from": "generate",
            "to": "events",
            "notes": len(compiled.pm.instruments[0].notes),
            "automation_points": 0,
            "origin_tick": 0,
        }
    ]
    assert verify_compiled_matches_edited_midi(compile_score(updated), manifest, snapshot)["ok"] is True


def test_daw_apply_lowers_clip_owned_controller_edit(tmp_path: Path):
    source = _v3_score()
    source["parts"][0]["voices"][0]["clips"][0]["automation"] = [
        {"id": "expression", "at": 0, "cc": 11, "value": 64}
    ]
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    changed_cc = False
    for track in edited.tracks:
        for msg in track:
            if msg.type == "control_change" and msg.control == 11 and msg.value == 64:
                msg.value = 90
                changed_cc = True
                break
        if changed_cc:
            break
    assert changed_cc
    edited_path = tmp_path / "automation-edited.mid"
    edited.save(str(edited_path))
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["summary"]["controller_changes"] == 1
    assert report["summary"]["unassigned_controller_edits"] == 0
    assert report["apply"]["supported"] is True
    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    clip = updated["parts"][0]["voices"][0]["clips"][0]
    assert clip["automation"] == [
        {"id": "daw_automation_0000", "at": 0, "cc": 11, "value": 90}
    ]
    assert apply_report["clips_lowered"][0]["automation_points"] == 1


def test_daw_reconcile_blocks_conductor_edits(tmp_path: Path):
    source = _v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    changed_tempo = False
    for track in edited.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                msg.tempo = mido.bpm2tempo(123)
                changed_tempo = True
                break
        if changed_tempo:
            break
    assert changed_tempo
    edited_path = tmp_path / "tempo-edited.mid"
    edited.save(str(edited_path))
    report = reconcile_edited_midi(compiled, manifest, read_midi_snapshot(edited_path))
    assert report["summary"]["conductor_changed"] is True
    assert report["apply"]["supported"] is False
    assert report["apply"]["blocked_by"] == ["tempo_meter_marker_edits_need_conductor_stage"]


def test_daw_reconcile_rejects_stale_musicir_baseline(tmp_path: Path):
    source = _v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    modified_source = _v3_score()
    modified_source["materials"]["hook"]["events"][0]["velocity"] = 81
    try:
        reconcile_edited_midi(
            compile_score(modified_source),
            manifest,
            read_midi_snapshot(paths["midi"]),
        )
    except DawRoundtripError as ex:
        assert "fresh DAW bundle" in str(ex)
    else:
        raise AssertionError("expected stale MusicIR source to reject DAW reconciliation")
