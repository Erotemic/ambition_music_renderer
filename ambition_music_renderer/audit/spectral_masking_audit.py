"""Audio-domain spectral masking diagnostics for orchestral group stems."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi
from scipy import signal

from ..render.foreground_protection import build_group_role_priority


BANDS: tuple[tuple[str, float, float], ...] = (
    ("bass", 50.0, 180.0),
    ("low_mid", 180.0, 500.0),
    ("mid", 500.0, 1200.0),
    ("presence", 1200.0, 3000.0),
    ("brilliance", 3000.0, 7000.0),
)


def _db(power: np.ndarray | float) -> np.ndarray | float:
    return 10.0 * np.log10(np.maximum(power, 1e-18))


def _window_band_power(
    audio: np.ndarray,
    sample_rate: int,
    *,
    window_s: float,
    hop_s: float,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return center times and per-band power using downsampled Welch windows."""
    mono = np.mean(audio, axis=1, dtype=np.float64) if audio.ndim == 2 else audio.astype(np.float64)
    # 16 kHz is enough for the diagnostic bands and keeps a full 9-minute cue
    # inexpensive enough to analyze on every bundle render.
    target_sr = min(16000, int(sample_rate))
    if sample_rate != target_sr:
        gcd = math.gcd(int(sample_rate), target_sr)
        mono = signal.resample_poly(mono, target_sr // gcd, int(sample_rate) // gcd)
    nperseg = max(256, int(round(window_s * target_sr)))
    step = max(128, int(round(hop_s * target_sr)))
    if mono.size < nperseg:
        mono = np.pad(mono, (0, nperseg - mono.size))
    starts = np.arange(0, max(1, mono.size - nperseg + 1), step, dtype=np.int64)
    if starts.size == 0:
        starts = np.array([0], dtype=np.int64)
    window = np.hanning(nperseg).astype(np.float64)
    window_energy = float(np.sum(window * window))
    freqs = np.fft.rfftfreq(nperseg, 1.0 / target_sr)
    band_masks = {name: (freqs >= lo) & (freqs < hi) for name, lo, hi in BANDS}
    powers = {name: np.zeros(starts.size, dtype=np.float64) for name, *_ in BANDS}
    for idx, start in enumerate(starts):
        chunk = mono[start : start + nperseg]
        if chunk.size < nperseg:
            chunk = np.pad(chunk, (0, nperseg - chunk.size))
        spectrum = np.fft.rfft(chunk * window)
        psd = (np.abs(spectrum) ** 2) / max(window_energy, 1e-12)
        for name, mask in band_masks.items():
            powers[name][idx] = float(np.sum(psd[mask]))
    centers = (starts + nperseg / 2.0) / target_sr
    return centers, powers




def _instrument_specs_by_name(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("name")): row
        for row in (spec.get("instruments") or [])
        if isinstance(row, dict) and row.get("name") is not None
    }


def _role_priorities(spec: dict[str, Any]) -> dict[str, int]:
    out = {"background": 0, "support": 1, "lead": 2, "foreground": 3}
    cfg = dict(((spec.get("render") or {}).get("foreground_protection") or {}))
    raw = cfg.get("role_priorities") or {}
    out.update({str(role).lower(): int(value) for role, value in dict(raw).items()})
    return out


def _pitch_harmonic_band_indices(pitch: int, *, max_harmonics: int = 8) -> tuple[int, ...]:
    fundamental = 440.0 * (2.0 ** ((int(pitch) - 69) / 12.0))
    indices: set[int] = set()
    for harmonic in range(1, max_harmonics + 1):
        freq = fundamental * harmonic
        if freq >= BANDS[-1][2]:
            break
        for idx, (_name, lo, hi) in enumerate(BANDS):
            if lo <= freq < hi:
                indices.add(idx)
                break
    return tuple(sorted(indices))


def _build_group_harmonic_band_priority(
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    spec: dict[str, Any],
    *,
    duration_s: float,
    hop_s: float,
) -> dict[str, np.ndarray]:
    """Highest authored role priority whose active pitch excites each band.

    This prevents the masking audit from asking whether, for example, a high
    oboe line is winning the 50--180 Hz bass band. A band is relevant to a lead
    only when the lead's active written pitches have a low-order harmonic there.
    """
    bins = max(1, int(math.ceil(max(0.0, duration_s) / hop_s)))
    group_names = sorted(set(groups.values()))
    out = {
        group: np.full((bins, len(BANDS)), -1, dtype=np.int8)
        for group in group_names
    }
    instrument_specs = _instrument_specs_by_name(spec)
    priorities = _role_priorities(spec)
    for inst in pm.instruments:
        group = groups.get(inst.name)
        if group not in out:
            continue
        role = str((instrument_specs.get(inst.name) or {}).get("mix_role", "support")).lower()
        priority = int(priorities.get(role, priorities.get("support", 1)))
        matrix = out[group]
        for note in inst.notes:
            band_indices = _pitch_harmonic_band_indices(note.pitch)
            if not band_indices:
                continue
            start = max(0, min(bins - 1, int(math.floor(note.start / hop_s))))
            end = max(start + 1, min(bins, int(math.ceil(note.end / hop_s))))
            for band_idx in band_indices:
                matrix[start:end, band_idx] = np.maximum(
                    matrix[start:end, band_idx], priority
                )
    return out


def analyze_spectral_masking(
    stem_audio: dict[str, np.ndarray],
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    spec: dict[str, Any],
    sample_rate: int,
    *,
    window_s: float = 0.5,
    hop_s: float = 0.25,
    warning_margin_db: float = 3.0,
    lead_relative_floor_db: float = 24.0,
    foreground_underdrive_db: float = -55.0,
) -> dict[str, Any]:
    """Find windows where support families mask an authored foreground family."""
    if not stem_audio:
        return {"schema": "ambition.music_spectral_masking.v1", "warnings": [], "groups": {}}
    duration_s = max(len(audio) for audio in stem_audio.values()) / float(sample_rate)
    role_priority = build_group_role_priority(
        pm,
        groups,
        spec,
        duration_s=duration_s,
        hop_s=hop_s,
    )
    harmonic_band_priority = _build_group_harmonic_band_priority(
        pm,
        groups,
        spec,
        duration_s=duration_s,
        hop_s=hop_s,
    )
    band_db: dict[str, dict[str, np.ndarray]] = {}
    centers: np.ndarray | None = None
    for group, audio in sorted(stem_audio.items()):
        group_centers, powers = _window_band_power(
            audio, sample_rate, window_s=window_s, hop_s=hop_s
        )
        if centers is None:
            centers = group_centers
        n = min(len(group_centers), len(centers))
        band_db[group] = {name: np.asarray(_db(power[:n])) for name, power in powers.items()}
    centers = np.asarray(centers if centers is not None else [0.0], dtype=np.float64)
    nwin = len(centers)

    warnings: list[dict[str, Any]] = []
    group_summary: dict[str, Any] = {}
    for group, bands in band_db.items():
        group_summary[group] = {
            "median_band_db": {
                name: round(float(np.median(values[np.isfinite(values)])), 2)
                if np.any(np.isfinite(values))
                else -180.0
                for name, values in bands.items()
            }
        }

    # Activity masks share hop_s but are aligned to bin starts.  Trim to the
    # available audio windows and use the corresponding bin for each center.
    for idx, center_s in enumerate(centers):
        activity_idx = min(
            max(0, int(center_s / hop_s)),
            next(iter(role_priority.values())).size - 1,
        )
        active_priority = {
            group: int(values[activity_idx])
            for group, values in role_priority.items()
            if int(values[activity_idx]) >= 0
        }
        if not active_priority:
            continue
        max_priority = max(active_priority.values())
        lead_groups = [group for group, priority in active_priority.items() if priority == max_priority]
        support_groups = [group for group, priority in active_priority.items() if priority < max_priority]
        for lead_group in lead_groups:
            if lead_group not in band_db:
                continue
            for support_group in support_groups:
                if support_group == lead_group or support_group not in band_db:
                    continue
                lead_band_priority = harmonic_band_priority.get(lead_group)
                if lead_band_priority is None:
                    continue
                relevant_indices = [
                    band_idx
                    for band_idx in range(len(BANDS))
                    if int(lead_band_priority[activity_idx, band_idx]) >= max_priority
                ]
                if not relevant_indices:
                    continue
                relevant_levels = [
                    float(
                        band_db[lead_group][BANDS[band_idx][0]][
                            min(idx, len(band_db[lead_group][BANDS[band_idx][0]]) - 1)
                        ]
                    )
                    for band_idx in relevant_indices
                ]
                lead_relevant_peak = max(relevant_levels)
                for band_idx in relevant_indices:
                    band_name, _lo, _hi = BANDS[band_idx]
                    lead_level = float(
                        band_db[lead_group][band_name][
                            min(idx, len(band_db[lead_group][band_name]) - 1)
                        ]
                    )
                    support_level = float(
                        band_db[support_group][band_name][
                            min(idx, len(band_db[support_group][band_name]) - 1)
                        ]
                    )
                    # A low-order harmonic may technically land in a band while
                    # the actual sampled instrument contributes almost nothing
                    # there. Compare only bands that are meaningfully present in
                    # the lead's own local spectrum.
                    if lead_level < -95.0 or support_level < -95.0:
                        continue
                    if lead_level < lead_relevant_peak - abs(float(lead_relative_floor_db)):
                        continue
                    margin = lead_level - support_level
                    if margin < warning_margin_db:
                        warnings.append(
                            {
                                "time_s": round(float(center_s), 3),
                                "lead_group": lead_group,
                                "support_group": support_group,
                                "band": band_name,
                                "lead_db": round(lead_level, 2),
                                "support_db": round(support_level, 2),
                                "lead_margin_db": round(margin, 2),
                                "lead_relevant_peak_db": round(lead_relevant_peak, 2),
                                "severity_db": round(float(warning_margin_db - margin), 2),
                            }
                        )

    # A score can declare a foreground while the selected sample/controller
    # combination produces almost no audio.  That is an under-driven source,
    # not ordinary masking, and should be diagnosed separately so authors do
    # not keep attenuating the accompaniment around a nearly silent solo.
    underdrive_candidates = [
        row for row in warnings
        if float(row.get("lead_relevant_peak_db", 0.0)) < float(foreground_underdrive_db)
    ]
    warnings = [
        row for row in warnings
        if float(row.get("lead_relevant_peak_db", 0.0)) >= float(foreground_underdrive_db)
    ]
    underdrive_candidates.sort(
        key=lambda row: (float(row.get("lead_relevant_peak_db", 0.0)), float(row["time_s"]))
    )
    underdriven: list[dict[str, Any]] = []
    for row in underdrive_candidates:
        if any(
            row["lead_group"] == prev["lead_group"]
            and abs(float(row["time_s"]) - float(prev["time_s"])) < 1.0
            for prev in underdriven
        ):
            continue
        underdriven.append(row)
        if len(underdriven) >= 40:
            break

    raw_warning_count = len(warnings)
    warnings.sort(key=lambda row: (-float(row["severity_db"]), float(row["time_s"])))
    # Hundreds of adjacent windows around one passage are not useful.  Keep the
    # worst representative per roughly one-second neighborhood and band pair.
    selected: list[dict[str, Any]] = []
    for row in warnings:
        if any(
            row["lead_group"] == prev["lead_group"]
            and row["support_group"] == prev["support_group"]
            and row["band"] == prev["band"]
            and abs(float(row["time_s"]) - float(prev["time_s"])) < 1.0
            for prev in selected
        ):
            continue
        selected.append(row)
        if len(selected) >= 80:
            break

    # A severity-only top list can hide an entire quiet section behind a dense
    # finale. Keep one strongest representative per ten-second bucket as a
    # second view so pervasive balance problems remain visible across the cue.
    timeline_by_bucket: dict[int, dict[str, Any]] = {}
    for row in warnings:
        bucket = int(float(row["time_s"]) // 10.0)
        if bucket not in timeline_by_bucket:
            timeline_by_bucket[bucket] = row
    timeline = [timeline_by_bucket[key] for key in sorted(timeline_by_bucket)]

    return {
        "schema": "ambition.music_spectral_masking.v1",
        "window_s": window_s,
        "hop_s": hop_s,
        "warning_margin_db": warning_margin_db,
        "lead_relative_floor_db": lead_relative_floor_db,
        "foreground_underdrive_db": foreground_underdrive_db,
        "band_relevance": "active lead-pitch low-order harmonics",
        "bands_hz": {name: [lo, hi] for name, lo, hi in BANDS},
        "groups": group_summary,
        "warnings": selected,
        "timeline_representatives": timeline,
        "raw_warning_count": raw_warning_count,
        "warning_count": len(selected),
        "timeline_warning_count": len(timeline),
        "underdriven_foreground": underdriven,
        "underdriven_foreground_count": len(underdriven),
    }


def write_reports(payload: dict[str, Any], reports_dir: Path) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "spectral_masking.json"
    txt_path = reports_dir / "spectral_masking_summary.txt"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")
    lines = [
        "spectral masking diagnostic",
        f"warning_count: {payload.get('warning_count', 0)}",
        f"raw_warning_count: {payload.get('raw_warning_count', payload.get('warning_count', 0))}",
        f"underdriven_foreground_count: {payload.get('underdriven_foreground_count', 0)}",
        f"band_relevance: {payload.get('band_relevance', 'all bands')}",
        "",
        "under-driven foreground windows:",
    ]
    for row in (payload.get("underdriven_foreground") or [])[:20]:
        lines.append(
            f"  {float(row['time_s']):7.3f}s  {row['lead_group']}  "
            f"local peak {float(row['lead_relevant_peak_db']):+5.1f} dBFS "
            f"while {row['support_group']} is present"
        )
    if not payload.get("underdriven_foreground"):
        lines.append("  none")
    lines.extend(["", "worst foreground/support collisions:"])
    for row in (payload.get("warnings") or [])[:30]:
        lines.append(
            f"  {float(row['time_s']):7.3f}s  {row['lead_group']} <- {row['support_group']}  "
            f"{row['band']}: lead margin {float(row['lead_margin_db']):+5.1f} dB"
        )
    if not payload.get("warnings"):
        lines.append("  none")
    lines.extend(["", "timeline representatives (worst per 10 s bucket):"])
    for row in payload.get("timeline_representatives") or []:
        lines.append(
            f"  {float(row['time_s']):7.3f}s  {row['lead_group']} <- {row['support_group']}  "
            f"{row['band']}: lead margin {float(row['lead_margin_db']):+5.1f} dB"
        )
    if not payload.get("timeline_representatives"):
        lines.append("  none")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf8")
    return {"json": str(json_path), "summary": str(txt_path)}
