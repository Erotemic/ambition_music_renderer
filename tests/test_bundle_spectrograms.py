from __future__ import annotations

from pathlib import Path

import sys

import numpy as np
import pytest

from ambition_music_renderer.render import bundle_spectrograms


def test_spectrogram_plot_decimation_bounds_mesh_and_preserves_peaks():
    freqs = np.arange(205, dtype="float64")
    times = np.arange(501, dtype="float64")
    spec = np.full((len(freqs), len(times)), -100.0, dtype="float32")
    spec[173, 432] = -12.0

    out_freqs, out_times, out_spec = (
        bundle_spectrograms.decimate_spectrogram_for_plot(
            freqs,
            times,
            spec,
            max_freq_bins=32,
            max_time_bins=50,
        )
    )

    assert out_spec.shape == (len(out_freqs), len(out_times))
    assert out_spec.shape[0] <= 32
    assert out_spec.shape[1] <= 50
    assert float(out_spec.max()) == -12.0


def test_write_spectrograms_reuses_one_transform_for_three_views(
    tmp_path: Path,
    monkeypatch,
):
    # ⛔ MATPLOTLIB IS INTENTIONALLY OPTIONAL, AND THIS TEST ASSERTS A PLOT
    # FILE. `write_spectrograms` says so in its own docstring -- "if it is
    # not installed, write a clear note and let the rest of the bundle
    # succeed" -- so on a machine set up exactly as `python_tools.sh`
    # intends, this failed on a missing FILE and read as a renderer bug.
    # The suite already skips for librosa, pyloudnorm, PySide6 and
    # pedalboard; this is the same move, and the fallback the docstring
    # promises has its own test below.
    pytest.importorskip("matplotlib")
    stem = tmp_path / "cue_hash.strings.npy"
    np.save(stem, np.zeros((32, 2), dtype="float32"))
    monkeypatch.setattr(
        bundle_spectrograms,
        "current_scratch_stem_paths",
        lambda outdir, manifest: [stem],
    )

    transform_calls = 0
    sentinel = (
        np.asarray([100.0, 200.0]),
        np.asarray([0.0, 0.1]),
        np.asarray([[-80.0, -70.0], [-60.0, -50.0]]),
    )

    def fake_transform(audio, sample_rate, signal_module):
        nonlocal transform_calls
        transform_calls += 1
        return sentinel

    seen_spectrograms = []

    def fake_save(audio, title, dest, **kwargs):
        seen_spectrograms.append(kwargs["spectrogram"])
        dest.touch()

    monkeypatch.setattr(bundle_spectrograms, "spectrogram_db", fake_transform)
    monkeypatch.setattr(bundle_spectrograms, "save_audio_spectrogram_plot", fake_save)
    monkeypatch.setattr(bundle_spectrograms, "save_high_detail_spectrogram_plot", fake_save)
    monkeypatch.setattr(bundle_spectrograms, "save_shrill_detail_spectrogram_plot", fake_save)

    written = bundle_spectrograms.write_spectrograms(
        tmp_path,
        {"sample_rate": 48_000, "files": {}},
        tmp_path / "plots",
    )

    assert transform_calls == 1
    assert len(written) == 3
    assert all(item is sentinel for item in seen_spectrograms)


def test_a_machine_without_matplotlib_gets_the_note_and_a_working_bundle(
    tmp_path: Path,
    monkeypatch,
):
    """⭐ THE DOCUMENTED FALLBACK, WHICH NOTHING TESTED.

    `write_spectrograms` promises in its own docstring that *"matplotlib is
    intentionally optional — if it is not installed, write a clear note and let
    the rest of the bundle succeed"*. That is the behaviour a fresh machine
    actually gets, because the package deliberately does not declare matplotlib,
    and it was the ONE path in this module with no arm on it.

    ⛔ The absence had already been read the wrong way once: three tests asserted
    a plot FILE and failed on a machine set up exactly as `python_tools.sh`
    intends, which reads as a renderer bug and was written up as an undeclared
    dependency. It is neither — the dependency is optional on purpose, and the
    tests were asserting an optional path unconditionally.

    ⭐ Forcing the ImportError rather than relying on the module being absent, so
    this exercises the same branch on a machine that HAS matplotlib. Without
    that, the arm would pass vacuously exactly where somebody would run it to
    check the claim.
    """
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", None)

    plots = tmp_path / "plots"
    written = bundle_spectrograms.write_spectrograms(
        tmp_path,
        {"sample_rate": 48_000, "files": {}},
        plots,
    )

    assert written == [], "a machine without matplotlib must write no plots"
    note = plots / "spectrograms_skipped.txt"
    assert note.exists(), "the docstring promises a clear note and there is none"
    body = note.read_text(encoding="utf8")
    assert "spectrogram generation skipped" in body
    # The note must name the CAUSE. "skipped" alone sends a reader looking for a
    # renderer defect, which is the trip this whole arm exists to prevent.
    assert "Error" in body or "error" in body, f"the note does not say why: {body!r}"
