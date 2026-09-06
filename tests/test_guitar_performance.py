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


def test_sampled_chord_emits_one_root_and_a_classified_keyswitch():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "sampled_chord_trigger",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [{"name": "gtr", "group": "strings", "program": "clean_guitar"}],
        "sections": [{
            "id": "loop", "bars": 1, "harmony": ["Em"],
            "layers": [{
                "kind": "sampled_chord", "instrument": "gtr",
                "quality": "power", "keyswitches": {"power": 33, "minor": 34, "major": 35},
                "pattern": [[0, 0.0, 0.5]], "octave": 3,
            }],
        }],
    }
    pm, _groups, _meta = build_score(spec)
    events = [event for event in pm._ambition_note_events if event["instrument"] == "gtr"]
    assert [event["event_type"] for event in events] == ["keyswitch", "note"]
    assert events[0]["keyswitch"] == 33
    assert events[1]["pitch"] == 52
    assert [note.pitch for note in pm.instruments[0].notes] == [33, 52]


def test_sampled_chord_can_target_selected_section_bars():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "sampled_chord_bar_selection",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [{"name": "gtr", "group": "strings", "program": "clean_guitar"}],
        "sections": [{
            "id": "loop", "bars": 4, "harmony": ["Em", "G", "C", "B7"],
            "layers": [{
                "kind": "sampled_chord", "instrument": "gtr", "bars": [0, 3],
                "quality": "power", "keyswitches": {"power": 33},
                "pattern": [[0, 0.0, 0.5]], "octave": 3,
            }],
        }],
    }
    pm, _groups, _meta = build_score(spec)
    notes = [
        event for event in pm._ambition_note_events
        if event["instrument"] == "gtr" and event["event_type"] == "note"
    ]
    assert [event["nominal_bar"] for event in notes] == [0.0, 3.0]


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


def test_guitar_strum_per_hit_duration_and_shell_voicing():
    from ambition_music_renderer.render.score_core import RenderContext
    from ambition_music_renderer.render.score_layers import render_layer_guitar_strum
    from ambition_music_renderer.render.score_theory import chord_pitches

    assert len(chord_pitches("D(add9)", octave=3, voicing="guitar_shell")) == 3
    assert len(chord_pitches("A/C#", octave=3, voicing="root_fifth_octave")) == 3

    import numpy as np
    import pretty_midi

    spec = {
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [{"name": "gtr", "program": "clean_guitar", "group": "gtr"}],
        "constraints": {"min_pitch": 36, "max_pitch": 88},
    }
    inst = pretty_midi.Instrument(program=pretty_midi.instrument_name_to_program("Acoustic Guitar (nylon)"), name="gtr")
    ctx = RenderContext(
        spec=spec,
        sample_rate=48000,
        bpm=120,
        beats_per_bar=4,
        rng=np.random.default_rng(0),
        pm=pretty_midi.PrettyMIDI(initial_tempo=120),
        instruments={"gtr": inst},
        groups={"gtr": "gtr"},
        section_starts={"s": 0},
        motifs={},
        instrument_specs={"gtr": spec["instruments"][0]},
    )
    section = {"id": "s", "bars": 1, "start_bar": 0, "harmony": ["D(add9)"], "intensity": 1.0}
    render_layer_guitar_strum(
        ctx,
        section,
        {
            "kind": "guitar_strum",
            "instrument": "gtr",
            "hits": [[0, 0.0, "down", 2.5], [0, 2.0, "up", 0.75]],
            "voicing": "guitar_shell",
            "max_notes": 3,
            "spread_ms": 1,
            "humanize_ms": 0,
            "gate": 1.0,
            "physical_string_sustain": False,
        },
    )
    beat_durs = sorted(round((n.end - n.start) * ctx.bpm / 60.0, 2) for n in ctx.instruments["gtr"].notes)
    assert min(beat_durs) == 0.75
    assert max(beat_durs) == 2.5


def test_strum_shape_plan_preserves_authored_open_chord():
    # Open-position Bm7: x20202. This intentionally avoids the allocator's
    # otherwise legal seventh-fret barre voicing.
    events, assignment = gp.strum_shape_plan(
        ["x", 2, 0, 2, 0, 2], bpm=96, direction="down", spread_ms=24
    )
    assert [(item.string_index, item.fret) for item in assignment] == [
        (1, 2), (2, 0), (3, 2), (4, 0), (5, 2)
    ]
    assert [int(event["pitch"]) for event in events] == [47, 50, 57, 59, 66]


def test_guitar_strum_chord_shapes_override_allocator():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "authored_guitar_shape",
        "tempo": {"bpm": 96},
        "meter": {"beats_per_bar": 4},
        "instruments": [{"name": "gtr", "group": "gtr", "program": "steel_guitar"}],
        "sections": [{
            "id": "bar",
            "bars": 1,
            "harmony": ["Bm7"],
            "layers": [{
                "kind": "guitar_strum",
                "instrument": "gtr",
                "hits": [[0, 0.0, "down", 1.0]],
                "humanize_ms": 0,
                "chord_shapes": {"Bm7": ["x", 2, 0, 2, 0, 2]},
            }],
        }],
    }
    pm, _groups, _meta = build_score(spec)
    pitches = sorted(note.pitch for note in pm.instruments[0].notes)
    assert pitches == [47, 50, 57, 59, 66]


def test_guitar_strum_chokes_old_fret_on_same_physical_string():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "physical_string_sustain",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [{"name": "gtr", "group": "gtr", "program": "steel_guitar"}],
        "sections": [{
            "id": "bar",
            "bars": 1,
            "harmony": ["Dadd9"],
            "layers": [{
                "kind": "guitar_strum",
                "instrument": "gtr",
                "hits": [[0, 0.0, "down", 3.96], [0, 2.0, "down", "F#7", 1.96]],
                "spread_ms": 1,
                "humanize_ms": 0,
                "gate": 1.0,
                "chord_shapes": {
                    "Dadd9": ["x", "x", 0, 2, 3, 0],
                    "F#7": [2, 4, 2, 3, 2, 2],
                },
            }],
        }],
    }
    pm, _groups, _meta = build_score(spec)
    first_shape_pitches = {50, 57, 62, 64}
    first_notes = [note for note in pm.instruments[0].notes if note.pitch in first_shape_pitches and note.start < 0.1]
    assert len(first_notes) == 4
    # Beat 2 at 120 bpm is 1.0s. Every old string should be released at its
    # re-fret rather than ringing under F#7 for the original 3.96 beats.
    assert max(note.end for note in first_notes) < 1.01
    assert min(note.end for note in first_notes) > 0.97


def test_guitar_shape_pick_uses_authored_physical_strings_and_paired_courses():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "shape_pick_courses",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "body", "group": "body", "program": "steel_guitar"},
            {"name": "courses", "group": "courses", "program": "steel_guitar"},
        ],
        "sections": [
            {
                "id": "s",
                "bars": 1,
                "harmony": ["Bm7"],
                "layers": [
                    {
                        "kind": "guitar_shape_pick",
                        "instrument": "body",
                        "tuning": "standard",
                        "chord_shapes": {"Bm7": ["x", 2, 0, 2, 0, 2]},
                        "pattern": [0, 1, 2, 3, 4],
                        "step": 0.5,
                        "duration_beats": 0.4,
                        "velocity": 80,
                        "density": 1.0,
                        "humanize_ms": 0,
                        "humanize_velocity_pct": 0,
                        "paired_course_instrument": "courses",
                        "paired_course_delay_ms": 0,
                        "paired_course_velocity_scale": 0.5,
                    }
                ],
            }
        ],
    }
    pm, _groups, _meta = build_score(spec)
    by_name = {inst.name: inst for inst in pm.instruments}
    body = [note.pitch for note in by_name["body"].notes[:5]]
    courses = [note.pitch for note in by_name["courses"].notes[:5]]
    assert body == [47, 50, 57, 59, 66]
    # Low four physical courses are octave-paired; B/high-E courses are unison.
    assert courses == [59, 62, 69, 59, 66]


def test_guitar_shape_pick_can_reuse_chord_shapes_from_strum_template():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "shape_pick_template",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [{"name": "body", "group": "body", "program": "steel_guitar"}],
        "layer_templates": {
            "strum": {
                "kind": "guitar_strum",
                "instrument": "body",
                "chord_shapes": {"Dadd9": [0, 0, 0, 2, 3, 0]},
            }
        },
        "sections": [
            {
                "id": "s",
                "bars": 1,
                "harmony": ["Dadd9"],
                "layers": [
                    {
                        "kind": "guitar_shape_pick",
                        "instrument": "body",
                        "tuning": "drop_d",
                        "shape_template": "strum",
                        "pattern": [0, 5],
                        "step": 2.0,
                        "duration_beats": 0.5,
                        "humanize_ms": 0,
                        "humanize_velocity_pct": 0,
                    }
                ],
            }
        ],
    }
    pm, _groups, _meta = build_score(spec)
    pitches = [note.pitch for inst in pm.instruments for note in inst.notes]
    assert pitches == [38, 64]


def test_sampled_chord_keyswitch_is_released_before_humanized_attack():
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "sampled_chord_keyswitch_timing",
        "seed": 7,
        "tempo": {"bpm": 180},
        "meter": {"beats_per_bar": 4},
        "instruments": [{"name": "gtr", "group": "strings", "program": "clean_guitar"}],
        "sections": [{
            "id": "loop", "bars": 1, "harmony": ["Em"],
            "layers": [{
                "kind": "sampled_chord", "instrument": "gtr",
                "quality": "power", "keyswitches": {"power": 33},
                "pattern": [[0, 0.0, 0.5]], "octave": 3,
                "humanize_ms": 25.0,
                "keyswitch_lead_ms": 10.0,
                "keyswitch_duration_ms": 5.0,
            }],
        }],
    }
    pm, _groups, _meta = build_score(spec)
    events = [event for event in pm._ambition_note_events if event["instrument"] == "gtr"]
    switch, note = events
    assert switch["event_type"] == "keyswitch"
    assert note["event_type"] == "note"
    assert switch["end_time"] <= note["start_time"]
    assert note["start_time"] - switch["start_time"] >= 0.0099


def test_sampled_chord_rejects_keyswitch_duration_without_release_gap():
    import pytest
    from ambition_music_renderer.render.score_layers import build_score

    spec = {
        "schema": "ambition.musicir.v1",
        "id": "sampled_chord_bad_keyswitch_timing",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [{"name": "gtr", "group": "strings", "program": "clean_guitar"}],
        "sections": [{
            "id": "loop", "bars": 1, "harmony": ["Em"],
            "layers": [{
                "kind": "sampled_chord", "instrument": "gtr",
                "quality": "power", "keyswitches": {"power": 33},
                "pattern": [[0, 0.0, 0.5]], "octave": 3,
                "keyswitch_lead_ms": 5.0,
                "keyswitch_duration_ms": 5.0,
            }],
        }],
    }
    with pytest.raises(ValueError, match="keyswitch_duration_ms must be smaller"):
        build_score(spec)
