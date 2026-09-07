from __future__ import annotations

import pretty_midi

from ambition_music_renderer.render.tuning import (
    build_tuning_lane_pms,
    correction_cents_for_pitch,
    normalize_tuning_correction,
)


def _pm(notes):
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0, name="test")
    inst.notes = [
        pretty_midi.Note(velocity=100, pitch=pitch, start=start, end=end)
        for pitch, start, end in notes
    ]
    pm.instruments = [inst]
    return pm


def test_tuning_curve_interpolates_and_clamps_endpoints():
    profile = normalize_tuning_correction(
        {"mode": "curve", "points": {"C4": -20.0, "C5": -8.0}}
    )
    assert correction_cents_for_pitch(profile, 48) == -20.0
    assert correction_cents_for_pitch(profile, 60) == -20.0
    assert correction_cents_for_pitch(profile, 66) == -14.0
    assert correction_cents_for_pitch(profile, 72) == -8.0
    assert correction_cents_for_pitch(profile, 84) == -8.0


def test_monophonic_per_note_curve_stays_one_render_lane():
    pm = _pm([(60, 0.0, 0.5), (64, 0.5, 1.0), (67, 1.0, 1.5)])
    spec = {
        "name": "test",
        "tuning_correction": {
            "mode": "curve",
            "points": {"C4": -10.0, "E4": -20.0, "G4": -30.0},
        },
    }
    lanes = build_tuning_lane_pms(pm, spec)
    assert len(lanes) == 1
    inst = lanes[0].instruments[0]
    assert [note.pitch for note in inst.notes] == [60, 64, 67]
    bends = [(pb.time, pb.pitch) for pb in inst.pitch_bends]
    assert len(bends) >= 3
    assert bends[0][1] < 0
    assert len({pb.pitch for pb in inst.pitch_bends if pb.pitch != 0}) >= 3


def test_polyphonic_different_offsets_split_only_conflicting_notes():
    pm = _pm(
        [
            (60, 0.0, 1.0),
            (64, 0.0, 1.0),
            (67, 1.0, 2.0),
        ]
    )
    spec = {
        "name": "test",
        "tuning_correction": {
            "mode": "curve",
            "points": {"C4": -10.0, "E4": -20.0, "G4": -30.0},
        },
    }
    lanes = build_tuning_lane_pms(pm, spec)
    # The C/E chord needs two bends. G is sequential, so it reuses one lane.
    assert len(lanes) == 2
    assert sum(len(lane.instruments[0].notes) for lane in lanes) == 3


def test_global_correction_keeps_chord_in_one_lane():
    pm = _pm([(60, 0.0, 1.0), (64, 0.0, 1.0), (67, 0.0, 1.0)])
    lanes = build_tuning_lane_pms(pm, {"name": "test", "tuning_correction": -7.0})
    assert len(lanes) == 1
    assert len(lanes[0].instruments[0].notes) == 3


def test_group_renderer_uses_polyphony_safe_tuning_lanes(monkeypatch, tmp_path):
    import numpy as np
    from ambition_music_renderer.render import group as group_mod

    pm = _pm([(60, 0.0, 1.0), (64, 0.0, 1.0)])
    spec = {
        "name": "test",
        "group": "keys",
        "program": "acoustic_grand_piano",
        "tuning_correction": {
            "mode": "curve",
            "points": {"C4": -10.0, "E4": -20.0},
        },
    }
    seen = []

    def fake_render_synth_audio(
        lane_pm, backend, soundfont, sample_rate, midi_path, dry_wav, minimum_duration
    ):
        inst = lane_pm.instruments[0]
        seen.append(
            {
                "notes": [note.pitch for note in inst.notes],
                "bends": [(pb.time, pb.pitch) for pb in inst.pitch_bends],
            }
        )
        return np.zeros((100, 2), dtype=np.float32) + 0.01

    monkeypatch.setattr(group_mod, "render_synth_audio", fake_render_synth_audio)
    audio = group_mod.render_group_audio(
        pm,
        {"test": "keys"},
        "keys",
        "pretty-midi",
        "/tmp/dummy.sf2",
        1000,
        tmp_path,
        1.0,
        120.0,
        instrument_specs={"test": spec},
    )
    assert audio.shape == (100, 2)
    assert len(seen) == 2
    assert sorted(row["notes"] for row in seen) == [[60], [64]]
    assert all(any(value != 0 for _time, value in row["bends"]) for row in seen)


def test_musicir_normalization_canonicalizes_tuning_curve_keys():
    from ambition_music_renderer.musicir.normalize import normalize_musicir_spec

    by_name = {
        "schema": "ambition.musicir.v3",
        "id": "tuning-name",
        "instruments": [
            {
                "name": "lead",
                "group": "lead",
                "program": "electric_guitar_clean",
                "tuning_correction": {
                    "mode": "curve",
                    "points": {"C4": -8.0, "E4": -6.0},
                },
            }
        ],
        "sections": [],
    }
    by_number = {
        **by_name,
        "id": "tuning-number",
        "instruments": [
            {
                **by_name["instruments"][0],
                "tuning_correction": {
                    "mode": "curve",
                    "points": {60: -8.0, 64: -6.0},
                },
            }
        ],
    }
    normalized_name = normalize_musicir_spec(by_name).spec["instruments"][0]["tuning_correction"]
    normalized_number = normalize_musicir_spec(by_number).spec["instruments"][0]["tuning_correction"]
    assert normalized_name == normalized_number
    assert normalized_name["points"] == {60: -8.0, 64: -6.0}


def test_global_tuning_correction_spelling_is_canonical():
    scalar = normalize_tuning_correction(-7.0)
    mapping = normalize_tuning_correction({"mode": "global", "cents": -7.0})
    assert scalar == mapping
    assert "interpolation" not in scalar
    assert normalize_tuning_correction({"mode": "global", "cents": 0.0}) is None
