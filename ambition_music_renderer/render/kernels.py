"""Optional compiled DSP kernels for the music renderer.

This module is imported lazily by :mod:`ambition_music_renderer.render.musicir_renderer`
so normal CLI startup and YAML-only tooling do not pay the Numba import/compile
cost.  The small wrappers in ``musicir_renderer`` retain the public/testable
Python API and line-profiler visibility, while these functions provide the
sample-by-sample loops as native code for long renders.
"""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True)
def comb_filter_lowpass_feedback(
    signal_in: np.ndarray,
    delay: int,
    feedback: float,
    damping: float,
) -> np.ndarray:
    """Lowpass-feedback comb filter used by the internal reverb."""
    n = signal_in.shape[0]
    out = np.zeros(n, dtype=np.float32)
    if delay <= 0 or delay >= n:
        return out
    buffer = np.zeros(delay, dtype=np.float32)
    filter_state = 0.0
    write = 0
    one_minus_damping = 1.0 - damping
    for i in range(n):
        delayed = buffer[write]
        out[i] = delayed
        filter_state = delayed * one_minus_damping + filter_state * damping
        buffer[write] = signal_in[i] + filter_state * feedback
        write += 1
        if write >= delay:
            write = 0
    return out


@njit(cache=True)
def allpass_filter(
    signal_in: np.ndarray,
    delay: int,
    feedback: float,
) -> np.ndarray:
    """Schroeder-style allpass/diffuser filter used by the internal reverb."""
    n = signal_in.shape[0]
    out = np.zeros(n, dtype=np.float32)
    if delay <= 0 or delay >= n:
        return out
    buffer = np.zeros(delay, dtype=np.float32)
    write = 0
    for i in range(n):
        bufout = buffer[write]
        out[i] = -signal_in[i] + bufout
        buffer[write] = signal_in[i] + bufout * feedback
        write += 1
        if write >= delay:
            write = 0
    return out
