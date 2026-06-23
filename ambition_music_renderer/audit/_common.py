"""Shared numeric/formatting helpers for the audit tools.

Several audit modules had independently reimplemented these identical dB / RMS /
peak / rounding helpers (and ``level_report`` even imported them across module
boundaries from ``transition_audit``). They live here now so there is a single
definition — and a single silence floor — for the whole audit package.
"""

from __future__ import annotations

import math

import lazy_loader as lazy

from ..profiler import profile

np = lazy.load("numpy")


@profile
def db(value: float) -> float:
    """Linear amplitude -> dBFS, floored at 1e-12 to avoid log(0)."""
    value = max(float(value), 1e-12)
    return 20.0 * math.log10(value)


@profile
def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))


@profile
def peak(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.max(np.abs(audio)))


def round3(value: float) -> float:
    return round(float(value), 3)
