"""Reference-audio analysis for music direction.

This is intentionally not source separation. It extracts LLM- and human-friendly
surface features from an existing audio file: loudness envelope, dynamic range,
rough spectral-band balance, brightness, and onset-density proxies. That is
useful when trying to mimic the *shape* of a reference track without pretending
we can recover its stems.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

BANDS = [
    ("sub", 20.0, 80.0),
    ("bass", 80.0, 250.0),
    ("low_mid", 250.0, 700.0),
    ("mid", 700.0, 2000.0),
    ("presence", 2000.0, 6000.0),
    ("air", 6000.0, 12000.0),
]


def _db(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-12))


def _read_audio(path: Path) -> tuple[np.ndarray, int, str]:
    """Read audio as stereo float32.

    ``soundfile`` handles WAV/FLAC/OGG on most systems. MP3 support depends on
    the local libsndfile build, so we fall back to ffmpeg when available.
    """
    try:
        import soundfile as sf

        audio, sr = sf.read(path, always_2d=True, dtype="float32")
        return audio.astype("float32", copy=False), int(sr), "soundfile"
    except Exception as sf_ex:  # noqa: BLE001
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=sample_rate,channels",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            info = json.loads(probe.stdout)
            stream = (info.get("streams") or [{}])[0]
            sr = int(stream.get("sample_rate") or 48000)
            cmd = [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-f",
                "f32le",
                "-ac",
                "2",
                "-ar",
                str(sr),
                "pipe:1",
            ]
            raw = subprocess.check_output(cmd)
            audio = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
            return audio.astype("float32", copy=False), sr, "ffmpeg"
        except Exception as ff_ex:  # noqa: BLE001
            raise RuntimeError(
                f"could not decode {path}; soundfile failed with {sf_ex!r}, ffmpeg failed with {ff_ex!r}"
            ) from ff_ex


def _mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=1).astype("float32", copy=False) if audio.ndim == 2 else audio.astype("float32", copy=False)


def _frames(mono: np.ndarray, sr: int, frame_seconds: float = 0.5) -> list[tuple[int, int]]:
    hop = max(1, int(round(sr * frame_seconds)))
    return [(start, min(len(mono), start + hop)) for start in range(0, len(mono), hop)]


def analyze_audio(path: Path, *, frame_seconds: float = 0.5) -> dict[str, Any]:
    audio, sr, decoder = _read_audio(path)
    mono = _mono(audio)
    duration = float(len(mono) / sr) if sr else 0.0
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float64))) if mono.size else 0.0

    envelope: list[dict[str, float]] = []
    spectral_frames: list[np.ndarray] = []
    centroid_values: list[float] = []
    band_energy_totals = {name: 0.0 for name, _lo, _hi in BANDS}
    flux_values: list[float] = []
    prev_mag: np.ndarray | None = None

    for start, stop in _frames(mono, sr, frame_seconds):
        chunk = mono[start:stop]
        if chunk.size < 16:
            continue
        frame_rms = float(np.sqrt(np.mean(np.square(chunk), dtype=np.float64)))
        frame_peak = float(np.max(np.abs(chunk)))
        window = np.hanning(len(chunk)).astype("float32")
        spec = np.fft.rfft(chunk * window)
        freqs = np.fft.rfftfreq(len(chunk), d=1.0 / sr)
        mag = np.abs(spec).astype("float64")
        power = np.square(mag)
        total_power = float(power.sum())
        centroid = float((freqs * power).sum() / total_power) if total_power > 0 else 0.0
        centroid_values.append(centroid)
        if prev_mag is not None and prev_mag.shape == mag.shape:
            flux_values.append(float(np.maximum(mag - prev_mag, 0.0).sum()))
        prev_mag = mag
        band_fracs: dict[str, float] = {}
        for name, lo, hi in BANDS:
            mask = (freqs >= lo) & (freqs < hi)
            val = float(power[mask].sum()) if np.any(mask) else 0.0
            band_energy_totals[name] += val
            band_fracs[name] = val / total_power if total_power > 0 else 0.0
        envelope.append(
            {
                "time_start_s": float(start / sr),
                "time_end_s": float(stop / sr),
                "rms_dbfs": _db(frame_rms),
                "peak_dbfs": _db(frame_peak),
                "spectral_centroid_hz": centroid,
                **{f"band_{k}": v for k, v in band_fracs.items()},
            }
        )
        spectral_frames.append(power)

    rms_values = np.array([row["rms_dbfs"] for row in envelope], dtype="float64") if envelope else np.array([])
    centroid_arr = np.array(centroid_values, dtype="float64") if centroid_values else np.array([])
    flux_arr = np.array(flux_values, dtype="float64") if flux_values else np.array([])
    if flux_arr.size:
        threshold = float(np.percentile(flux_arr, 85))
        onset_proxy_count = int(np.sum(flux_arr > threshold))
    else:
        onset_proxy_count = 0
    band_total = sum(band_energy_totals.values())
    band_fractions = {
        name: (float(value) / band_total if band_total > 0 else 0.0)
        for name, value in band_energy_totals.items()
    }

    return {
        "schema": "ambition.reference_audio_audit.v1",
        "path": str(path),
        "decoder": decoder,
        "sample_rate": sr,
        "duration_s": duration,
        "channels": int(audio.shape[1]) if audio.ndim == 2 else 1,
        "overall": {
            "rms_dbfs": _db(rms),
            "peak_dbfs": _db(peak),
            "crest_db": _db(peak) - _db(rms) if rms > 0 else 0.0,
            "envelope_p10_dbfs": float(np.percentile(rms_values, 10)) if rms_values.size else -120.0,
            "envelope_p50_dbfs": float(np.percentile(rms_values, 50)) if rms_values.size else -120.0,
            "envelope_p90_dbfs": float(np.percentile(rms_values, 90)) if rms_values.size else -120.0,
            "envelope_dynamic_range_db": float(np.percentile(rms_values, 90) - np.percentile(rms_values, 10)) if rms_values.size else 0.0,
            "spectral_centroid_mean_hz": float(centroid_arr.mean()) if centroid_arr.size else 0.0,
            "spectral_centroid_p90_hz": float(np.percentile(centroid_arr, 90)) if centroid_arr.size else 0.0,
            "onset_proxy_per_second": float(onset_proxy_count / duration) if duration > 0 else 0.0,
        },
        "band_fractions": band_fractions,
        "envelope": envelope,
        "note": "Surface-feature analysis only; this does not decompose stems or infer instrumentation.",
    }


def write_reports(payload: dict[str, Any], outdir: Path, *, plot_format: str = "jpg", jpeg_quality: int = 86) -> dict[str, str]:
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "reference_audio_audit.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    env_path = outdir / "reference_audio_envelope.tsv"
    env_cols = ["time_start_s", "time_end_s", "rms_dbfs", "peak_dbfs", "spectral_centroid_hz"] + [f"band_{b[0]}" for b in BANDS]
    lines = ["\t".join(env_cols)]
    for row in payload.get("envelope", []):
        lines.append("\t".join(f"{float(row.get(c, 0.0)):.6f}" for c in env_cols))
    env_path.write_text("\n".join(lines) + "\n", encoding="utf8")

    summary = outdir / "reference_audio_summary.txt"
    overall = payload.get("overall", {})
    bands = payload.get("band_fractions", {})
    text = [
        f"path: {payload.get('path')}",
        f"decoder: {payload.get('decoder')}",
        f"duration_s: {float(payload.get('duration_s', 0.0)):.2f}",
        f"rms_dbfs: {float(overall.get('rms_dbfs', -120.0)):.1f}",
        f"peak_dbfs: {float(overall.get('peak_dbfs', -120.0)):.1f}",
        f"crest_db: {float(overall.get('crest_db', 0.0)):.1f}",
        f"envelope_dynamic_range_db: {float(overall.get('envelope_dynamic_range_db', 0.0)):.1f}",
        f"spectral_centroid_mean_hz: {float(overall.get('spectral_centroid_mean_hz', 0.0)):.0f}",
        f"onset_proxy_per_second: {float(overall.get('onset_proxy_per_second', 0.0)):.2f}",
        "",
        "band fractions:",
    ]
    for name, value in sorted(bands.items(), key=lambda item: item[1], reverse=True):
        text.append(f"  {name}: {float(value) * 100:.1f}%")
    summary.write_text("\n".join(text) + "\n", encoding="utf8")

    paths = {"json": str(json_path), "summary": str(summary), "envelope": str(env_path)}
    try:
        import matplotlib.pyplot as plt

        suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
        save_kwargs: dict[str, object] = {"dpi": 130, "bbox_inches": "tight"}
        if suffix == "jpg":
            save_kwargs["format"] = "jpeg"
            save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality), "optimize": True}
        env = payload.get("envelope", [])
        if env:
            xs = [(float(r["time_start_s"]) + float(r["time_end_s"])) * 0.5 for r in env]
            fig, ax = plt.subplots(figsize=(11, 4.0))
            ax.plot(xs, [float(r["rms_dbfs"]) for r in env], label="RMS")
            ax.plot(xs, [float(r["peak_dbfs"]) for r in env], label="Peak")
            ax.set_title("Reference loudness envelope")
            ax.set_xlabel("time (s)")
            ax.set_ylabel("dBFS")
            ax.grid(True, alpha=0.3)
            ax.legend(loc="best")
            plot_path = outdir / f"reference_loudness_envelope.{suffix}"
            fig.savefig(plot_path, **save_kwargs)
            plt.close(fig)
            paths["loudness_plot"] = str(plot_path)

            fig, ax = plt.subplots(figsize=(11, 4.0))
            ax.plot(xs, [float(r["spectral_centroid_hz"]) for r in env], label="centroid")
            ax.set_title("Reference brightness proxy")
            ax.set_xlabel("time (s)")
            ax.set_ylabel("spectral centroid (Hz)")
            ax.grid(True, alpha=0.3)
            plot_path = outdir / f"reference_brightness.{suffix}"
            fig.savefig(plot_path, **save_kwargs)
            plt.close(fig)
            paths["brightness_plot"] = str(plot_path)
    except Exception as ex:  # noqa: BLE001
        (outdir / "reference_audio_plots_skipped.txt").write_text(f"plots skipped: {type(ex).__name__}: {ex}\n", encoding="utf8")
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="reference audio file, e.g. WAV/OGG/MP3 if decoder support exists")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--frame-seconds", type=float, default=0.5)
    parser.add_argument("--plot-format", choices=["jpg", "png"], default="jpg")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = analyze_audio(args.audio, frame_seconds=args.frame_seconds)
    paths = write_reports(payload, args.outdir, plot_format=args.plot_format)
    print(paths["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
