"""Small shared audio-array helpers (no internal deps so render *and* backends
can use them without import cycles)."""

from __future__ import annotations

import numpy as np


def coerce_stereo(audio: np.ndarray) -> np.ndarray:
    """Return ``audio`` as a contiguous float32 stereo ``(N, 2)`` array.

    Accepts mono (1-D), sample-first ``(N, C)``, and channel-first ``(C, N)``
    layouts — Pedalboard returns channel-first, SoundFile sample-first — plus
    mono ``C == 1`` and over-wide ``C > 2`` inputs. One home for this replaces
    the half-dozen near-identical copies that had drifted across the
    render/backends/loudness modules.
    """
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim == 1:
        return np.repeat(arr[:, None], 2, axis=1)
    if arr.ndim != 2:
        raise ValueError(f"audio must be 1-D or 2-D, got shape {arr.shape!r}")
    # Channel-first (e.g. Pedalboard ``(1|2, N)``): transpose to sample-first.
    # A real audio buffer never has only 1-2 samples, so rows in {1,2} with more
    # columns unambiguously means channels-as-rows.
    if arr.shape[0] in (1, 2) and arr.shape[1] > arr.shape[0]:
        arr = arr.T
    if arr.shape[1] == 1:
        return np.repeat(arr, 2, axis=1)
    if arr.shape[1] >= 2:
        return np.ascontiguousarray(arr[:, :2], dtype=np.float32)
    return np.zeros((arr.shape[0], 2), dtype=np.float32)
