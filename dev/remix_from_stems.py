#!/usr/bin/env python3
"""Mix a render again from its group stems, with a gain change for some groups.

A full render of a cue with sampled instruments takes 10 to 30 minutes. A group
gain at the end of a group chain is linear, so this gives the same mix in
seconds: it adds the gain to the group stem, sums the stems, and runs the master
chain of the score.

    .venv/bin/python dev/remix_from_stems.py generated/<cue>/latest \\
        scores/active/<cue>.music.yaml --gain drums=3 --gain hats=7 --out /tmp/mix.ogg

The stems are ``scratch_stems/*.npy``: render with ``--include_scratch_stems=True``.
The result is an audition copy. Put the gains in the score and render again
before you publish. Section mix gains and section bus processing are not applied.
"""
from __future__ import annotations

import argparse
import glob
from pathlib import Path

import numpy as np
import yaml

from ambition_music_renderer.processing.mastering import master_composition
from ambition_music_renderer.render.export import write_ogg_from_audio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("render", type=Path, help="a render directory that has scratch_stems/")
    parser.add_argument("score", type=Path)
    parser.add_argument("--gain", action="append", default=[], metavar="GROUP=DB")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample_rate", type=int, default=48000)
    args = parser.parse_args()

    gains = {}
    for pair in args.gain:
        group, _, value = pair.partition("=")
        gains[group] = float(value)
    stems = {Path(f).name.split(".")[-2]: f for f in sorted(glob.glob(str(args.render / "scratch_stems" / "*.npy")))}
    if not stems:
        raise SystemExit(f"no scratch stems under {args.render}")
    unknown = sorted(set(gains) - set(stems))
    if unknown:
        raise SystemExit(f"no stem for {unknown}; the groups are {sorted(stems)}")

    mix = None
    for group, path in stems.items():
        audio = np.load(path).astype("float32") * 10 ** (gains.get(group, 0.0) / 20.0)
        mix = audio if mix is None else mix + audio
    spec = yaml.safe_load(args.score.read_text())
    master, _plan = master_composition(mix, args.sample_rate, spec, base_dir=args.score.parent)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_ogg_from_audio(master, args.sample_rate, args.out, quality=6, keep_wav=False)
    rms = 20 * np.log10(np.sqrt(np.mean(master ** 2)) + 1e-9)
    print(f"wrote {args.out}: {len(master) / args.sample_rate:.1f} s, rms {rms:.1f} dBFS, peak {np.abs(master).max():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
