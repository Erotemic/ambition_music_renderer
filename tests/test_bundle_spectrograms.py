from __future__ import annotations

from pathlib import Path

import numpy as np

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
