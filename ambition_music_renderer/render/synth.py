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
from .score_core import RENDERER_VERSION

def spec_hash(spec_path: Path, soundfont_path: str, backend: str) -> str:
    payload = {
        "renderer_version": RENDERER_VERSION,
        "spec_text": spec_path.read_text(encoding="utf8"),
        "soundfont": str(soundfont_path),
        "backend": backend,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf8")
    ).hexdigest()[:16]


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


