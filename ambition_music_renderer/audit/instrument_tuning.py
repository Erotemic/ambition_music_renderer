"""Measured tuning audit for isolated pitched instruments.

Unlike a generic pitch detector, this audit knows the MIDI note the renderer was
asked to synthesize.  It therefore estimates pitch only in a narrow window around
the equal-tempered target, which avoids most octave/fundamental ambiguity on
bright sampled instruments.

The result is observational machine evidence.  It never changes MusicIR,
instrument-catalog authority, or render tuning automatically.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .sfz_measurement import midi_frequency


TUNING_REPORT_SCHEMA = "ambition.instrument_tuning_audit.v2"


def _mono(audio: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float64)
    if arr.ndim == 2:
        if arr.shape[1] == 0:
            return np.empty(0, dtype=np.float64)
        # Do not average stereo samples blindly: opposite-polarity or wide
        # microphone channels can partially cancel even when each channel has a
        # perfectly measurable pitch. Use the channel with the most energy.
        energies = np.mean(np.square(arr), axis=0, dtype=np.float64)
        arr = arr[:, int(np.argmax(energies))]
    return arr[np.isfinite(arr)]


def estimate_known_note_tuning(
    audio: np.ndarray,
    sample_rate: int,
    expected_midi: int,
    *,
    attack_seconds: float = 0.06,
    release_seconds: float = 0.04,
    search_cents: float = 100.0,
) -> dict[str, Any]:
    """Estimate cents offset for audio whose intended MIDI pitch is known.

    The estimator uses normalized autocorrelation in a narrow lag interval around
    the expected equal-tempered period.  Several overlapping frames are measured
    and combined robustly, so ordinary sample attacks and mild vibrato do not
    become a single-frame tuning claim.
    """

    mono = _mono(audio)
    expected_hz = midi_frequency(expected_midi)
    base = {
        "midi": int(expected_midi),
        "expected_hz": round(float(expected_hz), 5),
    }
    if len(mono) < 256:
        return {**base, "status": "unreliable", "reason": "too_short"}

    peak = float(np.max(np.abs(mono), initial=0.0))
    rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float64))) if len(mono) else 0.0
    if peak < 1e-6 or rms < 1e-7:
        return {**base, "status": "silent", "reason": "no_measurable_audio"}

    attack = min(int(max(0.0, attack_seconds) * sample_rate), len(mono) // 5)
    release = min(int(max(0.0, release_seconds) * sample_rate), len(mono) // 8)
    stop = len(mono) - release if release else len(mono)
    steady = mono[attack:stop]
    if len(steady) < 256:
        steady = mono

    expected_period = sample_rate / expected_hz
    desired = max(1024.0, expected_period * 10.0)
    power = int(math.ceil(math.log2(desired)))
    frame_len = int(max(2048, min(8192, 2**power)))
    frame_len = min(frame_len, len(steady))
    if frame_len < 256:
        return {**base, "status": "unreliable", "reason": "steady_window_too_short"}
    hop = max(128, frame_len // 2)

    min_hz = expected_hz * 2.0 ** (-float(search_cents) / 1200.0)
    max_hz = expected_hz * 2.0 ** (float(search_cents) / 1200.0)
    lag_min = max(1, int(math.floor(sample_rate / max_hz)) - 2)
    lag_max = int(math.ceil(sample_rate / min_hz)) + 2

    measurements: list[tuple[float, float]] = []
    last_start = max(0, len(steady) - frame_len)
    starts = list(range(0, last_start + 1, hop))
    if starts and starts[-1] != last_start:
        starts.append(last_start)
    if not starts:
        starts = [0]

    for start in starts:
        frame = steady[start:start + frame_len]
        if len(frame) < max(256, frame_len // 2):
            continue
        frame = frame - float(np.mean(frame))
        frame_rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
        if frame_rms < 1e-6:
            continue
        local_lag_max = min(len(frame) - 2, lag_max)
        if local_lag_max <= lag_min:
            continue
        correlations: list[float] = []
        for lag in range(lag_min, local_lag_max + 1):
            left = frame[:-lag]
            right = frame[lag:]
            denom = float(np.linalg.norm(left) * np.linalg.norm(right))
            correlations.append(float(np.dot(left, right) / denom) if denom > 1e-12 else -1.0)
        if not correlations:
            continue
        index = int(np.argmax(correlations))
        lag = float(lag_min + index)
        confidence = float(correlations[index])
        if 0 < index < len(correlations) - 1:
            y0, y1, y2 = correlations[index - 1:index + 2]
            denom = y0 - 2.0 * y1 + y2
            if abs(denom) > 1e-12:
                delta = 0.5 * (y0 - y2) / denom
                if abs(delta) <= 1.0:
                    lag += float(delta)
        measured_hz = sample_rate / lag
        cents = 1200.0 * math.log2(measured_hz / expected_hz)
        measurements.append((float(cents), confidence))

    if not measurements:
        return {**base, "status": "unreliable", "reason": "no_voiced_frames"}

    cents_values = np.asarray([row[0] for row in measurements], dtype=np.float64)
    confidences = np.asarray([row[1] for row in measurements], dtype=np.float64)
    confidence_floor = max(0.12, float(np.percentile(confidences, 25)))
    keep = confidences >= confidence_floor
    if np.any(keep):
        cents_values = cents_values[keep]
        confidences = confidences[keep]

    cents = float(np.median(cents_values))
    spread = float(np.median(np.abs(cents_values - cents)))
    confidence = float(np.median(confidences))
    measured_hz = expected_hz * 2.0 ** (cents / 1200.0)
    near_search_edge = abs(cents) >= max(1.0, float(search_cents) - 4.0)
    if confidence < 0.15:
        status = "unreliable"
        reason = "weak_periodicity"
    elif near_search_edge:
        status = "unreliable"
        reason = "search_boundary"
    elif spread > 10.0:
        status = "unstable"
        reason = "pitch_varies_within_note"
    else:
        status = "ok"
        reason = None
    result = {
        **base,
        "status": status,
        "measured_hz": round(float(measured_hz), 5),
        "cents": round(cents, 3),
        "spread_cents": round(spread, 3),
        "confidence": round(confidence, 4),
        "frames": int(len(cents_values)),
    }
    if reason:
        result["reason"] = reason
    return result


def estimate_known_note_tuning_spectral(
    audio: np.ndarray,
    sample_rate: int,
    expected_midi: int,
    *,
    attack_seconds: float = 0.08,
    release_seconds: float = 0.05,
    search_cents: float = 100.0,
    max_harmonics: int = 12,
) -> dict[str, Any]:
    """Independent known-note estimate from harmonic spectral peaks.

    This intentionally does not reuse the autocorrelation period estimate.  A
    Hann-windowed FFT is searched around each expected harmonic, the local peak
    is parabolically refined, and every usable harmonic votes for the implied
    fundamental.  Bright instruments therefore remain measurable even when the
    fundamental itself is weak.
    """

    mono = _mono(audio)
    expected_hz = midi_frequency(expected_midi)
    base = {"midi": int(expected_midi), "expected_hz": round(float(expected_hz), 5)}
    if len(mono) < 256:
        return {**base, "status": "unreliable", "reason": "too_short"}
    attack = min(int(max(0.0, attack_seconds) * sample_rate), len(mono) // 4)
    release = min(int(max(0.0, release_seconds) * sample_rate), len(mono) // 8)
    stop = len(mono) - release if release else len(mono)
    steady = mono[attack:stop]
    if len(steady) < 256:
        steady = mono
    steady = steady - float(np.mean(steady))
    rms = float(np.sqrt(np.mean(np.square(steady), dtype=np.float64)))
    if rms < 1e-7:
        return {**base, "status": "silent", "reason": "no_measurable_audio"}

    window = np.hanning(len(steady))
    nfft_target = max(4096, len(steady) * 8)
    nfft = 1 << int(math.ceil(math.log2(nfft_target)))
    spectrum = np.abs(np.fft.rfft(steady * window, n=nfft))
    freqs = np.fft.rfftfreq(nfft, 1.0 / sample_rate)
    nyquist = sample_rate / 2.0
    votes: list[tuple[float, float, float]] = []
    low_ratio = 2.0 ** (-float(search_cents) / 1200.0)
    high_ratio = 2.0 ** (float(search_cents) / 1200.0)

    for harmonic in range(1, max(2, int(max_harmonics)) + 1):
        expected_peak = expected_hz * harmonic
        if expected_peak >= nyquist * 0.96:
            break
        lo_hz = expected_peak * low_ratio
        hi_hz = expected_peak * high_ratio
        lo = max(1, int(np.searchsorted(freqs, lo_hz, side="left")))
        hi = min(len(spectrum) - 2, int(np.searchsorted(freqs, hi_hz, side="right")))
        if hi <= lo:
            continue
        local = spectrum[lo:hi + 1]
        rel = int(np.argmax(local))
        idx = lo + rel
        peak = float(spectrum[idx])
        floor = float(np.median(local)) + 1e-15
        prominence = peak / floor
        if prominence < 2.0 or peak <= 1e-12:
            continue
        refined = float(idx)
        y0, y1, y2 = [math.log(max(float(spectrum[j]), 1e-18)) for j in (idx - 1, idx, idx + 1)]
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > 1e-12:
            delta = 0.5 * (y0 - y2) / denom
            if abs(delta) <= 1.0:
                refined += float(delta)
        peak_hz = refined * sample_rate / nfft
        fundamental_hz = peak_hz / harmonic
        cents = 1200.0 * math.log2(fundamental_hz / expected_hz)
        weight = math.sqrt(max(peak, 1e-18)) * min(prominence, 20.0) / math.sqrt(harmonic)
        votes.append((float(cents), float(weight), float(prominence)))

    if len(votes) < 2:
        return {**base, "status": "unreliable", "reason": "insufficient_harmonic_peaks", "harmonics": len(votes)}
    ordered = sorted(votes, key=lambda row: row[0])
    total_weight = sum(row[1] for row in ordered)
    cursor = 0.0
    cents = ordered[-1][0]
    for value, weight, _prominence in ordered:
        cursor += weight
        if cursor >= total_weight * 0.5:
            cents = value
            break
    deviations = sorted((abs(row[0] - cents), row[1]) for row in votes)
    total = sum(weight for _dev, weight in deviations)
    cursor = 0.0
    spread = deviations[-1][0]
    for dev, weight in deviations:
        cursor += weight
        if cursor >= total * 0.5:
            spread = dev
            break
    measured_hz = expected_hz * 2.0 ** (cents / 1200.0)
    if abs(cents) >= max(1.0, float(search_cents) - 4.0):
        status, reason = "unreliable", "search_boundary"
    elif spread > 8.0:
        status, reason = "unstable", "harmonics_disagree"
    else:
        status, reason = "ok", None
    result = {
        **base,
        "status": status,
        "measured_hz": round(float(measured_hz), 5),
        "cents": round(float(cents), 3),
        "spread_cents": round(float(spread), 3),
        "harmonics": len(votes),
        "median_prominence": round(float(np.median([row[2] for row in votes])), 3),
    }
    if reason:
        result["reason"] = reason
    return result


def combine_tuning_estimators(
    primary: Mapping[str, Any],
    spectral: Mapping[str, Any],
    *,
    agreement_cents: float = 3.0,
) -> dict[str, Any]:
    """Return a conservative consensus used for correction proposals."""

    p = primary.get("cents")
    s = spectral.get("cents")
    if p is None or s is None or primary.get("status") not in {"ok", "unstable"} or spectral.get("status") not in {"ok", "unstable"}:
        return {
            "validation_status": "insufficient",
            "validated_cents": None,
            "estimator_agreement_cents": None,
        }
    agreement = abs(float(p) - float(s))
    if agreement > float(agreement_cents):
        return {
            "validation_status": "disagree",
            "validated_cents": None,
            "estimator_agreement_cents": round(agreement, 3),
        }
    return {
        "validation_status": "agree",
        "validated_cents": round((float(p) + float(s)) / 2.0, 3),
        "estimator_agreement_cents": round(agreement, 3),
    }


def select_tuning_notes(
    low_midi: int,
    high_midi: int,
    *,
    max_notes: int = 61,
    anchors: Iterable[int] = (),
) -> list[int]:
    """Choose a range-covering chromatic audit set while retaining C anchors."""

    low = max(0, min(127, int(low_midi)))
    high = max(low, min(127, int(high_midi)))
    all_notes = list(range(low, high + 1))
    limit = max(3, int(max_notes))
    if len(all_notes) <= limit:
        return all_notes

    must = {low, high}
    must.update(int(note) for note in anchors if low <= int(note) <= high)
    # Keep every C.  These octave anchors make C5-like problems visible even
    # when a very broad keyboard range has to be subsampled.
    must.update(note for note in all_notes if note % 12 == 0)
    if len(must) >= limit:
        # Extremely small max_notes values still preserve caller anchors and
        # endpoints; exceeding the requested cap is preferable to dropping them.
        return sorted(must)

    remaining = limit - len(must)
    candidates = [note for note in all_notes if note not in must]
    if remaining >= len(candidates):
        must.update(candidates)
        return sorted(must)
    positions = np.linspace(0, len(candidates) - 1, remaining)
    must.update(candidates[int(round(pos))] for pos in positions)
    return sorted(must)


def summarize_tuning_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize measured note offsets without implying automatic correction."""

    usable = [row for row in rows if row.get("status") in {"ok", "unstable"} and row.get("cents") is not None]
    if not usable:
        return {
            "classification": "insufficient_evidence",
            "reliable_notes": 0,
            "suggested_global_correction_cents": None,
        }
    midi = np.asarray([float(row["midi"]) for row in usable], dtype=np.float64)
    cents = np.asarray([float(row["cents"]) for row in usable], dtype=np.float64)
    median = float(np.median(cents))
    residual = cents - median
    residual_mad = float(np.median(np.abs(residual)))
    abs_cents = np.abs(cents)
    p95 = float(np.percentile(abs_cents, 95))
    max_abs = float(np.max(abs_cents))
    span = float(np.max(midi) - np.min(midi)) if len(midi) > 1 else 0.0
    if len(midi) >= 3 and span > 0:
        slope_per_midi = float(np.polyfit(midi, cents, 1)[0])
        slope_per_octave = slope_per_midi * 12.0
    else:
        slope_per_octave = 0.0

    if abs(slope_per_octave) >= 4.0 and span >= 12.0:
        classification = "range_dependent"
        correction = None
    elif abs(median) >= 3.0 and residual_mad <= 2.5 and p95 <= abs(median) + 6.0:
        classification = "global_offset"
        correction = -median
    elif p95 >= 8.0 or residual_mad >= 4.0:
        classification = "local_outliers_or_mixed"
        correction = None
    else:
        classification = "centered"
        correction = 0.0

    return {
        "classification": classification,
        "reliable_notes": len(usable),
        "median_cents": round(median, 3),
        "residual_mad_cents": round(residual_mad, 3),
        "p95_abs_cents": round(p95, 3),
        "max_abs_cents": round(max_abs, 3),
        "slope_cents_per_octave": round(slope_per_octave, 3),
        "suggested_global_correction_cents": (
            round(float(correction), 3) if correction is not None else None
        ),
    }
