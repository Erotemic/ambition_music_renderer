"""Fast in-Python additive synth backend.

This module is the iteration-time renderer used by `--backend fallback`. It is
**not** a faithful instrument simulator — it composes bandlimited harmonic
stacks plus filtered noise bands to give the YAML something audible without
needing FluidSynth or a SoundFont.

Everything in here is fallback-backend-specific. The rest of the package
(`musicir_renderer.py`) is a YAML interpreter and post-process pipeline that
can dispatch to any synth backend; this module is one such backend. Keeping
its hacks isolated from the main module makes it clear what is YAML-faithful
versus what is a synthesis approximation.

Public entry point: `render_fallback(pm, sample_rate, *, minimum_duration=None)`.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np
import pretty_midi

from .musicir_renderer import _lowpass_mono, clamp


# ---------------------------------------------------------------------------
# Instrument-family classification (fallback renderer only).
# ---------------------------------------------------------------------------


def _program_family(program: int) -> str | None:
    """Classify a GM program into a fallback-renderer family.

    Names returned here must match the branches in `_synth_note_fallback`.
    Specific programs (harp, timpani) need to be checked before the
    string range that nominally contains them.
    """
    program = int(program)
    if program == 46:
        return "harp"
    if program == 47:
        return "timpani"
    if 9 <= program <= 15 or 112 <= program <= 119:
        return "mallet"
    if 0 <= program <= 7:
        return "piano"
    if 32 <= program <= 39:
        return "bass"
    if 40 <= program <= 45 or 48 <= program <= 51:
        return "string"
    if 52 <= program <= 54:
        return "choir"
    if 56 <= program <= 63:
        return "brass"
    if 64 <= program <= 79:
        return "wind"
    if 80 <= program <= 87:
        return "lead"
    if 88 <= program <= 103:
        return "pad"
    return None


def _instrument_family(inst: pretty_midi.Instrument) -> str:
    """Classify instruments for the fallback renderer.

    Family names returned here must match the branches in `_synth_note_fallback`.
    GM program is preferred over name; name fallback covers exotic /
    synthesised cues that don't carry a meaningful program.
    """
    if inst.is_drum:
        return "drum"

    family = _program_family(int(getattr(inst, "program", 0)))
    if family is not None:
        return family

    name = (inst.name or "").lower()
    if "harp" in name and "harpsichord" not in name:
        return "harp"
    if "timpani" in name:
        return "timpani"
    if any(
        k in name
        for k in ("marimba", "mallet", "xylo", "vibe", "glock", "celesta", "bell")
    ):
        return "mallet"
    if any(
        k in name
        for k in ("violin", "viola", "celli", "cello", "cell", "contrabass", "string")
    ):
        return "string"
    if any(k in name for k in ("trumpet", "trombone", "tuba", "brass")) or (
        "horn" in name and "english" not in name
    ):
        return "brass"
    if any(
        k in name
        for k in (
            "flute",
            "oboe",
            "clarinet",
            "bassoon",
            "piccolo",
            "recorder",
            "english_horn",
            "english horn",
            "wind",
        )
    ):
        return "wind"
    if any(k in name for k in ("choir", "voice")):
        return "choir"
    if "pad" in name:
        return "pad"
    if any(k in name for k in ("piano", "keys")):
        return "piano"
    return "generic"


# ---------------------------------------------------------------------------
# Waveform / envelope helpers used by the per-note synth.
# ---------------------------------------------------------------------------


def _saw(phase: np.ndarray) -> np.ndarray:
    return (2.0 * (phase % 1.0) - 1.0).astype(np.float32)


def _tri(phase: np.ndarray) -> np.ndarray:
    return (4.0 * np.abs((phase % 1.0) - 0.5) - 1.0).astype(np.float32)


def _pulse(phase: np.ndarray, duty: float = 0.5) -> np.ndarray:
    return np.where((phase % 1.0) < duty, 1.0, -1.0).astype(np.float32)


def _adsr_curve(
    n: int, sr: int, attack: float, decay: float, sustain: float, release: float
) -> np.ndarray:
    a = max(1, int(attack * sr))
    d = max(1, int(decay * sr))
    r = max(1, int(release * sr))
    s = max(0, n - a - d - r)
    env = np.concatenate(
        [
            np.linspace(0.0, 1.0, a, endpoint=False),
            np.linspace(1.0, sustain, d, endpoint=False),
            np.full(s, sustain, dtype=np.float32),
            np.linspace(sustain, 0.0, r, endpoint=True),
        ]
    ).astype(np.float32)
    if len(env) < n:
        env = np.pad(env, (0, n - len(env)))
    return env[:n]


def _declick(
    sig: np.ndarray, sr: int, attack: float = 0.006, release: float = 0.018
) -> np.ndarray:
    """Apply a tiny edge fade to synthetic notes/drums.

    The fallback renderer is additive and section/stem based.  Hard synthetic
    starts/stops that are barely audible in isolation can become obvious when
    multiple stems line up.  This helper keeps the renderer deterministic
    while avoiding those edge discontinuities.
    """
    n = len(sig)
    if n == 0:
        return sig.astype(np.float32, copy=False)
    out = sig.astype(np.float32, copy=True)
    a = min(n, max(1, int(attack * sr)))
    r = min(n, max(1, int(release * sr)))
    if a > 1:
        out[:a] *= np.linspace(0.0, 1.0, a, endpoint=True, dtype=np.float32)
    if r > 1:
        out[-r:] *= np.linspace(1.0, 0.0, r, endpoint=True, dtype=np.float32)
    return out.astype(np.float32, copy=False)


def _pan_stereo(mono: np.ndarray, pan: float) -> np.ndarray:
    pan = float(clamp(pan, -1.0, 1.0))
    left = math.sqrt((1.0 - pan) / 2.0)
    right = math.sqrt((1.0 + pan) / 2.0)
    return np.column_stack([mono * left, mono * right]).astype(np.float32)


# ---------------------------------------------------------------------------
# Per-note voices.
# ---------------------------------------------------------------------------


def _synth_note_fallback(
    frequency: float,
    duration: float,
    velocity: int,
    family: str,
    sr: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Built-in fallback instrument model.

    Composes bandlimited harmonic stacks (`_harm_saw` / `_harm_stack`) plus
    filtered noise bands per family. Not a sample library replacement; the
    point is to give the YAML something audible without needing FluidSynth.
    """
    n = max(1, int(duration * sr))
    t = np.arange(n, dtype=np.float32) / sr
    vel = (velocity / 127.0) ** 1.22
    drift = 1.0 + float(rng.normal(0.0, 0.00035))
    f = frequency * drift
    phase = f * t
    nyquist = sr * 0.5
    twopi_f_t = 2 * np.pi * f * t

    def _harm_stack(weights: list[float]) -> np.ndarray:
        out = np.zeros(n, dtype=np.float32)
        cap = nyquist * 0.85
        for n_idx, w in enumerate(weights, start=1):
            if w == 0.0:
                continue
            if f * n_idx >= cap:
                break
            out += w * np.sin(twopi_f_t * n_idx).astype(np.float32)
        return out

    def _harm_saw(amp: float, n_max: int = 32, exponent: float = 1.0) -> np.ndarray:
        out = np.zeros(n, dtype=np.float32)
        cap = nyquist * 0.85
        for n_idx in range(1, n_max + 1):
            if f * n_idx >= cap:
                break
            out += (amp / (n_idx**exponent)) * np.sin(twopi_f_t * n_idx).astype(
                np.float32
            )
        return out

    if family == "string":
        raw = _harm_saw(0.45, n_max=28, exponent=1.05)
        body = np.tanh(raw * 1.50).astype(np.float32)
        bow = rng.normal(0.0, 0.40, n).astype(np.float32)
        bow_band = bow - _lowpass_mono(bow, 0.05)
        bow_band = _lowpass_mono(bow_band, 0.50)
        sig = _lowpass_mono(body, 0.70) + bow_band * 0.16
        env = _adsr_curve(n, sr, 0.085, 0.16, 0.66, 0.34)
    elif family == "brass":
        raw = _harm_saw(0.45, n_max=24, exponent=0.95)
        body = np.tanh(raw * 1.55).astype(np.float32)
        buzz = rng.normal(0.0, 0.30, n).astype(np.float32)
        buzz_band = buzz - _lowpass_mono(buzz, 0.03)
        buzz_band = _lowpass_mono(buzz_band, 0.45)
        sig = _lowpass_mono(body, 0.70) + buzz_band * 0.10
        env = _adsr_curve(n, sr, 0.045, 0.10, 0.72, 0.22)
    elif family == "wind":
        raw = _harm_saw(0.55, n_max=22, exponent=1.20)
        body = np.tanh(raw * 1.30).astype(np.float32)
        breath = rng.normal(0.0, 0.36, n).astype(np.float32)
        breath_band = breath - _lowpass_mono(breath, 0.04)
        breath_band = _lowpass_mono(breath_band, 0.60)
        sig = _lowpass_mono(body, 0.70) + breath_band * 0.12
        env = _adsr_curve(n, sr, 0.060, 0.070, 0.78, 0.24)
    elif family == "pad":
        raw = (
            0.42 * np.sin(2 * np.pi * f * 0.997 * t)
            + 0.40 * np.sin(2 * np.pi * f * 1.003 * t)
            + 0.18 * np.sin(twopi_f_t * 2.0)
            + 0.08 * np.sin(twopi_f_t * 3.0)
            + 0.03 * np.sin(twopi_f_t * 4.0)
        )
        sig = _lowpass_mono(raw, 0.22)
        env = _adsr_curve(n, sr, 0.30, 0.35, 0.68, 0.90)
    elif family == "choir":
        vib = 0.0028 * np.sin(2 * np.pi * 5.2 * t)
        raw = (
            0.45 * np.sin(2 * np.pi * f * (1.0 + vib) * t)
            + 0.28 * np.sin(twopi_f_t * 2.0)
            + 0.20 * np.sin(twopi_f_t * 3.0)
            + 0.10 * np.sin(twopi_f_t * 4.0)
            + 0.04 * np.sin(twopi_f_t * 5.0)
        )
        sig = _lowpass_mono(raw, 0.28)
        env = _adsr_curve(n, sr, 0.20, 0.30, 0.78, 0.55)
    elif family == "mallet":
        raw = _harm_stack([1.00, 0.30, 0.14, 0.06, 0.03])
        sig = _lowpass_mono(raw, 0.55)
        env = np.exp(-t / max(0.18, duration * 0.50)).astype(np.float32)
        ramp = np.linspace(
            0.0, 1.0, min(n, max(8, int(0.014 * sr))), endpoint=True, dtype=np.float32
        )
        env[: len(ramp)] *= ramp
    elif family == "harp":
        raw = _harm_stack([0.70, 0.30, 0.16, 0.08, 0.04, 0.02])
        sig = _lowpass_mono(raw, 0.55)
        decay_tau = max(0.40, duration * 0.85)
        env = np.exp(-t / decay_tau).astype(np.float32)
        ramp = np.linspace(
            0.0, 1.0, min(n, max(6, int(0.005 * sr))), endpoint=True, dtype=np.float32
        )
        env[: len(ramp)] *= ramp
    elif family == "timpani":
        body_freq = max(40.0, frequency * 0.5)
        sweep_t = np.exp(-t / 0.045)
        f_sweep = body_freq + (frequency - body_freq) * sweep_t
        phase_int = 2 * np.pi * np.cumsum(f_sweep) / sr
        raw = (
            0.80 * np.sin(phase_int)
            + 0.18 * np.sin(2 * np.pi * frequency * 1.5 * t)
            + 0.08 * np.sin(2 * np.pi * frequency * 2.0 * t)
        )
        rumble = rng.normal(0.0, 0.05, n).astype(np.float32) * np.exp(-t / 0.060)
        sig = _lowpass_mono(raw + rumble, 0.20)
        env = np.exp(-t / max(0.55, duration * 0.85)).astype(np.float32)
        ramp = np.linspace(
            0.0, 1.0, min(n, max(6, int(0.004 * sr))), endpoint=True, dtype=np.float32
        )
        env[: len(ramp)] *= ramp
    elif family == "piano":
        raw = _harm_stack([0.62, 0.28, 0.16, 0.10, 0.06, 0.03])
        sig = _lowpass_mono(raw, 0.40)
        env = np.exp(-t / max(0.34, duration * 0.70)).astype(np.float32)
        ramp = np.linspace(
            0.0, 1.0, min(n, max(8, int(0.010 * sr))), endpoint=True, dtype=np.float32
        )
        env[: len(ramp)] *= ramp
    elif family == "bass":
        raw = _harm_stack([0.65, 0.32, 0.18, 0.08, 0.04])
        sig = _lowpass_mono(raw, 0.28)
        env = _adsr_curve(n, sr, 0.018, 0.08, 0.72, 0.18)
    elif family == "lead":
        raw = (
            0.50 * np.sin(twopi_f_t)
            + 0.26 * _tri(phase)
            + 0.10 * _pulse(phase, 0.45)
            + 0.10 * np.sin(twopi_f_t * 2.0)
        )
        sig = np.tanh(raw * 0.88).astype(np.float32)
        sig = _lowpass_mono(sig, 0.40)
        env = _adsr_curve(n, sr, 0.018, 0.06, 0.60, 0.16)
    else:
        raw = _harm_stack([0.70, 0.22, 0.10, 0.04])
        sig = _lowpass_mono(raw, 0.40)
        env = _adsr_curve(n, sr, 0.024, 0.06, 0.68, 0.18)
    return _declick(sig * env * vel, sr, 0.004, 0.012).astype(np.float32)


def _synth_drum_fallback(
    pitch: int, duration: float, velocity: int, sr: int, rng: np.random.Generator
) -> np.ndarray:
    n = max(1, int(duration * sr))
    t = np.arange(n, dtype=np.float32) / sr
    vel = (velocity / 127.0) ** 1.18
    noise = rng.normal(0, 1, n).astype(np.float32)
    if pitch in {35, 36}:
        f0, f1 = 74.0, 40.0
        sweep = f0 * ((f1 / f0) ** (t / max(duration, 1e-4)))
        phase = 2 * np.pi * np.cumsum(sweep) / sr
        sig = np.sin(phase).astype(np.float32) * np.exp(-t / 0.18)
        sig += 0.025 * noise * np.exp(-t / 0.018)
        sig = _lowpass_mono(sig, 0.060)
        sig = _declick(sig, sr, 0.010, 0.025)
    elif pitch in {38, 40, 37}:
        tone = np.sin(2 * np.pi * 160 * t).astype(np.float32) * np.exp(-t / 0.075)
        body = _lowpass_mono(noise, 0.060) * np.exp(-t / 0.060) * 0.22
        sig = tone * 0.48 + body
        sig = _declick(sig, sr, 0.008, 0.025)
    elif pitch in {41, 43, 45, 48, 47}:
        base = {41: 82, 43: 98, 45: 118, 48: 148, 47: 132}.get(pitch, 112)
        sig = np.sin(2 * np.pi * base * t).astype(np.float32) * np.exp(-t / 0.16)
        sig += _lowpass_mono(noise, 0.045) * np.exp(-t / 0.050) * 0.055
        sig = _declick(sig, sr, 0.008, 0.025)
    elif pitch in {42, 44, 46, 51, 49, 55, 52, 80, 81}:
        hp = noise - _lowpass_mono(noise, 0.035)
        hp = _lowpass_mono(hp, 0.090)
        sig = hp * np.exp(-t / (0.032 if pitch in {42, 44} else 0.18)) * 0.42
        sig = _declick(sig, sr, 0.006, 0.030)
    else:
        sig = _lowpass_mono(noise, 0.080) * np.exp(-t / 0.09) * 0.40
        sig = _declick(sig, sr, 0.006, 0.020)
    return (sig * vel).astype(np.float32)


# ---------------------------------------------------------------------------
# Note-stream rendering.
# ---------------------------------------------------------------------------


def _midi_content_seed(pm: pretty_midi.PrettyMIDI) -> int:
    """Stable pseudo-random seed derived from score content."""
    h = hashlib.sha256()
    for inst in pm.instruments:
        h.update(str(inst.program).encode())
        h.update(str(inst.is_drum).encode())
        h.update((inst.name or "").encode())
        for note in inst.notes[:2048]:
            h.update(
                f"{note.pitch}:{note.start:.4f}:{note.end:.4f}:{note.velocity}".encode()
            )
    return int.from_bytes(h.digest()[:8], "big") & 0xFFFFFFFF


def _cc_track(
    inst: pretty_midi.Instrument, number: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return sorted (times, values) arrays for one CC number on `inst`."""
    events = [(c.time, c.value) for c in inst.control_changes if c.number == number]
    if not events:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float32)
    events.sort(key=lambda tv: tv[0])
    times = np.fromiter(
        (float(t) for t, _ in events), dtype=np.float64, count=len(events)
    )
    values = np.fromiter(
        (float(v) for _, v in events), dtype=np.float32, count=len(events)
    )
    return times, values


def _cc_value(times: np.ndarray, values: np.ndarray, t: float, default: float) -> float:
    """Latest CC value at-or-before time `t`, with stairstep semantics."""
    if times.size == 0:
        return float(default)
    idx = int(np.searchsorted(times, t + 1e-6, side="right")) - 1
    if idx < 0:
        return float(default)
    return float(values[idx])


def render_fallback(
    pm: pretty_midi.PrettyMIDI,
    sample_rate: int,
    *,
    minimum_duration: float | None = None,
) -> np.ndarray:
    """Synthesize the score with the fallback in-Python additive engine."""
    end_time = pm.get_end_time()
    if minimum_duration is not None:
        end_time = max(end_time, minimum_duration)
    total_samples = int(math.ceil((end_time + 0.75) * sample_rate))
    mix = np.zeros((total_samples, 2), dtype=np.float32)
    rng = np.random.default_rng(_midi_content_seed(pm))
    for inst in pm.instruments:
        family = _instrument_family(inst)
        # MIDI CC envelopes are stairstep. Sampling at note attack lets the
        # YAML expression / volume / pan ramps actually shape the rendered
        # audio instead of being silently dropped.
        vol_t, vol_v = _cc_track(inst, 7)
        pan_t, pan_v = _cc_track(inst, 10)
        expr_t, expr_v = _cc_track(inst, 11)
        for note in inst.notes:
            start = max(0, int(note.start * sample_rate))
            dur = max(0.025, note.end - note.start)
            vol_cc = _cc_value(vol_t, vol_v, note.start, 100.0)
            expr_cc = _cc_value(expr_t, expr_v, note.start, 100.0)
            pan_cc = _cc_value(pan_t, pan_v, note.start, 64.0)
            vol = (vol_cc / 127.0) * (expr_cc / 127.0)
            pan = (pan_cc - 64.0) / 63.0
            if inst.is_drum:
                mono = _synth_drum_fallback(
                    note.pitch, dur, note.velocity, sample_rate, rng
                )
            else:
                mono = _synth_note_fallback(
                    pretty_midi.note_number_to_hz(note.pitch),
                    dur,
                    note.velocity,
                    family,
                    sample_rate,
                    rng,
                )
            n = min(len(mono), total_samples - start)
            if n <= 0:
                continue
            mix[start : start + n] += _pan_stereo(mono[:n] * vol, pan)
    # Leave authored/stem relative loudness alone. Only protect the
    # fallback renderer from obvious clipping; normalization-up happens
    # later only if the YAML master postprocess asks for it.
    peak = float(np.max(np.abs(mix)))
    if peak > 0.92:
        mix *= 0.92 / peak
    return mix.astype(np.float32, copy=False)
