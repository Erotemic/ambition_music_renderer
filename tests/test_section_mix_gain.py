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
