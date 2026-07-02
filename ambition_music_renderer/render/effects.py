"""Audio post-processing effects for rendered MusicIR stems."""

from __future__ import annotations

import functools
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal

from ..profiler import profile
from ..audio_utils import coerce_stereo
from .score_theory import clamp

@profile
def _lowpass_mono(signal_in: np.ndarray, amount: float) -> np.ndarray:
    # One-pole lowpass: y[n] = y[n-1] + amount * (x[n] - y[n-1]).
    # Implemented with scipy.signal.lfilter because this runs for every rendered
    # note and Python loops make long pad-heavy scores unacceptably slow.
    if len(signal_in) == 0:
        return signal_in
    amount = float(clamp(amount, 1e-5, 1.0))
    return signal.lfilter([amount], [1.0, -(1.0 - amount)], signal_in).astype(
        np.float32
    )



def _one_pole_alpha(hz: float, sample_rate: int) -> float:
    hz = float(clamp(hz, 1.0, sample_rate * 0.49))
    return float(1.0 - math.exp(-2.0 * math.pi * hz / sample_rate))


def _sos_filter(audio: np.ndarray, sos: np.ndarray) -> np.ndarray:
    """Apply a numerically stable stereo SOS filter.

    The old post bus used one-pole subtraction for tone shaping. That was fast,
    but it was too shallow for mix decisions like "remove the 4 kHz guitar
    whistle" or "keep bass out of the cymbal band". SciPy is a normal
    dependency now, so use real Butterworth/RBJ-style filters for the authoring
    path while keeping the one-pole helper available for fallback synthesis.
    """
    audio = coerce_stereo(audio)
    if audio.size == 0:
        return audio.astype(np.float32, copy=False)
    return signal.sosfilt(sos, audio, axis=0).astype(np.float32, copy=False)


def _safe_cutoff(hz: float, sample_rate: int) -> float:
    return float(clamp(float(hz), 1.0, sample_rate * 0.49))


@profile
def lowpass(
    audio: np.ndarray, sample_rate: int, hz: float = 12_000.0, order: int = 2
) -> np.ndarray:
    if hz <= 0 or hz >= sample_rate * 0.49:
        return audio.astype(np.float32, copy=False)
    sos = signal.butter(
        max(1, int(order)), _safe_cutoff(hz, sample_rate), btype="lowpass", fs=sample_rate, output="sos"
    )
    return _sos_filter(audio, sos)


@profile
def highpass(audio: np.ndarray, sample_rate: int, hz: float = 35.0, order: int = 2) -> np.ndarray:
    if hz <= 0:
        return audio.astype(np.float32, copy=False)
    sos = signal.butter(
        max(1, int(order)), _safe_cutoff(hz, sample_rate), btype="highpass", fs=sample_rate, output="sos"
    )
    return _sos_filter(audio, sos)


def _biquad_filter(
    audio: np.ndarray,
    sample_rate: int,
    *,
    kind: str,
    hz: float,
    q: float = 0.707,
    db: float = 0.0,
) -> np.ndarray:
    """RBJ cookbook biquad for mix EQ bands.

    Supported kinds: ``peak`` / ``bell``, ``notch``, ``high_shelf``,
    ``low_shelf``.  ``notch`` may be used with either an explicit negative
    ``db`` cut or no gain, in which case it becomes a true notch.
    """
    if abs(float(db)) < 1e-6 and kind not in {"notch", "bandstop"}:
        return audio.astype(np.float32, copy=False)
    audio = coerce_stereo(audio)
    hz = _safe_cutoff(hz, sample_rate)
    q = max(float(q), 1e-3)
    w0 = 2.0 * math.pi * hz / float(sample_rate)
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    kind = kind.lower().replace("-", "_")

    if kind in {"notch", "bandstop"} and abs(float(db)) < 1e-6:
        b = np.array([1.0, -2.0 * cos_w0, 1.0], dtype=np.float64)
        a = np.array([1.0 + alpha, -2.0 * cos_w0, 1.0 - alpha], dtype=np.float64)
    else:
        a_gain = 10.0 ** (float(db) / 40.0)
        if kind in {"peak", "bell", "peaking", "notch", "bandstop"}:
            b = np.array([1.0 + alpha * a_gain, -2.0 * cos_w0, 1.0 - alpha * a_gain], dtype=np.float64)
            a = np.array([1.0 + alpha / a_gain, -2.0 * cos_w0, 1.0 - alpha / a_gain], dtype=np.float64)
        elif kind in {"high_shelf", "highshelf", "shelf_high"}:
            sqrt_a = math.sqrt(a_gain)
            two_sqrt_a_alpha = 2.0 * sqrt_a * alpha
            b = np.array([
                a_gain * ((a_gain + 1.0) + (a_gain - 1.0) * cos_w0 + two_sqrt_a_alpha),
                -2.0 * a_gain * ((a_gain - 1.0) + (a_gain + 1.0) * cos_w0),
                a_gain * ((a_gain + 1.0) + (a_gain - 1.0) * cos_w0 - two_sqrt_a_alpha),
            ], dtype=np.float64)
            a = np.array([
                (a_gain + 1.0) - (a_gain - 1.0) * cos_w0 + two_sqrt_a_alpha,
                2.0 * ((a_gain - 1.0) - (a_gain + 1.0) * cos_w0),
                (a_gain + 1.0) - (a_gain - 1.0) * cos_w0 - two_sqrt_a_alpha,
            ], dtype=np.float64)
        elif kind in {"low_shelf", "lowshelf", "shelf_low"}:
            sqrt_a = math.sqrt(a_gain)
            two_sqrt_a_alpha = 2.0 * sqrt_a * alpha
            b = np.array([
                a_gain * ((a_gain + 1.0) - (a_gain - 1.0) * cos_w0 + two_sqrt_a_alpha),
                2.0 * a_gain * ((a_gain - 1.0) - (a_gain + 1.0) * cos_w0),
                a_gain * ((a_gain + 1.0) - (a_gain - 1.0) * cos_w0 - two_sqrt_a_alpha),
            ], dtype=np.float64)
            a = np.array([
                (a_gain + 1.0) + (a_gain - 1.0) * cos_w0 + two_sqrt_a_alpha,
                -2.0 * ((a_gain - 1.0) + (a_gain + 1.0) * cos_w0),
                (a_gain + 1.0) + (a_gain - 1.0) * cos_w0 - two_sqrt_a_alpha,
            ], dtype=np.float64)
        else:
            raise ValueError(f"unknown eq band type {kind!r}")

    if abs(a[0]) < 1e-12:
        return audio.astype(np.float32, copy=False)
    b = b / a[0]
    a = a / a[0]
    out = signal.lfilter(b, a, audio, axis=0)
    return out.astype(np.float32, copy=False)


@profile
def high_shelf(
    audio: np.ndarray, sample_rate: int, *, hz: float = 4_500.0, db: float = -2.0
) -> np.ndarray:
    """High shelf using a proper biquad instead of highpass side-band mixing."""
    return _biquad_filter(audio, sample_rate, kind="high_shelf", hz=hz, q=0.707, db=db)


@profile
def parametric_eq(
    audio: np.ndarray, sample_rate: int, bands: list[dict[str, Any]] | tuple[dict[str, Any], ...]
) -> np.ndarray:
    out = coerce_stereo(audio)
    for raw in bands or []:
        band = dict(raw or {})
        kind = str(band.get("type") or band.get("kind") or band.get("shape") or "peak")
        out = _biquad_filter(
            out,
            sample_rate,
            kind=kind,
            hz=float(band.get("hz") or band.get("freq") or band.get("frequency_hz") or 1000.0),
            q=float(band.get("q") or band.get("Q") or 0.707),
            db=float(band.get("db") or band.get("gain_db") or 0.0),
        )
    return out.astype(np.float32, copy=False)


@profile
def band_gain(
    audio: np.ndarray, sample_rate: int, *, low_hz: float, high_hz: float, db: float
) -> np.ndarray:
    if abs(db) < 1e-6:
        return audio.astype(np.float32, copy=False)
    audio = coerce_stereo(audio)
    low_hz = max(20.0, float(low_hz))
    high_hz = min(float(high_hz), sample_rate * 0.49)
    if high_hz <= low_hz:
        return audio.astype(np.float32, copy=False)
    # A broad bell at the geometric midpoint sounds more mix-console-like than
    # subtracting two one-pole lowpasses, and avoids mushy phase cancellation.
    center = math.sqrt(low_hz * high_hz)
    bandwidth_oct = math.log2(high_hz / low_hz)
    q = max(0.25, 1.0 / max(bandwidth_oct, 0.25))
    return _biquad_filter(audio, sample_rate, kind="peak", hz=center, q=q, db=db)


@functools.cache
def _audio_kernels():
    """Return lazily imported compiled DSP kernels, or ``None`` for fallback."""
    disabled = os.environ.get("AMBITION_MUSIC_RENDERER_DISABLE_NUMBA", "").lower()
    if disabled in {"1", "true", "yes", "on"}:
        return None
    try:
        from . import kernels
    except Exception as ex:
        # The pure-Python comb/allpass loops are orders of magnitude slower;
        # never fall back silently or long renders look mysteriously hung.
        print(
            f"[ambition_music_renderer] compiled DSP kernels unavailable ({ex}); "
            "using slow pure-Python reverb fallback",
            file=sys.stderr,
        )
        return None
    return kernels


def _comb_filter_python(
    signal_in: np.ndarray, delay: int, feedback: float, damping: float
) -> np.ndarray:
    n = len(signal_in)
    out = np.zeros(n, dtype=np.float32)
    if delay <= 0 or delay >= n:
        return out
    buffer = np.zeros(delay, dtype=np.float32)
    filter_state = 0.0
    write = 0
    damping = float(clamp(damping, 0.0, 0.99))
    one_minus_damping = 1.0 - damping
    fb = float(feedback)
    sig = signal_in.astype(np.float32, copy=False)
    for i in range(n):
        delayed = buffer[write]
        out[i] = delayed
        # One-pole lowpass on the feedback path.
        filter_state = delayed * one_minus_damping + filter_state * damping
        buffer[write] = sig[i] + filter_state * fb
        write += 1
        if write >= delay:
            write = 0
    return out


def _allpass_filter_python(
    signal_in: np.ndarray, delay: int, feedback: float = 0.5
) -> np.ndarray:
    n = len(signal_in)
    out = np.zeros(n, dtype=np.float32)
    if delay <= 0 or delay >= n:
        return out
    buffer = np.zeros(delay, dtype=np.float32)
    write = 0
    fb = float(feedback)
    sig = signal_in.astype(np.float32, copy=False)
    for i in range(n):
        bufout = buffer[write]
        out[i] = -sig[i] + bufout
        buffer[write] = sig[i] + bufout * fb
        write += 1
        if write >= delay:
            write = 0
    return out


@profile
def _comb_filter(
    signal_in: np.ndarray, delay: int, feedback: float, damping: float
) -> np.ndarray:
    """Lowpass-feedback comb (Freeverb-style).

    The pure-Python implementation is retained as a fallback/reference, but the
    normal render path uses lazily imported Numba kernels so these long
    sample-by-sample feedback loops run as native code instead of dominating
    line profiles.
    """
    sig = np.ascontiguousarray(signal_in, dtype=np.float32)
    damping = float(clamp(damping, 0.0, 0.99))
    kernels = _audio_kernels()
    if kernels is not None:
        return kernels.comb_filter_lowpass_feedback(
            sig, int(delay), float(feedback), damping
        )
    return _comb_filter_python(sig, int(delay), float(feedback), damping)


@profile
def _allpass_filter(
    signal_in: np.ndarray, delay: int, feedback: float = 0.5
) -> np.ndarray:
    """Schroeder-style allpass/diffuser for the internal reverb."""
    sig = np.ascontiguousarray(signal_in, dtype=np.float32)
    kernels = _audio_kernels()
    if kernels is not None:
        return kernels.allpass_filter(sig, int(delay), float(feedback))
    return _allpass_filter_python(sig, int(delay), float(feedback))


def _compressor_envelope_python(
    gain_reduction_db: np.ndarray,
    attack_coeff: float,
    release_coeff: float,
) -> np.ndarray:
    env = np.zeros_like(gain_reduction_db, dtype=np.float32)
    state = 0.0
    for i in range(len(gain_reduction_db)):
        target = float(gain_reduction_db[i])
        if target < state:
            state = attack_coeff * state + (1.0 - attack_coeff) * target
        else:
            state = release_coeff * state + (1.0 - release_coeff) * target
        env[i] = state
    return env


@profile
def _compressor_envelope(
    gain_reduction_db: np.ndarray,
    attack_coeff: float,
    release_coeff: float,
) -> np.ndarray:
    """Smooth compressor gain reduction with lazy Numba acceleration."""
    gr = np.ascontiguousarray(gain_reduction_db, dtype=np.float32)
    kernels = _audio_kernels()
    if kernels is not None:
        return kernels.compressor_envelope(
            gr,
            float(attack_coeff),
            float(release_coeff),
        )
    return _compressor_envelope_python(gr, float(attack_coeff), float(release_coeff))


@profile
def simple_reverb(
    audio: np.ndarray,
    sr: int,
    wet: float = 0.08,
    decay: float = 0.9,
    damping_hz: float = 6500.0,
) -> np.ndarray:
    """Schroeder-Freeverb-style reverb.

    Four parallel lowpass-feedback combs in series with two allpass
    diffusers. RT60 is set from `decay` (in seconds) by mapping it to
    feedback gain per comb. `damping_hz` controls the brightness of the
    tail (lower = darker).
    """
    wet = float(wet)
    decay = max(float(decay), 1e-3)
    if wet <= 0.0 or audio.size == 0:
        return audio.astype("float32", copy=False)

    y = coerce_stereo(audio)
    n = len(y)

    # Comb-filter delay times in samples (Freeverb's prime-number choices,
    # adjusted for our 48 kHz target). Each comb gives a different "color"
    # and their primes minimize ringing.
    comb_delays_seconds = (0.0297, 0.0371, 0.0411, 0.0437)
    allpass_delays_seconds = (0.0050, 0.0017)

    # Map decay (RT60 in seconds) to per-comb feedback. RT60 = -3 / log10(fb)
    # for one comb; we average the comb delays for the calculation.
    avg_delay = sum(comb_delays_seconds) / len(comb_delays_seconds)
    rt60_iterations = decay / avg_delay
    feedback = (
        0.0 if rt60_iterations <= 0 else 10.0 ** (-3.0 / max(rt60_iterations, 1.0))
    )
    feedback = float(clamp(feedback, 0.0, 0.97))

    # Damping coefficient from cutoff: alpha for one-pole = exp(-2π * fc / sr).
    damping = float(clamp(math.exp(-2.0 * math.pi * float(damping_hz) / sr), 0.0, 0.97))
    # Convert "fraction of signal that survives one filter step" to the
    # internal damping convention used by `_comb_filter` (where damping=0
    # means no smoothing, damping near 1 is heavy lowpassing).
    internal_damping = float(clamp(1.0 - damping, 0.0, 0.97))

    wet_chans = []
    for chan in (0, 1):
        x = np.ascontiguousarray(y[:, chan])
        comb_sum = np.zeros(n, dtype=np.float32)
        for d_sec in comb_delays_seconds:
            d = max(2, int(round(d_sec * sr)))
            comb_sum += _comb_filter(x, d, feedback, internal_damping)
        comb_sum /= float(len(comb_delays_seconds))
        # Series allpass diffusers smear the comb output's impulse response.
        for d_sec in allpass_delays_seconds:
            d = max(2, int(round(d_sec * sr)))
            comb_sum = _allpass_filter(comb_sum, d, 0.5)
        wet_chans.append(comb_sum)
    wet_arr = np.column_stack(wet_chans).astype(np.float32)

    return (y * (1.0 - wet) + wet_arr * wet).astype(np.float32, copy=False)


@profile
def compressor(
    audio: np.ndarray,
    sr: int,
    *,
    threshold_db: float = -18.0,
    ratio: float = 3.0,
    attack_ms: float = 10.0,
    release_ms: float = 100.0,
    makeup_db: float = 0.0,
    knee_db: float = 6.0,
) -> np.ndarray:
    """Feed-forward peak compressor with attack/release smoothing.

    Pulls signal above `threshold_db` toward `1/ratio:1`. `knee_db` softens
    the threshold transition (0 = hard knee, 6 = typical soft knee). Attack
    and release are time constants for the gain-reduction envelope.
    """
    if ratio <= 1.0:
        return audio.astype(np.float32, copy=False)
    audio = coerce_stereo(audio)
    # Detector signal: per-sample stereo peak, in dB.
    det = np.maximum(np.abs(audio[:, 0]), np.abs(audio[:, 1]))
    det = np.maximum(det, 1e-9)
    det_db = 20.0 * np.log10(det)

    # Soft-knee gain reduction in dB.
    threshold_db = float(threshold_db)
    knee = max(float(knee_db), 0.0)
    over = det_db - threshold_db
    if knee > 0.0:
        # Smooth knee: 0 below threshold-knee/2, soft transition through knee, full ratio above.
        below = over <= -knee / 2
        above = over >= knee / 2
        soft = ~below & ~above
        gr_db = np.zeros_like(over)
        # Above knee: linear ratio
        gr_db[above] = -(over[above] - over[above] / ratio)
        # Soft-knee region: standard quadratic knee. Continuous with the
        # above-knee branch at over = knee/2 and monotonic through the knee
        # (the previous interpolation could *boost* inside the knee and jumped
        # by several dB at the knee top).
        gr_db[soft] = (1.0 / ratio - 1.0) * np.square(over[soft] + knee / 2) / (2.0 * knee)
    else:
        gr_db = np.where(over > 0, -(over - over / ratio), 0.0)

    # Attack/release smoothing of the gain reduction envelope (in dB).
    a = math.exp(-1.0 / max(float(attack_ms) * 1e-3 * sr, 1.0))
    r = math.exp(-1.0 / max(float(release_ms) * 1e-3 * sr, 1.0))
    env = _compressor_envelope(gr_db, a, r)

    # Apply gain reduction + makeup to both channels.
    gain = np.power(10.0, (env + float(makeup_db)) / 20.0).astype(np.float32)
    out = audio * gain[:, None]
    return out.astype(np.float32, copy=False)


@profile
def stereo_widen(audio: np.ndarray, amount: float = 0.12) -> np.ndarray:
    if amount <= 0:
        return audio.astype(np.float32, copy=False)
    mid = (audio[:, 0] + audio[:, 1]) * 0.5
    side = (audio[:, 0] - audio[:, 1]) * 0.5 * (1.0 + amount)
    return np.column_stack([mid + side, mid - side]).astype(np.float32)


@profile
def soft_limit(
    audio: np.ndarray,
    target_peak_db: float = -1.0,
    *,
    drive: float = 1.08,
    normalize: bool = True,
) -> np.ndarray:
    driven = np.tanh(audio * drive).astype(np.float32)
    peak = float(np.max(np.abs(driven)))
    target = 10 ** (target_peak_db / 20.0)
    if peak > 1e-8:
        # Master previews should normalize up to the target peak. Stems should
        # usually only be scaled down if too hot; otherwise quiet layers like
        # glimmer/mallets become unintentionally huge and shrill when mixed.
        if normalize or peak > target:
            driven *= target / peak
    return driven.astype(np.float32)


@profile
def post_process(
    audio: np.ndarray,
    sample_rate: int,
    settings: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> np.ndarray:
    audio = coerce_stereo(audio)
    if settings.get("gain_db", 0):
        audio = audio * (10 ** (float(settings["gain_db"]) / 20.0))
    if settings.get("highpass_hz", 0):
        audio = highpass(audio, sample_rate, float(settings["highpass_hz"]))
    # Tame very fast transients by blending toward a darker copy. This is most
    # useful for synthetic mallets, cymbals, and plucked/arpeggiated layers.
    tame = float(settings.get("transient_tame", 0.0))
    if tame > 0:
        dark = lowpass(
            audio, sample_rate, float(settings.get("transient_lowpass_hz", 6_500))
        )
        audio = (audio * (1.0 - tame) + dark * tame).astype(np.float32)
    if settings.get("presence_db", 0):
        audio = band_gain(
            audio,
            sample_rate,
            low_hz=float(settings.get("presence_low_hz", 2_000)),
            high_hz=float(settings.get("presence_high_hz", 4_500)),
            db=float(settings["presence_db"]),
        )
    if settings.get("high_shelf_db", 0):
        audio = high_shelf(
            audio,
            sample_rate,
            hz=float(settings.get("high_shelf_hz", 4_500)),
            db=float(settings["high_shelf_db"]),
        )
    eq_bands = settings.get("eq_bands") or settings.get("parametric_eq") or []
    if eq_bands:
        audio = parametric_eq(audio, sample_rate, list(eq_bands))
    if settings.get("lowpass_hz", 0):
        audio = lowpass(audio, sample_rate, float(settings["lowpass_hz"]))
    # Real bus compressor — opt-in via `compressor_threshold_db`. Glues the mix
    # before reverb so the room responds to compressed material rather than
    # raw transients. Set ratio:1 between 2 and 6 for typical bus glue.
    if "compressor_threshold_db" in settings:
        audio = compressor(
            audio,
            sample_rate,
            threshold_db=float(settings["compressor_threshold_db"]),
            ratio=float(settings.get("compressor_ratio", 3.0)),
            attack_ms=float(settings.get("compressor_attack_ms", 10.0)),
            release_ms=float(settings.get("compressor_release_ms", 100.0)),
            makeup_db=float(settings.get("compressor_makeup_db", 0.0)),
            knee_db=float(settings.get("compressor_knee_db", 6.0)),
        )
    # Built-in room. Skippable so a score can replace it with a Pedalboard/VST
    # reverb in `effect_chain` instead of stacking on top: set
    # `reverb_enabled: false` (or `reverb_wet: 0`).
    reverb_wet = float(settings.get("reverb_wet", 0.18))
    if settings.get("reverb_enabled", True) and reverb_wet > 0:
        audio = simple_reverb(
            audio,
            sample_rate,
            wet=reverb_wet,
            decay=float(settings.get("reverb_decay_seconds", 1.4)),
            damping_hz=float(settings.get("reverb_damping_hz", 6_000)),
        )
    # Apply one final brightness control after the room, because undamped
    # reverb can reintroduce fizz on synthetic sources.
    if settings.get("post_reverb_high_shelf_db", 0):
        audio = high_shelf(
            audio,
            sample_rate,
            hz=float(settings.get("post_reverb_high_shelf_hz", 5_000)),
            db=float(settings["post_reverb_high_shelf_db"]),
        )
    audio = stereo_widen(audio, float(settings.get("stereo_width", 0.10)))

    # Optional cross-backend effects. `effect_chain` is the single explicit
    # surface for pro-audio processing: each step names its host family
    # (`pedalboard`/`vst3`, `lv2`/`lv2proc`, or `command` for NAM/Guitarix) and
    # ordering is explicit. The default render path stays dependency-free
    # because this only runs when a score provides a chain.
    effect_chain = settings.get("effect_chain") or []
    if effect_chain:
        from ..backends.plugin_chain import apply_effect_chain

        audio = apply_effect_chain(audio, sample_rate, list(effect_chain), base_dir=base_dir)

    lufs_requested = (
        settings.get("target_lufs") is not None
        or settings.get("loudness_target_lufs") is not None
        or settings.get("loudness") is not None
    )
    if lufs_requested:
        from ..loudness import apply_loudness_settings

        audio = apply_loudness_settings(audio, sample_rate, settings)

    # Built-in master limiter. Skippable (`limiter_enabled: false`) so a score
    # can end its `effect_chain` with an external limiter/maximizer instead.
    if not settings.get("limiter_enabled", True):
        return audio.astype(np.float32, copy=False)
    target_peak = settings.get("true_peak_db", settings.get("target_peak_db", -1.0))
    # When a LUFS target was applied, the limiter must only *cap* at the peak
    # target; peak-normalizing here would re-gain the audio and silently undo
    # the loudness normalization the YAML asked for.
    normalize = bool(settings.get("normalize", True)) and not lufs_requested
    return soft_limit(
        audio,
        float(target_peak),
        drive=float(settings.get("limiter_drive", 1.08)),
        normalize=normalize,
    )


