"""Spectrogram plotting helpers for bundle reports."""

from __future__ import annotations

from . import bundle_base as _bundle_base
from . import bundle_audio_reports as _bundle_audio_reports
from . import bundle_spectral_reports as _bundle_spectral_reports
from . import bundle_adaptive_reports as _bundle_adaptive_reports

globals().update({k: v for k, v in vars(_bundle_base).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_bundle_audio_reports).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_bundle_spectral_reports).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_bundle_adaptive_reports).items() if not k.startswith("__")})

@profile
def spectrogram_db(audio: np.ndarray, sample_rate: int, signal_module) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute a compact dB spectrogram for bundle plots."""
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio.astype("float32")
    if mono.size == 0:
        return np.asarray([]), np.asarray([]), np.asarray([[]])
    nperseg = min(4096, max(256, int(2 ** math.floor(math.log2(max(256, min(len(mono), 4096)))))))
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
def spectrogram_save_kwargs(dest: Path, jpeg_quality: int) -> dict:
    save_kwargs = {"dpi": 120}
    if dest.suffix.lower() in {".jpg", ".jpeg"}:
        save_kwargs["format"] = "jpeg"
        save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality), "optimize": True}
    return save_kwargs


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
) -> None:
    freqs, times, spec_db = spectrogram_db(audio, sample_rate, signal_module)
    if spec_db.size == 0:
        return
    pyplot.figure(figsize=(14, 5))
    pyplot.pcolormesh(times, freqs, spec_db, shading="auto", vmin=-110, vmax=-35, cmap="inferno")
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
) -> None:
    freqs, times, spec_db = spectrogram_db(audio, sample_rate, signal_module)
    if spec_db.size == 0:
        return
    mask = (freqs >= 2500) & (freqs <= 16000)
    if not np.any(mask):
        return
    focus = spec_db[mask]
    finite = focus[np.isfinite(focus)]
    if finite.size:
        vmax = float(np.percentile(finite, 99.7))
        vmin = max(vmax - 60.0, float(np.percentile(finite, 20.0)))
    else:
        vmin, vmax = -100.0, -40.0
    pyplot.figure(figsize=(14, 5))
    pyplot.pcolormesh(times, freqs[mask], focus, shading="auto", vmin=vmin, vmax=vmax, cmap="inferno")
    pyplot.yscale("log")
    pyplot.ylim(2500, 16000)
    pyplot.axhline(4000, linestyle="--", linewidth=0.8)
    pyplot.axhline(8000, linestyle=":", linewidth=0.9)
    pyplot.title(f"{title} — high-frequency detail")
    pyplot.xlabel("time (s)")
    pyplot.ylabel("frequency (Hz)")
    pyplot.colorbar(label=f"relative dB, local percentile {vmin:.0f}..{vmax:.0f}")
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
) -> None:
    freqs, times, spec_db = spectrogram_db(audio, sample_rate, signal_module)
    if spec_db.size == 0:
        return
    mask = (freqs >= 3500) & (freqs <= 12500)
    if not np.any(mask):
        return
    focus = spec_db[mask]
    finite = focus[np.isfinite(focus)]
    if finite.size:
        vmax = float(np.percentile(finite, 99.85))
        vmin = max(vmax - 48.0, float(np.percentile(finite, 35.0)))
    else:
        vmin, vmax = -95.0, -45.0
    pyplot.figure(figsize=(14, 5))
    pyplot.pcolormesh(times, freqs[mask], focus, shading="auto", vmin=vmin, vmax=vmax, cmap="inferno")
    pyplot.ylim(3500, 12500)
    for hz, label in ((4000, "4k review"), (6000, "6k piercing"), (8000, "8k whistle"), (10000, "10k extreme")):
        pyplot.axhline(hz, linestyle="--", linewidth=0.7)
        if times.size:
            pyplot.text(float(times[0]), hz * 1.01, label, fontsize=7, va="bottom")
    pyplot.title(f"{title} — shrill-band detail")
    pyplot.xlabel("time (s)")
    pyplot.ylabel("frequency (Hz, linear)")
    pyplot.colorbar(label=f"relative dB, local percentile {vmin:.0f}..{vmax:.0f}")
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
    """Write compact spectrogram PNGs for retained scratch stems and key previews.

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

    for kind, path, label in candidates[:limit]:
        try:
            if kind == "npy":
                audio = np.load(path).astype("float32", copy=False)
            else:
                import soundfile as sf

                audio, _sample_rate = sf.read(path, always_2d=True, dtype="float32")
            suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
            dest = plots_dir / f"{label}.spectrogram.{suffix}"
            save_audio_spectrogram_plot(audio, label, dest, sample_rate=sample_rate, signal_module=signal, pyplot=plt, jpeg_quality=jpeg_quality)
            if dest.exists():
                written.append(dest)
            high_dest = plots_dir / f"{label}.spectrogram_high_detail.{suffix}"
            save_high_detail_spectrogram_plot(audio, label, high_dest, sample_rate=sample_rate, signal_module=signal, pyplot=plt, jpeg_quality=jpeg_quality)
            if high_dest.exists():
                written.append(high_dest)
            shrill_dest = plots_dir / f"{label}.spectrogram_shrill_detail.{suffix}"
            save_shrill_detail_spectrogram_plot(audio, label, shrill_dest, sample_rate=sample_rate, signal_module=signal, pyplot=plt, jpeg_quality=jpeg_quality)
            if shrill_dest.exists():
                written.append(shrill_dest)
        except Exception as ex:  # noqa: BLE001
            (plots_dir / f"{label}.spectrogram.error.txt").write_text(
                f"failed to render {path}: {type(ex).__name__}: {ex}\n",
                encoding="utf8",
            )
    return written


