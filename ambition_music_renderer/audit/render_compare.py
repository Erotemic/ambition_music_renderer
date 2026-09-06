"""Before/after audio comparison for intentional renderer and mix changes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..audio_utils import coerce_stereo
from ..processing.metrics import audio_regression_metrics


def _analysis_window(x: np.ndarray, maximum: int = 262144) -> np.ndarray:
    if len(x) <= maximum:
        return x
    # Deterministic center window: enough resolution for broad spectral evidence
    # without allocating an FFT proportional to an hour-long asset.
    start = (len(x) - maximum) // 2
    return x[start:start + maximum]


def spectral_metrics(audio: np.ndarray, sample_rate: int) -> dict[str, Any]:
    x = coerce_stereo(audio).astype(np.float64, copy=False)
    if not len(x) or sample_rate <= 0:
        return {"centroid_hz": 0.0, "bass_energy_fraction": 0.0, "mid_energy_fraction": 0.0, "high_energy_fraction": 0.0}
    mono = np.mean(_analysis_window(x), axis=1)
    if len(mono) < 2:
        return {"centroid_hz": 0.0, "bass_energy_fraction": 0.0, "mid_energy_fraction": 0.0, "high_energy_fraction": 0.0}
    mono = mono - np.mean(mono)
    window = np.hanning(len(mono))
    spectrum = np.abs(np.fft.rfft(mono * window)) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sample_rate)
    total = float(np.sum(spectrum))
    if total <= 1e-24:
        return {"centroid_hz": 0.0, "bass_energy_fraction": 0.0, "mid_energy_fraction": 0.0, "high_energy_fraction": 0.0}
    def frac(lo: float, hi: float) -> float:
        mask = (freqs >= lo) & (freqs < hi)
        return float(np.sum(spectrum[mask]) / total)
    centroid = float(np.sum(freqs * spectrum) / total)
    return {
        "centroid_hz": centroid,
        "bass_energy_fraction": frac(20.0, 250.0),
        "mid_energy_fraction": frac(250.0, 4000.0),
        "high_energy_fraction": frac(4000.0, sample_rate / 2.0 + 1.0),
    }


def stereo_metrics(audio: np.ndarray) -> dict[str, Any]:
    x = coerce_stereo(audio).astype(np.float64, copy=False)
    if not len(x):
        return {"correlation": 0.0, "side_to_mid_rms_ratio": 0.0}
    left, right = x[:, 0], x[:, 1]
    denom = float(np.sqrt(np.sum(left * left) * np.sum(right * right)))
    correlation = float(np.sum(left * right) / denom) if denom > 1e-24 else 0.0
    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    mid_rms = float(np.sqrt(np.mean(mid * mid)))
    side_rms = float(np.sqrt(np.mean(side * side)))
    return {
        "correlation": max(-1.0, min(1.0, correlation)),
        "side_to_mid_rms_ratio": float(side_rms / max(mid_rms, 1e-12)),
    }


def _extended_metrics(audio: np.ndarray, sample_rate: int) -> dict[str, Any]:
    result = audio_regression_metrics(audio, sample_rate, include_lufs=True)
    peak = 10.0 ** (float(result["peak_dbfs"]) / 20.0)
    rms = 10.0 ** (float(result["rms_dbfs"]) / 20.0)
    result["crest_factor_db"] = float(20.0 * np.log10(max(peak / max(rms, 1e-12), 1e-12)))
    result["stereo"] = stereo_metrics(audio)
    result["spectrum"] = spectral_metrics(audio, sample_rate)
    return result


def compare_audio_arrays(before: np.ndarray, after: np.ndarray, sample_rate: int) -> dict[str, Any]:
    a = coerce_stereo(before).astype(np.float64, copy=False)
    b = coerce_stereo(after).astype(np.float64, copy=False)
    before_metrics = _extended_metrics(a, sample_rate)
    after_metrics = _extended_metrics(b, sample_rate)
    n = min(len(a), len(b))
    if n:
        delta = b[:n] - a[:n]
        delta_rms = float(np.sqrt(np.mean(delta * delta)))
        denom = float(np.sqrt(np.sum(a[:n] * a[:n]) * np.sum(b[:n] * b[:n])))
        correlation = float(np.sum(a[:n] * b[:n]) / denom) if denom > 1e-24 else 0.0
        max_abs_delta = float(np.max(np.abs(delta)))
    else:
        delta_rms = 0.0
        correlation = 0.0
        max_abs_delta = 0.0
    def d(path: tuple[str, ...]) -> float | None:
        x: Any = before_metrics
        y: Any = after_metrics
        for key in path:
            x = x.get(key) if isinstance(x, dict) else None
            y = y.get(key) if isinstance(y, dict) else None
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return float(y - x)
        return None
    return {
        "schema": "ambition.audio_comparison.v1",
        "sample_rate": int(sample_rate),
        "before": before_metrics,
        "after": after_metrics,
        "delta": {
            "duration_s": d(("duration_s",)),
            "peak_db": d(("peak_dbfs",)),
            "rms_db": d(("rms_dbfs",)),
            "integrated_lufs": d(("integrated_lufs",)),
            "crest_factor_db": d(("crest_factor_db",)),
            "spectral_centroid_hz": d(("spectrum", "centroid_hz")),
            "side_to_mid_rms_ratio": d(("stereo", "side_to_mid_rms_ratio")),
            "aligned_rms": delta_rms,
            "aligned_max_abs": max_abs_delta,
            "aligned_waveform_correlation": correlation,
            "common_duration_s": float(n / sample_rate) if sample_rate else 0.0,
        },
    }


def compare_audio_files(before_path: str | Path, after_path: str | Path) -> dict[str, Any]:
    import soundfile as sf
    before, sr_before = sf.read(str(before_path), always_2d=True, dtype="float32")
    after, sr_after = sf.read(str(after_path), always_2d=True, dtype="float32")
    if int(sr_before) != int(sr_after):
        raise ValueError(f"sample-rate mismatch: {sr_before} != {sr_after}")
    result = compare_audio_arrays(before, after, int(sr_before))
    result["before_path"] = str(Path(before_path))
    result["after_path"] = str(Path(after_path))
    return result
