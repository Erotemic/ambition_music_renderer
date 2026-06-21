#!/usr/bin/env python3
"""Single-number squeak metric for an A/B sweep.

Reads `<cue_outdir>/scratch_stems/*.npy`, sums vhigh (3-6 kHz) and air
(6-12 kHz) band energy across all groups in a target window, and prints
both the absolute squeak energy and its ratio to mid-band (300-1000 Hz)
energy in the same window. The ratio is a "perceived brightness" proxy
that doesn't fall just from lowering master volume.

Lower numbers = less squeak.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype("float32")
    if audio.shape[-1] == 2:
        return audio.mean(axis=-1).astype("float32")
    return audio.mean(axis=0).astype("float32")


def band_energy(
    mono: np.ndarray, sr: int, t_lo: float, t_hi: float, lo_hz: float, hi_hz: float
) -> float:
    s = int(t_lo * sr)
    e = int(t_hi * sr)
    seg = mono[s:e]
    if len(seg) == 0:
        return 0.0
    nfft = 1 << (len(seg) - 1).bit_length()
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)).astype("float32"), nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    mask = (freqs >= lo_hz) & (freqs < hi_hz)
    return float(spec[mask].sum())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cue_outdir", type=Path)
    ap.add_argument(
        "--window", nargs=2, type=float, metavar=("LO", "HI"), default=(38.0, 43.0)
    )
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--label", type=str, default="")
    ns = ap.parse_args(argv)

    stems = sorted((ns.cue_outdir / "scratch_stems").glob("*.npy"))
    t_lo, t_hi = ns.window

    by_group = {}
    for p in stems:
        name = p.stem.split(".")[-1]
        mono = to_mono(np.load(p))
        by_group[name] = {
            "mid": band_energy(mono, ns.sr, t_lo, t_hi, 300, 1000),
            "vhigh": band_energy(mono, ns.sr, t_lo, t_hi, 3000, 6000),
            "air": band_energy(mono, ns.sr, t_lo, t_hi, 6000, 12000),
        }

    total = {b: sum(by_group[g][b] for g in by_group) for b in ("mid", "vhigh", "air")}
    squeak = total["vhigh"] + total["air"]
    ratio = squeak / max(total["mid"], 1e-12)

    label = f"[{ns.label}] " if ns.label else ""
    print(f"{label}window={t_lo:.1f}-{t_hi:.1f}s")
    print(f"  squeak (vhigh+air absolute):  {squeak:11.3e}")
    print(f"  mid (300-1k absolute):        {total['mid']:11.3e}")
    print(f"  squeak/mid ratio:             {ratio:7.4f}")
    print(f"  per-group vhigh contributions:")
    vhigh_total = max(total["vhigh"], 1e-12)
    for g in sorted(by_group, key=lambda x: -by_group[x]["vhigh"]):
        frac = by_group[g]["vhigh"] / vhigh_total
        print(f"    {g:14s} {frac * 100:5.1f}%   abs={by_group[g]['vhigh']:.3e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
