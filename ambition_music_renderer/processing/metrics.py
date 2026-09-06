"""Small deterministic audio-regression metrics for processing/mastering tests."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from ..audio_utils import coerce_stereo


def _db(value: float) -> float:
    return float(20.0 * np.log10(max(float(value), 1e-12)))


def audio_regression_metrics(audio: np.ndarray, sample_rate: int, *, include_lufs: bool = False) -> dict[str, Any]:
    x = coerce_stereo(audio).astype(np.float64, copy=False)
    if not x.size:
        return {
            "duration_s": 0.0,
            "peak_dbfs": -240.0,
            "rms_dbfs": -240.0,
            "clipped_sample_count": 0,
            "dc_offset": [0.0, 0.0],
        }
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(np.square(x))))
    result: dict[str, Any] = {
        "duration_s": float(len(x) / sample_rate) if sample_rate else 0.0,
        "peak_dbfs": _db(peak),
        "rms_dbfs": _db(rms),
        "clipped_sample_count": int(np.count_nonzero(np.abs(x) > 1.0)),
        "dc_offset": [float(v) for v in np.mean(x, axis=0)],
    }
    if include_lufs and sample_rate and len(x) >= int(sample_rate * 0.4):
        try:
            import pyloudnorm as pyln

            result["integrated_lufs"] = float(pyln.Meter(sample_rate).integrated_loudness(x))
        except Exception:
            result["integrated_lufs"] = None
    return result


def section_boundary_metrics(
    audio: np.ndarray,
    sample_rate: int,
    sections: Sequence[Mapping[str, Any]],
    *,
    window_ms: float = 10.0,
) -> list[dict[str, Any]]:
    x = coerce_stereo(audio).astype(np.float64, copy=False)
    radius = max(1, int(round(float(window_ms) * 1e-3 * sample_rate)))
    rows: list[dict[str, Any]] = []
    for idx in range(1, len(sections)):
        sec = sections[idx]
        boundary = int(round(float(sec.get("start_seconds", 0.0)) * sample_rate))
        if boundary <= 0 or boundary >= len(x):
            continue
        left = x[max(0, boundary - radius):boundary]
        right = x[boundary:min(len(x), boundary + radius)]
        left_rms = float(np.sqrt(np.mean(np.square(left)))) if left.size else 0.0
        right_rms = float(np.sqrt(np.mean(np.square(right)))) if right.size else 0.0
        jump = float(np.max(np.abs(x[boundary] - x[boundary - 1])))
        rows.append({
            "section": str(sec.get("id")),
            "time_s": float(boundary / sample_rate),
            "sample_jump": jump,
            "left_rms_dbfs": _db(left_rms),
            "right_rms_dbfs": _db(right_rms),
            "rms_step_db": float(_db(right_rms) - _db(left_rms)),
        })
    return rows
