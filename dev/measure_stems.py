#!/usr/bin/env python3
"""Measure the scratch stems of one render: levels, placement, and pitch.

Render with ``cue bundle <cue> --include_scratch_stems=True`` first. Then:

    python dev/measure_stems.py generated/<cue>/latest scores/.../<cue>.music.yaml
    python dev/measure_stems.py generated/<cue>/latest <score> --pitch lead_2 45 46

The first form prints the RMS of each stem group in each form section, and the
left-minus-right level of each group. The second form prints the pitch of one
stem, twice for each sixteenth note, as note name and cents.

The stems are the audio after group processing and before the master chain. The
score must have one tempo and a 4/4 meter.

What this found on dinosaur_liberators_v2 (2026-10-10):

- An instrument ``pan`` before an amp simulator gave only 2 dB between left and
  right. The amp compresses each channel separately. A ``balance`` stage after
  the amp gave 10 dB.
- The Black and Green guitar vibrato (CC111) is about 2.2 cents for each
  controller step: a value of 108 moved a held G5 up to A5.
- The Emily guitar follows pitch bend with a range of 1200 cents.
"""
from __future__ import annotations

import argparse
import glob
import os

import numpy as np
import yaml

NOTE_NAMES = "C C# D D# E F F# G G# A A# B".split()


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9))


def load_stems(render_dir: str) -> dict[str, np.ndarray]:
    stems = {}
    for path in sorted(glob.glob(os.path.join(os.path.realpath(render_dir), "scratch_stems", "*.npy"))):
        audio = np.load(path)
        if audio.ndim == 2 and audio.shape[0] < audio.shape[1]:
            audio = audio.T
        stems[path.split(".")[-2]] = audio.astype(np.float32)
    if not stems:
        raise SystemExit(f"no scratch stems under {render_dir}; render with --include_scratch_stems=True")
    return stems


def print_levels(stems: dict[str, np.ndarray], sections: list[tuple[str, int, int]], bar_seconds: float, sr: int) -> None:
    names = list(stems)
    print("section".ljust(12) + " ".join(n.rjust(11) for n in names) + "         sum")
    for name, first, last in sections:
        lo, hi = int((first - 1) * bar_seconds * sr), int((last - 1) * bar_seconds * sr)
        row = [rms_db(stems[n][lo:hi]) for n in names]
        total = sum(stems[n][lo:hi][: hi - lo] for n in names if len(stems[n]) >= hi)
        print(name.ljust(12) + " ".join(f"{v:11.1f}" for v in row) + f" {rms_db(total):11.1f}")
    print("left minus right (dB): " + " ".join(f"{n}={rms_db(stems[n][:, 0]) - rms_db(stems[n][:, 1]):+.1f}" for n in names))


def print_pitch(audio: np.ndarray, first: float, last: float, bar_seconds: float, sr: int) -> None:
    mono = audio.mean(axis=1)[int((first - 1) * bar_seconds * sr): int((last - 1) * bar_seconds * sr)]
    win, hop = 4096, 1024
    track: list[float | None] = []
    for i in range(0, len(mono) - win, hop):
        frame = mono[i:i + win] * np.hanning(win)
        if np.sqrt(np.mean(frame * frame)) < 1e-4:
            track.append(None)
            continue
        ac = np.correlate(frame, frame, "full")[win - 1:]
        lo, hi = int(sr / 1600), int(sr / 150)
        k = float(lo + int(np.argmax(ac[lo:hi])))
        a, b, c = ac[int(k) - 1], ac[int(k)], ac[int(k) + 1]
        k += 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
        track.append(69 + 12 * np.log2(sr / k / 440))
    step = max(1, int(round(bar_seconds * sr / 16 / hop / 2)))
    cells = []
    for midi in track[::step]:
        if midi is None:
            cells.append("  --  ")
        else:
            note = int(round(midi))
            cells.append(f"{NOTE_NAMES[note % 12]}{note // 12 - 1}{(midi - note) * 100:+04.0f}")
    for i in range(0, len(cells), 16):
        print(f"bar {first + i / 32:6.2f}: " + " ".join(cells[i:i + 16]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("render_dir", help="generated/<cue>/latest")
    parser.add_argument("score", help="the MusicIR v3 score of that render")
    parser.add_argument("--pitch", nargs=3, metavar=("GROUP", "FIRST_BAR", "LAST_BAR"))
    parser.add_argument("--sample_rate", type=int, default=48000)
    args = parser.parse_args()
    spec = yaml.safe_load(open(args.score, encoding="utf8"))
    bar_seconds = 4 * 60.0 / float(spec["tempo"])
    stems = load_stems(args.render_dir)
    if args.pitch:
        group, first, last = args.pitch
        print_pitch(stems[group], float(first), float(last), bar_seconds, args.sample_rate)
    else:
        sections = [(str(f["id"]), int(f["from"]["bar"]), int(f["to"]["bar"])) for f in spec["form"]]
        print_levels(stems, sections, bar_seconds, args.sample_rate)


if __name__ == "__main__":
    main()
