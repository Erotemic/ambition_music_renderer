#!/usr/bin/env python3
"""MusicIR score expansion and MIDI event construction.

A data-driven, non-ML music renderer for compact YAML music assets.

The renderer intentionally keeps composition out of Python code.  New cues should
be authored by changing YAML: instruments, motifs, sections, harmony, and layers.
The Python library interprets those declarative layers, emits MIDI events, renders
through either FluidSynth or a built-in orchestral/synth fallback, post-processes,
and exports OGG Vorbis section/stem assets plus a full soundtrack preview.
"""

from __future__ import annotations

import dataclasses as dc
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pretty_midi
import yaml

RENDERER_VERSION = "ambition-musicir-renderer-v0.9.0-pro-render-backends-guitar-v1"
DEFAULT_SOUNDFONTS = [
    "/usr/share/sounds/sf3/MuseScore_General_Full.sf3",
    "/usr/share/sounds/sf3/MuseScore_General.sf3",
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/TimGM6mb.sf2",
    "/usr/share/sounds/sf2/default-GM.sf2",
    "/usr/share/sounds/sf3/default-GM.sf3",
]

NOTE_CLASS = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}

GM_PROGRAMS = {
    "acoustic_grand_piano": 0,
    "bright_piano": 1,
    "electric_grand_piano": 2,
    "honky_tonk_piano": 3,
    "electric_piano_1": 4,
    "electric_piano_2": 5,
    "harpsichord": 6,
    "clavinet": 7,
    "celesta": 8,
    "glockenspiel": 9,
    "music_box": 10,
    "vibraphone": 11,
    "marimba": 12,
    "xylophone": 13,
    "tubular_bells": 14,
    "dulcimer": 15,
    "drawbar_organ": 16,
    "church_organ": 19,
    "accordion": 21,
    "nylon_guitar": 24,
    "steel_guitar": 25,
    "jazz_guitar": 26,
    "clean_guitar": 27,
    "muted_guitar": 28,
    "overdrive_guitar": 29,
    "distortion_guitar": 30,
    "acoustic_bass": 32,
    "fingered_bass": 33,
    "picked_bass": 34,
    "fretless_bass": 35,
    "slap_bass_1": 36,
    "synth_bass_1": 38,
    "synth_bass_2": 39,
    "violin": 40,
    "viola": 41,
    "cello": 42,
    "contrabass": 43,
    "tremolo_strings": 44,
    "pizzicato_strings": 45,
    "orchestral_harp": 46,
    "timpani": 47,
    "string_ensemble_1": 48,
    "string_ensemble_2": 49,
    "synth_strings_1": 50,
    "synth_strings_2": 51,
    "choir_aahs": 52,
    "voice_oohs": 53,
    "synth_voice": 54,
    "orchestra_hit": 55,
    "trumpet": 56,
    "trombone": 57,
    "tuba": 58,
    "muted_trumpet": 59,
    "french_horn": 60,
    "brass_section": 61,
    "synth_brass_1": 62,
    "synth_brass_2": 63,
    "soprano_sax": 64,
    "alto_sax": 65,
    "tenor_sax": 66,
    "baritone_sax": 67,
    "oboe": 68,
    "english_horn": 69,
    "bassoon": 70,
    "clarinet": 71,
    "piccolo": 72,
    "flute": 73,
    "recorder": 74,
    "pan_flute": 75,
    "blown_bottle": 76,
    "shakuhachi": 77,
    "whistle": 78,
    "ocarina": 79,
    "lead_square": 80,
    "lead_saw": 81,
    "lead_calliope": 82,
    "lead_chiff": 83,
    "lead_charang": 84,
    "lead_voice": 85,
    "lead_fifths": 86,
    "lead_basslead": 87,
    "pad_new_age": 88,
    "pad_warm": 89,
    "pad_poly": 90,
    "pad_choir": 91,
    "pad_bowed": 92,
    "pad_metallic": 93,
    "pad_halo": 94,
    "pad_sweep": 95,
    "fx_rain": 96,
    "fx_soundtrack": 97,
    "fx_crystal": 98,
    "fx_atmosphere": 99,
    "fx_brightness": 100,
    "fx_goblins": 101,
    "fx_echoes": 102,
    "fx_scifi": 103,
    "sitar": 104,
    "banjo": 105,
    "shamisen": 106,
    "koto": 107,
    "kalimba": 108,
    "bagpipe": 109,
    "fiddle": 110,
    "shanai": 111,
    "tinkle_bell": 112,
    "agogo": 113,
    "steel_drums": 114,
    "woodblock": 115,
    "taiko_drum": 116,
    "melodic_tom": 117,
    "synth_drum": 118,
    "reverse_cymbal": 119,
}

DRUMS = {
    "kick": 36,
    "concert_bass_drum": 35,
    "side_stick": 37,
    "snare": 38,
    "hand_clap": 39,
    "electric_snare": 40,
    "floor_tom": 41,
    "closed_hat": 42,
    "low_tom": 43,
    "pedal_hat": 44,
    "mid_tom": 45,
    "open_hat": 46,
    "high_tom": 48,
    "crash": 49,
    "ride": 51,
    "china": 52,
    "ride_bell": 53,
    "tambourine": 54,
    "splash": 55,
    "cowbell": 56,
    "vibraslap": 58,
    "bongo_hi": 60,
    "bongo_low": 61,
    "conga_hi": 62,
    "conga_low": 64,
    "timbale_hi": 65,
    "timbale_low": 66,
    "agogo_hi": 67,
    "agogo_low": 68,
    "shaker": 70,
    "whistle_short": 71,
    "whistle_long": 72,
    "guiro_short": 73,
    "guiro_long": 74,
    "claves": 75,
    "woodblock_hi": 76,
    "woodblock_low": 77,
    "triangle_mute": 80,
    "triangle": 81,
}

ARTICULATION_GATE = {
    "staccato": 0.40,
    "spiccato": 0.34,
    "pluck": 0.46,
    "marcato": 0.68,
    "normal": 0.86,
    "tenuto": 0.98,
    "legato": 1.10,
    "pad": 1.02,
    "hit": 0.28,
    "bell": 1.40,
}

CC_NUMBERS = {
    "modulation": 1,
    "breath": 2,
    "volume": 7,
    "pan": 10,
    "expression": 11,
    "sustain": 64,
    "reverb": 91,
    "chorus": 93,
}


@dc.dataclass(frozen=True)
class TempoMap:
    """Piecewise-linear tempo (bpm as a function of beat).

    Authored as ``tempo.map`` in MusicIR YAML::

        tempo:
          bpm: 144
          map:
            - {bar: 62, bpm: 120, ramp_bars: 4}   # ritardando over 4 bars
            - {bar: 67, bpm: 84, ramp_bars: 1}    # pool on the final phrase

    Each entry ramps linearly from the previous tempo, starting at ``bar``
    (absolute, fractional allowed) and reaching ``bpm`` after ``ramp_bars``,
    then holds until the next entry.  With no ``map`` the cue is constant
    tempo and behaves exactly as before.

    ``knots`` are ``(beat, bpm)`` waypoints; between knots bpm is linear in
    the beat, so beat->time integrates in closed form:
    ``dt = 60 * db * ln(v1/v0) / (v1 - v0)`` per segment.
    """

    knots: tuple[tuple[float, float], ...]  # ((beat, bpm), ...) sorted by beat
    _times: tuple[float, ...] = dc.field(default=(), compare=False)

    @staticmethod
    def constant(bpm: float) -> "TempoMap":
        return TempoMap(knots=((0.0, float(bpm)),), _times=(0.0,))

    @staticmethod
    def from_spec(spec: dict[str, Any]) -> "TempoMap":
        tempo_cfg = spec.get("tempo", {}) or {}
        base_bpm = float(tempo_cfg.get("bpm", spec.get("bpm", 120)))
        entries = tempo_cfg.get("map") or []
        if not entries:
            return TempoMap.constant(base_bpm)
        beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
        knots: list[tuple[float, float]] = [(0.0, base_bpm)]
        for entry in entries:
            start_beat = float(entry["bar"]) * beats_per_bar
            target = float(entry["bpm"])
            ramp_beats = float(entry.get("ramp_bars", 0.0)) * beats_per_bar
            prev_beat, prev_bpm = knots[-1]
            if start_beat < prev_beat - 1e-9:
                raise ValueError(
                    f"tempo.map entries must be ordered by bar; bar {entry['bar']} "
                    f"starts before the previous entry ends"
                )
            # Hold the previous tempo up to the ramp start, then ramp.
            if start_beat > prev_beat + 1e-9:
                knots.append((start_beat, prev_bpm))
            knots.append((start_beat + max(ramp_beats, 1e-6), target))
        return TempoMap(knots=tuple(knots), _times=TempoMap._integrate(tuple(knots)))

    @staticmethod
    def _integrate(knots: tuple[tuple[float, float], ...]) -> tuple[float, ...]:
        times = [0.0]
        for (b0, v0), (b1, v1) in zip(knots, knots[1:]):
            times.append(times[-1] + TempoMap._segment_time(b0, v0, b1, v1, b1))
        return tuple(times)

    @staticmethod
    def _segment_time(b0: float, v0: float, b1: float, v1: float, beat: float) -> float:
        """Seconds from ``b0`` to ``beat`` (``b0 <= beat <= b1``), bpm linear."""
        db = beat - b0
        if db <= 0.0:
            return 0.0
        if abs(v1 - v0) < 1e-9:
            return 60.0 * db / v0
        # bpm at `beat` along the linear segment
        v = v0 + (v1 - v0) * (beat - b0) / (b1 - b0)
        slope = (v1 - v0) / (b1 - b0)
        return 60.0 / slope * math.log(v / v0)

    def bpm_at(self, beat: float) -> float:
        knots = self.knots
        if beat <= knots[0][0]:
            return knots[0][1]
        for (b0, v0), (b1, v1) in zip(knots, knots[1:]):
            if beat <= b1:
                return v0 + (v1 - v0) * (beat - b0) / (b1 - b0)
        return knots[-1][1]

    def beat_to_time(self, beat: float) -> float:
        knots = self.knots
        if beat <= knots[0][0]:
            return 60.0 * (beat - knots[0][0]) / knots[0][1]
        for i, ((b0, v0), (b1, v1)) in enumerate(zip(knots, knots[1:])):
            if beat <= b1:
                return self._times[i] + self._segment_time(b0, v0, b1, v1, beat)
        b_last, v_last = knots[-1]
        return self._times[-1] + 60.0 * (beat - b_last) / v_last

    def time_to_beat(self, time: float) -> float:
        """Inverse of :meth:`beat_to_time` (bisection inside one segment)."""
        knots = self.knots
        if time <= 0.0:
            return knots[0][0] + time * knots[0][1] / 60.0
        for i, ((b0, _v0), (b1, _v1)) in enumerate(zip(knots, knots[1:])):
            if time <= self._times[i + 1]:
                lo, hi = b0, b1
                for _ in range(60):
                    mid = 0.5 * (lo + hi)
                    if self.beat_to_time(mid) < time:
                        lo = mid
                    else:
                        hi = mid
                return 0.5 * (lo + hi)
        b_last, v_last = knots[-1]
        return b_last + (time - self._times[-1]) * v_last / 60.0


@dc.dataclass
class RenderContext:
    spec: dict[str, Any]
    sample_rate: int
    bpm: float
    beats_per_bar: float
    rng: np.random.Generator
    pm: pretty_midi.PrettyMIDI
    instruments: dict[str, pretty_midi.Instrument]
    groups: dict[str, str]
    section_starts: dict[str, int]
    motifs: dict[str, dict[str, Any]]
    instrument_specs: dict[str, dict[str, Any]] = dc.field(default_factory=dict)
    last_guitar_voicing: dict[str, list[Any]] = dc.field(default_factory=dict)
    # Tracks the most recent chord voicing per instrument for the
    # `voice_leading: minimize_motion` constraint.
    last_voicing: dict[str, list[int]] = dc.field(default_factory=dict)
    # Lightweight provenance captured while MusicIR expands into MIDI notes.
    # Debug tooling uses this to attribute harmonic clashes back to section /
    # layer / group without changing the PrettyMIDI output format.
    note_events: list[dict[str, Any]] = dc.field(default_factory=list)
    active_section_id: str | None = None
    active_layer_id: str | None = None
    active_layer_kind: str | None = None
    # `tempo.map` support; None means constant `bpm` (the historical model).
    tempo: TempoMap | None = None
    # Set per-layer while rendering: scales note velocity by beat position
    # (`dynamics:` crescendo/decrescendo curves). None = no scaling.
    dynamics_scale: "Callable[[float], float] | None" = None

    def beat_to_time(self, beat: float) -> float:
        if self.tempo is not None:
            return self.tempo.beat_to_time(beat)
        return beat * 60.0 / self.bpm

    def time_to_beat(self, time: float) -> float:
        if self.tempo is not None:
            return self.tempo.time_to_beat(time)
        return time * self.bpm / 60.0

    def beat_duration_to_seconds(self, start_beat: float, dur_beats: float) -> float:
        """Duration of ``dur_beats`` starting at ``start_beat`` in seconds."""
        if self.tempo is None:
            return dur_beats * 60.0 / self.bpm
        return self.tempo.beat_to_time(start_beat + dur_beats) - self.tempo.beat_to_time(start_beat)

    def bar_to_beat(self, bar: float, beat: float = 0.0) -> float:
        return bar * self.beats_per_bar + beat

    def bar_to_time(self, bar: float, beat: float = 0.0) -> float:
        return self.beat_to_time(self.bar_to_beat(bar, beat))


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf8") as f:
        return yaml.safe_load(f)


def choose_soundfont(path: str | None = None) -> str:
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"soundfont does not exist: {p}")
        return str(p)
    for candidate in DEFAULT_SOUNDFONTS:
        if Path(candidate).exists():
            return candidate
    return ""


