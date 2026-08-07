from ambition_music_renderer.render.score_theory import chord_pitches


def test_chord_pitches_can_leave_slash_bass_to_low_sections():
    with_bass = chord_pitches("Bb/D", octave=4, voicing="triad")
    upper_only = chord_pitches(
        "Bb/D",
        octave=4,
        voicing="triad",
        include_slash_bass=False,
    )

    assert min(with_bass) == 50
    assert upper_only == [70, 74, 77]
