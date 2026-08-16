from __future__ import annotations

from pathlib import Path

import yaml

from ambition_music_renderer.render.score_layers import build_score


# Public-domain Mutopia soprano line, moved up one octave only for register
# separation in this piano control. These tuples intentionally encode the
# irregular rhythm: dotted quarters, eighths, halves, and the two eighth-note
# pairs in bars 10-11.
EXPECTED_MELODY = [
    (0, 0.0, "B5", 1.0), (0, 1.0, "B5", 1.0), (0, 2.0, "C6", 1.0), (0, 3.0, "D6", 1.0),
    (1, 0.0, "D6", 1.0), (1, 1.0, "C6", 1.0), (1, 2.0, "B5", 1.0), (1, 3.0, "A5", 1.0),
    (2, 0.0, "G5", 1.0), (2, 1.0, "G5", 1.0), (2, 2.0, "A5", 1.0), (2, 3.0, "B5", 1.0),
    (3, 0.0, "B5", 1.5), (3, 1.5, "A5", 0.5), (3, 2.0, "A5", 2.0),
    (4, 0.0, "B5", 1.0), (4, 1.0, "B5", 1.0), (4, 2.0, "C6", 1.0), (4, 3.0, "D6", 1.0),
    (5, 0.0, "D6", 1.0), (5, 1.0, "C6", 1.0), (5, 2.0, "B5", 1.0), (5, 3.0, "A5", 1.0),
    (6, 0.0, "G5", 1.0), (6, 1.0, "G5", 1.0), (6, 2.0, "A5", 1.0), (6, 3.0, "B5", 1.0),
    (7, 0.0, "A5", 1.5), (7, 1.5, "G5", 0.5), (7, 2.0, "G5", 2.0),
    (8, 0.0, "A5", 1.0), (8, 1.0, "A5", 1.0), (8, 2.0, "B5", 1.0), (8, 3.0, "G5", 1.0),
    (9, 0.0, "A5", 1.0), (9, 1.0, "B5", 0.5), (9, 1.5, "C6", 0.5), (9, 2.0, "B5", 1.0), (9, 3.0, "G5", 1.0),
    (10, 0.0, "A5", 1.0), (10, 1.0, "B5", 0.5), (10, 1.5, "C6", 0.5), (10, 2.0, "B5", 1.0), (10, 3.0, "A5", 1.0),
    (11, 0.0, "G5", 1.0), (11, 1.0, "A5", 1.0), (11, 2.0, "D6", 2.0),
    (12, 0.0, "B5", 1.0), (12, 1.0, "B5", 1.0), (12, 2.0, "C6", 1.0), (12, 3.0, "D6", 1.0),
    (13, 0.0, "D6", 1.0), (13, 1.0, "C6", 1.0), (13, 2.0, "B5", 1.0), (13, 3.0, "A5", 1.0),
    (14, 0.0, "G5", 1.0), (14, 1.0, "G5", 1.0), (14, 2.0, "A5", 1.0), (14, 3.0, "B5", 1.0),
    (15, 0.0, "A5", 1.5), (15, 1.5, "G5", 0.5), (15, 2.0, "G5", 2.0),
]


def _load_control() -> dict:
    path = Path(__file__).resolve().parents[1] / "scores" / "active" / "public_domain_ode_to_joy_autopiano_control.music.yaml"
    return yaml.safe_load(path.read_text(encoding="utf8"))


def test_ode_to_joy_control_preserves_public_domain_melody_timing_exactly():
    spec = _load_control()
    assert spec["tempo"]["bpm"] == 100

    pm, _groups, _sections = build_score(spec)
    melody = [
        event for event in pm._ambition_note_events
        if event["layer"] == "right_hand_exact_melody"
    ]
    assert len(melody) == len(EXPECTED_MELODY) == 62

    actual = [
        (
            int(event["nominal_bar"]),
            round(float(event["nominal_beat"]), 6),
            event["note"],
            round(float(event["nominal_duration_beats"]), 6),
        )
        for event in melody
    ]
    assert actual == EXPECTED_MELODY

    # The renderer must preserve the authored beat timing, not quantize the
    # line into evenly spaced quarter notes.
    starts = [round(float(event["start_beat"]), 6) for event in melody]
    onset_gaps = {round(b - a, 6) for a, b in zip(starts, starts[1:])}
    durations = {round(float(event["end_beat"] - event["start_beat"]), 6) for event in melody}
    assert {0.5, 1.0, 1.5, 2.0}.issubset(onset_gaps)
    assert durations == {0.5, 1.0, 1.5, 2.0}

    # At 100 quarter notes/minute, 64 beats are exactly 38.4 seconds.
    assert abs(max(float(event["end_time"]) for event in melody) - 38.4) < 1e-6


def test_ode_to_joy_control_is_polyphonic_and_register_separated():
    spec = _load_control()
    pm, _groups, _sections = build_score(spec)
    events = list(pm._ambition_note_events)
    melody = [event for event in events if event["layer"] == "right_hand_exact_melody"]
    accompaniment = [event for event in events if event["layer"] != "right_hand_exact_melody"]

    # One actual piano instrument is used for all voices.
    assert len(pm.instruments) == 1

    # The octave lift is deliberate: accompaniment tops at B4, melody bottoms
    # at G5, so no accompaniment note can masquerade as the lead voice.
    assert max(int(event["pitch"]) for event in accompaniment) == 71  # B4
    assert min(int(event["pitch"]) for event in melody) == 79  # G5

    # Every melody attack happens while the public-domain lower voices are also
    # sounding/attacking, proving the renderer handles simultaneous polyphony
    # rather than sequencing a melody and accompaniment one after another.
    for note in melody:
        t = float(note["start_beat"])
        assert any(
            float(acc["start_beat"]) <= t < float(acc["end_beat"])
            for acc in accompaniment
        )


def test_ode_to_joy_timing_survives_midi_serialization(tmp_path):
    import pretty_midi

    spec = _load_control()
    pm, _groups, _sections = build_score(spec)
    path = tmp_path / "ode-to-joy-control.mid"
    pm.write(str(path))

    round_trip = pretty_midi.PrettyMIDI(str(path))
    notes = [
        note
        for inst in round_trip.instruments
        for note in inst.notes
        if int(note.pitch) >= 79  # G5 and above: the isolated melody register
    ]
    notes.sort(key=lambda note: (float(note.start), int(note.pitch)))
    assert len(notes) == len(EXPECTED_MELODY)

    seconds_per_beat = 60.0 / 100.0
    for note, (bar, beat, _pitch_name, duration_beats) in zip(notes, EXPECTED_MELODY):
        expected_start = (bar * 4.0 + beat) * seconds_per_beat
        expected_duration = duration_beats * seconds_per_beat
        assert abs(float(note.start) - expected_start) < 1e-4
        assert abs((float(note.end) - float(note.start)) - expected_duration) < 1e-4


def test_source_exact_control_preserves_mutopia_soprano_pitches_and_timing():
    path = Path(__file__).resolve().parents[1] / "scores" / "active" / "public_domain_ode_to_joy_source_exact_control.music.yaml"
    spec = yaml.safe_load(path.read_text(encoding="utf8"))
    pm, _groups, _sections = build_score(spec)
    soprano = [event for event in pm._ambition_note_events if event["layer"] == "source_soprano"]
    assert len(soprano) == len(EXPECTED_MELODY)

    # The register-separated control is exactly one octave above this source
    # transcription; rhythmic coordinates and durations are otherwise identical.
    from ambition_music_renderer.render.score_theory import note_to_midi

    actual = [
        (
            int(event["nominal_bar"]),
            round(float(event["nominal_beat"]), 6),
            int(event["pitch"]),
            round(float(event["nominal_duration_beats"]), 6),
        )
        for event in soprano
    ]
    expected = [
        (bar, beat, note_to_midi(note) - 12, duration)
        for bar, beat, note, duration in EXPECTED_MELODY
    ]
    assert actual == expected
