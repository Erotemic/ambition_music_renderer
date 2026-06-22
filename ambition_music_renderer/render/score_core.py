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

import copy
import dataclasses as dc
import functools
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
import gc
import os
import sys

import numpy as np
import pretty_midi
import soundfile as sf
import yaml
import kwconf
from ..profiler import profile
from scipy import signal

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

    def beat_to_time(self, beat: float) -> float:
        return beat * 60.0 / self.bpm

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


