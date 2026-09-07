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


def test_daw_reconcile_applies_step_tempo_edit(tmp_path: Path):
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
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["summary"]["conductor_changed"] is True
    assert report["summary"]["tempo_event_changes"] == 1
    assert report["apply"]["supported"] is True
    assert report["conductor"]["tempo"]["ramps"] == []

    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    assert abs(float(updated["tempo"][0]["bpm"]) - 123.0) < 1e-3
    assert apply_report["conductor"]["tempo"] is True
    verification = verify_compiled_matches_edited_midi(compile_score(updated), manifest, snapshot)
    assert verification["ok"] is True
    assert verification["conductor"]["tempo"]["mode"] == "exact_step_events"


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


def _edit_first_time_signature(mid: mido.MidiFile, *, numerator: int, denominator: int) -> None:
    for track in mid.tracks:
        for msg in track:
            if msg.type == "time_signature":
                msg.numerator = numerator
                msg.denominator = denominator
                return
    raise AssertionError("no time signature event")


def _ramp_v3_score():
    source = _v3_score()
    source["id"] = "interchange_ramp_v3"
    source["tempo"] = [
        {"tick": 0, "bpm": [120, 90], "to": {"tick": 1920}, "curve": "linear"},
    ]
    source["form"] = [{"id": "main", "from": {"tick": 0}, "to": {"tick": 1920}}]
    source["end"] = {"tick": 1920}
    return source


def _rewrite_ramp_tempos(mid: mido.MidiFile, *, start_bpm: float, end_bpm: float, end_tick: int) -> None:
    changed = 0
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += int(msg.time)
            if msg.type == "set_tempo" and 0 <= tick <= end_tick:
                frac = tick / float(end_tick)
                bpm = start_bpm + (end_bpm - start_bpm) * frac
                msg.tempo = mido.bpm2tempo(bpm)
                changed += 1
    assert changed >= 3


def test_daw_apply_reconstructs_linear_tempo_ramp(tmp_path: Path):
    source = _ramp_v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    assert manifest["midi"]["tempo_ramps_sampled_to_smf"] is True
    assert manifest["midi"]["exact_timing"]["tempo_segments"][0]["curve"] == "linear"

    edited = mido.MidiFile(str(paths["midi"]))
    _rewrite_ramp_tempos(edited, start_bpm=120.0, end_bpm=100.0, end_tick=1920)
    edited_path = tmp_path / "ramp-edited.mid"
    edited.save(str(edited_path))
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["apply"]["supported"] is True
    ramps = report["conductor"]["tempo"]["ramps"]
    assert ramps[0]["status"] == "reconstructed"
    assert ramps[0]["curve"] == "linear"
    assert abs(ramps[0]["end_bpm"] - 100.0) < 1e-3

    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    assert updated["tempo"][0]["curve"] == "linear"
    assert updated["tempo"][0]["to"] == {"tick": 1920}
    assert abs(updated["tempo"][0]["bpm"][1] - 100.0) < 1e-3
    assert apply_report["conductor"]["tempo_ramps"][0]["status"] == "reconstructed"
    verification = verify_compiled_matches_edited_midi(compile_score(updated), manifest, snapshot)
    assert verification["ok"] is True, verification
    assert verification["conductor"]["tempo"]["mode"] == "semantic_ramp_and_smf_clock"


def test_daw_reconcile_blocks_non_curve_ramp_sample_edit(tmp_path: Path):
    source = _ramp_v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    changed = False
    for track in edited.tracks:
        tick = 0
        for msg in track:
            tick += int(msg.time)
            if msg.type == "set_tempo" and 0 < tick < 1920:
                msg.tempo = mido.bpm2tempo(170)
                changed = True
                break
        if changed:
            break
    assert changed
    edited_path = tmp_path / "ramp-corrupt.mid"
    edited.save(str(edited_path))
    report = reconcile_edited_midi(compiled, manifest, read_midi_snapshot(edited_path))
    assert report["apply"]["supported"] is False
    assert any(
        reason.startswith("tempo_ramp_samples_do_not_fit_supported_curve")
        for reason in report["apply"]["blocked_by"]
    )


def test_daw_apply_meter_edit_preserves_exact_score_extent(tmp_path: Path):
    source = _v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    _edit_first_time_signature(edited, numerator=3, denominator=4)
    edited_path = tmp_path / "meter-edited.mid"
    edited.save(str(edited_path))
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["summary"]["meter_event_changes"] == 1
    assert report["apply"]["supported"] is True

    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    assert updated["meter"] == [{"bar": 1, "signature": "3/4"}]
    assert updated["end"] == {"tick": 1920}
    assert updated["form"][0]["from"] == {"tick": 0}
    assert updated["form"][0]["to"] == {"tick": 1920}
    assert apply_report["conductor"]["meter"] is True
    assert verify_compiled_matches_edited_midi(compile_score(updated), manifest, snapshot)["ok"] is True


def test_daw_reconcile_blocks_meter_change_off_bar_boundary(tmp_path: Path):
    source = _v3_score()
    source["end"] = {"bar": 3, "beat": 1}
    source["form"] = [{"id": "main", "from": {"bar": 1, "beat": 1}, "to": {"bar": 3, "beat": 1}}]
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    conductor = edited.tracks[0]
    # Insert a 3/4 signature 500 ticks after the initial conductor events.  500
    # is not a 4/4 bar boundary at PPQ 480.
    inserted = False
    absolute = 0
    for idx, msg in enumerate(conductor):
        next_absolute = absolute + int(msg.time)
        if next_absolute >= 500:
            before = 500 - absolute
            msg.time -= before
            conductor.insert(idx, mido.MetaMessage("time_signature", numerator=3, denominator=4, time=before))
            inserted = True
            break
        absolute = next_absolute
    assert inserted
    edited_path = tmp_path / "meter-off-grid.mid"
    edited.save(str(edited_path))
    report = reconcile_edited_midi(compiled, manifest, read_midi_snapshot(edited_path))
    assert report["apply"]["supported"] is False
    assert "meter_change_not_on_bar_boundary:500" in report["apply"]["blocked_by"]


def test_daw_apply_moves_and_renames_form_marker(tmp_path: Path):
    source = _v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    moved = False
    conductor = edited.tracks[0]
    for index, msg in enumerate(conductor):
        if msg.type == "marker":
            msg.text = "Rooftop main"
            msg.time += 120
            if index + 1 < len(conductor):
                conductor[index + 1].time -= 120
            moved = True
            break
    assert moved
    edited_path = tmp_path / "marker-edited.mid"
    edited.save(str(edited_path))
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["summary"]["form_marker_changes"] == 1
    assert report["apply"]["supported"] is True
    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    assert updated["form"][0]["from"] == {"tick": 120}
    assert updated["form"][0]["label"] == "Rooftop main"
    assert apply_report["conductor"]["form_markers"] is True
    assert verify_compiled_matches_edited_midi(compile_score(updated), manifest, snapshot)["ok"] is True


def test_daw_apply_preserves_musicir_hold_while_editing_tempo(tmp_path: Path):
    source = _v3_score()
    source["tempo"] = [
        {"tick": 0, "bpm": 120},
        {"tick": 960, "bpm": 120, "hold_seconds": 1.5},
    ]
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    assert manifest["midi"]["holds_sidecar_authoritative"] is True
    assert manifest["midi"]["exact_timing"]["holds"] == [{"tick": 960, "seconds": 1.5}]

    edited = mido.MidiFile(str(paths["midi"]))
    for track in edited.tracks:
        for msg in track:
            if msg.type == "set_tempo" and msg.time == 0:
                msg.tempo = mido.bpm2tempo(110)
                break
    edited_path = tmp_path / "hold-tempo-edited.mid"
    edited.save(str(edited_path))
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["apply"]["supported"] is True
    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    hold_rows = [row for row in updated["tempo"] if row.get("hold_seconds") is not None]
    assert len(hold_rows) == 1
    assert hold_rows[0]["tick"] == 960
    assert abs(float(hold_rows[0]["bpm"]) - 110.0) < 1e-3
    assert hold_rows[0]["hold_seconds"] == 1.5
    compiled_after = compile_score(updated)
    assert compiled_after.exact_metadata["holds"] == [{"tick": 960, "seconds": 1.5}]
    assert apply_report["conductor"]["holds"]["policy"] == "sidecar_authoritative_preserved"
    assert verify_compiled_matches_edited_midi(compiled_after, manifest, snapshot)["ok"] is True


def _replace_conductor_tempos(mid: mido.MidiFile, points: list[tuple[int, float]]) -> None:
    track = mid.tracks[0]
    absolute = 0
    kept = []
    order = 0
    for msg in track:
        absolute += int(msg.time)
        if msg.type not in {"set_tempo", "end_of_track"}:
            kept.append((absolute, order, msg.copy(time=0)))
            order += 1
    for tick, bpm in points:
        kept.append((int(tick), order, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(float(bpm)), time=0)))
        order += 1
    end_tick = max([absolute] + [int(tick) for tick, _bpm in points])
    kept.sort(key=lambda row: (row[0], row[1]))
    rebuilt = mido.MidiTrack()
    previous = 0
    for tick, _order, msg in kept:
        rebuilt.append(msg.copy(time=int(tick) - previous))
        previous = int(tick)
    rebuilt.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - previous)))
    mid.tracks[0] = rebuilt


def test_daw_apply_infers_new_dense_linear_tempo_ramp(tmp_path: Path):
    source = _v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    points = []
    for tick in range(0, 1921, 120):
        frac = tick / 1920.0
        points.append((tick, 120.0 + (96.0 - 120.0) * frac))
    _replace_conductor_tempos(edited, points)
    edited_path = tmp_path / "new-ramp.mid"
    edited.save(str(edited_path))
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["apply"]["supported"] is True
    inferred = [row for row in report["conductor"]["tempo"]["ramps"] if row["status"] == "inferred_new_ramp"]
    assert len(inferred) == 1
    assert inferred[0]["curve"] == "linear"
    updated, _apply_report = lower_reconciled_clips(source, manifest, report)
    assert updated["tempo"][0]["curve"] == "linear"
    assert updated["tempo"][0]["to"] == {"tick": 1920}
    verification = verify_compiled_matches_edited_midi(compile_score(updated), manifest, snapshot)
    assert verification["ok"] is True, verification


def test_daw_apply_combines_clip_and_conductor_edits(tmp_path: Path):
    source = _v3_score()
    compiled = compile_score(source)
    paths = export_interchange_bundle(compiled, tmp_path / "baseline")
    manifest = json.loads(paths["manifest"].read_text())
    edited = mido.MidiFile(str(paths["midi"]))
    changed_note = False
    changed_tempo = False
    for track in edited.tracks:
        for msg in track:
            if msg.type == "set_tempo" and not changed_tempo:
                msg.tempo = mido.bpm2tempo(126)
                changed_tempo = True
            if msg.type == "note_on" and msg.velocity > 0 and not changed_note:
                msg.velocity += 5
                changed_note = True
    assert changed_note and changed_tempo
    edited_path = tmp_path / "combined-edited.mid"
    edited.save(str(edited_path))
    snapshot = read_midi_snapshot(edited_path)
    report = reconcile_edited_midi(compiled, manifest, snapshot)
    assert report["summary"]["note_changes"] == 1
    assert report["summary"]["tempo_event_changes"] == 1
    assert report["apply"]["supported"] is True
    updated, apply_report = lower_reconciled_clips(source, manifest, report)
    assert len(apply_report["clips_lowered"]) == 1
    assert apply_report["conductor"]["tempo"] is True
    verification = verify_compiled_matches_edited_midi(compile_score(updated), manifest, snapshot)
    assert verification["ok"] is True, verification
