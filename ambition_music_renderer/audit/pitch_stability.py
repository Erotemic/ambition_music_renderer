"""Rendered-audio pitch-stability audit for lead stems.

The score-level audits cannot hear what effects and samples do to pitch:
a deep/slow chorus LFO reads as a "bend-down" on long sustained notes, an
authored pitch bend can start a note audibly flat, and a detuned sample
layer survives every note-level check. This audit analyzes the RENDERED
per-group stems (``scratch_stems/*.npy`` retained by ``cue bundle``) and
reports, with wall-clock timestamps:

* **wobble** - within one sustained voiced note, cyclic/f0 deviation beyond
  ``wobble_cents`` after the attack (chorus/vibrato depth problems);
* **off-pitch onsets** - a note whose first ~80 ms is more than
  ``onset_cents`` away from its own sustained median (bends that start
  detuned, scoop artifacts).

Bends are sometimes intentional (feedback squeals, falls); the audit
reports, a human decides. Analysis uses librosa pyin on mono stem audio,
so run it on melody-carrying groups (``--groups hook,sparkle``) rather
than pads/drums.
"""

from __future__ import annotations

from ..profiler import profile

import lazy_loader as lazy

import kwconf
import json
from pathlib import Path
from typing import Any

np = lazy.load("numpy")

from ._common import round3 as _round3


def _fmt_time(seconds: float) -> str:
    m, s = divmod(max(0.0, float(seconds)), 60.0)
    return f"{int(m)}:{s:05.2f}"


@profile
def analyze_stem(
    audio: "np.ndarray",
    sample_rate: int,
    *,
    fmin_hz: float = 70.0,
    fmax_hz: float = 1600.0,
    min_note_s: float = 0.30,
    attack_s: float = 0.08,
    wobble_cents: float = 30.0,
    onset_cents: float = 45.0,
    max_rows: int = 24,
) -> dict[str, Any]:
    """Track f0 and flag unstable sustained notes in one mono buffer."""
    import librosa

    mono = np.asarray(audio, dtype=np.float64)
    if mono.ndim == 2:
        mono = mono.mean(axis=1)
    hop = 512
    f0, voiced_flag, _voiced_prob = librosa.pyin(
        mono.astype(np.float32),
        fmin=fmin_hz,
        fmax=fmax_hz,
        sr=sample_rate,
        frame_length=2048,
        hop_length=hop,
    )
    times = librosa.times_like(f0, sr=sample_rate, hop_length=hop)
    frame_s = hop / float(sample_rate)
    min_frames = max(3, int(min_note_s / frame_s))
    attack_frames = max(1, int(attack_s / frame_s))

    wobble_rows: list[dict[str, Any]] = []
    onset_rows: list[dict[str, Any]] = []
    # Split into voiced runs, then split runs again at sharp pitch jumps:
    # legato playing keeps pyin voiced across note changes, and a melodic
    # step must not read as "detune". A jump > ~80 cents between adjacent
    # frames is a new note; gradual drift (bends, chorus wobble) stays
    # within one segment where it belongs.
    n = len(f0)
    runs: list[slice] = []
    run_start = None
    for i in range(n + 1):
        voiced = i < n and bool(voiced_flag[i]) and np.isfinite(f0[i])
        if voiced and run_start is None:
            run_start = i
        elif not voiced and run_start is not None:
            runs.append(slice(run_start, i))
            run_start = None
    notes: list[slice] = []
    for run in runs:
        seg_f0 = f0[run]
        steps = np.abs(1200.0 * np.log2(seg_f0[1:] / seg_f0[:-1]))
        cut_points = [0] + [int(j) + 1 for j in np.nonzero(steps > 80.0)[0]] + [run.stop - run.start]
        for a, b in zip(cut_points, cut_points[1:]):
            notes.append(slice(run.start + a, run.start + b))
    for note in notes:
        if (note.stop - note.start) < min_frames:
            continue
        seg = f0[note]
        sustain = seg[attack_frames:] if (note.stop - note.start) > attack_frames * 2 else seg
        median = float(np.median(sustain))
        if median <= 0:
            continue
        cents = 1200.0 * np.log2(sustain / median)
        worst = float(np.max(np.abs(cents)))
        if worst >= wobble_cents:
            worst_idx = int(np.argmax(np.abs(cents))) + attack_frames
            wobble_rows.append({
                "time": _fmt_time(times[note.start]),
                "start_seconds": _round3(float(times[note.start])),
                "worst_at": _fmt_time(times[min(note.start + worst_idx, n - 1)]),
                "note_seconds": _round3(float((note.stop - note.start) * frame_s)),
                "median_hz": _round3(median),
                "deviation_cents": _round3(worst),
            })
        onset = seg[: max(1, attack_frames)]
        onset_median = float(np.median(onset))
        if onset_median > 0:
            onset_dev = abs(1200.0 * np.log2(onset_median / median))
            if onset_dev >= onset_cents:
                onset_rows.append({
                    "time": _fmt_time(times[note.start]),
                    "start_seconds": _round3(float(times[note.start])),
                    "note_seconds": _round3(float((note.stop - note.start) * frame_s)),
                    "median_hz": _round3(median),
                    "onset_deviation_cents": _round3(onset_dev),
                })
    wobble_rows.sort(key=lambda r: -r["deviation_cents"])
    onset_rows.sort(key=lambda r: -r["onset_deviation_cents"])
    return {
        "wobble_count": len(wobble_rows),
        "off_pitch_onset_count": len(onset_rows),
        "wobble": wobble_rows[:max_rows],
        "off_pitch_onsets": onset_rows[:max_rows],
    }


@profile
def audit_outdir(
    outdir: Path,
    *,
    groups: list[str] | None = None,
    sample_rate: int = 48000,
    **kwargs: Any,
) -> dict[str, Any]:
    stems_dir = Path(outdir) / "scratch_stems"
    if not stems_dir.is_dir():
        # versioned layouts pass the run dir; flat layouts may pass the cue dir
        candidates = sorted(Path(outdir).glob("**/scratch_stems"))
        if not candidates:
            raise FileNotFoundError(
                f"no scratch_stems under {outdir}; render with debug stems retained"
            )
        stems_dir = candidates[0]
    report: dict[str, Any] = {
        "schema": "ambition.music_pitch_stability.v1",
        "stems_dir": str(stems_dir),
        "stems": {},
    }
    for npy in sorted(stems_dir.glob("*.npy")):
        group = npy.stem.rsplit(".", 1)[-1]
        if groups and group not in groups:
            continue
        audio = np.load(npy)
        report["stems"][group] = analyze_stem(audio, sample_rate, **kwargs)
    return report


class PitchStabilityConfig(kwconf.Config):
    """Flag pitch wobble / off-pitch onsets in rendered lead stems."""

    outdir: Path = kwconf.Value(None, position=1, parser=Path,
                                help="render output dir containing scratch_stems/")
    groups: str = kwconf.Value("", help="comma-separated stem groups (default: all)")
    sample_rate: int = kwconf.Value(48000, help="stem sample rate")
    wobble_cents: float = kwconf.Value(30.0, help="sustained deviation threshold")
    onset_cents: float = kwconf.Value(45.0, help="onset detune threshold")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        args = cls.cli(argv=argv, data=kwargs)
        wanted = [g.strip() for g in str(args.groups).split(",") if g.strip()] or None
        report = audit_outdir(
            Path(args.outdir),
            groups=wanted,
            sample_rate=int(args.sample_rate),
            wobble_cents=float(args.wobble_cents),
            onset_cents=float(args.onset_cents),
        )
        print(json.dumps(report, indent=2))
        return 0


def main(argv: list[str] | None = None) -> int:
    return int(PitchStabilityConfig.main(argv=argv))


if __name__ == "__main__":
    raise SystemExit(main())
