#!/usr/bin/env python3
"""Measure the playback layer files of one render or one published cue.

    python dev/measure_playback_layers.py generated/<cue>/latest bed+tune bed+tune+drums

For each playback section this prints the RMS of each layer and of all layers
together. Each more argument is a state: layers joined with ``+``. For a state
it prints the RMS and the peak of the sum, and the RMS of each half of the
section. Use it to set the layer gains of the game's states.

What this found on dinosaur_liberators_adaptive (2026-10-10): the soft state
(bed and tune) is 4 dB above the lofi room tracks with no gain, so no state
needs a gain above one. The heavy guitar and horns add 0.6 dB: they add
texture, not level.
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np
import soundfile as sf


def db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9))


def peak_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.abs(x).max() + 1e-9))


def main() -> None:
    root = os.path.realpath(sys.argv[1])
    for section in sorted(os.listdir(os.path.join(root, "playback"))):
        layers = {}
        for path in sorted(glob.glob(os.path.join(root, "playback", section, "*.ogg"))):
            layers[path.split(".")[-2]], rate = sf.read(path)
        n = min(len(audio) for audio in layers.values())
        everything = sum(audio[:n] for audio in layers.values())
        print(f"{section} {n / rate:.3f} s  " + " ".join(f"{k}={db(v):.1f}" for k, v in layers.items())
              + f"  all={db(everything):.1f} peak={peak_db(everything):.1f}")
        for state in sys.argv[2:]:
            names = state.split("+")
            if not all(name in layers for name in names):
                continue
            mix = sum(layers[name][:n] for name in names)
            print(f"   {state}: {db(mix):.1f}  halves {db(mix[:n // 2]):.1f} {db(mix[n // 2:]):.1f}  peak {peak_db(mix):.1f}")


if __name__ == "__main__":
    main()
