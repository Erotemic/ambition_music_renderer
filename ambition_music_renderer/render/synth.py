"""MIDI/audio synthesis helpers for the MusicIR renderer."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi
import soundfile as sf
from scipy import signal

from ..profiler import profile
from ..audio_utils import coerce_stereo

def legacy_spec_hash(spec_path: Path, soundfont_path: str, backend: str) -> str:
    """Return the pre-render-dependency hash for migration diagnostics only.

    New currentness/layout code must use ``render.dependencies``.  Keeping this
    helper makes old manifests explainable without allowing the hand-bumped
    renderer version to remain a cache authority.
    """
    from .score_core import RENDERER_VERSION

    payload = {
        "renderer_version": RENDERER_VERSION,
        "spec_text": Path(spec_path).read_text(encoding="utf8"),
        "soundfont": str(soundfont_path),
        "backend": backend,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf8")
    ).hexdigest()[:16]


def spec_hash(spec_path: Path, soundfont_path: str, backend: str) -> str:
    """Compatibility facade for the canonical render-dependency short hash.

    ``soundfont_path`` is retained in the signature for callers from the old
    API; the canonical builder resolves the score's SoundFont itself so every
    caller shares one dependency plan.
    """
    from .dependencies import render_dependency_fingerprint_for_score

    return render_dependency_fingerprint_for_score(
        Path(spec_path), backend, soundfont_override=str(soundfont_path)
    ).short_hash


def sanitize_same_pitch_overlaps(
    pm: pretty_midi.PrettyMIDI, *, min_duration: float = 0.001
) -> None:
    """Trim overlapping same-pitch notes on each MIDI instrument.

    FluidSynth's channel model cannot represent two simultaneously sounding
    notes with the same pitch on the same channel. If a long pad/choir note is
    re-articulated before the previous same-pitch note-off, the older note-off
    can silence the newer note and create an audible dropout. Keep exact
    adjacency intact, but trim true overlaps before synthesis.
    """
    for inst in pm.instruments:
        by_pitch: dict[int, list[pretty_midi.Note]] = {}
        for note in inst.notes:
            by_pitch.setdefault(int(note.pitch), []).append(note)
        for notes in by_pitch.values():
            notes.sort(key=lambda n: (float(n.start), float(n.end)))
            prev: pretty_midi.Note | None = None
            for note in notes:
                if prev is not None and float(prev.end) > float(note.start):
                    prev.end = max(float(prev.start) + min_duration, float(note.start))
                prev = note


@profile
def _fluidsynth_stereo_samples(fl: Any, n: int) -> np.ndarray:
    """Return ``n`` stereo frames from pyFluidSynth as float32 [-1, 1]."""
    if n <= 0:
        return np.zeros((0, 2), dtype=np.float32)
    buf = fl.get_samples(int(n))
    stereo = np.column_stack(
        [buf[0::2].astype(np.float32), buf[1::2].astype(np.float32)]
    )
    stereo /= 32768.0
    return stereo


@profile
def _new_fluidsynth(soundfont: str, sample_rate: int) -> tuple[Any, int]:
    try:
        import fluidsynth  # type: ignore
    except ImportError as e:
        raise ImportError(
            "pretty-midi backend needs pyfluidsynth. Install it with "
            "`uv pip install pyfluidsynth`."
        ) from e

    fl = fluidsynth.Synth(samplerate=float(sample_rate), gain=1.6)
    try:
        fl.setting("synth.reverb.active", 0)
        fl.setting("synth.chorus.active", 0)
    except Exception as ex:
        # If this fails, FluidSynth's internal reverb/chorus stays on and every
        # render silently stacks a second room on top of the YAML postprocess.
        print(
            f"[ambition_music_renderer] could not disable FluidSynth internal reverb/chorus: {ex}",
            file=sys.stderr,
        )
    sfid = fl.sfload(soundfont)
    return fl, sfid


@profile
def _render_pretty_midi_per_instrument(
    pm: pretty_midi.PrettyMIDI, soundfont: str, sample_rate: int
) -> np.ndarray:
    """Legacy pyFluidSynth path: one synth instance per MIDI instrument."""
    if not pm.instruments:
        return np.zeros((1, 2), dtype=np.float32)

    fs_float = float(sample_rate)
    waveforms: list[np.ndarray] = []
    for inst in pm.instruments:
        if not inst.notes:
            continue
        fl, sfid = _new_fluidsynth(soundfont, sample_rate)
        if inst.is_drum:
            channel = 9
            fl.program_select(channel, sfid, 128, 0)
        else:
            channel = 0
            fl.program_select(channel, sfid, 0, int(inst.program))

        events: list[tuple] = []
        for note in inst.notes:
            events.append((float(note.start), 1, channel, "on", int(note.pitch), int(note.velocity)))
            events.append((float(note.end), 0, channel, "off", int(note.pitch), 0))
        for cc in inst.control_changes:
            events.append((float(cc.time), 0, channel, "cc", int(cc.number), int(cc.value)))
        for pb in inst.pitch_bends:
            events.append((float(pb.time), 0, channel, "pb", int(pb.pitch), 0))
        events.sort(key=lambda e: (e[0], e[1]))

        last_event_time = events[-1][0] if events else 0.0
        total_samples = int(math.ceil((last_event_time + 0.6) * fs_float))
        out = np.zeros((total_samples, 2), dtype=np.float32)
        cursor = 0
        for ev in events:
            target = min(int(ev[0] * fs_float), total_samples)
            n = target - cursor
            if n > 0:
                stereo = _fluidsynth_stereo_samples(fl, n)
                out[cursor : cursor + len(stereo), :] = stereo[:n]
                cursor += n
            kind = ev[3]
            if kind == "on":
                fl.noteon(channel, ev[4], ev[5])
            elif kind == "off":
                fl.noteoff(channel, ev[4])
            elif kind == "cc":
                fl.cc(channel, ev[4], ev[5])
            elif kind == "pb":
                fl.pitch_bend(channel, ev[4])
        if cursor < total_samples:
            stereo = _fluidsynth_stereo_samples(fl, total_samples - cursor)
            out[cursor : cursor + len(stereo), :] = stereo[: total_samples - cursor]
        fl.delete()
        waveforms.append(out)

    if not waveforms:
        return np.zeros((1, 2), dtype=np.float32)
    max_len = max(len(w) for w in waveforms)
    mixed = np.zeros((max_len, 2), dtype=np.float32)
    for w in waveforms:
        mixed[: len(w), :] += coerce_stereo(w)
    return coerce_stereo(mixed)


@profile
def render_pretty_midi(
    pm: pretty_midi.PrettyMIDI, soundfont: str, sample_rate: int
) -> np.ndarray:
    """Render via pyFluidSynth with one synth pass per stem group.

    The original implementation created one FluidSynth instance per instrument
    and rendered each instrument to a separate waveform before summing.  That is
    easy to reason about, but it is painfully slow for multi-instrument groups:
    a group with six instruments pays six full-duration synthesis passes.

    This path assigns each melodic instrument to its own MIDI channel in one
    FluidSynth instance, reserves channel 9 for drums, and renders the whole
    group in a single event sweep.  That preserves per-instrument programs, CCs,
    pitch bends, and pan while turning the dominant cost from
    O(instruments * duration) into O(duration).  Set
    ``AMBITION_PRETTY_MIDI_LEGACY=1`` to use the old path for A/B debugging.
    """
    if os.environ.get("AMBITION_PRETTY_MIDI_LEGACY") == "1":
        return _render_pretty_midi_per_instrument(pm, soundfont, sample_rate)
    if not pm.instruments:
        return np.zeros((1, 2), dtype=np.float32)

    active_insts = [inst for inst in pm.instruments if inst.notes]
    if not active_insts:
        return np.zeros((1, 2), dtype=np.float32)

    melodic = [inst for inst in active_insts if not inst.is_drum]
    if len(melodic) > 15:
        # MIDI has only 16 channels and channel 9 is reserved for drums here.
        # Large groups are rare; keep behavior safe rather than clever.
        return _render_pretty_midi_per_instrument(pm, soundfont, sample_rate)

    channels = [ch for ch in range(16) if ch != 9]
    channel_for_inst: dict[int, int] = {}
    for inst, channel in zip(melodic, channels):
        channel_for_inst[id(inst)] = channel
    for inst in active_insts:
        if inst.is_drum:
            channel_for_inst[id(inst)] = 9

    fl, sfid = _new_fluidsynth(soundfont, sample_rate)
    selected_channels: set[int] = set()
    for inst in active_insts:
        channel = channel_for_inst[id(inst)]
        if inst.is_drum:
            if channel not in selected_channels:
                fl.program_select(channel, sfid, 128, 0)
                selected_channels.add(channel)
        else:
            fl.program_select(channel, sfid, 0, int(inst.program))
            selected_channels.add(channel)

    fs_float = float(sample_rate)
    events: list[tuple] = []
    for inst in active_insts:
        channel = channel_for_inst[id(inst)]
        for note in inst.notes:
            events.append((float(note.start), 1, channel, "on", int(note.pitch), int(note.velocity)))
            events.append((float(note.end), 0, channel, "off", int(note.pitch), 0))
        for cc in inst.control_changes:
            events.append((float(cc.time), 0, channel, "cc", int(cc.number), int(cc.value)))
        for pb in inst.pitch_bends:
            events.append((float(pb.time), 0, channel, "pb", int(pb.pitch), 0))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    last_event_time = events[-1][0] if events else 0.0
    total_samples = int(math.ceil((last_event_time + 0.6) * fs_float))
    out = np.zeros((total_samples, 2), dtype=np.float32)
    cursor = 0
    for ev in events:
        target = min(int(ev[0] * fs_float), total_samples)
        n = target - cursor
        if n > 0:
            stereo = _fluidsynth_stereo_samples(fl, n)
            out[cursor : cursor + len(stereo), :] = stereo[:n]
            cursor += n
        _, _, channel, kind, a, b = ev
        if kind == "on":
            fl.noteon(channel, a, b)
        elif kind == "off":
            fl.noteoff(channel, a)
        elif kind == "cc":
            fl.cc(channel, a, b)
        elif kind == "pb":
            fl.pitch_bend(channel, a)
    if cursor < total_samples:
        stereo = _fluidsynth_stereo_samples(fl, total_samples - cursor)
        out[cursor : cursor + len(stereo), :] = stereo[: total_samples - cursor]
    fl.delete()
    return coerce_stereo(out)



@profile
def render_with_fluidsynth_cli(
    midi_path: Path, soundfont: str, sample_rate: int, dry_wav_path: Path
) -> np.ndarray:
    # `-R 0 -C 0` disables fluidsynth's internal reverb and chorus so they
    # don't stack on top of the YAML postprocess chain. `-g 1.6` lifts the
    # synth gain off its quiet 0.2 default so authored MIDI velocities map
    # to sensible per-stem levels (matches the pyfluidsynth gain).
    cmd = [
        "fluidsynth",
        "-ni",
        "-R",
        "0",
        "-C",
        "0",
        "-g",
        "1.6",
        "-r",
        str(sample_rate),
        "-F",
        str(dry_wav_path),
        soundfont,
        str(midi_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio, sr = sf.read(dry_wav_path, dtype="float32", always_2d=True)
    if sr != sample_rate:
        audio = signal.resample_poly(audio, sample_rate, sr, axis=0).astype(np.float32)
    return coerce_stereo(audio)


def _initial_cc_value(inst: pretty_midi.Instrument, number: int, default: int) -> int:
    """Return the latest controller value authored at time zero."""
    value = int(default)
    for cc in inst.control_changes:
        if int(cc.number) == int(number) and float(cc.time) <= 1e-9:
            value = int(cc.value)
    return max(0, min(127, value))


def _fm_modulator(phase: np.ndarray, waveform: str) -> np.ndarray:
    waveform = str(waveform).lower().strip()
    if waveform in {"sine", "sin"}:
        return np.sin(phase)
    if waveform in {"triangle", "tri"}:
        return (2.0 / np.pi) * np.arcsin(np.sin(phase))
    if waveform in {"square", "pulse"}:
        return np.where(np.sin(phase) >= 0.0, 1.0, -1.0)
    if waveform in {"saw", "sawtooth"}:
        return signal.sawtooth(phase).astype(np.float64, copy=False)
    raise ValueError(f"unsupported procedural FM modulator waveform {waveform!r}")


def _bandlimited_carrier(phase: np.ndarray, waveform: str, harmonics: int) -> np.ndarray:
    """Evaluate a compact Fourier oscillator at an already-modulated phase."""
    waveform = str(waveform).lower().strip()
    harmonics = max(1, int(harmonics))
    if waveform in {"sine", "sin"}:
        return np.sin(phase).astype(np.float64, copy=False)
    out = np.zeros_like(phase, dtype=np.float64)
    if waveform in {"square", "pulse"}:
        for k in range(1, harmonics + 1, 2):
            out += np.sin(k * phase) / k
        out *= 4.0 / np.pi
        return out
    if waveform in {"triangle", "tri"}:
        sign = 1.0
        for k in range(1, harmonics + 1, 2):
            out += sign * np.sin(k * phase) / (k * k)
            sign *= -1.0
        out *= 8.0 / (np.pi * np.pi)
        return out
    if waveform in {"saw", "sawtooth"}:
        for k in range(1, harmonics + 1):
            out += ((-1.0) ** (k + 1)) * np.sin(k * phase) / k
        out *= 2.0 / np.pi
        return out
    raise ValueError(f"unsupported procedural FM carrier waveform {waveform!r}")


def _adsr_envelope(
    n_sustain: int,
    n_release: int,
    sample_rate: int,
    *,
    attack_ms: float,
    decay_ms: float,
    sustain: float,
) -> np.ndarray:
    total = max(1, int(n_sustain) + int(n_release))
    env = np.ones(total, dtype=np.float64)
    sustain = float(np.clip(sustain, 0.0, 1.0))
    attack = min(max(0, int(round(float(attack_ms) * sample_rate / 1000.0))), n_sustain)
    decay = min(max(0, int(round(float(decay_ms) * sample_rate / 1000.0))), max(0, n_sustain - attack))
    if attack > 0:
        env[:attack] = np.linspace(0.0, 1.0, attack, endpoint=False)
    if decay > 0:
        env[attack : attack + decay] = np.linspace(1.0, sustain, decay, endpoint=False)
    if attack + decay < n_sustain:
        env[attack:n_sustain] = np.maximum(env[attack:n_sustain], sustain)
        env[attack + decay : n_sustain] = sustain
    release_start = sustain if n_sustain > 0 else 0.0
    if n_release > 0:
        env[n_sustain:] = np.linspace(release_start, 0.0, n_release, endpoint=True)
    return env


@profile
def render_procedural_fm(
    pm: pretty_midi.PrettyMIDI,
    backend_spec: dict[str, Any],
    sample_rate: int,
    minimum_duration: float,
) -> np.ndarray:
    """Render one or more MIDI instruments with a small oscillator-level FM synth.

    This backend exists for timbres that cannot be expressed by General MIDI /
    SoundFonts: the carrier oscillator is phase/frequency modulated at audio
    rate before optional saturation.  It intentionally remains a compact synth
    primitive rather than a cue-specific effect.
    """
    active = [inst for inst in pm.instruments if inst.notes]
    total_end = max(
        [float(minimum_duration)]
        + [float(note.end) for inst in active for note in inst.notes]
    )
    env_cfg = dict(backend_spec.get("envelope") or {})
    fm_cfg = dict(backend_spec.get("fm") or {})
    carrier_cfg = dict(backend_spec.get("carrier") or {})
    release_ms = float(env_cfg.get("release_ms", 75.0))
    release_s = max(0.0, release_ms / 1000.0)
    total_samples = max(1, int(math.ceil((total_end + release_s + 0.02) * sample_rate)))
    out = np.zeros((total_samples, 2), dtype=np.float64)

    carrier_waveform = str(carrier_cfg.get("waveform", backend_spec.get("waveform", "square")))
    mod_waveform = str(fm_cfg.get("waveform", "sine"))
    ratio = float(fm_cfg.get("ratio", 0.25))
    index = float(fm_cfg.get("index", fm_cfg.get("amount", 0.12)))
    harmonics = int(carrier_cfg.get("harmonics", backend_spec.get("harmonics", 15)))
    attack_ms = float(env_cfg.get("attack_ms", 4.0))
    decay_ms = float(env_cfg.get("decay_ms", 55.0))
    sustain = float(env_cfg.get("sustain", 0.9))
    saturation_drive = max(0.01, float(backend_spec.get("saturation_drive", 1.0)))
    output_gain_db = float(backend_spec.get("output_gain_db", -7.0))
    output_gain = 10.0 ** (output_gain_db / 20.0)

    for inst in active:
        volume = _initial_cc_value(inst, 7, 100) / 127.0
        expression = _initial_cc_value(inst, 11, 127) / 127.0
        pan = _initial_cc_value(inst, 10, 64) / 127.0
        pan_angle = pan * (np.pi / 2.0)
        pan_l = math.cos(pan_angle)
        pan_r = math.sin(pan_angle)
        for note in inst.notes:
            start = max(0, int(round(float(note.start) * sample_rate)))
            sustain_samples = max(1, int(round((float(note.end) - float(note.start)) * sample_rate)))
            release_samples = max(0, int(round(release_s * sample_rate)))
            n = sustain_samples + release_samples
            if start >= total_samples or n <= 0:
                continue
            n = min(n, total_samples - start)
            sustain_samples = min(sustain_samples, n)
            release_samples = max(0, n - sustain_samples)
            t = np.arange(n, dtype=np.float64) / float(sample_rate)
            freq = pretty_midi.note_number_to_hz(int(note.pitch))
            carrier_phase = 2.0 * np.pi * freq * t
            mod_phase = 2.0 * np.pi * (freq * ratio) * t
            mod = _fm_modulator(mod_phase, mod_waveform)
            modulated_phase = carrier_phase + index * mod
            # Limit Fourier content against the note's base frequency.  The
            # post-filter in the score handles the remaining FM sidebands.
            max_harmonic = max(1, int((0.45 * sample_rate) / max(freq, 1.0)))
            note_harmonics = min(harmonics, max_harmonic)
            carrier = _bandlimited_carrier(modulated_phase, carrier_waveform, note_harmonics)
            env = _adsr_envelope(
                sustain_samples,
                release_samples,
                sample_rate,
                attack_ms=attack_ms,
                decay_ms=decay_ms,
                sustain=sustain,
            )
            velocity = (float(note.velocity) / 127.0) ** 0.85
            mono = carrier * env * velocity * volume * expression * output_gain
            if abs(saturation_drive - 1.0) > 1e-6:
                mono = np.tanh(mono * saturation_drive) / math.tanh(saturation_drive)
            out[start : start + n, 0] += mono * pan_l
            out[start : start + n, 1] += mono * pan_r

    return coerce_stereo(out.astype(np.float32, copy=False))


@profile
def render_synth_audio(
    pm: pretty_midi.PrettyMIDI,
    backend: str,
    soundfont: str,
    sample_rate: int,
    midi_path: Path,
    dry_wav_path: Path,
    minimum_duration: float,
) -> np.ndarray:
    if backend == "fallback":
        from .. import fallback_backend  # imported lazily so its synth code stays out of YAML-only paths

        return fallback_backend.render_fallback(
            pm, sample_rate, minimum_duration=minimum_duration
        )
    if backend == "fluidsynth-cli":
        if not soundfont:
            raise FileNotFoundError(
                "fluidsynth-cli backend requires --soundfont or installed default SoundFont"
            )
        if not shutil.which("fluidsynth"):
            raise FileNotFoundError("fluidsynth binary not found")
        return render_with_fluidsynth_cli(
            midi_path, soundfont, sample_rate, dry_wav_path
        )
    if backend == "pretty-midi":
        if not soundfont:
            raise FileNotFoundError(
                "pretty-midi backend requires --soundfont or installed default SoundFont"
            )
        return render_pretty_midi(pm, soundfont, sample_rate)
    if backend in {"sfizz", "sfizz-render"}:
        raise ValueError(
            "sfizz rendering is instrument-aware; call render_group_audio so YAML can provide instrument_backend.sfz"
        )
    if backend == "auto":
        if soundfont and shutil.which("fluidsynth"):
            try:
                return render_with_fluidsynth_cli(
                    midi_path, soundfont, sample_rate, dry_wav_path
                )
            except Exception as ex:
                print(
                    f"[WARN] fluidsynth-cli failed ({ex}); falling back to fallback renderer"
                )
        from .. import fallback_backend

        return fallback_backend.render_fallback(
            pm, sample_rate, minimum_duration=minimum_duration
        )
    raise ValueError(f"unknown backend {backend}")


