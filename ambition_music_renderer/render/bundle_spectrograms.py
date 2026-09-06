"""Spectrogram plotting helpers for bundle reports."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..profiler import profile
from .bundle_base import current_scratch_stem_paths, report_plot_save_kwargs

SpectrogramData = tuple[np.ndarray, np.ndarray, np.ndarray]


@profile
def spectrogram_db(
    audio: np.ndarray,
    sample_rate: int,
    signal_module,
) -> SpectrogramData:
    """Compute a full-resolution dB spectrogram for analysis and plotting."""
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio.astype("float32")
    if mono.size == 0:
        return np.asarray([]), np.asarray([]), np.asarray([[]])
    bounded_length = max(256, min(len(mono), 4096))
    nperseg = min(4096, max(256, int(2 ** math.floor(math.log2(bounded_length)))))
    noverlap = max(0, int(nperseg * 0.75))
    freqs, times, spec = signal_module.spectrogram(
        mono,
        fs=sample_rate,
        nperseg=nperseg,
        noverlap=noverlap,
        scaling="spectrum",
        mode="magnitude",
    )
    return freqs, times, 20 * np.log10(spec + 1e-10)


@profile
def decimate_spectrogram_for_plot(
    freqs: np.ndarray,
    times: np.ndarray,
    spec_db: np.ndarray,
    *,
    max_freq_bins: int = 1024,
    max_time_bins: int = 1200,
) -> SpectrogramData:
    """Peak-pool a spectrogram to a plotting-sized grid.

    The full-resolution transform remains available to numerical audits. Plotting
    millions of quadrilaterals adds little diagnostic value, so this helper uses
    block maxima to preserve narrow peaks and transients while bounding the
    expensive matplotlib mesh.
    """
    if spec_db.size == 0:
        return freqs, times, spec_db
    if max_freq_bins < 1 or max_time_bins < 1:
        raise ValueError("spectrogram plot bin limits must be positive")

    freq_step = max(1, math.ceil(spec_db.shape[0] / max_freq_bins))
    time_step = max(1, math.ceil(spec_db.shape[1] / max_time_bins))
    freq_starts = np.arange(0, spec_db.shape[0], freq_step)
    time_starts = np.arange(0, spec_db.shape[1], time_step)

    pooled = np.maximum.reduceat(spec_db, freq_starts, axis=0)
    pooled = np.maximum.reduceat(pooled, time_starts, axis=1)

    freq_centers = np.minimum(
        freq_starts + (freq_step - 1) // 2,
        len(freqs) - 1,
    )
    time_centers = np.minimum(
        time_starts + (time_step - 1) // 2,
        len(times) - 1,
    )
    return freqs[freq_centers], times[time_centers], pooled


def _spectrogram_or_compute(
    audio: np.ndarray,
    sample_rate: int,
    signal_module,
    spectrogram: SpectrogramData | None,
) -> SpectrogramData:
    if spectrogram is not None:
        return spectrogram
    return spectrogram_db(audio, sample_rate, signal_module)


@profile
def spectrogram_save_kwargs(dest: Path, jpeg_quality: int) -> dict[str, object]:
    return report_plot_save_kwargs(dest, jpeg_quality=jpeg_quality)


@profile
def save_audio_spectrogram_plot(
    audio: np.ndarray,
    title: str,
    dest: Path,
    *,
    sample_rate: int,
    signal_module,
    pyplot,
    jpeg_quality: int,
    spectrogram: SpectrogramData | None = None,
) -> None:
    freqs, times, spec_db = _spectrogram_or_compute(
        audio, sample_rate, signal_module, spectrogram
    )
    if spec_db.size == 0:
        return
    freqs, times, spec_db = decimate_spectrogram_for_plot(freqs, times, spec_db)
    pyplot.figure(figsize=(14, 5))
    pyplot.pcolormesh(
        times,
        freqs,
        spec_db,
        shading="auto",
        vmin=-110,
        vmax=-35,
        cmap="inferno",
    )
    pyplot.yscale("log")
    pyplot.ylim(80, 12000)
    pyplot.axhspan(3000, 6000, alpha=0.15)
    pyplot.axhspan(6000, 12000, alpha=0.10)
    pyplot.title(title)
    pyplot.xlabel("time (s)")
    pyplot.ylabel("frequency (Hz)")
    pyplot.colorbar(label="dB, fixed -110..-35")
    pyplot.tight_layout()
    pyplot.savefig(dest, **spectrogram_save_kwargs(dest, jpeg_quality))
    pyplot.close()


@profile
def save_high_detail_spectrogram_plot(
    audio: np.ndarray,
    title: str,
    dest: Path,
    *,
    sample_rate: int,
    signal_module,
    pyplot,
    jpeg_quality: int,
    spectrogram: SpectrogramData | None = None,
) -> None:
    freqs, times, spec_db = _spectrogram_or_compute(
        audio, sample_rate, signal_module, spectrogram
    )
    if spec_db.size == 0:
        return
    mask = (freqs >= 2500) & (freqs <= 16000)
    if not np.any(mask):
        return
    freqs, times, focus = decimate_spectrogram_for_plot(
        freqs[mask], times, spec_db[mask]
    )
    vmin, vmax = -110.0, -35.0
    pyplot.figure(figsize=(14, 5))
    pyplot.pcolormesh(
        times,
        freqs,
        focus,
        shading="auto",
        vmin=vmin,
        vmax=vmax,
        cmap="inferno",
    )
    pyplot.yscale("log")
    pyplot.ylim(2500, 16000)
    pyplot.axhline(4000, linestyle="--", linewidth=0.8)
    pyplot.axhline(8000, linestyle=":", linewidth=0.9)
    pyplot.title(f"{title} — high-frequency detail")
    pyplot.xlabel("time (s)")
    pyplot.ylabel("frequency (Hz)")
    pyplot.colorbar(label=f"dB, fixed {vmin:.0f}..{vmax:.0f}")
    pyplot.tight_layout()
    pyplot.savefig(dest, **spectrogram_save_kwargs(dest, jpeg_quality))
    pyplot.close()


@profile
def save_shrill_detail_spectrogram_plot(
    audio: np.ndarray,
    title: str,
    dest: Path,
    *,
    sample_rate: int,
    signal_module,
    pyplot,
    jpeg_quality: int,
    spectrogram: SpectrogramData | None = None,
) -> None:
    freqs, times, spec_db = _spectrogram_or_compute(
        audio, sample_rate, signal_module, spectrogram
    )
    if spec_db.size == 0:
        return
    mask = (freqs >= 3500) & (freqs <= 12500)
    if not np.any(mask):
        return
    freqs, times, focus = decimate_spectrogram_for_plot(
        freqs[mask], times, spec_db[mask]
    )
    vmin, vmax = -110.0, -35.0
    pyplot.figure(figsize=(14, 5))
    pyplot.pcolormesh(
        times,
        freqs,
        focus,
        shading="auto",
        vmin=vmin,
        vmax=vmax,
        cmap="inferno",
    )
    pyplot.ylim(3500, 12500)
    for hz, label in (
        (4000, "4k review"),
        (6000, "6k piercing"),
        (8000, "8k whistle"),
        (10000, "10k extreme"),
    ):
        pyplot.axhline(hz, linestyle="--", linewidth=0.7)
        if times.size:
            pyplot.text(float(times[0]), hz * 1.01, label, fontsize=7, va="bottom")
    pyplot.title(f"{title} — shrill-band detail")
    pyplot.xlabel("time (s)")
    pyplot.ylabel("frequency (Hz, linear)")
    pyplot.colorbar(label=f"dB, fixed {vmin:.0f}..{vmax:.0f}")
    pyplot.tight_layout()
    pyplot.savefig(dest, **spectrogram_save_kwargs(dest, jpeg_quality))
    pyplot.close()


@profile
def write_spectrograms(
    outdir: Path,
    manifest: dict,
    plots_dir: Path,
    *,
    limit: int = 16,
    plot_format: str = "jpg",
    jpeg_quality: int = 84,
) -> list[Path]:
    """Write compact spectrogram plots for retained stems and key previews.

    Matplotlib is intentionally optional. If it is not installed, write a clear
    note and let the rest of the bundle succeed.
    """
    plots_dir.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib.pyplot as plt
        from scipy import signal
    except Exception as ex:  # noqa: BLE001
        note = plots_dir / "spectrograms_skipped.txt"
        note.write_text(
            f"spectrogram generation skipped: {type(ex).__name__}: {ex}\n",
            encoding="utf8",
        )
        return []

    sample_rate = int(manifest.get("sample_rate", 48000))
    written: list[Path] = []

    candidates: list[tuple[str, Path, str]] = []
    for npy in current_scratch_stem_paths(outdir, manifest):
        candidates.append(("npy", npy, npy.stem.split(".")[-1]))
    files = manifest.get("files") or {}
    preview = files.get("preview") or {}
    if isinstance(preview, dict):
        for name, rel in sorted(preview.items()):
            if isinstance(rel, str):
                candidates.append(("audio", outdir / rel, f"preview_{name}"))

    if len(candidates) > limit:
        note = plots_dir / "spectrograms_truncated.txt"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            f"only the first {limit} of {len(candidates)} stems/previews were plotted\n",
            encoding="utf8",
        )
    for kind, path, label in candidates[:limit]:
        try:
            file_sample_rate = sample_rate
            if kind == "npy":
                audio = np.load(path).astype("float32", copy=False)
            else:
                import soundfile as sf

                # Use the file's real rate: if it differs from the manifest,
                # trusting the manifest would mislabel every frequency axis.
                audio, file_sample_rate = sf.read(
                    path, always_2d=True, dtype="float32"
                )
            # All three views share the same full-resolution STFT. Numerical
            # audits are separate and retain their original resolution.
            spectrogram = spectrogram_db(audio, int(file_sample_rate), signal)
            suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
            dest = plots_dir / f"{label}.spectrogram.{suffix}"
            save_audio_spectrogram_plot(
                audio,
                label,
                dest,
                sample_rate=int(file_sample_rate),
                signal_module=signal,
                pyplot=plt,
                jpeg_quality=jpeg_quality,
                spectrogram=spectrogram,
            )
            if dest.exists():
                written.append(dest)
            high_dest = plots_dir / f"{label}.spectrogram_high_detail.{suffix}"
            save_high_detail_spectrogram_plot(
                audio,
                label,
                high_dest,
                sample_rate=int(file_sample_rate),
                signal_module=signal,
                pyplot=plt,
                jpeg_quality=jpeg_quality,
                spectrogram=spectrogram,
            )
            if high_dest.exists():
                written.append(high_dest)
            shrill_dest = plots_dir / f"{label}.spectrogram_shrill_detail.{suffix}"
            save_shrill_detail_spectrogram_plot(
                audio,
                label,
                shrill_dest,
                sample_rate=int(file_sample_rate),
                signal_module=signal,
                pyplot=plt,
                jpeg_quality=jpeg_quality,
                spectrogram=spectrogram,
            )
            if shrill_dest.exists():
                written.append(shrill_dest)
        except Exception as ex:  # noqa: BLE001
            (plots_dir / f"{label}.spectrogram.error.txt").write_text(
                f"failed to render {path}: {type(ex).__name__}: {ex}\n",
                encoding="utf8",
            )
    return written
