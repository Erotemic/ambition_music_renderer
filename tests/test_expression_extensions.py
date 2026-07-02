"""Tests for the MusicIR expression extensions: tempo.map, notes layers,
and per-layer velocity `dynamics` curves."""

from __future__ import annotations

import math

import pytest

from ambition_music_renderer.render.score_core import TempoMap
from ambition_music_renderer.render.score_layers import (
    build_score,
    section_metadata_from_spec,
)


def _base_spec(**overrides):
    spec = {
        "id": "expr_test",
        "seed": 7,
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "piano", "group": "keys", "program": "acoustic_grand_piano"},
        ],
        "sections": [
            {"id": "a", "bars": 4, "harmony": ["C", "F", "G", "C"], "layers": []},
        ],
    }
    spec.update(overrides)
    return spec


# ---------------------------------------------------------------- TempoMap

def test_constant_tempo_matches_historical_model():
    tm = TempoMap.constant(120.0)
    assert tm.beat_to_time(8.0) == pytest.approx(8.0 * 60.0 / 120.0)
    assert tm.time_to_beat(4.0) == pytest.approx(8.0)


def test_tempo_map_ramp_integrates_exactly():
    # 120 bpm for 4 bars (16 beats), then ramp to 60 bpm over 4 bars.
    spec = _base_spec(tempo={"bpm": 120, "map": [{"bar": 4, "bpm": 60, "ramp_bars": 4}]})
    tm = TempoMap.from_spec(spec)
    # Constant region unchanged
    assert tm.beat_to_time(16.0) == pytest.approx(8.0)
    # Ramp region: closed form is 60*db/(v1-v0)*ln(v1/v0)
    ramp = 60.0 * 16.0 / (60.0 - 120.0) * math.log(60.0 / 120.0)
    assert tm.beat_to_time(32.0) == pytest.approx(8.0 + ramp)
    # After the map ends the final tempo holds
    assert tm.beat_to_time(36.0) == pytest.approx(8.0 + ramp + 4.0 * 60.0 / 60.0)
    # bpm_at reads back the ramp midpoint
    assert tm.bpm_at(24.0) == pytest.approx(90.0)


def test_tempo_map_time_to_beat_roundtrip():
    spec = _base_spec(tempo={"bpm": 144, "map": [
        {"bar": 8, "bpm": 100, "ramp_bars": 2},
        {"bar": 12, "bpm": 160, "ramp_bars": 4},
    ]})
    tm = TempoMap.from_spec(spec)
    for beat in (0.0, 3.7, 32.0, 41.5, 47.9, 64.0, 100.0):
        assert tm.time_to_beat(tm.beat_to_time(beat)) == pytest.approx(beat, abs=1e-6)


def test_tempo_map_is_monotone():
    spec = _base_spec(tempo={"bpm": 144, "map": [{"bar": 2, "bpm": 60, "ramp_bars": 1}]})
    tm = TempoMap.from_spec(spec)
    times = [tm.beat_to_time(b * 0.25) for b in range(200)]
    assert all(t1 > t0 for t0, t1 in zip(times, times[1:]))


def test_tempo_map_out_of_order_entries_rejected():
    spec = _base_spec(tempo={"bpm": 120, "map": [
        {"bar": 8, "bpm": 100, "ramp_bars": 2},
        {"bar": 4, "bpm": 140, "ramp_bars": 2},
    ]})
    with pytest.raises(ValueError):
        TempoMap.from_spec(spec)


def test_section_metadata_uses_tempo_map():
    spec = _base_spec(
        tempo={"bpm": 120, "map": [{"bar": 4, "bpm": 60, "ramp_bars": 4}]},
        sections=[
            {"id": "a", "bars": 4, "harmony": ["C"], "layers": []},
            {"id": "b", "bars": 4, "harmony": ["C"], "layers": []},
        ],
    )
    meta = section_metadata_from_spec(spec)
    assert meta[0]["end_seconds"] == pytest.approx(8.0)
    # Section b spans the full ritardando, so it is LONGER than at 120 bpm.
    assert meta[1]["duration_seconds"] > 8.0
    assert meta[1]["start_seconds"] == pytest.approx(meta[0]["end_seconds"])


def test_notes_ride_the_ritardando():
    slow = _base_spec(
        tempo={"bpm": 120, "map": [{"bar": 0, "bpm": 60, "ramp_bars": 4}]},
        sections=[{
            "id": "a", "bars": 4, "harmony": ["C"],
            "layers": [{
                "kind": "notes", "instrument": "piano",
                "notes": [[3, 0.0, "C4", 1.0, 80]],
            }],
        }],
    )
    pm, _groups, _meta = build_score(slow)
    note = pm.instruments[0].notes[0]
    # At constant 120 bpm bar 3 starts at 6.0 s; the ritardando pushes it later.
    assert note.start > 6.0


# ------------------------------------------------------------- notes layer

def test_notes_layer_list_and_dict_forms():
    spec = _base_spec(sections=[{
        "id": "a", "bars": 2, "harmony": ["C", "G"],
        "layers": [{
            "kind": "notes",
            "instrument": "piano",
            "velocity": 70,
            "notes": [
                [0, 0.0, "C4", 2.0, 90],
                [0, 2.0, ["E4", "G4"], 1.0],  # chord, default velocity
                {"bar": 1, "beat": 0.0, "note": "B4", "dur": 2.0, "vel": 55, "gate": 1.0},
            ],
        }],
    }])
    pm, _groups, _meta = build_score(spec)
    notes = sorted(pm.instruments[0].notes, key=lambda n: (n.start, n.pitch))
    assert [n.pitch for n in notes] == [60, 64, 67, 71]
    assert notes[0].velocity == 90
    assert notes[1].velocity == 70 and notes[2].velocity == 70
    # gate 1.0 -> full 2 beats at 120 bpm = 1.0 s
    assert notes[3].end - notes[3].start == pytest.approx(1.0, abs=1e-6)


def test_notes_layer_dict_bend_reaches_pitch_bends():
    spec = _base_spec(sections=[{
        "id": "a", "bars": 1, "harmony": ["C"],
        "layers": [{
            "kind": "notes", "instrument": "piano",
            "notes": [{"bar": 0, "beat": 0.0, "note": "C4", "dur": 2.0, "vel": 80,
                       "bend": [[0.0, 0], [1.0, 100]]}],
        }],
    }])
    pm, _groups, _meta = build_score(spec)
    assert len(pm.instruments[0].pitch_bends) >= 2


def test_notes_layer_rejects_short_rows():
    spec = _base_spec(sections=[{
        "id": "a", "bars": 1, "harmony": ["C"],
        "layers": [{"kind": "notes", "instrument": "piano", "notes": [[0, 0.0, "C4"]]}],
    }])
    with pytest.raises(ValueError):
        build_score(spec)


# ---------------------------------------------------------------- dynamics

def test_dynamics_curve_scales_velocities():
    def spec_with(dynamics):
        return _base_spec(sections=[{
            "id": "a", "bars": 4, "harmony": ["C", "C", "C", "C"],
            "layers": [{
                "kind": "notes", "instrument": "piano",
                "dynamics": dynamics,
                "notes": [[b, 0.0, "C4", 1.0, 100] for b in range(4)],
            }],
        }])

    pm, _g, _m = build_score(spec_with([{"start_bar": 0, "bars": 4, "from": 0.5, "to": 1.0}]))
    vels = [n.velocity for n in sorted(pm.instruments[0].notes, key=lambda n: n.start)]
    assert vels[0] == pytest.approx(50, abs=1)
    assert vels[-1] == pytest.approx(round(100 * (0.5 + 0.5 * 0.75)), abs=1)
    assert vels == sorted(vels), "crescendo must be monotone"


def test_dynamics_do_not_leak_between_layers():
    spec = _base_spec(sections=[{
        "id": "a", "bars": 1, "harmony": ["C"],
        "layers": [
            {"kind": "notes", "instrument": "piano",
             "dynamics": [{"start_bar": 0, "bars": 1, "from": 0.1, "to": 0.1}],
             "notes": [[0, 0.0, "C4", 1.0, 100]]},
            {"kind": "notes", "instrument": "piano",
             "notes": [[0, 2.0, "E4", 1.0, 100]]},
        ],
    }])
    pm, _g, _m = build_score(spec)
    notes = sorted(pm.instruments[0].notes, key=lambda n: n.start)
    assert notes[0].velocity == pytest.approx(10, abs=1)
    assert notes[1].velocity == 100


def test_instrument_controls_cc_init():
    spec = _base_spec()
    spec["instruments"][0]["controls"] = {100: 64, "sustain": 0}
    pm, _g, _m = build_score(spec)
    ccs = {(c.number, c.value) for c in pm.instruments[0].control_changes if c.time == 0.0}
    assert (100, 64) in ccs and (64, 0) in ccs


def test_instrument_controls_bad_key_rejected():
    spec = _base_spec()
    spec["instruments"][0]["controls"] = {"blend": 64}
    with pytest.raises(KeyError):
        build_score(spec)


def test_lead_collision_flags_simultaneous_seconds():
    from ambition_music_renderer.audit.lead_collision import audit_spec as lead_audit

    spec = _base_spec(sections=[{
        "id": "a", "bars": 2, "harmony": ["C", "C"],
        "layers": [
            {"kind": "notes", "instrument": "piano",
             "notes": [[0, 0.0, "E5", 4.0, 90]]},
            {"kind": "notes", "instrument": "piano", "_source_layer": "other",
             "notes": [[0, 1.0, "D5", 2.0, 90]]},
        ],
    }])
    report = lead_audit(spec)
    assert report["collision_count"] >= 1
    top = report["collisions"][0]
    assert set(top["notes"]) == {"E5", "D5"}
    assert top["interval_semitones"] == 2


def test_lead_collision_ignores_consonant_and_background():
    from ambition_music_renderer.audit.lead_collision import audit_spec as lead_audit

    spec = _base_spec(sections=[{
        "id": "a", "bars": 2, "harmony": ["C", "C"],
        "layers": [
            {"kind": "notes", "instrument": "piano",
             "notes": [[0, 0.0, "E5", 4.0, 90]]},
            # a third apart: fine
            {"kind": "notes", "instrument": "piano", "_source_layer": "other",
             "notes": [[0, 1.0, "G5", 2.0, 90]]},
            # background pad seconds are NOT this audit's business
            {"kind": "pad_chords", "instrument": "piano", "octave": 4,
             "duration_beats": 4.0},
        ],
    }])
    report = lead_audit(spec)
    assert report["collision_count"] == 0


def test_lead_collision_flags_exposed_tension():
    from ambition_music_renderer.audit.lead_collision import audit_spec as lead_audit

    spec = _base_spec(sections=[{
        "id": "a", "bars": 2, "harmony": ["D", "D"],
        "layers": [
            # E over D held 3 beats = an exposed 9th
            {"kind": "notes", "instrument": "piano",
             "notes": [{"bar": 0, "beat": 0.0, "note": "E5", "dur": 3.0, "vel": 80, "gate": 1.0}]},
        ],
    }])
    report = lead_audit(spec)
    assert report["exposed_tension_count"] >= 1
    assert report["exposed_tensions"][0]["tension"] == "9th"


def test_pitch_stability_flags_wobble_and_clean_steady():
    pytest.importorskip("librosa")
    import numpy as np
    from ambition_music_renderer.audit.pitch_stability import analyze_stem

    sr = 22050
    t = np.arange(int(sr * 2.0)) / sr
    # steady 440 for 2s: clean
    steady = 0.2 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    r = analyze_stem(steady, sr, min_note_s=0.5)
    assert r["wobble_count"] == 0
    # 440 wobbling +-60 cents at 0.7 Hz: flagged
    inst_freq = 440.0 * 2 ** (0.05 * np.sin(2 * np.pi * 0.7 * t))
    phase = 2 * np.pi * np.cumsum(inst_freq) / sr
    wobbly = 0.2 * np.sin(phase).astype(np.float32)
    r = analyze_stem(wobbly, sr, min_note_s=0.5)
    assert r["wobble_count"] >= 1
    assert r["wobble"][0]["deviation_cents"] > 30
