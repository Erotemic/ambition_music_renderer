#!/usr/bin/env python3
"""Measure how a cue that loops as a whole file joins: its end against its start.

    .venv/bin/python dev/measure_loop_join.py <full.ogg or preview.ogg> scores/active/<cue>.music.yaml
    .venv/bin/python dev/measure_loop_join.py <file> <score> --notes generated/<cue>/latest

It prints:

- the length of the file and the length of the form (a difference is a gap or a cut at the join);
- the level of the last bar, beat and 50 ms, and of the first bar, beat and 50 ms;
- the step between the last sample and the first sample, against the largest step in the file;
- the pitch classes that have the most energy in the last bar and in the first bar, and how alike
  the two bars are (1.0 is the same balance of pitch classes);
- with ``--notes``, for each group the highest note and the highest note that is held, each note
  that sounds across the end of the form, and the notes of the last bar and of the first bar.

The score must have one tempo and a 4/4 meter.
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import soundfile as sf
import yaml

NOTE_NAMES = "C C# D D# E F F# G G# A A# B".split()


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9))


def chroma(mono: np.ndarray, sr: int) -> np.ndarray:
    """Energy of each pitch class, 60 Hz to 2 kHz."""
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
    keep = (freqs >= 60) & (freqs <= 2000)
    classes = np.round(69 + 12 * np.log2(freqs[keep] / 440.0)).astype(int) % 12
    out = np.zeros(12)
    np.add.at(out, classes, spectrum[keep])
    return out / (out.sum() + 1e-20)


def top(c: np.ndarray, n: int = 4) -> str:
    order = np.argsort(c)[::-1][:n]
    return " ".join(f"{NOTE_NAMES[i]}={c[i] * 100:.0f}%" for i in order)


def name_of(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def print_notes(render_dir: str, bar_beats: float, end_beat: float, held_beats: float) -> None:
    timeline = glob.glob(os.path.join(os.path.realpath(render_dir), "authoring", "*.note_timeline.json"))[0]
    notes = json.load(open(timeline, encoding="utf8"))["notes"]
    groups: dict[str, list[dict]] = {}
    for n in notes:
        groups.setdefault(n["group"], []).append(n)
    for group, rows in sorted(groups.items()):
        if any(str(r.get("layer_kind", "")).startswith("generator:drums") for r in rows):
            continue
        pitches = [(r["pitch"], r["end_beat"] - r["start_beat"]) for r in rows]
        highest = max(p for p, _ in pitches)
        held = [p for p, d in pitches if d >= held_beats]
        print(f"{group:10s} notes={len(rows):4d} highest={name_of(highest):4s} highest held (>= {held_beats:g} beat)={name_of(max(held)) if held else '-'}")
    late = [n for n in notes if n["end_beat"] > end_beat + 1e-6]
    long = [n for n in notes if n["end_beat"] - n["start_beat"] > bar_beats + 1e-6]
    print(f"notes that sound across the end of the form: {len(late)}; notes longer than one bar: {len(long)}")
    for n in late[:8]:
        print(f"  {n['group']} {n['note']} beat {n['start_beat']:.2f} to {n['end_beat']:.2f}")
    for label, lo, hi in (("last bar ", end_beat - bar_beats, end_beat), ("first bar", 0.0, bar_beats)):
        names: dict[str, set] = {}
        for n in notes:
            drum = str(n.get("layer_kind", "")).startswith("generator:drums")
            if not drum and n["start_beat"] < hi - 1e-6 and n["end_beat"] > lo + 1e-6:
                names.setdefault(n["group"], set()).add(n["pitch"])
        print(f"notes in the {label}: " + "; ".join(f"{g}: {' '.join(name_of(p) for p in sorted(ps))}" for g, ps in sorted(names.items())))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("audio", help="the file that loops")
    parser.add_argument("score", help="the MusicIR v3 score of that file")
    parser.add_argument("--notes", metavar="RENDER_DIR", help="also read the note timeline of this render")
    parser.add_argument("--held_beats", type=float, default=0.75, help="shortest note that counts as held")
    args = parser.parse_args()
    spec = yaml.safe_load(open(args.score, encoding="utf8"))
    bar_seconds = 4 * 60.0 / float(spec["tempo"])
    bars = int(spec["end"]["bar"]) - 1
    audio, sr = sf.read(args.audio, always_2d=True)
    mono = audio.mean(axis=1)
    form_seconds = bars * bar_seconds
    print(f"file {len(mono) / sr:.3f} s, form {form_seconds:.3f} s ({bars} bars), difference {(len(mono) / sr - form_seconds) * 1000:+.1f} ms")
    print(f"file peak {20 * np.log10(np.abs(audio).max() + 1e-9):.2f} dBFS, rms {rms_db(mono):.1f} dBFS")
    bar, beat, short = int(bar_seconds * sr), int(bar_seconds * sr / 4), int(0.05 * sr)
    print("level (dBFS)      bar    beat   50 ms")
    print(f"  end of file  {rms_db(mono[-bar:]):6.1f}  {rms_db(mono[-beat:]):6.1f}  {rms_db(mono[-short:]):6.1f}")
    print(f"  start        {rms_db(mono[:bar]):6.1f}  {rms_db(mono[:beat]):6.1f}  {rms_db(mono[:short]):6.1f}")
    step = np.abs(audio[0] - audio[-1]).max()
    largest = np.abs(np.diff(audio, axis=0)).max()
    typical = np.percentile(np.abs(np.diff(mono[-bar:])), 99)
    print(f"step at the join {step:.4f}; largest step in the file {largest:.4f}; 99th percentile step in the last bar {typical:.4f}")
    first, last = chroma(mono[:bar], sr), chroma(mono[-bar:], sr)
    alike = float(np.dot(first, last) / (np.linalg.norm(first) * np.linalg.norm(last) + 1e-20))
    print(f"pitch classes, last bar : {top(last)}")
    print(f"pitch classes, first bar: {top(first)}")
    print(f"first bar and last bar alike: {alike:.2f}")
    if args.notes:
        print_notes(args.notes, 4.0, bars * 4.0, args.held_beats)


if __name__ == "__main__":
    main()
