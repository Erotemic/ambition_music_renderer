"""Small audio-array helpers shared by render modules."""

from __future__ import annotations

import numpy as np


def coerce_stereo(audio: np.ndarray) -> np.ndarray:
    """Return ``audio`` as a contiguous float32 stereo array.

    Renderer code accepts mono, stereo, and occasionally over-wide arrays from
    backends/plugins. Normalizing that shape in one tiny module avoids circular
    imports between synth/effects/export/report modules.
    """
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim == 1:
        return np.repeat(arr[:, None], 2, axis=1)
    if arr.ndim != 2:
        raise ValueError(f"audio must be 1-D or 2-D, got shape {arr.shape!r}")
    if arr.shape[1] == 1:
        return np.repeat(arr, 2, axis=1)
    if arr.shape[1] >= 2:
        return np.ascontiguousarray(arr[:, :2], dtype=np.float32)
    return np.zeros((arr.shape[0], 2), dtype=np.float32)
