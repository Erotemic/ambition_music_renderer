"""Tests for the music cue level report (audit/level_report.py).

The exact metrics (RMS / sample-peak / true-peak / crest / duration) are
verified against a synthesized 1 kHz sine whose values are known in
closed form, so a regression in the math fails loudly. Run under pytest,
or directly with the renderer venv python (which carries numpy /
soundfile / scipy):

    .venv/bin/python tests/test_level_report.py
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from ambition_music_renderer.audit import level_report as lr

SR = 48_000


def _write_sine(
    directory: Path, cue: str, amplitude: float, seconds: float = 1.0
) -> Path:
    cue_dir = directory / cue
    cue_dir.mkdir(parents=True, exist_ok=True)
    path = cue_dir / "full.wav"
    t = np.arange(int(SR * seconds)) / SR
    sig = (amplitude * np.sin(2 * math.pi * 1000.0 * t)).astype("float32")
    sf.write(path, np.stack([sig, sig], axis=1), SR)
    return path


def test_sine_metrics_match_closed_form():
    with tempfile.TemporaryDirectory() as td:
        path = _write_sine(Path(td), "mycue", amplitude=0.5)
        row = lr.analyze(path)
        assert row["cue"] == "mycue"
        assert abs(row["duration_s"] - 1.0) < 0.01
        # peak = 0.5 -> -6.02 dBFS; rms = 0.5/sqrt2 -> -9.03 dBFS.
        assert abs(row["peak_dbfs"] - (-6.0206)) < 0.1, row["peak_dbfs"]
        assert abs(row["rms_dbfs"] - (-9.0309)) < 0.1, row["rms_dbfs"]
        # A sine's crest factor is exactly 3.01 dB.
        assert abs(row["crest_db"] - 3.0103) < 0.1, row["crest_db"]
        # True (inter-sample) peak is never below the sample peak, and for a
        # well-sampled sine stays within a fraction of a dB of it.
        assert row["true_peak_dbtp"] >= row["peak_dbfs"] - 1e-6
        assert row["true_peak_dbtp"] - row["peak_dbfs"] < 0.5


def test_scaling_amplitude_shifts_levels_by_expected_db():
    with tempfile.TemporaryDirectory() as td:
        loud = lr.analyze(_write_sine(Path(td), "loud", amplitude=0.5))
        quiet = lr.analyze(_write_sine(Path(td), "quiet", amplitude=0.25))
        # Halving amplitude drops both RMS and peak by ~6.02 dB.
        assert abs((loud["rms_dbfs"] - quiet["rms_dbfs"]) - 6.0206) < 0.1
        assert abs((loud["peak_dbfs"] - quiet["peak_dbfs"]) - 6.0206) < 0.1


def test_flags_clip_loud_quiet():
    with tempfile.TemporaryDirectory() as td:
        near_full = lr.analyze(_write_sine(Path(td), "hot", amplitude=0.99))
        # peak ~-0.09 dBFS, true peak above the -1 dBTP ceiling -> CLIP.
        assert "CLIP" in lr._flags(near_full, target_rms_db=-20.0, rms_tol=3.0)

        loud = lr.analyze(_write_sine(Path(td), "loud", amplitude=0.5))  # rms ~-9
        assert "LOUD" in lr._flags(loud, target_rms_db=-20.0, rms_tol=3.0)
        assert "QUIET" not in lr._flags(loud, target_rms_db=-9.0, rms_tol=3.0)

        quiet = lr.analyze(_write_sine(Path(td), "quiet", amplitude=0.02))  # rms ~-37
        assert "QUIET" in lr._flags(quiet, target_rms_db=-20.0, rms_tol=3.0)


def test_render_table_and_summary():
    with tempfile.TemporaryDirectory() as td:
        rows = [
            lr.analyze(_write_sine(Path(td), "alpha", amplitude=0.5)),
            lr.analyze(_write_sine(Path(td), "beta", amplitude=0.25)),
        ]
        out = lr.render(rows, target_rms_db=-20.0, rms_tol=3.0, tsv=False)
        assert "alpha" in out and "beta" in out
        assert "2 cues" in out and "spread" in out
        tsv = lr.render(rows, target_rms_db=-20.0, rms_tol=3.0, tsv=True)
        assert "\t" in tsv and tsv.splitlines()[0].startswith("cue\t")


def test_check_mode_flags_clipping_and_passes_clean():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_sine(root, "clean", amplitude=0.5)  # ~-6 dBTP, fine
        # Clean root passes --check.
        assert lr.main(["--root", str(root), "--glob", "*/full.wav", "--check"]) == 0
        # Add a hot cue that clips, and --check must now fail.
        _write_sine(root, "hot", amplitude=0.999)
        assert lr.main(["--root", str(root), "--glob", "*/full.wav", "--check"]) == 1
        # Without --check, the same root still reports successfully.
        assert lr.main(["--root", str(root), "--glob", "*/full.wav"]) == 0


def _run_all() -> int:
    fns = [
        v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
