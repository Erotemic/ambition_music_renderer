#!/usr/bin/env python3
"""Diff-friendly loudness / level report for generated music cues.

For each ``<cue>/full.ogg`` (or any ``*.ogg``) under the music asset
root, report duration, RMS (dBFS), sample peak (dBFS), true peak (dBTP,
4x oversampled per ITU-R BS.1770), crest factor, and the delta from a
target RMS. The output is sorted by cue name and fixed precision so it
can be committed and diffed across re-renders — a loudness or clipping
regression shows up as a line change instead of needing every cue
re-listened to.

Integrated LUFS (BS.1770) is shown only when ``pyloudnorm`` is
importable; the exact metrics above need only numpy / soundfile / scipy
(already required by the renderer) and are always reported. Cues whose
true peak exceeds -1 dBTP, or whose RMS is far from target, are flagged.

Examples:
  python level_report.py                          # default root, table
  python level_report.py --format tsv             # machine / commit form
  python level_report.py --root some/dir --target-rms-db -20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from transition_audit import db, peak, rms

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "crates/ambition_gameplay_core/assets/audio/music/generated"
CLIP_DBTP = -1.0  # ITU true-peak ceiling convention; above this we flag.

try:
    import pyloudnorm as _pyln
except Exception:  # pragma: no cover - optional dependency
    _pyln = None


def read_native(path: Path) -> tuple[np.ndarray, int]:
    """Read audio keeping its native channel count (no mono->stereo dup),
    so the optional LUFS measurement isn't biased by channel doubling."""
    audio, sample_rate = sf.read(path, always_2d=True, dtype="float32")
    return audio.astype("float32", copy=False), int(sample_rate)


def true_peak_dbtp(audio: np.ndarray, oversample: int = 4) -> float:
    """Inter-sample (true) peak in dBTP via integer oversampling."""
    if audio.size == 0:
        return db(0.0)
    up = resample_poly(audio, oversample, 1, axis=0)
    return db(peak(up))


def integrated_lufs(audio: np.ndarray, sample_rate: int) -> float | None:
    if _pyln is None:
        return None
    meter = _pyln.Meter(sample_rate)
    return float(meter.integrated_loudness(audio))


def analyze(path: Path) -> dict:
    audio, sr = read_native(path)
    frames = audio.shape[0]
    rms_db = db(rms(audio))
    peak_db = db(peak(audio))
    return {
        "cue": path.parent.name,
        "duration_s": frames / sr if sr else 0.0,
        "rms_dbfs": rms_db,
        "peak_dbfs": peak_db,
        "true_peak_dbtp": true_peak_dbtp(audio),
        "crest_db": peak_db - rms_db,
        "lufs": integrated_lufs(audio, sr),
        "sample_rate": sr,
    }


def _flags(row: dict, target_rms_db: float, rms_tol: float) -> str:
    out = []
    if row["true_peak_dbtp"] > CLIP_DBTP:
        out.append("CLIP")
    if abs(row["rms_dbfs"] - target_rms_db) > rms_tol:
        out.append("LOUD" if row["rms_dbfs"] > target_rms_db else "QUIET")
    return ",".join(out)


def _fmt_dur(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def render(rows: list[dict], target_rms_db: float, rms_tol: float, tsv: bool) -> str:
    has_lufs = any(r["lufs"] is not None for r in rows)
    headers = ["cue", "dur", "rms_dBFS", "peak_dBFS", "true_dBTP", "crest", "dRMS"]
    if has_lufs:
        headers.append("LUFS")
    headers.append("flags")

    def cells(r: dict) -> list[str]:
        c = [
            r["cue"],
            _fmt_dur(r["duration_s"]),
            f"{r['rms_dbfs']:.1f}",
            f"{r['peak_dbfs']:.1f}",
            f"{r['true_peak_dbtp']:.1f}",
            f"{r['crest_db']:.1f}",
            f"{r['rms_dbfs'] - target_rms_db:+.1f}",
        ]
        if has_lufs:
            c.append("n/a" if r["lufs"] is None else f"{r['lufs']:.1f}")
        c.append(_flags(r, target_rms_db, rms_tol))
        return c

    table = [headers] + [cells(r) for r in rows]
    if tsv:
        return "\n".join("\t".join(row) for row in table)
    widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(widths[i]) for i, c in enumerate(row)) for row in table]
    lines.insert(1, "  ".join("-" * widths[i] for i in range(len(headers))))
    lines.append("")
    lines.append(_summary(rows, target_rms_db, rms_tol))
    return "\n".join(lines)


def _summary(rows: list[dict], target_rms_db: float, rms_tol: float) -> str:
    rms_vals = [r["rms_dbfs"] for r in rows]
    lo, hi = min(rms_vals), max(rms_vals)
    mean = sum(rms_vals) / len(rms_vals)
    flag_counts = {"CLIP": 0, "LOUD": 0, "QUIET": 0}
    for r in rows:
        for f in _flags(r, target_rms_db, rms_tol).split(","):
            if f in flag_counts:
                flag_counts[f] += 1
    return (
        f"{len(rows)} cues | RMS dBFS min {lo:.1f} / mean {mean:.1f} / max {hi:.1f} "
        f"(spread {hi - lo:.1f} dB) | "
        f"{flag_counts['CLIP']} CLIP, {flag_counts['LOUD']} LOUD, "
        f"{flag_counts['QUIET']} QUIET vs target {target_rms_db:.1f}±{rms_tol:.0f}"
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="music root to scan (default: sandbox generated cues)",
    )
    ap.add_argument(
        "--glob", default="*/full.ogg", help="glob under --root for files to analyze"
    )
    ap.add_argument(
        "--target-rms-db",
        type=float,
        default=-20.0,
        help="reference RMS dBFS for the dRMS delta + LOUD/QUIET flags",
    )
    ap.add_argument(
        "--rms-tol",
        type=float,
        default=3.0,
        help="dB tolerance before a cue is flagged LOUD/QUIET",
    )
    ap.add_argument("--format", choices=["table", "tsv"], default="table")
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any cue clips (true peak > -1 dBTP) — "
        "a CI guard for the one unambiguous defect (loudness spread "
        "is a mastering call and stays report-only)",
    )
    args = ap.parse_args(argv)

    paths = sorted(args.root.glob(args.glob))
    if not paths:
        print(f"no audio matched {args.root}/{args.glob}", file=sys.stderr)
        return 1

    rows = [analyze(p) for p in paths]
    print(render(rows, args.target_rms_db, args.rms_tol, args.format == "tsv"))
    if _pyln is None:
        print("\n(install pyloudnorm for an integrated-LUFS column)", file=sys.stderr)
    if args.check:
        clipping = [r for r in rows if r["true_peak_dbtp"] > CLIP_DBTP]
        if clipping:
            names = ", ".join(
                f"{r['cue']} ({r['true_peak_dbtp']:.1f} dBTP)" for r in clipping
            )
            print(
                f"\nCLIP: {len(clipping)} cue(s) exceed {CLIP_DBTP:.0f} dBTP: {names}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
