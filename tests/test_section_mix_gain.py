import numpy as np

from ambition_music_renderer.render.isolated import apply_section_mix_gains, section_mix_gain_envelope


def _spec():
    return {
        "tempo": {"bpm": 120},
        "render": {"section_mix_transition_beats": 1.0},
        "sections": [
            {"id": "a", "mix_gain_db": 6.0},
            {"id": "b", "mix_gain_db": -2.0},
        ],
    }


def _meta():
    return [
        {"id": "a", "start_seconds": 0.0, "end_seconds": 1.0},
        {"id": "b", "start_seconds": 1.0, "end_seconds": 2.0},
    ]


def test_section_mix_gain_envelope_holds_levels_and_smooths_boundary():
    envelope, gains = section_mix_gain_envelope(_spec(), _meta(), sample_rate=100, frame_count=200)

    assert gains == {"a": 6.0, "b": -2.0}
    assert np.isclose(envelope[10], 10 ** (6.0 / 20.0), rtol=1e-5)
    assert np.isclose(envelope[190], 10 ** (-2.0 / 20.0), rtol=1e-5)
    # One beat at 120 BPM is a half-second transition centered on the boundary.
    assert envelope[80] > envelope[100] > envelope[120]


def test_section_mix_gain_scales_every_stem_without_changing_shape():
    stems = {
        "lead": np.ones((200, 2), dtype=np.float32),
        "pads": np.full((200, 2), 0.25, dtype=np.float32),
    }
    gains = apply_section_mix_gains(stems, _spec(), _meta(), sample_rate=100, frame_count=200)

    assert gains == {"a": 6.0, "b": -2.0}
    assert stems["lead"].shape == (200, 2)
    assert stems["pads"].shape == (200, 2)
    assert np.isclose(stems["lead"][10, 0], 10 ** (6.0 / 20.0), rtol=1e-5)
    assert np.isclose(stems["pads"][190, 0], 0.25 * 10 ** (-2.0 / 20.0), rtol=1e-5)


def test_section_stem_mix_gain_scales_groups_independently():
    from ambition_music_renderer.render.isolated import apply_section_stem_mix_gains

    stems = {
        "strings": np.ones((200, 2), dtype=np.float32),
        "woodwinds": np.ones((200, 2), dtype=np.float32),
    }
    meta = [
        {
            "id": "a",
            "start_seconds": 0.0,
            "end_seconds": 1.0,
            "stem_mix_db": {"strings": -6.0, "woodwinds": 3.0},
        },
        {
            "id": "b",
            "start_seconds": 1.0,
            "end_seconds": 2.0,
            "stem_mix_db": {"strings": 0.0, "woodwinds": -3.0},
        },
    ]
    gains = apply_section_stem_mix_gains(
        stems, _spec(), meta, sample_rate=100, frame_count=200
    )

    assert gains["a"] == {"strings": -6.0, "woodwinds": 3.0}
    assert gains["b"] == {"strings": 0.0, "woodwinds": -3.0}
    assert np.isclose(stems["strings"][10, 0], 10 ** (-6.0 / 20.0), rtol=1e-5)
    assert np.isclose(stems["woodwinds"][10, 0], 10 ** (3.0 / 20.0), rtol=1e-5)
    assert np.isclose(stems["strings"][190, 0], 1.0, rtol=1e-5)
    assert np.isclose(stems["woodwinds"][190, 0], 10 ** (-3.0 / 20.0), rtol=1e-5)


def test_exact_form_metadata_preserves_audio_domain_mix_intent():
    from ambition_music_renderer.render.exact_score import ExactTempoMap, ScoreClock, _form_metadata

    score = {
        "timebase": {"ppq": 960},
        "meter": [{"bar": 1, "signature": "4/4"}],
        "tempo": [{"tick": 0, "bpm": 120}],
        "form": [
            {
                "id": "solo",
                "from": {"tick": 0},
                "to": {"tick": 3840},
                "stem_mix_db": {"woodwinds": 3.0, "strings": -2.0},
                "stem_mix_transition_beats": 0.5,
            }
        ],
    }
    clock = ScoreClock(score)
    tempo = ExactTempoMap(score, clock).bind_ppq(clock.ppq)
    meta = _form_metadata({"score": score}, clock, tempo, 3840)

    assert meta[0]["stem_mix_db"] == {"woodwinds": 3.0, "strings": -2.0}
    assert meta[0]["stem_mix_transition_beats"] == 0.5
