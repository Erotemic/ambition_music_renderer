#!/usr/bin/env python3
"""Measure the joins of a cue's playback sections as a game's director plays them.

    .venv/bin/python dev/measure_section_joins.py generated/<cue>/latest intro>fight fight>fight fight>outro@64
    .venv/bin/python dev/measure_section_joins.py generated/<cue>/latest intro>fight>fight>outro@64 --reel OUT.ogg

The render's manifest gives each section's length in beats, its layers and its
files. A join ``A>B`` plays A for its length in beats, then B. The part of A's
file after its length (its ring) plays on under B and fades out over
``--fade`` seconds, as the director fades the bank of a section that ends. A
loop that joins itself (``fight>fight``) is its file played two times. ``>B@N``
starts B after N bars of A (an outro that the game asks for in a loop) and
crossfades over ``--crossfade`` seconds.

For each join this prints, over the second before and the second after it:

- the RMS of each 50 ms window next to the join against the median window
  (a gap is a deep dip, a doubled downbeat a step up);
- the step between the two samples at the join against the 99.9th percentile
  step near it (a click is a step far above it);
- the energy of the sample-to-sample difference in the 5 ms at the join
  against the median 5 ms window near it (a click is a spike of it);
- the peak near the join against the peak of the whole file.

With ``--reel`` it also writes the whole sequence, for listening.
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import soundfile as sf


def db(x: float) -> float:
    return float(20 * np.log10(x + 1e-12))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def load_render(root: str) -> tuple[dict, dict[str, np.ndarray], int]:
    manifest_path = sorted(glob.glob(os.path.join(root, "*.adaptive_manifest.json")))[0]
    manifest = json.load(open(manifest_path, encoding="utf8"))
    files = manifest["files"]["playback"]
    audio: dict[str, np.ndarray] = {}
    rate = 0
    for section_id, layers in files.items():
        mix = None
        for rel in layers.values():
            data, rate = sf.read(os.path.join(root, rel), always_2d=True)
            mix = data if mix is None else mix[: min(len(mix), len(data))] + data[: min(len(mix), len(data))]
        audio[section_id] = np.asarray(mix, dtype=np.float64)
    return manifest, audio, rate


def section_frames(manifest: dict, section_id: str, rate: int) -> int:
    plan = manifest["playback_layers"]
    section = next(s for s in plan["sections"] if s["id"] == section_id)
    return int(round(section["duration_beats"] * 60.0 / float(manifest["bpm"]) * rate))


def play(manifest: dict, audio: dict[str, np.ndarray], rate: int, steps: list[str], fade: float,
         crossfade: float) -> tuple[np.ndarray, list[tuple[str, int]]]:
    """The sequence ``steps`` as the director plays it, and the frame of each join."""
    bar = int(round(float(manifest["beats_per_bar"]) * 60.0 / float(manifest["bpm"]) * rate))
    out = np.zeros((0, 2))
    joins: list[tuple[str, int]] = []
    at = 0  # where the next section starts
    start = 0  # where the previous section started
    previous = None
    previous_loops = False
    for step in steps:
        section_id, _, after_bars = step.partition("@")
        piece = audio[section_id].copy()
        if previous is not None and after_bars:
            # Leave the previous section after N bars and crossfade into this one.
            at = start + int(after_bars) * bar
            ramp = min(int(crossfade * rate), len(piece))
            while previous_loops and len(out) < at + ramp:
                # A loop plays on into its next pass while it fades.
                out = np.concatenate([out, audio[previous]])
            out = out[: at + ramp].copy()
            out[at:] *= np.linspace(1.0, 0.0, len(out) - at)[:, None]
            up = np.ones(len(piece))
            up[:ramp] = np.linspace(0.0, 1.0, ramp)
            piece *= up[:, None]
            piece[: len(out) - at] += out[at:]
        elif previous is not None:
            # The previous section played to its length; its ring fades out under this one.
            ring = out[at:]
            n = min(len(ring), int(fade * rate))
            ring = ring[:n] * np.linspace(1.0, 0.0, n)[:, None]
            piece[: len(ring)] += ring[: len(piece)]
        if previous is not None:
            joins.append((f"{previous}>{section_id}", at))
        out = np.concatenate([out[:at], piece])
        start = at
        loops = next(x for x in manifest["playback_layers"]["sections"] if x["id"] == section_id)["loop"]
        # The game loops a looped file whole; it starts any other next section at the length in beats.
        at = start + (len(audio[section_id]) if loops else section_frames(manifest, section_id, rate))
        previous = section_id
        previous_loops = loops
    return out, joins


def report(name: str, mix: np.ndarray, at: int, rate: int, file_peak: float) -> None:
    mono = mix.mean(axis=1)
    lo, hi = max(0, at - rate), min(len(mono), at + rate)
    win = int(0.05 * rate)
    windows = [rms(mono[i:i + win]) for i in range(lo, hi - win, win)]
    median = float(np.median(windows))
    before, after = rms(mono[at - win:at]), rms(mono[at:at + win])
    steps = np.abs(np.diff(mix[lo:hi], axis=0)).max(axis=1)
    join_step = float(np.abs(mix[at] - mix[at - 1]).max())
    typical = float(np.percentile(steps, 99.9))
    short = int(0.005 * rate)
    diff = np.diff(mono[lo:hi])
    energy = [rms(diff[i:i + short]) for i in range(0, len(diff) - short, short)]
    at_join = rms(diff[at - lo - short // 2: at - lo + short // 2])
    peak_near = float(np.abs(mix[max(0, at - rate // 4): at + rate // 4]).max())
    print(f"{name} at {at / rate:.3f} s")
    print(f"  50 ms RMS: before {db(before) - db(median):+.1f} dB, after {db(after) - db(median):+.1f} dB, "
          f"lowest {db(min(windows)) - db(median):+.1f} dB against the median window ({db(median):.1f} dBFS)")
    print(f"  step at the join {join_step:.4f}; 99.9th percentile step near it {typical:.4f}")
    print(f"  difference energy at the join {db(at_join) - db(float(np.median(energy))):+.1f} dB against the median "
          f"5 ms window; highest window {db(max(energy)) - db(float(np.median(energy))):+.1f} dB")
    print(f"  peak near the join {db(peak_near):.2f} dBFS; peak of the files {db(file_peak):.2f} dBFS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("render", help="a render directory (generated/<cue>/latest)")
    parser.add_argument("sequences", nargs="+", help="sections joined with '>', e.g. intro>fight>fight>outro@64")
    parser.add_argument("--fade", type=float, default=0.65, help="seconds a section's ring fades under the next")
    parser.add_argument("--crossfade", type=float, default=1.65, help="seconds of an '@' crossfade")
    parser.add_argument("--reel", help="write the (last) sequence to this file")
    parser.add_argument("--reference", action="append", default=[], metavar="AUDIO@SECONDS",
                        help="measure the same way a point of a file with no join there (e.g. the same "
                             "downbeat in the whole-song render), to tell the music from the join")
    args = parser.parse_args()
    manifest, audio, rate = load_render(os.path.realpath(args.render))
    file_peak = max(float(np.abs(a).max()) for a in audio.values())
    for sequence in args.sequences:
        mix, joins = play(manifest, audio, rate, sequence.split(">"), args.fade, args.crossfade)
        for name, at in joins:
            report(name, mix, at, rate, file_peak)
        if args.reel and sequence == args.sequences[-1]:
            sf.write(args.reel, mix.astype(np.float32), rate)
            print(f"wrote {args.reel} ({len(mix) / rate:.1f} s)")
    for reference in args.reference:
        path, _, seconds = reference.rpartition("@")
        data, ref_rate = sf.read(path, always_2d=True)
        report(f"reference {os.path.basename(path)}", np.asarray(data, dtype=np.float64),
               int(round(float(seconds) * ref_rate)), ref_rate, float(np.abs(data).max()))


if __name__ == "__main__":
    main()
