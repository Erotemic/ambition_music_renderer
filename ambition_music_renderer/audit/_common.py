"""Shared numeric/audio/plotting helpers for the audit tools.

Several audit modules had independently reimplemented these identical dB / RMS /
peak / rounding helpers (and ``level_report`` even imported them across module
boundaries from ``transition_audit``). The same happened to the lazy matplotlib
loader, the jpeg-aware figure saver, and the mono downmix. They live here now so
there is a single definition — and a single silence floor — for the whole audit
package. Score-structure helpers (sections, chords, source hints) live in
``_score_common``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import lazy_loader as lazy

from ..profiler import profile

np = lazy.load("numpy")

# Matplotlib is the single heaviest import in the audit package and plotting is
# best-effort everywhere, so it is imported on first use and cached here.
_PLT: Any = None
_PLT_CHECKED = False


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


@profile
def to_mono(audio: np.ndarray) -> np.ndarray:
    """Downmix any audio layout to 1-D mono float32.

    Delegates layout handling (mono, sample-first, channel-first, ``(N, 1)``,
    over-wide) to ``audio_utils.coerce_stereo``; the previous per-module copies
    averaged over *time* for ``(N, 1)`` and ``(N, C>2)`` inputs.
    """
    from ..audio_utils import coerce_stereo

    return coerce_stereo(audio).mean(axis=1).astype("float32")


@profile
def ensure_matplotlib() -> Any:
    """Import matplotlib lazily (Agg backend); return pyplot or None.

    Plotting is best-effort across the audit tools; callers skip their plot
    when this returns None.
    """
    global _PLT, _PLT_CHECKED
    if _PLT_CHECKED:
        return _PLT
    _PLT_CHECKED = True
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _PLT = plt
    except Exception:  # pragma: no cover - plotting is best-effort.
        _PLT = None
    return _PLT


@profile
def save_figure(
    fig: Any,
    path: Path,
    *,
    plot_format: str,
    jpeg_quality: int = 90,
    dpi: int = 150,
) -> None:
    """Save and close a figure; jpeg gets quality/optimize, others save raw."""
    fmt = plot_format.lower()
    save_kwargs: dict[str, Any] = {"dpi": int(dpi), "bbox_inches": "tight"}
    if fmt in {"jpg", "jpeg"}:
        save_kwargs["format"] = "jpeg"
        save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality), "optimize": True}
    else:
        save_kwargs["format"] = fmt
    fig.savefig(path, **save_kwargs)
    plt = ensure_matplotlib()
    if plt is not None:
        plt.close(fig)
