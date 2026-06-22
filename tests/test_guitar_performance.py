from ambition_music_renderer import guitar_performance as gp


def test_allocate_chord_uses_unique_strings():
    assignment = gp.allocate_chord([52, 55, 59, 64], max_span=5)
    strings = [item.string_index for item in assignment]
    assert len(strings) == len(set(strings))
    assert all(0 <= item.fret <= 17 for item in assignment)


def test_down_and_up_strums_reverse_order():
    pitches = [52, 55, 59, 64]
    down, _ = gp.strum_plan(pitches, bpm=120, direction="down", spread_ms=40)
    up, _ = gp.strum_plan(pitches, bpm=120, direction="up", spread_ms=40)
    assert [ev["pitch"] for ev in down] == list(reversed([ev["pitch"] for ev in up]))
    assert down[0]["beat_offset"] == 0.0
    assert up[0]["beat_offset"] == 0.0
    assert down[-1]["beat_offset"] > down[0]["beat_offset"]


def test_take_specs_default_to_instruments():
    takes = gp.take_specs({}, ["left", "right"])
    assert [t["instrument"] for t in takes] == ["left", "right"]


def test_guitar_lead_honors_single_root_and_default_repeats_once():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "id": "guitar_lead_root_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "lead", "program": "overdrive_guitar", "group": "guitars"}
        ],
        "motifs": [
            {
                "id": "one_note",
                "root": "D4",
                "intervals": [0],
                "rhythm": [1.0],
                "velocities": [1.0],
            }
        ],
        "sections": [
            {
                "id": "loop",
                "bars": 4,
                "harmony": ["D"],
                "layers": [
                    {
                        "kind": "guitar_lead",
                        "instrument": "lead",
                        "motif": "one_note",
                        "root": "C4",
                        "starts": [[0, 0.0]],
                        "velocity": 80,
                    }
                ],
            }
        ],
    }
    pm, _, _ = build_score(spec)
    lead_events = [e for e in pm._ambition_note_events if e["instrument"] == "lead"]
    assert len(lead_events) == 1
    assert lead_events[0]["pitch"] % 12 == 0  # C, possibly octave-folded.



def test_guitar_chug_can_ignore_slash_bass_for_power_chords():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "slash_chug",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "gtr", "group": "strings", "program": "muted_guitar"},
        ],
        "layer_templates": {
            "chug": {
                "kind": "guitar_chug",
                "instrument": "gtr",
                "root_policy": "chord_root",
                "shape": "fifth",
                "pattern": [[0, 0.0, 0.25]],
                "octave": 2,
            },
        },
        "sections": [
            {"id": "loop", "bars": 1, "harmony": ["G/B"], "layers": ["chug"]},
        ],
    }
    pm, _groups, _meta = build_score(spec)
    pitches = sorted({note.pitch for inst in pm.instruments for note in inst.notes})
    assert pitches == [43, 50]


def test_guitar_chug_min_pitch_octave_folds_unplayable_low_roots():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "chug_min_pitch",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "gtr", "group": "strings", "program": "muted_guitar"},
        ],
        "layer_templates": {
            "chug": {
                "kind": "guitar_chug",
                "instrument": "gtr",
                "shape": "fifth",
                "pattern": [[0, 0.0, 0.25]],
                "octave": 2,
                "min_pitch": 40,
            },
        },
        "sections": [
            {"id": "loop", "bars": 1, "harmony": ["C"], "layers": ["chug"]},
        ],
    }
    pm, _groups, _meta = build_score(spec)
    pitches = sorted({note.pitch for inst in pm.instruments for note in inst.notes})
    assert pitches == [48, 55]


def test_guitar_lead_vibrato_adds_pitch_bend_events():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "lead_vibrato",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "lead", "group": "lead", "program": "overdrive_guitar"},
        ],
        "motifs": [
            {
                "id": "held",
                "root": "D4",
                "intervals": [0],
                "rhythm": [2.0],
                "velocities": [1.0],
            },
        ],
        "sections": [
            {
                "id": "loop",
                "bars": 1,
                "harmony": ["D"],
                "layers": [
                    {
                        "kind": "guitar_lead",
                        "instrument": "lead",
                        "motif": "held",
                        "root": "D4",
                        "pitch_vibrato_cents": 8.0,
                        "pitch_vibrato_rate_hz": 5.0,
                        "pitch_vibrato_delay_beats": 0.2,
                    }
                ],
            }
        ],
    }
    pm, _groups, _meta = build_score(spec)
    lead = pm.instruments[0]
    assert len(lead.notes) == 1
    assert len(lead.pitch_bends) > 4


def test_pad_chords_respect_max_notes_constraint():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "pad_max_notes",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "constraints": {"max_notes": 2},
        "instruments": [
            {"name": "pad", "group": "pad", "program": "clean_guitar"},
        ],
        "sections": [
            {
                "id": "loop",
                "bars": 1,
                "harmony": ["Gadd9"],
                "layers": [
                    {
                        "kind": "pad_chords",
                        "instrument": "pad",
                        "duration_beats": 3.8,
                        "voicing": "wide",
                        "constraints": {"max_notes": 2},
                    }
                ],
            }
        ],
    }
    pm, _groups, _meta = build_score(spec)
    assert len(pm.instruments[0].notes) == 2
