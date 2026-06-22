"""Spectral fingerprint and stem-amplitude analysis reports."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .audio_utils import coerce_stereo
from .bundle_base import (
    DBFS_PLOT_FLOOR,
    DBFS_SILENCE_FLOOR,
    _audio_stats,
    _db,
    _format_dbfs,
    _plot_db,
    current_scratch_stem_paths,
    manifest_audio_entries,
    manifest_duration,
    report_plot_save_kwargs,
    ordered_section_ids,
    section_time_offsets,
)

def write_spectral_fingerprint(
    outdir: Path,
    manifest: dict,
    reports_dir: Path,
    *,
    bucket_seconds: float = 1.0,
    max_events_per_band: int = 24,
) -> Path:
    """Write compact, LLM-friendly spectral summaries from scratch stems.

    The PNG/JPEG spectrograms are useful for human/vision review, but a chat
    agent can reason much more reliably from small JSON/TSV summaries. This
    report mirrors the broad bands used by ``spectral_localize.py`` and records
    per-band group fractions plus the strongest dominant time buckets.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    sample_rate = int(manifest.get("sample_rate", 48000))
    bands = [
        ("low", 0.0, 300.0),
        ("mid", 300.0, 1000.0),
        ("high", 1000.0, 3000.0),
        ("vhigh", 3000.0, 6000.0),
        ("air", 6000.0, 12000.0),
    ]
    paths = current_scratch_stem_paths(outdir, manifest)
    groups: list[str] = []
    audios: dict[str, np.ndarray] = {}
    max_frames = 0
    for path in paths:
        group = path.stem.split(".")[-1]
        try:
            arr = np.load(path).astype("float32", copy=False)
            arr = coerce_stereo(arr)
        except Exception:
            continue
        groups.append(group)
        audios[group] = arr.mean(axis=1).astype("float32", copy=False)
        max_frames = max(max_frames, len(audios[group]))

    frames_per_bucket = max(1, int(round(bucket_seconds * sample_rate)))
    bucket_count = max(1, int(math.ceil(max_frames / frames_per_bucket))) if max_frames else 0
    energy = {
        group: {band[0]: [0.0 for _ in range(bucket_count)] for band in bands}
        for group in groups
    }
    for group, mono in audios.items():
        for idx in range(bucket_count):
            start = idx * frames_per_bucket
            stop = min(len(mono), start + frames_per_bucket)
            chunk = mono[start:stop]
            if len(chunk) < 16:
                continue
            window = np.hanning(len(chunk)).astype("float32")
            spectrum = np.fft.rfft(chunk * window)
            freqs = np.fft.rfftfreq(len(chunk), d=1.0 / sample_rate)
            power = np.square(np.abs(spectrum)).astype("float64")
            for name, lo, hi in bands:
                mask = (freqs >= lo) & (freqs < hi)
                energy[group][name][idx] = float(power[mask].sum()) if np.any(mask) else 0.0

    mean_fractions: dict[str, dict[str, float]] = {}
    for name, _lo, _hi in bands:
        totals = {group: float(np.sum(energy[group][name])) for group in groups}
        denom = sum(totals.values())
        mean_fractions[name] = {
            group: (totals[group] / denom if denom > 0.0 else 0.0)
            for group in groups
        }

    dominant_events: dict[str, list[dict[str, object]]] = {}
    for name, _lo, _hi in bands:
        events: list[dict[str, object]] = []
        for idx in range(bucket_count):
            bucket_values = {group: energy[group][name][idx] for group in groups}
            total = sum(bucket_values.values())
            if total <= 0.0:
                continue
            top_group, top_energy = max(bucket_values.items(), key=lambda item: item[1])
            share = top_energy / total
            events.append(
                {
                    "time_start_s": round(idx * bucket_seconds, 3),
                    "time_end_s": round(min((idx + 1) * bucket_seconds, manifest_duration(manifest)), 3),
                    "group": top_group,
                    "share": share,
                    "band_energy": top_energy,
                }
            )
        events.sort(key=lambda row: (float(row["share"]), float(row["band_energy"])), reverse=True)
        dominant_events[name] = events[:max_events_per_band]

    payload = {
        "schema": "ambition.music_spectral_fingerprint.v1",
        "cue": manifest.get("id"),
        "hash": manifest.get("hash"),
        "sample_rate": sample_rate,
        "bucket_seconds": bucket_seconds,
        "groups": groups,
        "bands": [
            {"name": name, "low_hz": lo, "high_hz": hi} for name, lo, hi in bands
        ],
        "mean_band_fraction_by_group": mean_fractions,
        "dominant_events": dominant_events,
    }
    json_path = reports_dir / "spectral_fingerprint.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    tsv = reports_dir / "spectral_fingerprint.tsv"
    lines = ["band\tgroup\tmean_fraction"]
    for band_name, fractions in mean_fractions.items():
        for group, fraction in sorted(fractions.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"{band_name}\t{group}\t{fraction:.6f}")
    tsv.write_text("\n".join(lines) + "\n", encoding="utf8")

    summary = reports_dir / "spectral_fingerprint_summary.txt"
    text_lines: list[str] = [
        f"cue: {manifest.get('id')}",
        f"hash: {manifest.get('hash')}",
        f"bucket_seconds: {bucket_seconds}",
        "",
        "mean band fraction by group:",
    ]
    for band_name, fractions in mean_fractions.items():
        ordered = sorted(fractions.items(), key=lambda item: item[1], reverse=True)
        pieces = [f"{group} {fraction * 100:.1f}%" for group, fraction in ordered]
        text_lines.append(f"  {band_name}: " + ", ".join(pieces))
    text_lines.append("")
    text_lines.append("top dominant events:")
    for band_name, events in dominant_events.items():
        text_lines.append(f"  {band_name}:")
        for event in events[:8]:
            text_lines.append(
                f"    {event['time_start_s']:>6.2f}-{event['time_end_s']:>6.2f}s "
                f"{event['group']} {float(event['share']) * 100:.1f}%"
            )
    summary.write_text("\n".join(text_lines) + "\n", encoding="utf8")
    return json_path


def _rms_envelope(audio: np.ndarray, sample_rate: int, bucket_seconds: float) -> list[dict[str, float]]:
    """Return a short-time RMS envelope for plotting and report tables."""
    mono = audio.mean(axis=1).astype("float32", copy=False) if audio.ndim == 2 else audio.astype("float32", copy=False)
    hop = max(1, int(round(sample_rate * bucket_seconds)))
    rows: list[dict[str, float]] = []
    for start in range(0, len(mono), hop):
        stop = min(len(mono), start + hop)
        chunk = mono[start:stop]
        rms = float(np.sqrt(np.mean(np.square(chunk), dtype=np.float64))) if chunk.size else 0.0
        peak = float(np.max(np.abs(chunk))) if chunk.size else 0.0
        rows.append({
            "time_start_s": float(start / sample_rate),
            "time_end_s": float(stop / sample_rate),
            "rms_dbfs": _db(rms),
            "peak_dbfs": _db(peak),
            "rms_linear": rms,
            "peak_linear": peak,
        })
    return rows


def write_stem_amplitude_report(
    outdir: Path,
    spec: dict,
    manifest: dict,
    reports_dir: Path,
    plots_dir: Path | None = None,
    *,
    bucket_seconds: float = 0.5,
    plot_format: str = "jpg",
    jpeg_quality: int = 84,
) -> Path:
    """Write section-aware stem-level amplitude reports and plots.

    Adaptive section-stem cues contain the same group name in multiple section
    directories. Older reports keyed rows only by group, which meant later
    sections overwrote earlier sections and all envelopes were plotted from
    local t=0. This version keeps section/group rows distinct and adds absolute
    soundtrack time from the adaptive manifest.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    if plots_dir is not None:
        plots_dir.mkdir(parents=True, exist_ok=True)
    state_map = spec.get("state_map") or {}
    state_weights: dict[str, dict[str, float]] = {}
    if isinstance(state_map, dict):
        for state, cfg in state_map.items():
            if not isinstance(cfg, dict):
                continue
            stems = cfg.get("stems")
            if not isinstance(stems, dict):
                stems = cfg.get("fade_in")
            if isinstance(stems, dict):
                state_weights[str(state)] = {str(k): float(v) for k, v in stems.items()}

    default_weights = state_weights.get("default")
    default_is_raw_reference = default_weights is None
    offsets = section_time_offsets(manifest)

    rows_by_section_group: dict[tuple[str, str], dict[str, object]] = {}
    envelope_rows: list[dict[str, object]] = []
    sample_rate = int(manifest.get("sample_rate", 48000))
    for entry in manifest_audio_entries(manifest):
        if entry.get("kind") != "adaptive_audio":
            continue
        section = str(entry.get("section", ""))
        group = str(entry.get("group", ""))
        if not group or group == "full":
            continue
        path = outdir / str(entry["path"])
        try:
            import soundfile as sf
            audio, sr = sf.read(path, always_2d=True, dtype="float32")
            sample_rate = int(sr)
        except Exception as ex:  # noqa: BLE001
            rows_by_section_group[(section, group)] = {
                "group": group,
                "section": section,
                "section_start_s": offsets.get(section, 0.0),
                "path": entry.get("path"),
                "error": f"{type(ex).__name__}: {ex}",
            }
            continue
        stats = _audio_stats(audio.astype("float32", copy=False), sample_rate)
        default_weight = 1.0 if default_weights is None else float(default_weights.get(group, 0.0))
        row: dict[str, object] = {
            "group": group,
            "section": section,
            "section_start_s": offsets.get(section, 0.0),
            "path": entry.get("path"),
            "state_default_weight": default_weight,
            "state_default_is_raw_reference": default_is_raw_reference,
            "rms_dbfs": stats["rms_dbfs"],
            "peak_dbfs": stats["peak_dbfs"],
            "duration_s": stats["duration_s"],
            "weighted_default_rms_dbfs": stats["rms_dbfs"] + _db(default_weight) if default_weight > 0 else DBFS_SILENCE_FLOOR,
            "weighted_default_peak_dbfs": stats["peak_dbfs"] + _db(default_weight) if default_weight > 0 else DBFS_SILENCE_FLOOR,
            "error": "",
        }
        for state, weights in sorted(state_weights.items()):
            weight = float(weights.get(group, 0.0))
            row[f"state_{state}_weight"] = weight
            row[f"state_{state}_rms_dbfs"] = stats["rms_dbfs"] + _db(weight) if weight > 0 else DBFS_SILENCE_FLOOR
        rows_by_section_group[(section, group)] = row
        section_offset = float(offsets.get(section, 0.0))
        for env in _rms_envelope(audio, sample_rate, bucket_seconds):
            default_linear = float(env["rms_linear"] * default_weight)
            env_row: dict[str, object] = {
                "group": group,
                "section": section,
                "section_start_s": section_offset,
                "time_start_s": env["time_start_s"],
                "time_end_s": env["time_end_s"],
                "time_start_s_absolute": section_offset + float(env["time_start_s"]),
                "time_end_s_absolute": section_offset + float(env["time_end_s"]),
                "rms_dbfs": env["rms_dbfs"],
                "peak_dbfs": env["peak_dbfs"],
                "rms_linear": env["rms_linear"],
                "peak_linear": env["peak_linear"],
                "state_default_rms_linear": default_linear,
                "state_default_rms_dbfs": _db(default_linear),
            }
            envelope_rows.append(env_row)

    ordered_groups = sorted(
        rows_by_section_group.values(),
        key=lambda row: (
            str(row.get("section", "")),
            -float(row.get("weighted_default_rms_dbfs", DBFS_SILENCE_FLOOR)),
            str(row.get("group", "")),
        ),
    )
    payload = {
        "schema": "ambition.music_stem_amplitude.v1",
        "cue": manifest.get("id"),
        "hash": manifest.get("hash"),
        "bucket_seconds": bucket_seconds,
        # Backward-compatible key name; rows are now section/group rows.
        "groups": ordered_groups,
        "section_group_rows": ordered_groups,
        "envelope_rows": envelope_rows,
        "state_weights": state_weights,
        "default_is_raw_reference": default_is_raw_reference,
        "note": (
            "Rows are section/group scoped. When no explicit default state exists, "
            "weighted_default_* is a raw unweighted reference for plots, not a runtime default."
        ),
    }
    json_path = reports_dir / "stem_amplitude.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    columns = [
        "section",
        "group",
        "section_start_s",
        "state_default_weight",
        "rms_dbfs",
        "weighted_default_rms_dbfs",
        "peak_dbfs",
        "weighted_default_peak_dbfs",
        "duration_s",
        "path",
        "error",
    ]
    tsv_path = reports_dir / "stem_amplitude.tsv"
    lines = ["\t".join(columns)]
    for row in ordered_groups:
        lines.append("\t".join(f"{row.get(c, ''):.3f}" if isinstance(row.get(c, ""), float) else str(row.get(c, "")) for c in columns))
    tsv_path.write_text("\n".join(lines) + "\n", encoding="utf8")

    env_columns = [
        "section",
        "group",
        "time_start_s",
        "time_end_s",
        "time_start_s_absolute",
        "time_end_s_absolute",
        "rms_dbfs",
        "peak_dbfs",
        "state_default_rms_dbfs",
    ]
    env_tsv = reports_dir / "stem_amplitude_envelope.tsv"
    env_lines = ["\t".join(env_columns)]
    for row in envelope_rows:
        env_lines.append("\t".join(f"{row.get(c, ''):.3f}" if isinstance(row.get(c, ""), float) else str(row.get(c, "")) for c in env_columns))
    env_tsv.write_text("\n".join(env_lines) + "\n", encoding="utf8")

    summary = reports_dir / "stem_amplitude_summary.txt"
    text_lines = [
        f"cue: {manifest.get('id')}",
        f"hash: {manifest.get('hash')}",
        f"bucket_seconds: {bucket_seconds}",
        "section/group scoped: true",
    ]
    if default_is_raw_reference:
        text_lines.append("note: no explicit default state; weighted_default values use raw stem weight 1.0.")
    text_lines.extend(["", "section stem levels:"])
    by_section: dict[str, list[dict[str, object]]] = {}
    for row in ordered_groups:
        by_section.setdefault(str(row.get("section", "")), []).append(row)
    for section in ordered_section_ids(manifest) or sorted(by_section):
        rows = sorted(
            by_section.get(section, []),
            key=lambda row: float(row.get("weighted_default_rms_dbfs", DBFS_SILENCE_FLOOR)),
            reverse=True,
        )
        if not rows:
            continue
        text_lines.append(f"  {section}:")
        top = float(rows[0].get("weighted_default_rms_dbfs", DBFS_SILENCE_FLOOR))
        for row in rows:
            if row.get("error"):
                text_lines.append(f"    {row.get('group')}: ERROR {row.get('error')}")
            else:
                rel = float(row.get("weighted_default_rms_dbfs", DBFS_SILENCE_FLOOR)) - top
                text_lines.append(
                    f"    {row.get('group')}: raw {_format_dbfs(row.get('rms_dbfs', DBFS_SILENCE_FLOOR))} dBFS, "
                    f"weighted {_format_dbfs(row.get('weighted_default_rms_dbfs', DBFS_SILENCE_FLOOR))} dBFS, "
                    f"rel {rel:+.1f} dB, weight {float(row.get('state_default_weight', 0.0)):.2f}"
                )
    summary.write_text("\n".join(text_lines) + "\n", encoding="utf8")

    if plots_dir is not None and ordered_groups:
        try:
            import matplotlib.pyplot as plt
            suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
            save_kwargs = report_plot_save_kwargs(
                plot_format=suffix,
                jpeg_quality=jpeg_quality,
            )
            labels = [f"{row['section']}/{row['group']}" for row in ordered_groups if not row.get("error")]
            values = [_plot_db(float(row.get("weighted_default_rms_dbfs", DBFS_SILENCE_FLOOR))) for row in ordered_groups if not row.get("error")]
            if labels:
                fig, ax = plt.subplots(figsize=(9, max(3.5, 0.28 * len(labels) + 1.5)))
                positions = np.arange(len(labels))
                ax.barh(positions, values)
                ax.set_yticks(positions, labels=labels, fontsize=7)
                ax.invert_yaxis()
                ax.set_xlabel("weighted RMS (dBFS)")
                ax.set_title("Section/stem amplitude balance")
                ax.grid(True, axis="x", alpha=0.3)
                ax.set_xlim(DBFS_PLOT_FLOOR, 0.0)
                fig.savefig(plots_dir / f"stem_amplitude_balance.{suffix}", **save_kwargs)
                plt.close(fig)
            by_group: dict[str, list[dict[str, object]]] = {}
            for row in envelope_rows:
                by_group.setdefault(str(row["group"]), []).append(row)
            if by_group:
                fig, ax = plt.subplots(figsize=(12, 4.8))
                for group in sorted(by_group):
                    rows = sorted(by_group[group], key=lambda r0: float(r0["time_start_s_absolute"]))
                    xs = [(float(r0["time_start_s_absolute"]) + float(r0["time_end_s_absolute"])) * 0.5 for r0 in rows]
                    ys = [_plot_db(float(r0.get("state_default_rms_dbfs", DBFS_SILENCE_FLOOR))) for r0 in rows]
                    ax.plot(xs, ys, label=group)
                for section, start in sorted(offsets.items(), key=lambda item: item[1]):
                    if start > 0.0:
                        ax.axvline(start, alpha=0.18, linewidth=0.8)
                ax.set_xlabel("absolute soundtrack time (s)")
                ax.set_ylabel("weighted RMS (dBFS)")
                ax.set_title("Stem loudness over soundtrack time")
                ax.grid(True, alpha=0.3)
                ax.set_ylim(DBFS_PLOT_FLOOR, 0.0)
                ax.legend(loc="best", fontsize=8)
                fig.savefig(plots_dir / f"stem_loudness_timeline.{suffix}", **save_kwargs)
                fig.savefig(plots_dir / f"stem_amplitude_timeline.{suffix}", **save_kwargs)
                plt.close(fig)

                bucket_centers = sorted({
                    round((float(r0["time_start_s_absolute"]) + float(r0["time_end_s_absolute"])) * 0.5, 6)
                    for r0 in envelope_rows
                })
                index = {x: i for i, x in enumerate(bucket_centers)}
                stack_values = []
                stack_labels = []
                for group in sorted(by_group):
                    vals = [0.0 for _ in bucket_centers]
                    for r0 in by_group[group]:
                        x = round((float(r0["time_start_s_absolute"]) + float(r0["time_end_s_absolute"])) * 0.5, 6)
                        vals[index[x]] = float(r0.get("state_default_rms_linear", 0.0))
                    stack_values.append(vals)
                    stack_labels.append(group)
                if bucket_centers and stack_values:
                    fig, ax = plt.subplots(figsize=(12, 4.8))
                    ax.stackplot(bucket_centers, stack_values, labels=stack_labels)
                    for section, start in sorted(offsets.items(), key=lambda item: item[1]):
                        if start > 0.0:
                            ax.axvline(start, alpha=0.18, linewidth=0.8)
                    ax.set_xlabel("absolute soundtrack time (s)")
                    ax.set_ylabel("weighted RMS magnitude")
                    ax.set_title("Section-aware stem amplitude stack")
                    ax.legend(loc="best", fontsize=8)
                    fig.savefig(plots_dir / f"stem_amplitude_stack.{suffix}", **save_kwargs)
                    plt.close(fig)
        except Exception as ex:  # noqa: BLE001
            (plots_dir / "stem_amplitude_plots_skipped.txt").write_text(f"stem amplitude plot generation skipped: {type(ex).__name__}: {ex}\n", encoding="utf8")
    return json_path


def _spectral_band_features(audio: np.ndarray, sample_rate: int) -> dict[str, float]:
    """Return broad-band energy/flatness features for noise debugging.

    This intentionally stays lightweight: it is not source separation, but it is
    good at answering questions like "which section is unusually bright/noisy?"
    and "which stem carries the bright noise floor?".
    """
    if audio.size == 0 or sample_rate <= 0:
        return {
            "low_band_ratio": 0.0,
            "mid_band_ratio": 0.0,
            "high_band_ratio": 0.0,
            "air_band_ratio": 0.0,
            "high_band_flatness": 0.0,
        }
    mono = audio.mean(axis=1).astype("float32", copy=False) if audio.ndim == 2 else audio.astype("float32", copy=False)
    if mono.size == 0:
        return {
            "low_band_ratio": 0.0,
            "mid_band_ratio": 0.0,
            "high_band_ratio": 0.0,
            "air_band_ratio": 0.0,
            "high_band_flatness": 0.0,
        }
    mono = mono - float(np.mean(mono))
    if mono.size < 8:
        power = np.square(mono.astype("float64"))
        total = float(np.sum(power))
        return {
            "low_band_ratio": 1.0 if total > 0 else 0.0,
            "mid_band_ratio": 0.0,
            "high_band_ratio": 0.0,
            "air_band_ratio": 0.0,
            "high_band_flatness": 0.0,
        }
    window = np.hanning(mono.size).astype("float32")
    spec = np.fft.rfft(mono * window)
    power = np.square(np.abs(spec)).astype("float64")
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)
    total = float(np.sum(power)) + 1e-24

    def ratio(lo: float, hi: float) -> float:
        mask = (freqs >= lo) & (freqs < hi)
        return float(np.sum(power[mask]) / total) if np.any(mask) else 0.0

    high_mask = (freqs >= 4500.0) & (freqs < min(12000.0, sample_rate / 2.0))
    if np.any(high_mask):
        band = power[high_mask] + 1e-24
        high_flatness = float(np.exp(np.mean(np.log(band))) / (np.mean(band) + 1e-24))
    else:
        high_flatness = 0.0
    return {
        "low_band_ratio": ratio(20.0, 250.0),
        "mid_band_ratio": ratio(250.0, 2500.0),
        "high_band_ratio": ratio(4500.0, min(12000.0, sample_rate / 2.0)),
        "air_band_ratio": ratio(8000.0, min(16000.0, sample_rate / 2.0)),
        "high_band_flatness": high_flatness,
    }


def _head_tail_stats(audio: np.ndarray, sample_rate: int, seconds: float = 2.0) -> dict[str, float]:
    """Return whole/head/tail stats for a section file."""
    stats = _audio_stats(audio, sample_rate)
    frames = audio.shape[0] if audio.ndim else len(audio)
    win = min(frames, max(1, int(round(sample_rate * seconds))))
    head = audio[:win]
    tail = audio[-win:]
    head_stats = _audio_stats(head, sample_rate)
    tail_stats = _audio_stats(tail, sample_rate)
    return {
        **stats,
        "head_rms_dbfs": head_stats["rms_dbfs"],
        "head_peak_dbfs": head_stats["peak_dbfs"],
        "tail_rms_dbfs": tail_stats["rms_dbfs"],
        "tail_peak_dbfs": tail_stats["peak_dbfs"],
    }


def _safe_plot_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(name)).strip("_") or "section"




