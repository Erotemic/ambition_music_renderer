from __future__ import annotations

import numpy as np

from ambition_music_renderer.render.effects import _allpass_filter, _comb_filter, _compressor_envelope, compressor, simple_reverb
from ambition_music_renderer.render.score_theory import clamp


def _reference_comb_filter(signal_in, delay, feedback, damping):
    n = len(signal_in)
    out = np.zeros(n, dtype=np.float32)
    if delay <= 0 or delay >= n:
        return out
    buffer = np.zeros(delay, dtype=np.float32)
    filter_state = 0.0
    write = 0
    damping = float(clamp(damping, 0.0, 0.99))
    one_minus_damping = 1.0 - damping
    sig = np.asarray(signal_in, dtype=np.float32)
    for i in range(n):
        delayed = buffer[write]
        out[i] = delayed
        filter_state = delayed * one_minus_damping + filter_state * damping
        buffer[write] = sig[i] + filter_state * feedback
        write += 1
        if write >= delay:
            write = 0
    return out


def _reference_allpass_filter(signal_in, delay, feedback=0.5):
    n = len(signal_in)
    out = np.zeros(n, dtype=np.float32)
    if delay <= 0 or delay >= n:
        return out
    buffer = np.zeros(delay, dtype=np.float32)
    write = 0
    sig = np.asarray(signal_in, dtype=np.float32)
    for i in range(n):
        bufout = buffer[write]
        out[i] = -sig[i] + bufout
        buffer[write] = sig[i] + bufout * feedback
        write += 1
        if write >= delay:
            write = 0
    return out


def test_comb_filter_matches_reference():
    rng = np.random.default_rng(0)
    signal_in = rng.normal(size=4096).astype(np.float32)
    got = _comb_filter(signal_in, delay=137, feedback=0.83, damping=0.42)
    expected = _reference_comb_filter(signal_in, delay=137, feedback=0.83, damping=0.42)
    np.testing.assert_allclose(got, expected, rtol=1e-6, atol=1e-6)


def test_allpass_filter_matches_reference():
    rng = np.random.default_rng(1)
    signal_in = rng.normal(size=4096).astype(np.float32)
    got = _allpass_filter(signal_in, delay=71, feedback=0.5)
    expected = _reference_allpass_filter(signal_in, delay=71, feedback=0.5)
    np.testing.assert_allclose(got, expected, rtol=1e-6, atol=1e-6)


def test_simple_reverb_keeps_shape_and_dtype():
    rng = np.random.default_rng(2)
    audio = rng.normal(scale=0.05, size=(2048, 2)).astype(np.float32)
    out = simple_reverb(audio, 48_000, wet=0.12, decay=0.8)
    assert out.shape == audio.shape
    assert out.dtype == np.float32
    assert np.isfinite(out).all()


def test_compressor_envelope_matches_reference_loop():
    gr = np.array([0.0, -1.0, -4.0, -3.0, -0.5, 0.0], dtype=np.float32)
    attack = 0.8
    release = 0.95
    expected = np.zeros_like(gr)
    state = 0.0
    for idx, target in enumerate(gr):
        if target < state:
            state = attack * state + (1.0 - attack) * float(target)
        else:
            state = release * state + (1.0 - release) * float(target)
        expected[idx] = state
    got = _compressor_envelope(gr, attack, release)
    np.testing.assert_allclose(got, expected, rtol=1e-6, atol=1e-6)


def test_compressor_keeps_shape_dtype_and_finite_values():
    rng = np.random.default_rng(3)
    audio = rng.normal(scale=0.2, size=(8192, 2)).astype(np.float32)
    out = compressor(audio, 48_000, threshold_db=-18, ratio=3.0)
    assert out.shape == audio.shape
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
