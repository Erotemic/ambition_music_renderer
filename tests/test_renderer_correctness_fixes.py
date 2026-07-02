"""Pin tests for the audit-driven correctness fixes.

Each test here guards a bug found in the 2026-07 code audit: wrong chord
extensions, a non-monotonic compressor knee, target_lufs being undone by the
peak-normalizing limiter, and the broken rerun script subcommand.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def test_chord_b9_does_not_stack_natural_nine():
    from ambition_music_renderer.render.score_theory import chord_intervals

    _root, intervals, _slash = chord_intervals("C7b9")
    assert 13 in intervals
    assert 14 not in intervals, "b9 chords must not also carry the natural 9"
    _root, intervals, _slash = chord_intervals("C7#9")
    assert 15 in intervals
    assert 14 not in intervals


def test_chord_natural_nine_still_present_where_asked():
    from ambition_music_renderer.render.score_theory import chord_intervals

    for symbol in ("C9", "Cm9", "Cadd9", "Cmaj9", "C6/9"):
        _root, intervals, _slash = chord_intervals(symbol)
        assert 14 in intervals, f"{symbol} lost its ninth"


def test_chord_upper_case_major_seven_convention():
    from ambition_music_renderer.render.score_theory import chord_intervals

    _root, intervals, _slash = chord_intervals("CM7")
    assert 4 in intervals and 11 in intervals, "CM7 is a major seventh, not minor"


def test_chord_dim_requires_real_token():
    from ambition_music_renderer.render.score_theory import chord_intervals

    _root, intervals, _slash = chord_intervals("Cdim")
    assert intervals[:3] == [0, 3, 6]
    # A suffix merely containing the letter o must not read as diminished.
    _root, intervals, _slash = chord_intervals("Csus4")
    assert intervals[:3] == [0, 5, 7]


def test_compressor_knee_is_monotonic_and_continuous():
    from ambition_music_renderer.render.effects import compressor

    sr = 48000
    ratio, threshold, knee = 4.0, -18.0, 6.0
    # Static levels swept through the knee; with instant attack/release the
    # envelope tracks the static gain-reduction curve.
    levels_db = np.linspace(threshold - knee, threshold + knee, 41)
    outputs = []
    for level_db in levels_db:
        amp = 10.0 ** (level_db / 20.0)
        audio = np.full((sr // 10, 2), amp, dtype=np.float32)
        out = compressor(
            audio, sr,
            threshold_db=threshold, ratio=ratio,
            attack_ms=0.01, release_ms=0.01, knee_db=knee,
        )
        outputs.append(float(np.abs(out[-100:]).mean()))
    gains_db = 20.0 * np.log10(np.maximum(outputs, 1e-9)) - levels_db
    # Gain reduction must never *increase* the signal...
    assert max(gains_db) <= 1e-3, "knee region boosted the signal"
    # ...and must be monotonically non-increasing as level rises (no jump).
    diffs = np.diff(gains_db)
    assert np.all(diffs <= 1e-2), "gain reduction is non-monotonic through the knee"


def test_target_lufs_not_undone_by_normalizing_limiter():
    pytest.importorskip("pyloudnorm")
    import pyloudnorm as pyln
    from ambition_music_renderer.render.effects import post_process

    sr = 48000
    t = np.arange(sr * 3) / sr
    tone = (0.05 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    audio = np.column_stack([tone, tone])
    settings = {
        "target_lufs": -23.0,
        "true_peak_db": -1.0,
        "normalize": True,  # the old bug: this re-normalized peak to -1 dB
        "reverb_enabled": False,
        "stereo_width": 0.0,
        "limiter_drive": 1.0,
    }
    out = post_process(audio, sr, settings)
    loudness = pyln.Meter(sr).integrated_loudness(out.astype(np.float64))
    assert abs(loudness - (-23.0)) < 1.5, (
        f"LUFS target lost: got {loudness:.1f} LUFS (peak normalization "
        "re-gained the audio after loudness normalization)"
    )


def test_rerun_script_uses_real_subcommand(tmp_path: Path):
    from ambition_music_renderer.render.bundle_archive import build_rerun_script

    script = build_rerun_script(
        tmp_path,
        "some_cue",
        "pretty-midi",
        None,  # default versioned layout: no --outdir pin
        False,
        "native",
        "jpg",
        None,
        False,
        False,
    )
    body = script.read_text()
    assert "cue bundle" in body, "rerun script must call the real modal subcommand"
    assert "cue_bundle" not in body
    assert "--outdir" not in body, "default-layout reruns must re-resolve their layout"


def test_batch_build_command_forwards_all_bundle_options():
    from pathlib import Path as _Path

    from ambition_music_renderer.render.batch_bundle import _build_command
    from ambition_music_renderer.render.bundle import CueBundleConfig

    args = CueBundleConfig.cli(
        argv=False,
        data={"cue": "x", "dest_root": _Path("/custom/dest"), "skip_render": True},
    )
    args.render_jobs = 1
    cmd = _build_command(args, "x")
    joined = " ".join(str(part) for part in cmd)
    assert "/custom/dest" in joined, "--dest_root dropped on the batch path"
    assert "skip_render" in joined, "--skip_render dropped on the batch path"


def test_fallback_backend_guitar_family():
    from ambition_music_renderer.fallback_backend import _program_family

    assert _program_family(24) == "pluck"  # nylon guitar
    assert _program_family(30) == "pluck"  # distortion guitar
    assert _program_family(19) == "pad"  # church organ
