"""LUFS loudness normalization helpers for the MusicIR renderer.

This module keeps pyloudnorm isolated so the renderer can degrade gracefully in
minimal environments while still getting BS.1770-style loudness matching when
that dependency is installed.  The public function accepts normal renderer
shape audio (samples, channels) and returns the same shape.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from .audio_utils import coerce_stereo


def peak_limit(audio: np.ndarray, target_peak_db: float) -> np.ndarray:
    x = coerce_stereo(audio).copy()
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak <= 1e-12:
        return x.astype(np.float32)
    target = 10.0 ** (float(target_peak_db) / 20.0)
    if peak > target:
        x *= target / peak
    return x.astype(np.float32)


def normalize_lufs(
    audio: np.ndarray,
    sample_rate: int,
    *,
    target_lufs: float,
    true_peak_db: float | None = None,
    block_size: float = 0.400,
) -> np.ndarray:
    """Normalize to target LUFS and optionally cap the peak afterwards.

    The true-peak cap is implemented as a conservative sample-peak cap here.
    It is intentionally simple and deterministic; a future oversampled true
    peak limiter can replace this without changing the YAML surface.
    """
    try:
        import pyloudnorm as pyln  # type: ignore
    except Exception as ex:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "pyloudnorm is required for target_lufs loudness normalization. "
            "Install the music renderer dependencies or remove target_lufs."
        ) from ex
    x = coerce_stereo(audio)
    if len(x) == 0 or float(np.max(np.abs(x))) <= 1e-12:
        return x.astype(np.float32)
    meter = pyln.Meter(int(sample_rate), block_size=float(block_size))
    loudness = float(meter.integrated_loudness(x))
    out = pyln.normalize.loudness(x, loudness, float(target_lufs)).astype(np.float32)
    if true_peak_db is not None:
        out = peak_limit(out, float(true_peak_db))
    return out.astype(np.float32, copy=False)


def apply_loudness_settings(audio: np.ndarray, sample_rate: int, settings: dict[str, Any]) -> np.ndarray:
    """Apply loudness keys from a postprocess settings block.

    Accepted YAML shapes:

    ``target_lufs: -16``
    ``loudness_target_lufs: -16``
    ``loudness: {target_lufs: -16, true_peak_db: -1.5}``
    """
    cfg = settings.get("loudness") or {}
    if not isinstance(cfg, dict):
        cfg = {"target_lufs": cfg}
    target = cfg.get("target_lufs", settings.get("target_lufs", settings.get("loudness_target_lufs")))
    if target is None:
        return coerce_stereo(audio)
    true_peak = cfg.get("true_peak_db", settings.get("true_peak_db", settings.get("loudness_true_peak_db")))
    return normalize_lufs(
        audio,
        sample_rate,
        target_lufs=float(target),
        true_peak_db=None if true_peak is None else float(true_peak),
        block_size=float(cfg.get("block_size", settings.get("loudness_block_size", 0.400))),
    )
