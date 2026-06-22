#!/usr/bin/env python3
"""Localize spectral content in a rendered music cue to its source group.

Given a cue's per-group `.npy` scratch stems (kept by passing
`--keep-debug-stems` to the renderer), report which group dominates each
frequency band over a user-supplied time window. Useful when a listener
reports "there is a [squeak / rumble / boom / whatever] at T seconds" and
the YAML is ambiguous about which layer is responsible.

Usage:

    spectral_localize.py <cue_outdir> [--window LO HI] [--bucket SECS]

`<cue_outdir>` is the output directory passed to `render_isolated`, e.g.
`tools/ambition_music_renderer/generated/how_to_kill_a_mockingbird/`. The
script reads every `.npy` under `<cue_outdir>/scratch_stems/` and treats
each one as a single-group stereo buffer at the cue's render sample rate.

Workflow:

1. Render the cue with debug stems retained:
   ``python -m ambition_music_renderer.render.isolated <yaml> --outdir <dir>
   --keep-debug-stems``
2. ``spectral_localize.py <dir> --window 38 43`` to see which group
   contributes which fraction of each band's energy in the window.
3. The dominant group in the offending band is the one to investigate in
   the YAML. From there you can re-enter the layer→template→motif chain
   to find the YAML edit that actually changes the rendered audio.

The script intentionally does not mutate the YAML — it only diagnoses.
"""

from __future__ import annotations

from ..profiler import profile

import kwconf
from pathlib import Path

import numpy as np


DEFAULT_BANDS = {
    "low (<300)": (0.0, 300.0),
    "mid (300-1k)": (300.0, 1000.0),
    "high (1-3k)": (1000.0, 3000.0),
    "vhigh (3-6k)": (3000.0, 6000.0),
    "air (6-12k)": (6000.0, 12000.0),
}


@profile
def to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype("float32")
    if audio.shape[-1] == 2:
        return audio.mean(axis=-1).astype("float32")
    return audio.mean(axis=0).astype("float32")


@profile
def band_energy(spec: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    mask = (freqs >= lo) & (freqs < hi)
    return float(np.square(spec[mask]).sum())


@profile
def time_resolved_band_energy(
    mono: np.ndarray, sr: int, t_lo: float, t_hi: float, bucket_s: float, bands: dict
) -> tuple[np.ndarray, dict]:
    win = int(sr * bucket_s)
    nfft = 1 << (win - 1).bit_length()
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    hann = np.hanning(win).astype("float32")
    n_buckets = max(0, int((t_hi - t_lo) / bucket_s))
    times = np.array([t_lo + i * bucket_s for i in range(n_buckets)])
    energies = {b: np.zeros(n_buckets) for b in bands}
    for i, t in enumerate(times):
        s = int(t * sr)
        seg = mono[s : s + win]
        if len(seg) < win:
            break
        spec = np.abs(np.fft.rfft(seg * hann, nfft))
        for b, (lo, hi) in bands.items():
            energies[b][i] = band_energy(spec, freqs, lo, hi)
    return times, energies


@profile
def render_heatmap_row(name: str, vals: np.ndarray) -> str:
    peak = float(vals.max()) if len(vals) else 0.0
    cells: list[str] = []
    for v in vals:
        if peak <= 0:
            cells.append(" .")
            continue
        ratio = float(v) / peak
        if ratio > 0.8:
            cells.append("##")
        elif ratio > 0.5:
            cells.append("=#")
        elif ratio > 0.2:
            cells.append("==")
        elif ratio > 0.05:
            cells.append(" -")
        else:
            cells.append(" .")
    return f"{name:14s} " + "".join(cells)


class SpectralLocalizeConfig(kwconf.Config):
    """Localize spectral content in rendered scratch stems."""

    cue_outdir: Path = kwconf.Value(None, position=1, parser=Path)
    window: tuple[float, float] = kwconf.Value((0.0, -1.0), nargs=2, help="Time window in seconds")
    bucket: float = kwconf.Value(0.25, help="Bucket size in seconds")
    sr: int = kwconf.Value(48000, help="Sample rate of stems")
    bands: str = kwconf.Value("default", choices=["default", "vhigh-only"])


@profile
def main(argv: list[str] | None = None) -> int:
    ns = SpectralLocalizeConfig.cli(argv=argv)


    stems_dir = ns.cue_outdir / "scratch_stems"
    if not stems_dir.is_dir():
        raise SystemExit(f"no scratch_stems/ under {ns.cue_outdir} — re-render with --keep-debug-stems")
    stems = sorted(stems_dir.glob("*.npy"))
    if not stems:
        raise SystemExit(f"no .npy files under {stems_dir}")

    bands = (
        DEFAULT_BANDS if ns.bands == "default" else {"vhigh (3-6k)": (3000.0, 6000.0)}
    )

    # Determine track duration from the first stem
    first = np.load(stems[0])
    dur = (
        first.shape[0] / ns.sr
        if first.ndim == 1
        else first.shape[-2] / ns.sr
        if first.ndim == 2 and first.shape[-1] == 2
        else len(first) / ns.sr
    )
    t_lo, t_hi = ns.window
    if t_hi < 0:
        t_hi = dur
    print(
        f"track duration ~{dur:.2f}s, analyzing {t_lo:.2f}-{t_hi:.2f}s @ {ns.bucket}s buckets"
    )

    # Stem name = part of filename before .npy and after the cue hash, e.g. ".bass.npy"
    def stem_name(p: Path) -> str:
        return p.stem.split(".")[-1]

    # Aggregate across all stems
    all_data: dict[str, dict[str, np.ndarray]] = {}
    times_ref = None
    for p in stems:
        mono = to_mono(np.load(p))
        times, energies = time_resolved_band_energy(
            mono, ns.sr, t_lo, t_hi, ns.bucket, bands
        )
        all_data[stem_name(p)] = energies
        times_ref = times

    print(f"\nGroups found: {', '.join(sorted(all_data))}")

    # Window-mean fraction per band
    win_energy = {
        name: {b: float(all_data[name][b].mean()) for b in bands} for name in all_data
    }
    print(f"\nWindow-mean band energy fraction per group ({t_lo:.2f}-{t_hi:.2f}s):")
    print(f"{'group':14s}  " + "  ".join(f"{b:>14s}" for b in bands))
    for name in sorted(all_data):
        row = []
        for b in bands:
            total = sum(win_energy[g][b] for g in win_energy)
            frac = win_energy[name][b] / total if total > 0 else 0
            row.append(f"{frac * 100:13.1f}%")
        print(f"{name:14s}  " + "  ".join(row))

    # Heatmap per band, per group, per time bucket. Each row scaled to its own peak.
    if times_ref is not None and len(times_ref) > 0:
        for b in bands:
            print(f"\n{b} energy heatmap, per group, scaled to row peak:")
            tick = "             " + "".join(
                f"{int(t) % 10:>2d}" if t == int(t) else "  " for t in times_ref
            )
            print(tick)
            for name in sorted(all_data):
                print(render_heatmap_row(name, all_data[name][b]))

    # Identify the dominant group at each bucket per band
    print("\nDominant group at each bucket (>= 30% of total band energy):")
    for b in bands:
        print(f"  {b}:")
        for i, t in enumerate(times_ref):
            total = sum(all_data[g][b][i] for g in all_data)
            if total <= 0:
                continue
            ranked = sorted(
                ((all_data[g][b][i] / total, g) for g in all_data), reverse=True
            )
            top = ranked[0]
            if top[0] >= 0.30:
                runner = ranked[1] if len(ranked) > 1 else (0.0, "-")
                print(
                    f"    t={t:6.2f}s  {top[1]:14s} {top[0] * 100:5.1f}%  (next: {runner[1]} {runner[0] * 100:.0f}%)"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
