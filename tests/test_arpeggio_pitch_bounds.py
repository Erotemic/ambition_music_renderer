from __future__ import annotations

import pytest


def _spec(layer: dict) -> dict:
    return {
        "id": "arpeggio_pitch_bounds_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "banjo", "program": "banjo", "group": "banjo"}
        ],
        "sections": [
            {
                "id": "main",
                "bars": 1,
                "harmony": ["Cadd9"],
                "layers": [layer],
            }
        ],
    }


def test_arpeggio_pitch_bounds_octave_place_notes_before_backend_rendering():
    from ambition_music_renderer.render.score_layers import build_score

    pm, _groups, _sections = build_score(
        _spec(
            {
                "kind": "arpeggio",
                "instrument": "banjo",
                "octave": 4,
                "pattern": [3],
                "step": 1.0,
                "duration_beats": 0.5,
                "min_pitch": 38,
                "max_pitch": 72,
            }
        )
    )
    pitches = [
        int(event["pitch"])
        for event in pm._ambition_note_events  # type: ignore[attr-defined]
        if event["instrument"] == "banjo"
    ]
    assert pitches
    assert min(pitches) >= 38
    assert max(pitches) <= 72
    # Cadd9's 9th is D5 (74) at octave 4; authored bounds place it at D4 (62)
    # instead of leaving the SFZ backend to repair it later.
    assert 62 in pitches
    assert 74 not in pitches


def test_arpeggio_pitch_bounds_reject_impossible_pitch_class_window():
    from ambition_music_renderer.render.score_layers import build_score

    with pytest.raises(ValueError, match="cannot place arpeggio pitch"):
        build_score(
            _spec(
                {
                    "kind": "arpeggio",
                    "instrument": "banjo",
                    "octave": 4,
                    "pattern": [0],
                    "step": 1.0,
                    "min_pitch": 61,
                    "max_pitch": 61,
                }
            )
        )


def test_arpeggio_pitch_bounds_accept_note_names():
    from ambition_music_renderer.render.score_layers import build_score
    from ambition_music_renderer.render.score_theory import note_to_midi

    def rendered_pitches(min_pitch, max_pitch):
        pm, _groups, _sections = build_score(
            _spec(
                {
                    "kind": "arpeggio",
                    "instrument": "banjo",
                    "octave": 4,
                    "pattern": [0, 1, 2, 3],
                    "step": 0.5,
                    "duration_beats": 0.25,
                    "min_pitch": min_pitch,
                    "max_pitch": max_pitch,
                }
            )
        )
        return [
            int(event["pitch"])
            for event in pm._ambition_note_events  # type: ignore[attr-defined]
            if event["instrument"] == "banjo"
        ]

    named = rendered_pitches("B2", "B5")
    numeric = rendered_pitches(note_to_midi("B2"), note_to_midi("B5"))
    assert named == numeric
    assert named
    assert min(named) >= note_to_midi("B2")
    assert max(named) <= note_to_midi("B5")
