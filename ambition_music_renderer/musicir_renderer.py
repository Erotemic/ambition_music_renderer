#!/usr/bin/env python3
"""Ambition MusicIR renderer.

A data-driven, non-ML music renderer for compact YAML music assets.

The renderer intentionally keeps composition out of Python code.  New cues should
be authored by changing YAML: instruments, motifs, sections, harmony, and layers.
The Python library interprets those declarative layers, emits MIDI events, renders
through either FluidSynth or a built-in orchestral/synth fallback, post-processes,
and exports OGG Vorbis section/stem assets plus a full soundtrack preview.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses as dc
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable
import wave
import gc
import os
import sys

import numpy as np
import pretty_midi
import soundfile as sf
import yaml
from .profiler import profile
from scipy import signal

RENDERER_VERSION = "ambition-musicir-renderer-v0.8.2-adaptive-global-section-master-v1"
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


def note_to_midi(note: str) -> int:
    note = note.strip()
    m = re.fullmatch(r"([A-G](?:#|b)?)(-?\d+)", note)
    if not m:
        raise ValueError(f"bad note name: {note!r}")
    return 12 * (int(m.group(2)) + 1) + NOTE_CLASS[m.group(1)]


def midi_to_note(num: int) -> str:
    return pretty_midi.note_number_to_name(int(num))


def clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def fit_midi_pitch(num: int | float) -> int:
    """Fold an integer pitch into the valid MIDI range by octaves.

    Hard-clamping high generated voicings to 127 creates artificial G9 notes
    that are both musically wrong and extremely obvious in sour-note audits.
    Octave folding preserves pitch class while keeping generated pads playable.
    """
    p = int(round(float(num)))
    while p > 127:
        p -= 12
    while p < 0:
        p += 12
    return int(clamp(p, 0, 127))


def chord_intervals(chord_symbol: str) -> tuple[str, list[int], str | None]:
    raw = chord_symbol.strip()
    if "/" in raw:
        main_candidate, slash_candidate = raw.rsplit("/", 1)
        # Treat C/E and G/B as slash-bass chords, but keep extensions such as
        # D6/9 as part of the chord suffix instead of pretending "9" is a bass note.
        if re.match(r"^[A-G](?:#|b)?$", slash_candidate.strip()):
            main, slash_bass = main_candidate, slash_candidate.strip()
        else:
            main, slash_bass = raw, None
    else:
        main, slash_bass = raw, None
    m = re.match(r"^([A-G](?:#|b)?)(.*)$", main)
    if not m:
        raise ValueError(f"cannot parse chord root from {chord_symbol!r}")
    root = m.group(1)
    suffix = m.group(2).lower()
    if "dim" in suffix or "o" in suffix:
        intervals = [0, 3, 6]
    elif "aug" in suffix or "+" in suffix:
        intervals = [0, 4, 8]
    elif "sus2" in suffix:
        intervals = [0, 2, 7]
    elif "sus4" in suffix or "sus" in suffix:
        intervals = [0, 5, 7]
    elif suffix.startswith("m") and not suffix.startswith("maj"):
        intervals = [0, 3, 7]
    else:
        intervals = [0, 4, 7]
    if "maj7" in suffix or "Δ" in suffix:
        intervals.append(11)
    elif "7" in suffix or "9" in suffix or "13" in suffix:
        intervals.append(10)
    if "6" in suffix and 9 not in intervals:
        intervals.append(9)
    if "9" in suffix or "add9" in suffix:
        intervals.append(14)
    if "#11" in suffix:
        intervals.append(18)
    elif "11" in suffix:
        intervals.append(17)
    if "b13" in suffix:
        intervals.append(20)
    elif "13" in suffix:
        intervals.append(21)
    if "b9" in suffix:
        intervals.append(13)
    if "#9" in suffix:
        intervals.append(15)
    seen = set()
    intervals = [i for i in intervals if not (i in seen or seen.add(i))]
    return root, intervals, slash_bass


def chord_pitches(
    chord_symbol: str, octave: int = 4, *, voicing: str = "closed"
) -> list[int]:
    root, intervals, slash_bass = chord_intervals(chord_symbol)
    root_midi = note_to_midi(f"{root}{octave}")
    notes = [root_midi + i for i in intervals]
    if voicing in {"open", "spread"} and len(notes) >= 4:
        notes = [notes[0] - 12, notes[2], notes[1] + 12, notes[3]] + [
            n + 12 for n in notes[4:]
        ]
    elif voicing == "wide" and len(notes) >= 3:
        notes = [notes[0] - 12, notes[2], notes[1] + 12] + [n + 12 for n in notes[3:]]
    elif voicing == "drop2" and len(notes) >= 4:
        notes = notes[:]
        notes[-2] -= 12
        notes.sort()
    if slash_bass:
        bass_root = re.match(r"^([A-G](?:#|b)?)", slash_bass.strip())
        if bass_root:
            notes.insert(0, note_to_midi(f"{bass_root.group(1)}{octave - 1}"))
    return notes


def section_starts(sections: list[dict[str, Any]]) -> dict[str, int]:
    starts: dict[str, int] = {}
    cursor = 0
    for sec in sections:
        starts[sec["id"]] = cursor
        sec["start_bar"] = cursor
        cursor += int(sec["bars"])
    return starts


def add_cc(inst: pretty_midi.Instrument, number: int, value: int, time: float) -> None:
    inst.control_changes.append(
        pretty_midi.ControlChange(
            number=int(number), value=int(clamp(value, 0, 127)), time=float(time)
        )
    )


def add_instrument(ctx: RenderContext, spec: dict[str, Any]) -> None:
    name = spec["name"]
    if spec.get("is_drum", False):
        inst = pretty_midi.Instrument(program=0, is_drum=True, name=name)
    else:
        program_name = spec.get("program", "string_ensemble_1")
        if isinstance(program_name, int):
            program = int(program_name)
        elif program_name in GM_PROGRAMS:
            program = GM_PROGRAMS[program_name]
        else:
            raise ValueError(
                f"instrument {name!r}: unknown program {program_name!r}. "
                f"Use a GM program name (e.g. lead_saw, pad_warm, synth_brass_1) "
                f"or an int 0-127. Valid names: {', '.join(sorted(GM_PROGRAMS))}"
            )
        inst = pretty_midi.Instrument(program=program, is_drum=False, name=name)
    ctx.pm.instruments.append(inst)
    ctx.instruments[name] = inst
    ctx.groups[name] = spec.get("group", name)
    add_cc(inst, 7, int(spec.get("volume", 100)), 0.0)
    add_cc(inst, 10, int(spec.get("pan", 64)), 0.0)
    add_cc(inst, 11, int(spec.get("expression", 100)), 0.0)
    for key, cc_num in CC_NUMBERS.items():
        if key in spec and key not in {"volume", "pan", "expression"}:
            add_cc(inst, cc_num, int(spec[key]), 0.0)


def resolve_instruments(ctx: RenderContext, layer: dict[str, Any]) -> list[str]:
    if "instrument" in layer:
        return [layer["instrument"]]
    if "instruments" in layer:
        return list(layer["instruments"])
    if "group" in layer:
        return [name for name, group in ctx.groups.items() if group == layer["group"]]
    raise KeyError(f"layer needs instrument/instruments/group: {layer}")


def add_note(
    ctx: RenderContext,
    inst_name: str,
    pitch: int | str,
    bar: float,
    beat: float,
    dur_beats: float,
    vel: float,
    *,
    articulation: str = "normal",
    humanize_ms: float = 0.0,
    humanize_velocity_pct: float = 0.0,
    gate: float | None = None,
    pitch_scoop_cents: float = 0.0,
    pitch_bend_curve: list[tuple[float, float]] | None = None,
) -> None:
    """Schedule a single note.

    `humanize_velocity_pct` jitters velocity by N(0, pct) so motoric figures
    don't sound machine-perfect. ±2-4% is a typical ensemble-feel value.

    `pitch_bend_curve` is an optional list of `(beat_offset_in_note, cents)`
    waypoints that get interpolated across the note. Use it for sustained
    guitar bends — `[(0.0, 0), (0.1, 100), (0.5, 100), (0.7, 0)]` rises a
    semitone, holds, then releases.
    """
    if inst_name not in ctx.instruments:
        raise KeyError(f"unknown instrument {inst_name!r}")
    inst = ctx.instruments[inst_name]
    pitch_num = note_to_midi(pitch) if isinstance(pitch, str) else int(pitch)
    pitch_num = fit_midi_pitch(pitch_num)
    start_beat = ctx.bar_to_beat(bar, beat)
    start = ctx.beat_to_time(start_beat)
    if humanize_ms:
        start += float(ctx.rng.normal(0.0, humanize_ms / 1000.0))
    dur_scale = gate if gate is not None else ARTICULATION_GATE.get(articulation, 0.86)
    end = start + max(0.025, ctx.beat_to_time(dur_beats * dur_scale))
    start = max(0.0, start)
    if end <= start:
        end = start + 0.025
    if humanize_velocity_pct:
        vel = vel * (1.0 + float(ctx.rng.normal(0.0, humanize_velocity_pct / 100.0)))
    velocity = int(clamp(round(vel), 1, 127))
    inst.notes.append(
        pretty_midi.Note(velocity=velocity, pitch=pitch_num, start=start, end=end)
    )
    ctx.note_events.append(
        {
            "instrument": inst_name,
            "group": ctx.groups.get(inst_name, inst_name),
            "section": ctx.active_section_id,
            "layer": ctx.active_layer_id,
            "layer_kind": ctx.active_layer_kind,
            "pitch": int(pitch_num),
            "note": midi_to_note(pitch_num),
            "velocity": int(velocity),
            "nominal_bar": float(bar),
            "nominal_beat": float(beat),
            "nominal_duration_beats": float(dur_beats),
            "start_time": float(start),
            "end_time": float(end),
            "start_beat": float(start / 60.0 * ctx.bpm),
            "end_beat": float(end / 60.0 * ctx.bpm),
        }
    )
    if pitch_bend_curve:
        # Interpolate the curve in time and write as a sequence of pitch bends.
        # Cents are clamped to MIDI's ±2 semitone default range here (200 cents
        # max). For deeper bends, expand `synth.pitch_wheel_sensitivity` upstream.
        note_duration = ctx.beat_to_time(dur_beats)
        for beat_off, cents in pitch_bend_curve:
            bend_time = start + max(
                0.0, float(beat_off) * (note_duration / max(dur_beats, 1e-6))
            )
            bend_time = min(bend_time, end)
            bend_value = int(clamp(float(cents) / 200.0 * 8192.0, -8192, 8191))
            inst.pitch_bends.append(
                pretty_midi.PitchBend(pitch=bend_value, time=bend_time)
            )
        # Reset to 0 just past the note end so we don't drag bend into the next note.
        inst.pitch_bends.append(pretty_midi.PitchBend(pitch=0, time=end + 0.001))
    elif pitch_scoop_cents:
        bend_value = int(clamp(pitch_scoop_cents / 200.0 * 8192.0, -8192, 8191))
        inst.pitch_bends.append(pretty_midi.PitchBend(pitch=bend_value, time=start))
        inst.pitch_bends.append(
            pretty_midi.PitchBend(pitch=0, time=min(end, start + 0.10))
        )


def add_chord(
    ctx: RenderContext,
    inst_name: str,
    chord: str,
    bar: float,
    beat: float,
    dur_beats: float,
    vel: float,
    *,
    octave: int = 4,
    articulation: str = "pad",
    voicing: str = "open",
    humanize_ms: float = 0.0,
    humanize_velocity_pct: float = 0.0,
    gate: float | None = None,
    constraints: dict[str, Any] | None = None,
) -> None:
    notes = chord_pitches(chord, octave=octave, voicing=voicing)
    if constraints:
        notes = _apply_voicing_constraints(ctx, inst_name, notes, constraints)
    for idx, p in enumerate(notes):
        add_note(
            ctx,
            inst_name,
            p,
            bar,
            beat,
            dur_beats,
            vel - idx * 2,
            articulation=articulation,
            humanize_ms=humanize_ms,
            humanize_velocity_pct=humanize_velocity_pct,
            gate=gate,
        )


def _apply_voicing_constraints(
    ctx: RenderContext,
    inst_name: str,
    notes: list[int],
    constraints: dict[str, Any],
) -> list[int]:
    """Rewrite a chord's voicing per the YAML constraints block.

    All checks are opt-in: nothing is enforced unless the YAML asks for it.
    Two rules currently supported:

    - `voice_leading: minimize_motion` — given the previous chord's voicing
      on this instrument, permute / octave-shift the new notes so the total
      voice motion is minimized. Bass note (lowest) is preserved.
    - `no_clusters: true` — any pair of notes a minor 2nd apart is split
      apart by raising the higher one an octave.
    """
    out = list(notes)
    mode = constraints.get("voice_leading")
    if mode == "minimize_motion":
        prev = ctx.last_voicing.get(inst_name)
        if prev is not None and len(prev) >= len(out):
            # Permute new notes to align with prev — for each previous voice,
            # pick the new note (octave-shifted into the closest octave) that
            # minimizes pitch motion. Keep the lowest as bass.
            out = _voice_lead_minimize(prev, out)
    if constraints.get("no_clusters"):
        out = _spread_clusters(out)
    max_pitch = constraints.get("max_pitch")
    min_pitch = constraints.get("min_pitch")
    bounded: list[int] = []
    for p0 in out:
        p = int(round(float(p0)))
        if max_pitch is not None:
            max_p = int(max_pitch)
            while p > max_p:
                p -= 12
        if min_pitch is not None:
            min_p = int(min_pitch)
            while p < min_p:
                p += 12
        bounded.append(p)
    # Final guard: clamp every voice into the valid MIDI range and drop
    # exact duplicates so the constraint stages can't produce out-of-range
    # pitches that would crash the MIDI writer.
    out = [fit_midi_pitch(p) for p in bounded]
    seen: set[int] = set()
    deduped: list[int] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    out = deduped
    ctx.last_voicing[inst_name] = list(out)
    return out


def _voice_lead_minimize(prev: list[int], new: list[int]) -> list[int]:
    """Greedy nearest-voice mapping. Bass voice (lowest of `new`) stays put;
    upper voices are octave-shifted to the closest version of one of the
    remaining new notes."""
    if not new:
        return new
    bass = min(new)
    rest_new = [n for n in new if n != bass] + [n for n in new if n == bass][1:]
    rest_prev = sorted(prev)[1:] if len(prev) > 1 else []
    out = [bass]
    available = list(rest_new)
    for prev_note in rest_prev:
        if not available:
            break
        # Shift each candidate to the nearest octave of prev_note, then pick
        # the candidate with the smallest residual distance.
        best = None
        best_dist = 10**9
        for cand in available:
            shifted = cand
            while shifted < prev_note - 6:
                shifted += 12
            while shifted > prev_note + 6:
                shifted -= 12
            d = abs(shifted - prev_note)
            if d < best_dist:
                best = (cand, shifted)
                best_dist = d
        if best is None:
            break
        chosen_orig, chosen_shifted = best
        out.append(chosen_shifted)
        available.remove(chosen_orig)
    # Append any leftover new notes in their original octave.
    out.extend(available)
    return out


def _spread_clusters(notes: list[int]) -> list[int]:
    """Move any note that's a minor 2nd from another voice up by an octave
    until no two voices are adjacent semitones — but if shifting up would
    exceed MIDI 120, shift the lower voice DOWN by an octave instead."""
    if len(notes) < 2:
        return notes
    out = sorted(notes)
    changed = True
    iterations = 0
    while changed and iterations < 8:
        changed = False
        iterations += 1
        for i in range(len(out) - 1):
            if out[i + 1] - out[i] == 1:
                if out[i + 1] + 12 <= 120:
                    out[i + 1] += 12
                elif out[i] - 12 >= 12:
                    out[i] -= 12
                else:
                    # Both directions out of range — accept the cluster.
                    continue
                out.sort()
                changed = True
                break
    return out


def add_drum(
    ctx: RenderContext,
    kit: str,
    drum_name: str,
    bar: float,
    beat: float,
    vel: float,
    *,
    dur_beats: float = 0.30,
    humanize_ms: float = 0.0,
) -> None:
    if drum_name not in DRUMS:
        raise ValueError(
            f"unknown drum {drum_name!r} on kit {kit!r}. "
            f"Valid drums: {', '.join(sorted(DRUMS))}"
        )
    pitch = DRUMS[drum_name]
    add_note(
        ctx,
        kit,
        pitch,
        bar,
        beat,
        dur_beats,
        vel,
        articulation="normal",
        humanize_ms=humanize_ms,
        gate=1.0,
    )


def chord_for_bar(section: dict[str, Any], local_bar: int) -> str:
    harmony = section.get("harmony") or ["C"]
    return harmony[local_bar % len(harmony)]


def root_for_chord(chord: str, octave: int = 2) -> int:
    root, _intervals, slash = chord_intervals(chord)
    bass = slash or root
    bass = re.match(r"^([A-G](?:#|b)?)", bass).group(1)  # type: ignore[union-attr]
    return note_to_midi(f"{bass}{octave}")


def transform_motif(
    notes: list[int], transform: str | dict[str, Any] | None, pivot: int | None = None
) -> list[int]:
    out = list(notes)
    if not transform:
        return out
    if isinstance(transform, dict):
        kind = transform.get("kind")
    else:
        kind = transform
    if kind == "retrograde":
        out = list(reversed(out))
    elif kind == "invert":
        p = pivot if pivot is not None else out[0]
        out = [p - (n - p) for n in out]
    elif kind == "transpose":
        shift = int(transform.get("semitones", 0)) if isinstance(transform, dict) else 0
        out = [n + shift for n in out]
    elif kind == "up_octave":
        out = [n + 12 for n in out]
    elif kind == "down_octave":
        out = [n - 12 for n in out]
    return out


def motif_notes(
    ctx: RenderContext,
    motif_id: str,
    root: str | int | None = None,
    transform: Any = None,
    transpose: int = 0,
) -> tuple[list[int], list[float], list[float]]:
    motif = ctx.motifs[motif_id]
    if "notes" in motif:
        notes = [
            note_to_midi(n) if isinstance(n, str) else int(n) for n in motif["notes"]
        ]
        if root is not None and isinstance(root, str):
            base = note_to_midi(root)
            motif_base = note_to_midi(motif.get("root", "C4"))
            notes = [base + (n - motif_base) for n in notes]
    else:
        base = note_to_midi(root if isinstance(root, str) else motif.get("root", "C4"))
        notes = [base + int(x) for x in motif.get("intervals", [0])]
    notes = [n + transpose for n in notes]
    if transform:
        if isinstance(transform, list):
            for tr in transform:
                notes = transform_motif(notes, tr)
        else:
            notes = transform_motif(notes, transform)
    rhythm = [float(x) for x in motif.get("rhythm", [1.0] * len(notes))]
    velocities = [float(x) for x in motif.get("velocities", [1.0] * len(notes))]
    return notes, rhythm, velocities


def apply_automation(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    for auto in layer.get("automation", []):
        inst_names = (
            resolve_instruments(ctx, auto)
            if any(k in auto for k in ("instrument", "instruments", "group"))
            else resolve_instruments(ctx, layer)
        )
        cc = auto.get("cc", "expression")
        cc_num = CC_NUMBERS.get(
            cc, int(cc) if isinstance(cc, int) or str(cc).isdigit() else 11
        )
        start_bar = section["start_bar"] + float(auto.get("start_bar", 0.0))
        dur_bars = float(auto.get("bars", section["bars"]))
        start_val = float(auto.get("from", 80))
        end_val = float(auto.get("to", 110))
        curve = auto.get("curve", "linear")
        # `lfo` is a periodic sine sweep useful for vibrato (modulation CC) or
        # tremolo (volume CC). `from`/`to` are the troughs/peaks; `cycles` is
        # the number of full sine periods across the automation window. We
        # auto-pick a generous default sample count for sine so the curve is
        # smooth — 32 samples per cycle is plenty for typical vibrato rates.
        if curve == "lfo":
            cycles = float(auto.get("cycles", 4.0))
            points = int(auto.get("points", max(32, int(cycles * 32))))
        else:
            points = int(auto.get("points", 12))
        for inst_name in inst_names:
            inst = ctx.instruments[inst_name]
            for i in range(points):
                a = i / max(1, points - 1)
                if curve == "smooth":
                    a2 = a * a * (3 - 2 * a)
                    val = round(start_val * (1 - a2) + end_val * a2)
                elif curve == "exp":
                    a2 = a * a
                    val = round(start_val * (1 - a2) + end_val * a2)
                elif curve == "lfo":
                    cycles = float(auto.get("cycles", 4.0))
                    center = (start_val + end_val) / 2.0
                    amp = (end_val - start_val) / 2.0
                    val = round(center + amp * math.sin(2.0 * math.pi * cycles * a))
                else:  # linear
                    val = round(start_val * (1 - a) + end_val * a)
                add_cc(inst, cc_num, val, ctx.bar_to_time(start_bar + dur_bars * a))


def _layer_human(layer: dict[str, Any], default_ms: float) -> dict[str, float]:
    """Pull humanize parameters from a layer with a per-call default."""
    return {
        "humanize_ms": float(layer.get("humanize_ms", default_ms)),
        "humanize_velocity_pct": float(layer.get("humanize_velocity_pct", 0.0)),
    }


def _layer_constraints(
    spec: dict[str, Any], layer: dict[str, Any]
) -> dict[str, Any] | None:
    """Merge the spec-level and layer-level `constraints` blocks."""
    spec_c = spec.get("constraints") or {}
    layer_c = layer.get("constraints") or {}
    merged = dict(spec_c)
    merged.update(layer_c)
    return merged or None


@profile
def render_layer_pad_chords(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    every = float(layer.get("every_bars", 1.0))
    dur = float(layer.get("duration_beats", ctx.beats_per_bar * every))
    octave = int(layer.get("octave", 4))
    velocity = float(layer.get("velocity", 60)) * float(section.get("intensity", 1.0))
    articulation = layer.get("articulation", "pad")
    voicing = layer.get("voicing", "open")
    hk = _layer_human(layer, 8.0)
    constraints = _layer_constraints(ctx.spec, layer)
    for local in range(0, int(section["bars"]), max(1, int(every))):
        chord = chord_for_bar(section, local)
        for inst in insts:
            add_chord(
                ctx,
                inst,
                chord,
                section["start_bar"] + local,
                0.0,
                dur,
                velocity,
                octave=octave,
                articulation=articulation,
                voicing=voicing,
                constraints=constraints,
                **hk,
            )


@profile
def render_layer_arpeggio(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    pattern = [int(x) for x in layer.get("pattern", [0, 2, 1, 2])]
    step = float(layer.get("step", 0.5))
    dur = float(layer.get("duration_beats", step))
    octave = int(layer.get("octave", 4))
    velocity = float(layer.get("velocity", 64))
    density = float(layer.get("density", section.get("density", 1.0)))
    articulation = layer.get("articulation", "staccato")
    inst_velocity_offsets = layer.get("instrument_velocity_offsets", {}) or {}
    inst_octave_offsets = layer.get("instrument_octave_offsets", {}) or {}
    hk = _layer_human(layer, 4.0)
    for local in range(int(section["bars"])):
        if "every" in layer and local % int(layer["every"]) != int(
            layer.get("offset", 0)
        ):
            continue
        tones = chord_pitches(
            chord_for_bar(section, local),
            octave=octave,
            voicing=layer.get("voicing", "closed"),
        )
        count = int(ctx.beats_per_bar / step)
        for i in range(count):
            if ctx.rng.random() > density:
                continue
            base_pitch = tones[pattern[i % len(pattern)] % len(tones)]
            for inst in insts:
                p = base_pitch + 12 * int(inst_octave_offsets.get(inst, 0))
                v = velocity + float(inst_velocity_offsets.get(inst, 0.0))
                add_note(
                    ctx,
                    inst,
                    p,
                    section["start_bar"] + local,
                    i * step,
                    dur,
                    v * float(section.get("intensity", 1.0)),
                    articulation=articulation,
                    **hk,
                )


@profile
def render_layer_ostinato(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    intervals = [int(x) for x in layer.get("intervals", [0, 7, 12, 7])]
    rhythm = [float(x) for x in layer.get("rhythm", [0.5] * len(intervals))]
    root_octave = int(layer.get("octave", 3))
    velocity = float(layer.get("velocity", 60))
    articulation = layer.get("articulation", "spiccato")
    bars = int(section["bars"])
    hk = _layer_human(layer, 4.0)
    for local in range(bars):
        root = root_for_chord(chord_for_bar(section, local), root_octave)
        beat = 0.0
        idx = 0
        while beat < ctx.beats_per_bar - 1e-6:
            dur = rhythm[idx % len(rhythm)]
            p = root + intervals[idx % len(intervals)]
            for inst in insts:
                add_note(
                    ctx,
                    inst,
                    p,
                    section["start_bar"] + local,
                    beat,
                    dur,
                    velocity * float(section.get("intensity", 1.0)),
                    articulation=articulation,
                    **hk,
                )
            beat += dur
            idx += 1


@profile
def render_layer_bassline(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    inst = resolve_instruments(ctx, layer)[0]
    pattern = layer.get(
        "pattern", [[0, 0.0, 0.75], [7, 1.5, 0.5], [12, 2.5, 0.5], [7, 3.25, 0.4]]
    )
    octave = int(layer.get("octave", 2))
    velocity = float(layer.get("velocity", 74))
    articulation = layer.get("articulation", "marcato")
    hk = _layer_human(layer, 5.0)
    for local in range(int(section["bars"])):
        root = root_for_chord(chord_for_bar(section, local), octave)
        for item in pattern:
            interval, beat, dur = int(item[0]), float(item[1]), float(item[2])
            add_note(
                ctx,
                inst,
                root + interval,
                section["start_bar"] + local,
                beat,
                dur,
                velocity * float(section.get("intensity", 1.0)),
                articulation=articulation,
                **hk,
            )


@profile
def render_layer_motif(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    roots = layer.get("roots") or [layer.get("root", None)]
    starts = layer.get("starts") or [[0, 0.0]]
    repeats = int(layer.get("repeats", 1))
    every_bars = float(layer.get("every_bars", 2.0))
    velocity = float(layer.get("velocity", 78))
    articulation = layer.get("articulation", "normal")
    gate_value = layer.get("gate")
    gate = float(gate_value) if gate_value is not None else None
    transpose = int(layer.get("transpose", 0))
    transform = layer.get("transform")
    inst_velocity_offsets = layer.get("instrument_velocity_offsets", {}) or {}
    inst_octave_offsets = layer.get("instrument_octave_offsets", {}) or {}
    inst_pitch_scoop = layer.get("instrument_pitch_scoop_cents", {}) or {}
    inst_pitch_bend_curves = layer.get("instrument_pitch_bend_curves", {}) or {}
    note_velocity_pattern = layer.get("note_velocity_pattern", None)
    hk = _layer_human(layer, 6.0)
    for rep in range(repeats):
        root = roots[rep % len(roots)]
        for start in starts:
            local_bar, start_beat = float(start[0]) + rep * every_bars, float(start[1])
            if local_bar >= section["bars"]:
                continue
            notes, rhythm, velocities = motif_notes(
                ctx, layer["motif"], root=root, transform=transform, transpose=transpose
            )
            beat = start_beat
            for i, p0 in enumerate(notes):
                dur = rhythm[i % len(rhythm)] * float(layer.get("rhythm_scale", 1.0))
                vel_scale = velocities[i % len(velocities)]
                if note_velocity_pattern:
                    vel_scale *= float(
                        note_velocity_pattern[i % len(note_velocity_pattern)]
                    )
                for j, inst in enumerate(insts):
                    p = p0 + 12 * int(inst_octave_offsets.get(inst, 0))
                    v = velocity + float(inst_velocity_offsets.get(inst, -8 * j))
                    scoop = float(
                        inst_pitch_scoop.get(inst, layer.get("pitch_scoop_cents", 0.0))
                    )
                    bend_curve = inst_pitch_bend_curves.get(
                        inst, layer.get("pitch_bend_curve")
                    )
                    bend_curve_pairs = (
                        [(float(x[0]), float(x[1])) for x in bend_curve]
                        if bend_curve
                        else None
                    )
                    add_note(
                        ctx,
                        inst,
                        p,
                        section["start_bar"] + local_bar,
                        beat,
                        dur,
                        v * vel_scale * float(section.get("intensity", 1.0)),
                        articulation=articulation,
                        gate=gate,
                        pitch_scoop_cents=scoop,
                        pitch_bend_curve=bend_curve_pairs,
                        **hk,
                    )
                beat += dur


@profile
def render_layer_chord_hits(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    hits = layer.get("hits", [[0, 0.0], [4, 0.0], [8, 0.0], [12, 0.0]])
    velocity = float(layer.get("velocity", 90))
    octave = int(layer.get("octave", 3))
    inst_octave_offsets = {
        str(k): int(v) for k, v in (layer.get("instrument_octave_offsets") or {}).items()
    }
    inst_velocity_offsets = {
        str(k): float(v) for k, v in (layer.get("instrument_velocity_offsets") or {}).items()
    }
    hk = _layer_human(layer, 6.0)
    constraints = _layer_constraints(ctx.spec, layer)
    for local, beat in hits:
        if float(local) >= section["bars"]:
            continue
        chord = chord_for_bar(section, int(local))
        for inst in insts:
            add_chord(
                ctx,
                inst,
                chord,
                section["start_bar"] + float(local),
                float(beat),
                float(layer.get("duration_beats", 0.75)),
                (velocity + float(inst_velocity_offsets.get(inst, 0.0))) * float(section.get("intensity", 1.0)),
                octave=octave + int(inst_octave_offsets.get(inst, 0)),
                articulation=layer.get("articulation", "marcato"),
                voicing=layer.get("voicing", "closed"),
                constraints=constraints,
                **hk,
            )


def render_layer_drums(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    kit = resolve_instruments(ctx, layer)[0]
    events = layer.get("events", [])
    if not events:
        return
    for local in range(int(section["bars"])):
        for ev in events:
            if "bars" in ev and local not in set(int(b) for b in ev["bars"]):
                continue
            if "every" in ev and local % int(ev["every"]) != int(ev.get("offset", 0)):
                continue
            beats = ev.get("beats", [ev.get("beat", 0.0)])
            for beat in beats:
                if ctx.rng.random() > float(ev.get("probability", 1.0)):
                    continue
                add_drum(
                    ctx,
                    kit,
                    ev["drum"],
                    section["start_bar"] + local,
                    float(beat),
                    float(ev.get("velocity", layer.get("velocity", 70)))
                    * float(section.get("intensity", 1.0)),
                    dur_beats=float(ev.get("duration_beats", 0.1)),
                    humanize_ms=float(
                        ev.get("humanize_ms", layer.get("humanize_ms", 2.0))
                    ),
                )


def render_layer_texture(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    scale = [int(x) for x in layer.get("scale", [0, 2, 3, 5, 7, 10, 12])]
    root = note_to_midi(layer.get("root", "D5"))
    count_per_bar = float(layer.get("events_per_bar", 1.0))
    velocity = float(layer.get("velocity", 38))
    hk = _layer_human(layer, 2.0)
    for local in range(int(section["bars"])):
        count = int(math.floor(count_per_bar)) + (
            1 if ctx.rng.random() < count_per_bar % 1 else 0
        )
        for _ in range(count):
            beat = float(ctx.rng.uniform(0.0, ctx.beats_per_bar))
            p = root + int(ctx.rng.choice(scale)) + 12 * int(ctx.rng.integers(-1, 2))
            inst = str(ctx.rng.choice(insts))
            add_note(
                ctx,
                inst,
                p,
                section["start_bar"] + local,
                beat,
                float(layer.get("duration_beats", 0.25)),
                velocity * float(section.get("intensity", 1.0)),
                articulation=layer.get("articulation", "bell"),
                **hk,
            )


def render_layer_pedal(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    pitch = layer.get("note")
    if pitch is None:
        pitch = root_for_chord(chord_for_bar(section, 0), int(layer.get("octave", 2)))
    velocity = float(layer.get("velocity", 45)) * float(section.get("intensity", 1.0))
    hk = _layer_human(layer, 8.0)
    for inst in insts:
        add_note(
            ctx,
            inst,
            pitch,
            section["start_bar"],
            0.0,
            section["bars"] * ctx.beats_per_bar,
            velocity,
            articulation=layer.get("articulation", "pad"),
            **hk,
        )


def render_layer_root_hits(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    hits = layer.get("hits", [[0, 0.0, 0, 0.75]])
    velocity = float(layer.get("velocity", 76))
    octave = int(layer.get("octave", 2))
    articulation = layer.get("articulation", "marcato")
    hk = _layer_human(layer, 2.0)
    for item in hits:
        local = float(item[0])
        beat = float(item[1])
        interval = int(item[2]) if len(item) > 2 else 0
        dur = (
            float(item[3])
            if len(item) > 3
            else float(layer.get("duration_beats", 0.75))
        )
        if local >= section["bars"]:
            continue
        root = root_for_chord(chord_for_bar(section, int(local)), octave)
        for inst in insts:
            add_note(
                ctx,
                inst,
                root + interval,
                section["start_bar"] + local,
                beat,
                dur,
                velocity * float(section.get("intensity", 1.0)),
                articulation=articulation,
                **hk,
            )


def render_layer_automation(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    # Note-free layer used to express section-wide CC ramps in YAML.
    apply_automation(ctx, section, layer)


@profile
def render_layer(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    kind = layer["kind"]
    if kind == "pad_chords":
        render_layer_pad_chords(ctx, section, layer)
    elif kind == "arpeggio":
        render_layer_arpeggio(ctx, section, layer)
    elif kind == "ostinato":
        render_layer_ostinato(ctx, section, layer)
    elif kind == "bassline":
        render_layer_bassline(ctx, section, layer)
    elif kind == "motif":
        render_layer_motif(ctx, section, layer)
    elif kind == "chord_hits":
        render_layer_chord_hits(ctx, section, layer)
    elif kind == "drums":
        render_layer_drums(ctx, section, layer)
    elif kind == "texture":
        render_layer_texture(ctx, section, layer)
    elif kind == "pedal":
        render_layer_pedal(ctx, section, layer)
    elif kind == "root_hits":
        render_layer_root_hits(ctx, section, layer)
    elif kind == "automation":
        render_layer_automation(ctx, section, layer)
        return
    else:
        raise KeyError(f"unknown layer kind {kind!r}")
    apply_automation(ctx, section, layer)


def merged_layers(
    spec: dict[str, Any], section: dict[str, Any]
) -> list[dict[str, Any]]:
    templates = spec.get("layer_templates", {})
    out: list[dict[str, Any]] = []
    for item in section.get("layers", []):
        if isinstance(item, str):
            layer = copy.deepcopy(templates[item])
            layer.setdefault("_source_layer", item)
        elif "template" in item:
            layer = copy.deepcopy(templates[item["template"]])
            layer.update({k: v for k, v in item.items() if k != "template"})
            layer.setdefault("_source_layer", str(item["template"]))
        else:
            layer = copy.deepcopy(item)
            layer.setdefault("_source_layer", str(layer.get("id", layer.get("kind", "inline"))))
        out.append(layer)
    return out


@profile
def build_score(
    spec: dict[str, Any],
) -> tuple[pretty_midi.PrettyMIDI, dict[str, str], list[dict[str, Any]]]:
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    ctx = RenderContext(
        spec=spec,
        sample_rate=int(spec.get("render", {}).get("sample_rate", 48000)),
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        rng=np.random.default_rng(int(spec.get("seed", 1))),
        pm=pm,
        instruments={},
        groups={},
        section_starts={},
        motifs={m["id"]: m for m in spec.get("motifs", [])},
    )
    for inst_spec in spec.get("instruments", []):
        add_instrument(ctx, inst_spec)
    starts = section_starts(spec["sections"])
    ctx.section_starts = starts
    section_meta = section_metadata_from_spec(spec)
    for section in spec["sections"]:
        for layer in merged_layers(spec, section):
            ctx.active_section_id = str(section.get("id", ""))
            ctx.active_layer_id = str(layer.get("_source_layer", layer.get("kind", "layer")))
            ctx.active_layer_kind = str(layer.get("kind", ""))
            render_layer(ctx, section, layer)
    pm._ambition_note_events = list(ctx.note_events)  # type: ignore[attr-defined]
    return pm, ctx.groups, section_meta


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


def _coerce_stereo(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 1:
        audio = np.column_stack([audio, audio])
    if audio.shape[1] > 2:
        audio = audio[:, :2]
    return audio.astype(np.float32, copy=False)


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
def render_pretty_midi(
    pm: pretty_midi.PrettyMIDI, soundfont: str, sample_rate: int
) -> np.ndarray:
    """Render via pyFluidSynth, with the synth's built-in reverb and chorus
    disabled so they don't stack on top of the YAML postprocess chain.

    pretty_midi.PrettyMIDI.fluidsynth() leaves both effects on, which adds a
    hissy diffuse wash to every stem. We re-implement the same per-instrument
    rendering loop so we can flip those settings off, and so we can render a
    clean tail past the last note (the stock implementation cuts off at the
    last event, which clips reverb-bus tails when stems are sliced later).
    """
    try:
        import fluidsynth  # type: ignore
    except ImportError as e:
        raise ImportError(
            "pretty-midi backend needs pyfluidsynth. Install it with "
            "`uv pip install pyfluidsynth`."
        ) from e

    if not pm.instruments:
        return np.zeros((1, 2), dtype=np.float32)

    fs_float = float(sample_rate)
    waveforms: list[np.ndarray] = []
    for inst in pm.instruments:
        if not inst.notes:
            continue
        # gain=1.6: at MIDI vel 100, vol/expr 100, the SoundFont samples come
        # out around -13 dB peak — comparable to per-stem fallback-backend levels
        # and well within headroom for stem summing. fluidsynth's stock default
        # is 0.2, which makes everything 18 dB quieter than authored.
        fl = fluidsynth.Synth(samplerate=fs_float, gain=1.6)
        # Kill fluidsynth's internal effects buses; the YAML controls reverb
        # and we don't want a chorus pseudo-noise floor on every stem.
        try:
            fl.setting("synth.reverb.active", 0)
            fl.setting("synth.chorus.active", 0)
        except Exception:
            pass
        sfid = fl.sfload(soundfont)
        if inst.is_drum:
            channel = 9
            fl.program_select(channel, sfid, 128, 0)
        else:
            channel = 0
            fl.program_select(channel, sfid, 0, int(inst.program))

        events: list[tuple] = []
        for note in inst.notes:
            events.append(
                (float(note.start), 1, "on", int(note.pitch), int(note.velocity))
            )
            events.append((float(note.end), 0, "off", int(note.pitch), 0))
        for cc in inst.control_changes:
            events.append((float(cc.time), 0, "cc", int(cc.number), int(cc.value)))
        for pb in inst.pitch_bends:
            events.append((float(pb.time), 0, "pb", int(pb.pitch), 0))
        # Sort by time, with note-on AFTER note-off and CCs at the same time
        # so coincident-time events don't accidentally trigger a note before
        # the previous one ends.
        events.sort(key=lambda e: (e[0], e[1]))

        last_event_time = events[-1][0] if events else 0.0
        # Add a tail (~0.6 s) so any release / built-in envelope tails finish
        # before the per-stem post-process slicing cuts in.
        total_samples = int(math.ceil((last_event_time + 0.6) * fs_float))
        out = np.zeros(total_samples, dtype=np.float32)
        cursor = 0
        for ev in events:
            target = min(int(ev[0] * fs_float), total_samples)
            n = target - cursor
            if n > 0:
                buf = fl.get_samples(n)
                # pyFluidSynth returns interleaved L,R,L,R,...; mix to mono.
                mono = (
                    buf[0::2].astype(np.float32) + buf[1::2].astype(np.float32)
                ) * 0.5
                # Normalize the int16 range pyFluidSynth uses by default.
                mono /= 32768.0
                out[cursor : cursor + len(mono)] = mono[:n]
                cursor += n
            kind = ev[2]
            if kind == "on":
                fl.noteon(channel, ev[3], ev[4])
            elif kind == "off":
                fl.noteoff(channel, ev[3])
            elif kind == "cc":
                fl.cc(channel, ev[3], ev[4])
            elif kind == "pb":
                fl.pitch_bend(channel, ev[3])
        if cursor < total_samples:
            buf = fl.get_samples(total_samples - cursor)
            mono = (buf[0::2].astype(np.float32) + buf[1::2].astype(np.float32)) * 0.5
            mono /= 32768.0
            out[cursor : cursor + len(mono)] = mono[: total_samples - cursor]
        fl.delete()
        waveforms.append(out)

    if not waveforms:
        return np.zeros((1, 2), dtype=np.float32)

    max_len = max(len(w) for w in waveforms)
    mixed = np.zeros(max_len, dtype=np.float32)
    for w in waveforms:
        mixed[: len(w)] += w
    return _coerce_stereo(mixed)


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
    return _coerce_stereo(audio)


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
        from . import (
            fallback_backend,
        )  # imported lazily so its synth code stays out of YAML-only paths

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
        from . import fallback_backend

        return fallback_backend.render_fallback(
            pm, sample_rate, minimum_duration=minimum_duration
        )
    raise ValueError(f"unknown backend {backend}")


def _one_pole_alpha(hz: float, sample_rate: int) -> float:
    hz = float(clamp(hz, 1.0, sample_rate * 0.49))
    return float(1.0 - math.exp(-2.0 * math.pi * hz / sample_rate))


def lowpass(
    audio: np.ndarray, sample_rate: int, hz: float = 12_000.0, order: int = 1
) -> np.ndarray:
    if hz <= 0 or hz >= sample_rate * 0.49:
        return audio.astype(np.float32, copy=False)
    audio = _coerce_stereo(audio)
    alpha = _one_pole_alpha(hz, sample_rate)
    out = audio.astype(np.float32, copy=True)
    # Cascade cheap one-pole sections for steeper response when requested.
    for _ in range(max(1, int(order))):
        out[:, 0] = _lowpass_mono(out[:, 0], alpha)
        out[:, 1] = _lowpass_mono(out[:, 1], alpha)
    return out.astype(np.float32, copy=False)


def highpass(audio: np.ndarray, sample_rate: int, hz: float = 35.0) -> np.ndarray:
    if hz <= 0:
        return audio.astype(np.float32, copy=False)
    audio = _coerce_stereo(audio)
    return (audio - lowpass(audio, sample_rate, hz, order=1)).astype(np.float32)


def high_shelf(
    audio: np.ndarray, sample_rate: int, *, hz: float = 4_500.0, db: float = -2.0
) -> np.ndarray:
    """Simple high-shelf using a high-passed side band."""
    if abs(db) < 1e-6:
        return audio.astype(np.float32, copy=False)
    hi = highpass(audio, sample_rate, hz)
    gain = 10 ** (db / 20.0)
    return (audio + hi * (gain - 1.0)).astype(np.float32)


def band_gain(
    audio: np.ndarray, sample_rate: int, *, low_hz: float, high_hz: float, db: float
) -> np.ndarray:
    if abs(db) < 1e-6:
        return audio.astype(np.float32, copy=False)
    audio = _coerce_stereo(audio)
    low_hz = max(20.0, float(low_hz))
    high_hz = min(float(high_hz), sample_rate * 0.49)
    if high_hz <= low_hz:
        return audio.astype(np.float32, copy=False)
    band = lowpass(audio, sample_rate, high_hz, order=1) - lowpass(
        audio, sample_rate, low_hz, order=1
    )
    gain = 10 ** (db / 20.0)
    return (audio + band * (gain - 1.0)).astype(np.float32)


def _comb_filter(
    signal_in: np.ndarray, delay: int, feedback: float, damping: float
) -> np.ndarray:
    """Lowpass-feedback comb (Freeverb-style). Delay in samples; feedback is
    the per-loop multiplier (RT60-controlling); damping applies a one-pole
    lowpass inside the feedback path so the reverb tail darkens over time.
    """
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


def _allpass_filter(
    signal_in: np.ndarray, delay: int, feedback: float = 0.5
) -> np.ndarray:
    """Schroeder-style allpass for diffusion. No spectral coloration, just
    smears the impulse response."""
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

    y = _coerce_stereo(audio)
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
    audio = _coerce_stereo(audio)
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
        # Soft-knee region: quadratic interpolation
        x = (over[soft] + knee / 2) / knee
        gr_db[soft] = -(x * x * (over[soft] / ratio + knee / 4 - over[soft]))
    else:
        gr_db = np.where(over > 0, -(over - over / ratio), 0.0)

    # Attack/release smoothing of the gain reduction envelope (in dB).
    a = math.exp(-1.0 / max(float(attack_ms) * 1e-3 * sr, 1.0))
    r = math.exp(-1.0 / max(float(release_ms) * 1e-3 * sr, 1.0))
    env = np.zeros_like(gr_db)
    state = 0.0
    for i in range(len(gr_db)):
        target = gr_db[i]
        if target < state:  # attack: gain reduction is increasing (more negative)
            state = a * state + (1.0 - a) * target
        else:  # release: gain reduction is decreasing
            state = r * state + (1.0 - r) * target
        env[i] = state

    # Apply gain reduction + makeup to both channels.
    gain = np.power(10.0, (env + float(makeup_db)) / 20.0).astype(np.float32)
    out = audio * gain[:, None]
    return out.astype(np.float32, copy=False)


def stereo_widen(audio: np.ndarray, amount: float = 0.12) -> np.ndarray:
    if amount <= 0:
        return audio.astype(np.float32, copy=False)
    mid = (audio[:, 0] + audio[:, 1]) * 0.5
    side = (audio[:, 0] - audio[:, 1]) * 0.5 * (1.0 + amount)
    return np.column_stack([mid + side, mid - side]).astype(np.float32)


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
    audio: np.ndarray, sample_rate: int, settings: dict[str, Any]
) -> np.ndarray:
    audio = _coerce_stereo(audio)
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
    audio = simple_reverb(
        audio,
        sample_rate,
        wet=float(settings.get("reverb_wet", 0.18)),
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
    return soft_limit(
        audio,
        float(settings.get("target_peak_db", -1.0)),
        drive=float(settings.get("limiter_drive", 1.08)),
        normalize=bool(settings.get("normalize", True)),
    )


def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, sample_rate, subtype="PCM_16")


def format_ogg_timestamp(seconds: float) -> str:
    """Return an OGM/Vorbis chapter timestamp like ``HH:MM:SS.mmm``."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds - hours * 3600 - minutes * 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def ogg_metadata_args(metadata: dict[str, object] | None) -> list[str]:
    args: list[str] = []
    if not metadata:
        return args
    for key, value in metadata.items():
        if value is None:
            continue
        key_s = str(key).strip()
        if not key_s:
            continue
        args.extend(["-metadata", f"{key_s}={value}"])
    return args


def write_metadata_sidecar(ogg_path: Path, metadata: dict[str, object] | None) -> Path | None:
    """Write a small sidecar recording the metadata we attempted to embed.

    OGG/Vorbis chapter display varies by player.  The audio file gets Vorbis
    comments when ffmpeg supports them; this sidecar makes the render report
    auditable even when a player hides those comments.
    """
    if not metadata:
        return None
    try:
        sidecar = ogg_path.with_name(ogg_path.name + ".metadata.json")
        sidecar.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf8")
        return sidecar
    except Exception:
        return None


def timeline_markers_from_spec(
    spec: dict[str, Any],
    sections: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return section/form markers suitable for OGG chapter comments.

    The default markers are section starts.  Cues may also define
    ``render.metadata_markers`` / ``render.markers`` entries with ``bar`` or
    ``seconds`` and an ``id``/``label``.  This lets long one-section pieces
    such as Emmy Extended expose A/B/return form markers even though the game
    still treats them as one loop component.
    """
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    seconds_per_bar = beats_per_bar * 60.0 / bpm
    markers: list[dict[str, Any]] = []
    for section in sections or []:
        sid = str(section.get("id", f"section_{len(markers)+1}"))
        label = str(section.get("label", sid))
        markers.append({
            "id": sid,
            "label": label,
            "start_seconds": float(section.get("start_seconds", 0.0) or 0.0),
            "kind": str(section.get("kind", "section")),
        })
    render_cfg = spec.get("render", {}) or {}
    explicit = render_cfg.get("metadata_markers", render_cfg.get("markers", []))
    if isinstance(explicit, list):
        for idx, item in enumerate(explicit, start=1):
            if not isinstance(item, dict):
                continue
            if "seconds" in item:
                start_s = float(item.get("seconds") or 0.0)
            elif "time_seconds" in item:
                start_s = float(item.get("time_seconds") or 0.0)
            elif "bar" in item:
                # Bar values are 1-based for human readability in YAML.
                start_s = max(0.0, (float(item.get("bar") or 1.0) - 1.0) * seconds_per_bar)
            elif "start_bar" in item:
                # start_bar remains 0-based for code-generated markers.
                start_s = max(0.0, float(item.get("start_bar") or 0.0) * seconds_per_bar)
            else:
                continue
            marker_id = str(item.get("id", item.get("name", f"marker_{idx}")))
            label = str(item.get("label", marker_id))
            markers.append({
                "id": marker_id,
                "label": label,
                "start_seconds": start_s,
                "kind": str(item.get("kind", "form_marker")),
            })
    # De-duplicate exact same id/time pairs and sort by time.
    seen: set[tuple[str, float]] = set()
    deduped: list[dict[str, Any]] = []
    for marker in sorted(markers, key=lambda m: (float(m.get("start_seconds", 0.0)), str(m.get("id", "")))):
        key = (str(marker.get("id", "")), round(float(marker.get("start_seconds", 0.0)), 3))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(marker)
    return deduped


def section_chapter_metadata(
    *,
    cue_id: str,
    title: str | None = None,
    sections: list[dict[str, Any]] | None = None,
    section_id: str | None = None,
    section_start_s: float | None = None,
    section_end_s: float | None = None,
) -> dict[str, object]:
    """Build Vorbis comments that VLC and tag tools can use as breadcrumbs.

    OGG/Vorbis does not have one universal chapter standard, but VLC and
    several tag readers understand the common ``CHAPTER001`` /
    ``CHAPTER001NAME`` Vorbis-comment convention.  We also write plain
    ``CUE_ID``/``SECTION_ID`` fields so the runtime asset can be traced even
    when a player ignores chapters.
    """
    meta: dict[str, object] = {
        "TITLE": title or cue_id,
        "ARTIST": "Ambition MusicIR",
        "ALBUM": "Ambition generated music",
        "CUE_ID": cue_id,
    }
    if section_id is not None:
        meta["SECTION_ID"] = section_id
    if section_start_s is not None:
        meta["SECTION_START"] = format_ogg_timestamp(float(section_start_s))
    if section_end_s is not None:
        meta["SECTION_END"] = format_ogg_timestamp(float(section_end_s))
    for idx, section in enumerate(sections or [], start=1):
        sid = str(section.get("id", f"section_{idx}"))
        label = str(section.get("label", sid))
        kind = str(section.get("kind", "section"))
        start_s = float(section.get("start_seconds", 0.0) or 0.0)
        meta[f"CHAPTER{idx:03d}"] = format_ogg_timestamp(start_s)
        meta[f"CHAPTER{idx:03d}NAME"] = label if label != sid else sid
        meta[f"CHAPTER{idx:03d}ID"] = sid
        meta[f"CHAPTER{idx:03d}KIND"] = kind
    meta["AMBITION_MARKER_COUNT"] = len(sections or [])
    return meta


def encode_ogg(wav_path: Path, ogg_path: Path, quality: float = 5.0, metadata: dict[str, object] | None = None) -> None:
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        raise FileNotFoundError("ffmpeg is required to encode OGG Vorbis")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(wav_path),
        "-map_metadata",
        "-1",
        *ogg_metadata_args(metadata),
        "-c:a",
        "libvorbis",
        "-q:a",
        str(quality),
        str(ogg_path),
    ]
    subprocess.run(cmd, check=True)
    write_metadata_sidecar(ogg_path, metadata)


@profile
def write_ogg_from_audio(
    audio: np.ndarray,
    sample_rate: int,
    ogg_path: Path,
    *,
    quality: float = 5.0,
    keep_wav: bool = False,
    metadata: dict[str, object] | None = None,
) -> Path:
    """Write OGG Vorbis, preferring ffmpeg pipe encoding for reliability/speed."""
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.nan_to_num(
        np.clip(_coerce_stereo(audio), -1.0, 1.0), nan=0.0, posinf=0.0, neginf=0.0
    ).astype(np.float32, copy=False)
    if not shutil.which("ffmpeg"):
        # Fallback for minimal environments. Some libsndfile builds are slow on
        # many OGG writes, but this keeps the renderer usable if ffmpeg is absent.
        sf.write(ogg_path, pcm, sample_rate, format="OGG", subtype="VORBIS")
        write_metadata_sidecar(ogg_path, metadata)
        if keep_wav:
            write_wav(ogg_path.with_suffix(".wav"), audio, sample_rate)
        return ogg_path
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        "2",
        "-i",
        "pipe:0",
        "-map_metadata",
        "-1",
        *ogg_metadata_args(metadata),
        "-c:a",
        "libvorbis",
        "-q:a",
        str(quality),
        str(ogg_path),
    ]
    proc = subprocess.run(
        cmd,
        input=pcm.tobytes(order="C"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf8", errors="replace"))
    if keep_wav:
        write_wav(ogg_path.with_suffix(".wav"), audio, sample_rate)
    return ogg_path


def copy_with_instruments(
    pm: pretty_midi.PrettyMIDI, instruments: list[pretty_midi.Instrument], bpm: float
) -> pretty_midi.PrettyMIDI:
    new_pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    new_pm.instruments = [copy.deepcopy(inst) for inst in instruments]
    return new_pm


def ensure_audio_length(audio: np.ndarray, target_samples: int) -> np.ndarray:
    if len(audio) < target_samples:
        audio = np.pad(audio, ((0, target_samples - len(audio)), (0, 0)))
    elif len(audio) > target_samples:
        audio = audio[:target_samples]
    return audio.astype(np.float32, copy=False)


def slice_audio(
    audio: np.ndarray, sample_rate: int, start_seconds: float, end_seconds: float
) -> np.ndarray:
    a = max(0, int(round(start_seconds * sample_rate)))
    b = max(a, int(round(end_seconds * sample_rate)))
    return audio[a:b]


def section_metadata_from_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    seconds_per_beat = 60.0 / bpm
    cursor = 0
    out = []
    for section in spec["sections"]:
        bars = int(section["bars"])
        start_beat = cursor * beats_per_bar
        end_beat = (cursor + bars) * beats_per_bar
        out.append(
            {
                "id": section["id"],
                "label": section.get("label", section["id"]),
                "kind": section.get("kind", "section"),
                "start_bar": cursor,
                "bars": bars,
                "start_beat": start_beat,
                "end_beat": end_beat,
                "start_seconds": start_beat * seconds_per_beat,
                "end_seconds": end_beat * seconds_per_beat,
                "duration_seconds": (end_beat - start_beat) * seconds_per_beat,
                "loopable": bool(section.get("loopable", False)),
                "valid_exit_local_bars": section.get("valid_exit_local_bars", []),
            }
        )
        cursor += bars
    return out


@profile
def render_group_audio(
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    group: str,
    backend: str,
    soundfont: str,
    sample_rate: int,
    tempdir: Path,
    minimum_duration: float,
    bpm: float,
) -> np.ndarray:
    insts = [inst for inst in pm.instruments if groups.get(inst.name) == group]
    sub_pm = copy_with_instruments(pm, insts, bpm)
    midi_path = tempdir / f"group_{group}.mid"
    dry_wav = tempdir / f"group_{group}.dry.wav"
    # The built-in fallback renderer consumes PrettyMIDI objects directly. Avoid
    # serializing stem MIDI unless an external backend actually needs it; this
    # keeps adaptive section x stem export snappy and avoids rare pretty_midi
    # writer stalls on sparse/empty instrument groups.
    if backend != "fallback":
        sub_pm.write(str(midi_path))
    return render_synth_audio(
        sub_pm, backend, soundfont, sample_rate, midi_path, dry_wav, minimum_duration
    )


def build_manifest(
    spec: dict[str, Any],
    cue_hash: str,
    section_meta: list[dict[str, Any]],
    group_names: list[str],
    output_files: dict[str, Any],
    sample_rate: int,
) -> dict[str, Any]:
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    return {
        "schema": "ambition.adaptive_music_manifest.v2",
        "renderer_version": RENDERER_VERSION,
        "id": spec["id"],
        "title": spec.get("title", spec["id"]),
        "hash": cue_hash,
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "sample_rate": sample_rate,
        "stems": group_names,
        "sections": section_meta,
        "files": output_files,
        "playback": spec.get("playback", {}),
        "state_map": spec.get("state_map", {}),
        "notes": spec.get("notes", ""),
    }




SECTION_FULL_MASTERING_MODES = ("section_postprocess", "global_master_slices")


def adaptive_section_mastering_config(spec: dict[str, Any]) -> dict[str, Any]:
    render_cfg = spec.get("render", {}) or {}
    cfg = render_cfg.get("adaptive_section_mastering") or render_cfg.get("adaptive_sections") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    mode = str(cfg.get("mode", cfg.get("full_mix_mode", "section_postprocess")))
    if mode not in SECTION_FULL_MASTERING_MODES:
        raise ValueError(
            f"render.adaptive_section_mastering.mode must be one of {SECTION_FULL_MASTERING_MODES}, got {mode!r}"
        )
    return {
        "mode": mode,
        "ignore_section_postprocess_for_full_mix": bool(
            cfg.get("ignore_section_postprocess_for_full_mix", mode == "global_master_slices")
        ),
        "notes": str(cfg.get("notes", "")),
    }


def render_all(args: argparse.Namespace) -> dict[str, Any]:
    spec_path = Path(args.spec).resolve()
    spec = load_yaml(spec_path)
    render_cfg = spec.get("render", {})
    sample_rate = int(render_cfg.get("sample_rate", 48000))
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    output_root = Path(args.outdir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    soundfont = choose_soundfont(args.soundfont or render_cfg.get("soundfont"))
    backend = args.backend or render_cfg.get("backend", "auto")
    cue_hash = spec_hash(spec_path, soundfont, backend)
    quality = float(render_cfg.get("ogg_quality", 5.0))
    pm, groups, section_meta = build_score(spec)
    sanitize_same_pitch_overlaps(pm)
    total_seconds = (
        section_meta[-1]["end_seconds"] if section_meta else pm.get_end_time()
    )
    target_samples = int(math.ceil(total_seconds * sample_rate))
    group_names = sorted(set(groups.values()))
    output_files: dict[str, Any] = {"preview": {}, "adaptive": {}}

    with tempfile.TemporaryDirectory() as d:
        tempdir = Path(d)
        # Render stems first, apply stem/bus tone controls without normalizing
        # them upward, write adaptive stem pieces, and sum the exact processed
        # stems to build the full preview. This guarantees that bus EQ and stem
        # gains affect both adaptive playback and the full soundtrack preview.
        full_stem_sum = np.zeros((target_samples, 2), dtype=np.float32)
        stem_base_settings = copy.deepcopy(spec.get("stem_postprocess", {}))
        group_post = spec.get("group_postprocess", {}) or {}
        for group in group_names:
            if getattr(args, "verbose", False):
                print(f"[render] stem {group}", flush=True)
            group_raw = render_group_audio(
                pm,
                groups,
                group,
                backend,
                soundfont,
                sample_rate,
                tempdir,
                total_seconds,
                bpm,
            )
            group_raw = ensure_audio_length(group_raw, target_samples)
            group_settings = copy.deepcopy(stem_base_settings)
            group_settings.update(group_post.get(group, {}))
            # Stems should preserve authored relative gain. The default is no
            # upward normalization unless YAML explicitly asks for it.
            group_settings.setdefault("normalize", False)
            group_settings.setdefault("target_peak_db", -2.5)
            if getattr(args, "verbose", False):
                print(f"[post] stem {group} settings={group_settings}", flush=True)
            import time as _time

            _t0 = _time.time()
            group_audio = post_process(group_raw, sample_rate, group_settings)
            if getattr(args, "verbose", False):
                print(
                    f"[post-done] stem {group} elapsed={_time.time() - _t0:.2f}s shape={group_audio.shape}",
                    flush=True,
                )
            _t0 = _time.time()
            full_stem_sum += ensure_audio_length(group_audio, target_samples)
            if getattr(args, "verbose", False):
                print(
                    f"[sum-done] stem {group} elapsed={_time.time() - _t0:.2f}s",
                    flush=True,
                )
            for meta in section_meta:
                piece = slice_audio(
                    group_audio, sample_rate, meta["start_seconds"], meta["end_seconds"]
                )
                path = (
                    output_root
                    / "adaptive"
                    / meta["id"]
                    / f"{spec['id']}_{cue_hash}.{meta['id']}.{group}.ogg"
                )
                if getattr(args, "verbose", False):
                    print(f"[write] stem {group} section {meta['id']}", flush=True)
                _t0 = _time.time()
                write_ogg_from_audio(
                    piece, sample_rate, path, quality=quality, keep_wav=args.keep_wav
                )
                if getattr(args, "verbose", False):
                    print(
                        f"[write-done] stem {group} section {meta['id']} elapsed={_time.time() - _t0:.2f}s",
                        flush=True,
                    )
                output_files["adaptive"].setdefault(meta["id"], {})[group] = str(
                    path.relative_to(output_root)
                )
            del group_raw, group_audio
            gc.collect()

        if getattr(args, "verbose", False):
            print("[post] master from processed stems", flush=True)
        full_audio = post_process(
            full_stem_sum, sample_rate, spec.get("postprocess", {})
        )
        preview_path = (
            output_root
            / "preview"
            / f"{spec['id']}_{cue_hash}.full_soundtrack_preview.ogg"
        )
        if getattr(args, "verbose", False):
            print("[write] preview", flush=True)
        write_ogg_from_audio(
            full_audio,
            sample_rate,
            preview_path,
            quality=quality,
            keep_wav=args.keep_wav,
        )
        output_files["preview"]["full_soundtrack"] = str(
            preview_path.relative_to(output_root)
        )

        # Full section renders. Prefer global-master slices for adaptive full
        # sections when requested; legacy render_all has no section-local full
        # postprocess path, so both modes slice the mastered stem sum.
        section_mastering = adaptive_section_mastering_config(spec)
        ignored_section_postprocess = []
        if section_mastering["mode"] == "global_master_slices":
            sections_by_id = {s0.get("id"): s0 for s0 in spec.get("sections", [])}
            ignored_section_postprocess = [
                str(meta["id"])
                for meta in section_meta
                if isinstance(sections_by_id.get(meta["id"], {}), dict)
                and sections_by_id.get(meta["id"], {}).get("postprocess")
            ]
        for meta in section_meta:
            section_dir = output_root / "adaptive" / meta["id"]
            section_dir.mkdir(parents=True, exist_ok=True)
            piece = slice_audio(
                full_audio, sample_rate, meta["start_seconds"], meta["end_seconds"]
            )
            path = section_dir / f"{spec['id']}_{cue_hash}.{meta['id']}.full.ogg"
            if getattr(args, "verbose", False):
                print(f"[write] section full {meta['id']}", flush=True)
            write_ogg_from_audio(
                piece, sample_rate, path, quality=quality, keep_wav=args.keep_wav
            )
            output_files["adaptive"].setdefault(meta["id"], {})["full"] = str(
                path.relative_to(output_root)
            )

        if args.keep_midi:
            midi_out = output_root / "debug" / f"{spec['id']}_{cue_hash}.mid"
            midi_out.parent.mkdir(parents=True, exist_ok=True)
            pm.write(str(midi_out))
            output_files["debug_midi"] = str(midi_out.relative_to(output_root))

    manifest = build_manifest(
        spec, cue_hash, section_meta, group_names, output_files, sample_rate
    )
    manifest.setdefault("diagnostics", {})["adaptive_section_mastering"] = {
        **adaptive_section_mastering_config(spec),
        "ignored_section_postprocess_sections": locals().get("ignored_section_postprocess", []),
    }
    manifest_path = output_root / f"{spec['id']}_{cue_hash}.adaptive_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf8")
    return {
        "manifest": str(manifest_path),
        "preview": str(preview_path),
        "hash": cue_hash,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render Ambition MusicIR YAML to adaptive OGG assets"
    )
    parser.add_argument("spec", help="Path to .music.yaml source")
    parser.add_argument("--outdir", default="output", help="Output directory")
    parser.add_argument(
        "--backend",
        choices=["auto", "fallback", "fluidsynth-cli", "pretty-midi"],
        default=None,
    )
    parser.add_argument("--soundfont", default=None)
    parser.add_argument("--keep-wav", action="store_true")
    parser.add_argument("--keep-midi", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    result = render_all(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(main())
