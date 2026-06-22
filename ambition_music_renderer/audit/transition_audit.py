#!/usr/bin/env python3
"""Analyze and preview adaptive music section transitions outside the game.

The tool reads generated cue output from ``render_isolated.py`` and reports
basic level/transition metrics for two full-mix section files. It writes WAV
previews, CSV metrics, PNG plots, and a Markdown report so a transition can be
audited visually when the ear is not enough.
"""

from __future__ import annotations

from ..profiler import profile

import kwconf
import csv
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import soundfile as sf

try:
    from rich import print as rich_print
except Exception:  # pragma: no cover
    rich_print = print


# Mirrors crates/ambition_audio/src/music/mod.rs STEM_GAIN_BLEND_SECONDS.
# The runtime does not use an equal-power audio editor crossfade; it starts a
# new bank and smooths layer gains exponentially toward their target.
AMBITION_STEM_GAIN_BLEND_SECONDS = 0.18


@profile
def path_link(path: Path) -> str:
    resolved = path.resolve()
    return f"[link=file://{resolved}]{resolved}[/link]"


@profile
def db(value: float) -> float:
    value = max(float(value), 1e-12)
    return 20.0 * math.log10(value)


@profile
def read_audio(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(path, always_2d=True, dtype="float32")
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    return audio.astype("float32", copy=False), int(sample_rate)


@profile
def ensure_length(audio: np.ndarray, frames: int) -> np.ndarray:
    if audio.shape[0] >= frames:
        return audio[:frames]
    pad = np.zeros((frames - audio.shape[0], audio.shape[1]), dtype=audio.dtype)
    return np.concatenate([audio, pad], axis=0)


@profile
def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))


@profile
def peak(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.max(np.abs(audio)))


@profile
def high_band_ratio(
    audio: np.ndarray, sample_rate: int, cutoff_hz: float = 8000.0
) -> float:
    """Approximate hiss/air as high-frequency energy ratio.

    This is intentionally simple: it is not a psychoacoustic noise metric, but
    it is useful for comparing generated sections quickly.
    """
    if audio.size == 0:
        return 0.0
    mono = np.mean(audio, axis=1)
    if mono.size < 64:
        return 0.0
    window = np.hanning(mono.size)
    spectrum = np.fft.rfft(mono * window)
    power = np.square(np.abs(spectrum))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / float(sample_rate))
    total = float(np.sum(power))
    if total <= 1e-20:
        return 0.0
    high = float(np.sum(power[freqs >= cutoff_hz]))
    return high / total


@profile
def section_file(root: Path, section: str) -> Path:
    section_dir = root / "adaptive" / section
    if not section_dir.exists():
        raise FileNotFoundError(f"missing section directory: {section_dir}")
    candidates: list[Path] = []
    for suffix in ("ogg", "oga", "wav", "flac", "mp3"):
        candidates.extend(sorted(section_dir.glob(f"*{section}.full.{suffix}")))
    if not candidates:
        for suffix in ("ogg", "oga", "wav", "flac", "mp3"):
            candidates.extend(sorted(section_dir.glob(f"*.full.{suffix}")))
    if not candidates:
        raise FileNotFoundError(f"no full-mix audio under {section_dir}")
    # Prefer stable installed names when present; otherwise use hashed renderer output.
    candidates.sort(
        key=lambda p: (p.name != f"{section}.full.ogg", len(p.name), p.name)
    )
    return candidates[0]


@profile
def stats_for(
    path: Path, *, sample_window_seconds: float, tail_window_seconds: float
) -> dict[str, float | str]:
    audio, sample_rate = read_audio(path)
    head_frames = max(1, int(round(sample_window_seconds * sample_rate)))
    tail_frames = max(1, int(round(tail_window_seconds * sample_rate)))
    head = audio[:head_frames]
    tail = audio[-tail_frames:]
    duration = audio.shape[0] / float(sample_rate)
    return {
        "path": str(path),
        "duration": duration,
        "peak": peak(audio),
        "peak_db": db(peak(audio)),
        "rms": rms(audio),
        "rms_db": db(rms(audio)),
        "head_rms_db": db(rms(head)),
        "tail_rms_db": db(rms(tail)),
        "tail_to_full_db": db(rms(tail)) - db(rms(audio)),
        "high_band_ratio": high_band_ratio(audio, sample_rate),
        "tail_high_band_ratio": high_band_ratio(tail, sample_rate),
    }


@profile
def fade(length: int, *, direction: str, shape: str = "linear") -> np.ndarray:
    if length <= 0:
        return np.zeros((0, 1), dtype="float32")
    phase = np.linspace(0.0, 1.0, length, endpoint=True, dtype="float32")
    if shape == "linear":
        if direction == "in":
            values = phase
        elif direction == "out":
            values = 1.0 - phase
        else:
            raise ValueError(direction)
    elif shape in {"equal_power", "equal-power"}:
        # Linear-amplitude crossfades can create a visible RMS dip when the two
        # sections are not correlated. Equal-power fades preserve perceived
        # energy better: outgoing=cos(theta), incoming=sin(theta).
        theta = phase * (0.5 * math.pi)
        if direction == "in":
            values = np.sin(theta)
        elif direction == "out":
            values = np.cos(theta)
        else:
            raise ValueError(direction)
    elif shape in {"ambition_runtime", "ambition-runtime"}:
        # Handled by transition_components because the incoming bank may start
        # at target for intro->loop, but keep a fallback for direct callers.
        t = phase * AMBITION_STEM_GAIN_BLEND_SECONDS
        if direction == "in":
            values = 1.0 - np.exp(-t / AMBITION_STEM_GAIN_BLEND_SECONDS)
        elif direction == "out":
            values = np.exp(-t / AMBITION_STEM_GAIN_BLEND_SECONDS)
        else:
            raise ValueError(direction)
    else:
        raise ValueError(f"unknown crossfade shape: {shape}")
    return values.astype("float32", copy=False)[:, None]


@profile
def transition_components(
    first_path: Path,
    second_path: Path,
    *,
    crossfade_seconds: float,
    context_seconds: float,
    level_match_second: bool = False,
    crossfade_shape: str = "linear",
    incoming_start: str = "smooth",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    first, sr1 = read_audio(first_path)
    second, sr2 = read_audio(second_path)
    if sr1 != sr2:
        raise ValueError(f"sample-rate mismatch: {sr1} vs {sr2}")
    sr = sr1
    context_frames = max(1, int(round(context_seconds * sr)))
    crossfade_frames = max(1, int(round(crossfade_seconds * sr)))
    first_tail = first[-context_frames:]
    second_head = ensure_length(second, context_frames)

    if level_match_second:
        # Match second head RMS to first tail RMS for diagnosis only. If this
        # preview sounds smooth but the raw preview does not, the seam is mostly
        # gain/mastering. If both are obvious, the arrangement/timbre boundary is
        # the larger issue.
        gain = rms(first_tail) / max(rms(second_head), 1e-8)
        second_head = np.clip(second_head * gain, -1.0, 1.0)

    zeros_pre = np.zeros_like(first_tail[:-crossfade_frames])
    zeros_post = np.zeros_like(second_head[crossfade_frames:])
    if crossfade_shape in {"ambition_runtime", "ambition-runtime"}:
        t = np.linspace(0.0, crossfade_seconds, crossfade_frames, endpoint=True, dtype="float32")
        outgoing_gain = np.exp(-t / AMBITION_STEM_GAIN_BLEND_SECONDS).astype("float32")[:, None]
        if incoming_start == "target":
            incoming_gain = np.ones((crossfade_frames, 1), dtype="float32")
        elif incoming_start == "smooth":
            incoming_gain = (1.0 - np.exp(-t / AMBITION_STEM_GAIN_BLEND_SECONDS)).astype("float32")[:, None]
        else:
            raise ValueError(f"unknown incoming_start: {incoming_start}")
        tail_gain = incoming_gain[-1:] if incoming_start == "smooth" else np.ones((1, 1), dtype="float32")
        second_tail = second_head[crossfade_frames:] * tail_gain
    else:
        outgoing_gain = fade(crossfade_frames, direction="out", shape=crossfade_shape)
        incoming_gain = fade(crossfade_frames, direction="in", shape=crossfade_shape)
        second_tail = second_head[crossfade_frames:]
    outgoing = np.concatenate(
        [
            first_tail[:-crossfade_frames],
            first_tail[-crossfade_frames:] * outgoing_gain,
            zeros_post,
        ],
        axis=0,
    )
    incoming = np.concatenate(
        [
            zeros_pre,
            second_head[:crossfade_frames] * incoming_gain,
            second_tail,
        ],
        axis=0,
    )
    preview = outgoing + incoming
    return outgoing, incoming, preview, sr


@profile
def write_runtime_preview(
    first_path: Path,
    second_path: Path,
    output: Path,
    *,
    crossfade_seconds: float,
    context_seconds: float,
    level_match_second: bool = False,
    crossfade_shape: str = "linear",
    incoming_start: str = "smooth",
) -> None:
    _, _, preview, sr = transition_components(
        first_path,
        second_path,
        crossfade_seconds=crossfade_seconds,
        context_seconds=context_seconds,
        level_match_second=level_match_second,
        crossfade_shape=crossfade_shape,
        incoming_start=incoming_start,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, preview, sr)


@profile
def mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio.astype("float32", copy=False)
    return np.mean(audio, axis=1).astype("float32", copy=False)


@profile
def windowed_rms_db(
    audio: np.ndarray, sample_rate: int, *, window_ms: float, hop_ms: float
) -> tuple[np.ndarray, np.ndarray]:
    signal = mono(audio)
    win = max(1, int(round(sample_rate * window_ms / 1000.0)))
    hop = max(1, int(round(sample_rate * hop_ms / 1000.0)))
    if signal.size < win:
        signal = np.pad(signal, (0, win - signal.size))
    times: list[float] = []
    values: list[float] = []
    for start in range(0, max(1, signal.size - win + 1), hop):
        chunk = signal[start : start + win]
        times.append((start + 0.5 * win) / float(sample_rate))
        values.append(db(rms(chunk[:, None])))
    return np.asarray(times, dtype="float32"), np.asarray(values, dtype="float32")


@profile
def windowed_peak_db(
    audio: np.ndarray, sample_rate: int, *, window_ms: float, hop_ms: float
) -> tuple[np.ndarray, np.ndarray]:
    signal = mono(audio)
    win = max(1, int(round(sample_rate * window_ms / 1000.0)))
    hop = max(1, int(round(sample_rate * hop_ms / 1000.0)))
    if signal.size < win:
        signal = np.pad(signal, (0, win - signal.size))
    times: list[float] = []
    values: list[float] = []
    for start in range(0, max(1, signal.size - win + 1), hop):
        chunk = signal[start : start + win]
        times.append((start + 0.5 * win) / float(sample_rate))
        values.append(db(peak(chunk[:, None])))
    return np.asarray(times, dtype="float32"), np.asarray(values, dtype="float32")


@profile
def spectrogram_db(
    audio: np.ndarray, sample_rate: int, *, n_fft: int = 2048, hop: int = 512
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    signal = mono(audio)
    if signal.size < n_fft:
        signal = np.pad(signal, (0, n_fft - signal.size))
    window = np.hanning(n_fft).astype("float32")
    frames: list[np.ndarray] = []
    times: list[float] = []
    for start in range(0, signal.size - n_fft + 1, hop):
        frame = signal[start : start + n_fft] * window
        power = np.square(np.abs(np.fft.rfft(frame)))
        frames.append(10.0 * np.log10(np.maximum(power, 1e-16)))
        times.append((start + 0.5 * n_fft) / float(sample_rate))
    spec = (
        np.stack(frames, axis=1)
        if frames
        else np.zeros((n_fft // 2 + 1, 0), dtype="float32")
    )
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / float(sample_rate))
    return (
        np.asarray(times, dtype="float32"),
        freqs.astype("float32"),
        spec.astype("float32"),
    )


@profile
def load_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except Exception as ex:  # pragma: no cover - optional authoring dependency
        rich_print(f"[yellow]plotting skipped[/yellow] matplotlib is unavailable: {ex}")
        return None


@profile
def plot_transition_components(
    path_a: Path,
    path_b: Path,
    output: Path,
    *,
    crossfade_seconds: float,
    context_seconds: float,
    window_ms: float,
    hop_ms: float,
    crossfade_shape: str = "linear",
    incoming_start: str = "smooth",
) -> Path | None:
    plt = load_matplotlib()
    if plt is None:
        return None
    outgoing, incoming, summed, sample_rate = transition_components(
        path_a,
        path_b,
        crossfade_seconds=crossfade_seconds,
        context_seconds=context_seconds,
        level_match_second=False,
        crossfade_shape=crossfade_shape,
        incoming_start=incoming_start,
    )
    t_out, y_out = windowed_rms_db(
        outgoing, sample_rate, window_ms=window_ms, hop_ms=hop_ms
    )
    t_in, y_in = windowed_rms_db(
        incoming, sample_rate, window_ms=window_ms, hop_ms=hop_ms
    )
    t_sum, y_sum = windowed_rms_db(
        summed, sample_rate, window_ms=window_ms, hop_ms=hop_ms
    )
    crossfade_start = max(0.0, context_seconds - crossfade_seconds)
    crossfade_end = context_seconds

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(t_out, y_out, label=f"outgoing {path_a.parent.name} RMS")
    ax.plot(t_in, y_in, label=f"incoming {path_b.parent.name} RMS")
    ax.plot(t_sum, y_sum, label="summed preview RMS", linewidth=2.0)
    ax.axvspan(
        crossfade_start, crossfade_end, alpha=0.18, label="runtime crossfade window"
    )
    ax.axvline(crossfade_start, linestyle="--", linewidth=1.0)
    ax.axvline(crossfade_end, linestyle="--", linewidth=1.0)
    ax.set_title("Transition components: outgoing vs incoming vs sum")
    ax.set_xlabel("seconds in preview")
    ax.set_ylabel("dBFS")
    ax.set_ylim(bottom=max(-80.0, float(np.nanmin(y_sum)) - 8.0), top=3.0)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


@profile
def plot_transition_envelope(
    preview_path: Path,
    output: Path,
    *,
    crossfade_seconds: float,
    context_seconds: float,
    window_ms: float,
    hop_ms: float,
) -> Path | None:
    plt = load_matplotlib()
    if plt is None:
        return None
    audio, sample_rate = read_audio(preview_path)
    t_rms, y_rms = windowed_rms_db(
        audio, sample_rate, window_ms=window_ms, hop_ms=hop_ms
    )
    t_peak, y_peak = windowed_peak_db(
        audio, sample_rate, window_ms=window_ms, hop_ms=hop_ms
    )
    crossfade_start = max(0.0, context_seconds - crossfade_seconds)
    crossfade_end = context_seconds

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(t_rms, y_rms, label="RMS envelope")
    ax.plot(t_peak, y_peak, label="Peak envelope", alpha=0.65)
    ax.axvspan(
        crossfade_start, crossfade_end, alpha=0.18, label="runtime crossfade window"
    )
    ax.axvline(crossfade_start, linestyle="--", linewidth=1.0)
    ax.axvline(crossfade_end, linestyle="--", linewidth=1.0)
    ax.set_title(f"Transition envelope: {preview_path.name}")
    ax.set_xlabel("seconds in preview")
    ax.set_ylabel("dBFS")
    ax.set_ylim(bottom=max(-80.0, float(np.nanmin(y_rms)) - 6.0), top=3.0)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


@profile
def plot_tail_head_comparison(
    path_a: Path,
    path_b: Path,
    output: Path,
    *,
    context_seconds: float,
    window_ms: float,
    hop_ms: float,
) -> Path | None:
    plt = load_matplotlib()
    if plt is None:
        return None
    audio_a, sr_a = read_audio(path_a)
    audio_b, sr_b = read_audio(path_b)
    if sr_a != sr_b:
        raise ValueError(f"sample-rate mismatch: {sr_a} vs {sr_b}")
    frames = max(1, int(round(context_seconds * sr_a)))
    tail_a = audio_a[-frames:]
    head_b = ensure_length(audio_b, frames)
    t_a, rms_a = windowed_rms_db(tail_a, sr_a, window_ms=window_ms, hop_ms=hop_ms)
    t_b, rms_b = windowed_rms_db(head_b, sr_a, window_ms=window_ms, hop_ms=hop_ms)
    _, peak_a = windowed_peak_db(tail_a, sr_a, window_ms=window_ms, hop_ms=hop_ms)
    _, peak_b = windowed_peak_db(head_b, sr_a, window_ms=window_ms, hop_ms=hop_ms)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(t_a - context_seconds, rms_a, label=f"{path_a.parent.name} tail RMS")
    ax.plot(t_b, rms_b, label=f"{path_b.parent.name} head RMS")
    ax.plot(
        t_a - context_seconds,
        peak_a,
        label=f"{path_a.parent.name} tail peak",
        alpha=0.55,
    )
    ax.plot(t_b, peak_b, label=f"{path_b.parent.name} head peak", alpha=0.55)
    ax.axvline(0.0, linestyle="--", linewidth=1.0, label="section boundary")
    ax.set_title("Tail/head level comparison")
    ax.set_xlabel("seconds relative to boundary")
    ax.set_ylabel("dBFS")
    ax.set_ylim(
        bottom=max(-80.0, float(min(np.nanmin(rms_a), np.nanmin(rms_b))) - 6.0), top=3.0
    )
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


@profile
def plot_preview_spectrogram(
    preview_path: Path,
    output: Path,
    *,
    crossfade_seconds: float,
    context_seconds: float,
) -> Path | None:
    plt = load_matplotlib()
    if plt is None:
        return None
    audio, sample_rate = read_audio(preview_path)
    times, freqs, spec = spectrogram_db(audio, sample_rate)
    if spec.size == 0:
        return None
    crossfade_start = max(0.0, context_seconds - crossfade_seconds)
    crossfade_end = context_seconds
    vmax = float(np.nanmax(spec))
    vmin = max(float(np.nanmin(spec)), vmax - 90.0)

    fig, ax = plt.subplots(figsize=(11, 5))
    image = ax.imshow(
        spec,
        origin="lower",
        aspect="auto",
        extent=[float(times[0]), float(times[-1]), float(freqs[0]), float(freqs[-1])],
        vmin=vmin,
        vmax=vmax,
    )
    ax.axvspan(crossfade_start, crossfade_end, alpha=0.18)
    ax.axvline(crossfade_start, linestyle="--", linewidth=1.0)
    ax.axvline(crossfade_end, linestyle="--", linewidth=1.0)
    ax.set_ylim(0, min(16000, sample_rate / 2))
    ax.set_title(f"Spectrogram: {preview_path.name}")
    ax.set_xlabel("seconds in preview")
    ax.set_ylabel("Hz")
    fig.colorbar(image, ax=ax, label="dB power")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


@profile
def crossfade_envelope_summary(
    path_a: Path,
    path_b: Path,
    *,
    crossfade_seconds: float,
    context_seconds: float,
    window_ms: float,
    hop_ms: float,
    crossfade_shape: str = "linear",
    incoming_start: str = "smooth",
) -> dict[str, float]:
    """Quantify the visible dip around the runtime-style crossfade."""
    _outgoing, _incoming, summed, sample_rate = transition_components(
        path_a,
        path_b,
        crossfade_seconds=crossfade_seconds,
        context_seconds=context_seconds,
        level_match_second=False,
        crossfade_shape=crossfade_shape,
        incoming_start=incoming_start,
    )
    times, values = windowed_rms_db(
        summed, sample_rate, window_ms=window_ms, hop_ms=hop_ms
    )
    crossfade_start = max(0.0, context_seconds - crossfade_seconds)
    crossfade_end = context_seconds
    pre_start = max(0.0, crossfade_start - 0.6)
    post_end = min(
        float(times[-1]) if times.size else crossfade_end, crossfade_end + 0.6
    )

    def finite_region(mask: np.ndarray) -> np.ndarray:
        region = values[mask]
        return region[np.isfinite(region)]

    cross = finite_region((times >= crossfade_start) & (times <= crossfade_end))
    pre = finite_region((times >= pre_start) & (times < crossfade_start))
    post = finite_region((times > crossfade_end) & (times <= post_end))
    if cross.size == 0:
        cross = np.asarray([float("nan")])
    if pre.size == 0:
        pre = np.asarray([float("nan")])
    if post.size == 0:
        post = np.asarray([float("nan")])
    pre_median = float(np.nanmedian(pre))
    post_median = float(np.nanmedian(post))
    floor = float(np.nanmin(cross))
    return {
        "crossfade_seconds": float(crossfade_seconds),
        "crossfade_floor_rms_db": floor,
        "pre_crossfade_median_rms_db": pre_median,
        "post_crossfade_median_rms_db": post_median,
        "dip_vs_pre_db": floor - pre_median,
        "dip_vs_post_db": floor - post_median,
    }


@profile
def write_markdown_report(
    path: Path,
    *,
    section_a: str,
    section_b: str,
    rows: list[dict[str, float | str]],
    generated_files: list[Path],
    raw_preview: Path | None,
    matched_preview: Path | None,
    crossfade_summary: dict[str, float] | None = None,
    crossfade_shape: str = "linear",
    incoming_start: str = "smooth",
) -> None:
    lookup = {str(row["section"]): row for row in rows}
    a = lookup.get(section_a, {})
    b = lookup.get(section_b, {})

    def fmt_delta(key: str) -> str:
        if key in a and key in b:
            return f"{float(b[key]) - float(a[key]):+.1f} dB"
        return "n/a"

    lines = [
        f"# Transition audit: {section_a} -> {section_b}",
        "",
        "## Quick interpretation",
        "",
        f"- Head RMS delta ({section_b} head - {section_a} head): {fmt_delta('head_rms_db')}",
        f"- Tail/head RMS delta ({section_b} head - {section_a} tail): "
        + (
            f"{float(b['head_rms_db']) - float(a['tail_rms_db']):+.1f} dB"
            if "head_rms_db" in b and "tail_rms_db" in a
            else "n/a"
        ),
        f"- Tail high-band ratio delta ({section_b} - {section_a}): "
        + (
            f"{100.0 * (float(b['tail_high_band_ratio']) - float(a['tail_high_band_ratio'])):+.2f} percentage points"
            if "tail_high_band_ratio" in b and "tail_high_band_ratio" in a
            else "n/a"
        ),
    ]
    if crossfade_summary:
        lines.extend(
            [
                f"- Runtime crossfade: {crossfade_summary['crossfade_seconds']:.2f}s ({crossfade_shape}, incoming_start={incoming_start})",
                f"- Crossfade floor RMS: {crossfade_summary['crossfade_floor_rms_db']:.1f} dBFS",
                f"- Crossfade dip vs pre-window median: {crossfade_summary['dip_vs_pre_db']:+.1f} dB",
                f"- Crossfade dip vs post-window median: {crossfade_summary['dip_vs_post_db']:+.1f} dB",
            ]
        )
    lines.extend(
        [
            "",
            "Use this report visually: a smooth handoff should have compatible tail/head RMS envelopes, no large high-frequency tail spike, no obvious spectral cliff at the crossfade window, and no deep dip in the component/summed RMS plot.",
            "",
            "## Audio previews",
            "",
        ]
    )
    if raw_preview:
        lines.append(f"- Runtime preview: `{raw_preview.name}`")
    if matched_preview:
        lines.append(f"- Level-matched diagnostic preview: `{matched_preview.name}`")
    lines.extend(["", "## Plots", ""])
    for file in generated_files:
        if file.suffix.lower() == ".png":
            lines.append(f"![{file.stem}]({file.name})")
            lines.append("")
    lines.extend(["## Metrics", "", "```csv"])
    metric_keys = [
        "section",
        "peak_db",
        "rms_db",
        "head_rms_db",
        "tail_rms_db",
        "tail_to_full_db",
        "high_band_ratio",
        "tail_high_band_ratio",
    ]
    lines.append(",".join(metric_keys))
    for row in rows:
        values = []
        for key in metric_keys:
            value = row.get(key, "")
            if isinstance(value, float):
                values.append(f"{value:.6g}")
            else:
                values.append(str(value))
        lines.append(",".join(values))
    lines.extend(["```", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf8")


@profile
def print_table(rows: list[dict[str, float | str]]) -> None:
    rich_print("[bold]transition audit[/bold]")
    rich_print(
        f"{'section':<12} {'peak_db':>8} {'rms_db':>8} {'head_db':>8} "
        f"{'tail_db':>8} {'tail/full':>9} {'hi%':>7} {'tail_hi%':>9}"
    )
    for row in rows:
        rich_print(
            f"{row['section']:<12} {row['peak_db']:8.1f} {row['rms_db']:8.1f} "
            f"{row['head_rms_db']:8.1f} {row['tail_rms_db']:8.1f} "
            f"{row['tail_to_full_db']:9.1f} {100.0 * row['high_band_ratio']:7.2f} "
            f"{100.0 * row['tail_high_band_ratio']:9.2f}"
        )


@profile
def write_csv(path: Path, rows: Iterable[dict[str, float | str]]) -> None:
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TransitionAuditConfig(kwconf.Config):
    """Audit adaptive section transition metrics and previews."""

    root: Path = kwconf.Value(None, position=1, parser=Path, help="generated cue root containing adaptive/<section>/")
    sections: list[str] = kwconf.Value(default_factory=lambda: ["intro", "wave1"], nargs=2)
    window: float = kwconf.Value(1.0, help="head/tail analysis window in seconds")
    tail_window: float = kwconf.Value(1.5, help="tail hiss/noise window in seconds")
    crossfade: float = kwconf.Value(0.35, help="runtime-style crossfade seconds")
    crossfade_shape: str = kwconf.Value("ambition_runtime", choices=["linear", "equal_power", "ambition_runtime"])
    incoming_start: str = kwconf.Value("smooth", choices=["smooth", "target"])
    context: float = kwconf.Value(4.0, help="seconds of each side to include in previews")
    outdir: Path | None = kwconf.Value(None, parser=Path)
    no_preview: bool = kwconf.Flag(False, help="only print metrics; do not write WAV previews")
    no_plots: bool = kwconf.Flag(False, help="skip plots and Markdown visual report")
    envelope_window_ms: float = kwconf.Value(80.0)
    envelope_hop_ms: float = kwconf.Value(20.0)


@profile
def main(argv: list[str] | None = None) -> int:
    args = TransitionAuditConfig.cli(argv=argv)


    root = args.root.resolve()
    outdir = (args.outdir or (root / "transition_audit")).resolve()
    section_a, section_b = args.sections
    path_a = section_file(root, section_a)
    path_b = section_file(root, section_b)

    rows = []
    for section, path in [(section_a, path_a), (section_b, path_b)]:
        row = stats_for(
            path,
            sample_window_seconds=args.window,
            tail_window_seconds=args.tail_window,
        )
        row["section"] = section
        rows.append(row)
    print_table(rows)
    csv_path = outdir / f"{section_a}_to_{section_b}_metrics.csv"
    write_csv(csv_path, rows)
    rich_print(f"[green]metrics[/green] {path_link(csv_path)}")

    generated_files: list[Path] = []
    raw_preview: Path | None = None
    matched_preview: Path | None = None
    crossfade_summary = crossfade_envelope_summary(
        path_a,
        path_b,
        crossfade_seconds=args.crossfade,
        context_seconds=args.context,
        window_ms=args.envelope_window_ms,
        hop_ms=args.envelope_hop_ms,
        crossfade_shape=args.crossfade_shape,
        incoming_start=args.incoming_start,
    )
    if not args.no_preview:
        raw_preview = outdir / f"{section_a}_to_{section_b}_runtime_preview.wav"
        matched_preview = (
            outdir / f"{section_a}_to_{section_b}_level_matched_preview.wav"
        )
        write_runtime_preview(
            path_a,
            path_b,
            raw_preview,
            crossfade_seconds=args.crossfade,
            context_seconds=args.context,
            level_match_second=False,
            crossfade_shape=args.crossfade_shape,
            incoming_start=args.incoming_start,
        )
        write_runtime_preview(
            path_a,
            path_b,
            matched_preview,
            crossfade_seconds=args.crossfade,
            context_seconds=args.context,
            level_match_second=True,
            crossfade_shape=args.crossfade_shape,
            incoming_start=args.incoming_start,
        )
        generated_files.extend([raw_preview, matched_preview])
        rich_print(f"[green]preview[/green] {path_link(raw_preview)}")
        rich_print(f"[green]preview[/green] {path_link(matched_preview)}")

    if not args.no_plots:
        plot_files: list[Path] = []
        tail_head = plot_tail_head_comparison(
            path_a,
            path_b,
            outdir / f"{section_a}_to_{section_b}_tail_head_envelope.png",
            context_seconds=args.context,
            window_ms=args.envelope_window_ms,
            hop_ms=args.envelope_hop_ms,
        )
        if tail_head is not None:
            plot_files.append(tail_head)
        if raw_preview is not None:
            components = plot_transition_components(
                path_a,
                path_b,
                outdir / f"{section_a}_to_{section_b}_component_envelope.png",
                crossfade_seconds=args.crossfade,
                context_seconds=args.context,
                window_ms=args.envelope_window_ms,
                hop_ms=args.envelope_hop_ms,
                crossfade_shape=args.crossfade_shape,
                incoming_start=args.incoming_start,
            )
            env = plot_transition_envelope(
                raw_preview,
                outdir / f"{section_a}_to_{section_b}_runtime_envelope.png",
                crossfade_seconds=args.crossfade,
                context_seconds=args.context,
                window_ms=args.envelope_window_ms,
                hop_ms=args.envelope_hop_ms,
            )
            spec = plot_preview_spectrogram(
                raw_preview,
                outdir / f"{section_a}_to_{section_b}_runtime_spectrogram.png",
                crossfade_seconds=args.crossfade,
                context_seconds=args.context,
            )
            if components is not None:
                plot_files.append(components)
            if env is not None:
                plot_files.append(env)
            if spec is not None:
                plot_files.append(spec)
        generated_files.extend(plot_files)
        for file in plot_files:
            rich_print(f"[green]plot[/green] {path_link(file)}")
        report = outdir / f"{section_a}_to_{section_b}_report.md"
        write_markdown_report(
            report,
            section_a=section_a,
            section_b=section_b,
            rows=rows,
            generated_files=plot_files,
            raw_preview=raw_preview,
            matched_preview=matched_preview,
            crossfade_summary=crossfade_summary,
            crossfade_shape=args.crossfade_shape,
            incoming_start=args.incoming_start,
        )
        rich_print(f"[green]report[/green] {path_link(report)}")

    rich_print(
        "[dim]Tip: if level_matched sounds smooth but runtime_preview does not, focus on mastering/gain. If both sounds obvious, focus on arrangement/timbre continuity. Use the component/envelope/spectrogram plots to spot outgoing/incoming handoff dips, loudness cliffs, noisy tails, or spectral discontinuities. Compare --crossfade-shape ambition_runtime vs equal_power to distinguish content holes from amplitude-curve dips.[/dim]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
