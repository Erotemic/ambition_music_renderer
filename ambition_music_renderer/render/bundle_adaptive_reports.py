"""Adaptive section, composition mastering, and shrillness reports."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ..audio_utils import coerce_stereo
from .bundle_base import (
    DBFS_SILENCE_FLOOR,
    _format_dbfs,
    _plot_db,
    adjacent_section_pairs,
    current_scratch_stem_paths,
    ordered_section_ids,
    report_plot_save_kwargs,
)
from .bundle_spectral_reports import (
    _head_tail_stats,
    _rms_envelope,
    _safe_plot_name,
    _spectral_band_features,
)

from .isolated import adaptive_section_mastering_config as adaptive_section_mastering_config_from_spec

def write_adaptive_section_report(
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
    """Write section/state diagnostics for dynamic adaptive cues.

    Transition plots answer seam questions. Stem-amplitude plots answer global
    balance questions. This report fills the missing middle for encounter cues:
    one view per adaptive part/section, plus full-section loudness and high-band
    noise proxies so a noisy intro does not hide inside the whole soundtrack.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    if plots_dir is not None:
        plots_dir.mkdir(parents=True, exist_ok=True)

    sections = [s for s in manifest.get("sections") or [] if isinstance(s, dict)]
    section_order = [str(s.get("id")) for s in sections if s.get("id") is not None]
    section_times = {
        str(s.get("id")): {
            "start_seconds": float(s.get("start_seconds", 0.0) or 0.0),
            "end_seconds": float(s.get("end_seconds", 0.0) or 0.0),
            "duration_seconds": float(s.get("duration_seconds", 0.0) or 0.0),
        }
        for s in sections
        if s.get("id") is not None
    }

    mastering_cfg = adaptive_section_mastering_config_from_spec(spec)
    section_specs = [s0 for s0 in spec.get("sections", []) if isinstance(s0, dict)]
    section_postprocess_ids = [
        str(s0.get("id")) for s0 in section_specs if isinstance(s0.get("postprocess"), dict)
    ]
    section_postprocess_normalizers = [
        str(s0.get("id"))
        for s0 in section_specs
        if isinstance(s0.get("postprocess"), dict)
        and (
            bool(s0.get("postprocess", {}).get("normalize", True))
            or "target_peak_db" in s0.get("postprocess", {})
        )
    ]

    state_map = spec.get("state_map") or {}
    states: list[dict[str, object]] = []
    if isinstance(state_map, dict):
        for state, cfg in sorted(state_map.items()):
            if not isinstance(cfg, dict):
                continue
            section = cfg.get("section") or cfg.get("preferred_section") or cfg.get("outro")
            weight_source = "stems" if isinstance(cfg.get("stems"), dict) else "fade_in" if isinstance(cfg.get("fade_in"), dict) else "none"
            weights = cfg.get("stems") if weight_source == "stems" else cfg.get("fade_in") if weight_source == "fade_in" else {}
            states.append(
                {
                    "state": str(state),
                    "section": section,
                    "weight_source": weight_source,
                    "weights": {str(k): float(v) for k, v in (weights or {}).items()} if isinstance(weights, dict) else {},
                    "transition": cfg.get("transition"),
                    "fade_beats": cfg.get("fade_beats"),
                }
            )

    rows: list[dict[str, object]] = []
    envelope_rows: list[dict[str, object]] = []
    adaptive = ((manifest.get("files") or {}).get("adaptive") or {})
    if isinstance(adaptive, dict):
        for section in section_order or sorted(adaptive):
            section_files = adaptive.get(section) or {}
            if not isinstance(section_files, dict):
                continue
            for group, rel in sorted(section_files.items()):
                if not isinstance(rel, str):
                    continue
                path = outdir / rel
                try:
                    import soundfile as sf

                    audio, sr = sf.read(path, always_2d=True, dtype="float32")
                    sample_rate = int(sr)
                    stats = _head_tail_stats(audio.astype("float32", copy=False), sample_rate)
                    bands = _spectral_band_features(audio.astype("float32", copy=False), sample_rate)
                    error = ""
                    for env in _rms_envelope(audio, sample_rate, bucket_seconds):
                        envelope_rows.append(
                            {
                                "section": section,
                                "group": str(group),
                                "time_start_s": env["time_start_s"],
                                "time_end_s": env["time_end_s"],
                                "rms_dbfs": env["rms_dbfs"],
                                "rms_linear": env["rms_linear"],
                            }
                        )
                except Exception as ex:  # noqa: BLE001
                    stats = {}
                    bands = {}
                    error = f"{type(ex).__name__}: {ex}"
                row = {
                    "section": section,
                    "group": str(group),
                    "kind": "full" if str(group) == "full" else "stem",
                    "section_start_s": float(section_times.get(section, {}).get("start_seconds", 0.0)),
                    "section_end_s": float(section_times.get(section, {}).get("end_seconds", 0.0)),
                    "path": rel,
                    **stats,
                    **bands,
                    "error": error,
                }
                rows.append(row)

    full_rows = [r0 for r0 in rows if r0.get("kind") == "full" and not r0.get("error")]
    stem_rows = [r0 for r0 in rows if r0.get("kind") == "stem" and not r0.get("error")]
    full_by_section = {str(r0.get("section")): r0 for r0 in full_rows}

    warnings: list[str] = []
    if mastering_cfg.get("mode") == "global_master_slices":
        if section_postprocess_ids:
            warnings.append(
                "global_master_slices active: section-local postprocess blocks are ignored for exported full mixes "
                f"({', '.join(section_postprocess_ids)})"
            )
    elif section_postprocess_normalizers:
        warnings.append(
            "legacy section_postprocess mode with section-local normalize/target_peak_db can break composition-level loudness: "
            + ", ".join(section_postprocess_normalizers)
        )
    if full_rows:
        high_values = [float(r0.get("high_band_ratio", 0.0)) for r0 in full_rows]
        median_high = float(np.median(high_values)) if high_values else 0.0
        for r0 in full_rows:
            high = float(r0.get("high_band_ratio", 0.0))
            flat = float(r0.get("high_band_flatness", 0.0))
            if high > max(0.025, median_high * 3.0):
                warnings.append(
                    f"section {r0.get('section')} full mix has high-band ratio {high * 100:.2f}% "
                    f"(median {median_high * 100:.2f}%, flatness {flat:.2f}); inspect per-section stem plots for hiss/noise"
                )
            head = float(r0.get("head_rms_dbfs", DBFS_SILENCE_FLOOR))
            tail = float(r0.get("tail_rms_dbfs", DBFS_SILENCE_FLOOR))
            if tail - head > 5.0:
                warnings.append(
                    f"section {r0.get('section')} grows by {tail - head:.1f} dB from head to tail; starts may feel too soft"
                )
        for first, second in adjacent_section_pairs(manifest):
            a = full_by_section.get(first)
            b = full_by_section.get(second)
            if not a or not b:
                continue
            delta = float(b.get("head_rms_dbfs", DBFS_SILENCE_FLOOR)) - float(a.get("tail_rms_dbfs", DBFS_SILENCE_FLOOR))
            if abs(delta) > 5.0:
                warnings.append(
                    f"adjacent full-section handoff {first}->{second} has {delta:+.1f} dB head/tail RMS jump before runtime crossfade"
                )
    for section in section_order:
        sec_stems = [r0 for r0 in stem_rows if str(r0.get("section")) == section]
        if not sec_stems:
            continue
        top_high = sorted(sec_stems, key=lambda r0: float(r0.get("high_band_ratio", 0.0)), reverse=True)[:3]
        if top_high and float(top_high[0].get("high_band_ratio", 0.0)) > 0.04:
            warnings.append(
                f"section {section} brightest stem is {top_high[0].get('group')} "
                f"({float(top_high[0].get('high_band_ratio', 0.0)) * 100:.2f}% high-band)"
            )

    payload = {
        "schema": "ambition.adaptive_section_audit.v1",
        "cue": manifest.get("id"),
        "hash": manifest.get("hash"),
        "bucket_seconds": bucket_seconds,
        "sections": section_times,
        "mastering": {
            **mastering_cfg,
            "section_postprocess_sections": section_postprocess_ids,
            "section_postprocess_normalizer_sections": section_postprocess_normalizers,
        },
        "states": states,
        "rows": rows,
        "warnings": warnings,
        "note": (
            "Full rows describe what the game will hear when a cue ships as one mastered full layer per section. "
            "Stem rows are diagnostic/source-localization only unless the runtime catalog uses those stems directly. "
            "High-band ratio and flatness are broad noise/brightness proxies, not source separation."
        ),
    }
    json_path = reports_dir / "adaptive_section_audit.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    columns = [
        "section",
        "group",
        "kind",
        "rms_dbfs",
        "peak_dbfs",
        "head_rms_dbfs",
        "tail_rms_dbfs",
        "high_band_ratio",
        "air_band_ratio",
        "high_band_flatness",
        "path",
        "error",
    ]
    tsv = reports_dir / "adaptive_section_audit.tsv"
    lines = ["\t".join(columns)]
    for row in rows:
        cells: list[str] = []
        for col in columns:
            value = row.get(col, "")
            cells.append(f"{value:.6g}" if isinstance(value, float) else str(value))
        lines.append("\t".join(cells))
    tsv.write_text("\n".join(lines) + "\n", encoding="utf8")

    summary = reports_dir / "adaptive_section_audit_summary.txt"
    text: list[str] = [
        f"cue: {manifest.get('id')}",
        f"hash: {manifest.get('hash')}",
        "purpose: section-by-section debug for adaptive cues",
        "",
        "full-section loudness/noise:",
        f"mastering mode: {mastering_cfg.get('mode')}",
    ]
    for section in section_order:
        row = full_by_section.get(section)
        if not row:
            continue
        text.append(
            f"  {section}: rms {_format_dbfs(row.get('rms_dbfs', DBFS_SILENCE_FLOOR))} dBFS, "
            f"peak {_format_dbfs(row.get('peak_dbfs', DBFS_SILENCE_FLOOR))} dBFS, "
            f"head {_format_dbfs(row.get('head_rms_dbfs', DBFS_SILENCE_FLOOR))}, tail {_format_dbfs(row.get('tail_rms_dbfs', DBFS_SILENCE_FLOOR))}, "
            f"high {float(row.get('high_band_ratio', 0.0)) * 100:.2f}%, "
            f"air {float(row.get('air_band_ratio', 0.0)) * 100:.2f}%, flat {float(row.get('high_band_flatness', 0.0)):.2f}"
        )
        sec_stems = sorted(
            [r0 for r0 in stem_rows if str(r0.get("section")) == section],
            key=lambda r0: float(r0.get("high_band_ratio", 0.0)),
            reverse=True,
        )[:4]
        if sec_stems:
            text.append("    brightest stems: " + ", ".join(
                f"{r0.get('group')} {float(r0.get('high_band_ratio', 0.0)) * 100:.2f}%"
                for r0 in sec_stems
            ))
    text.extend(["", "state/section map:"])
    for state in states:
        text.append(
            f"  {state.get('state')} -> {state.get('section')} "
            f"[{state.get('weight_source')}] weights={state.get('weights')}"
        )
    if warnings:
        text.extend(["", "warnings:"])
        for warning in warnings:
            text.append(f"  - {warning}")
    else:
        text.extend(["", "warnings: none"])
    summary.write_text("\n".join(text) + "\n", encoding="utf8")

    if plots_dir is not None and rows:
        try:
            import matplotlib.pyplot as plt

            suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
            save_kwargs = report_plot_save_kwargs(
                plot_format=suffix,
                jpeg_quality=jpeg_quality,
            )

            if full_rows:
                labels = [str(r0.get("section")) for r0 in full_rows]
                x = np.arange(len(labels))
                width = 0.25
                fig, ax = plt.subplots(figsize=(max(8.0, len(labels) * 1.2), 4.4))
                ax.bar(x - width, [_plot_db(float(r0.get("head_rms_dbfs", DBFS_SILENCE_FLOOR))) for r0 in full_rows], width, label="head RMS")
                ax.bar(x, [_plot_db(float(r0.get("rms_dbfs", DBFS_SILENCE_FLOOR))) for r0 in full_rows], width, label="full RMS")
                ax.bar(x + width, [_plot_db(float(r0.get("tail_rms_dbfs", DBFS_SILENCE_FLOOR))) for r0 in full_rows], width, label="tail RMS")
                ax.set_xticks(x, labels=labels, rotation=25, ha="right")
                ax.set_ylabel("dBFS")
                ax.set_title("Adaptive full-section loudness")
                ax.grid(True, axis="y", alpha=0.3)
                ax.legend(fontsize=8)
                fig.savefig(plots_dir / f"adaptive_section_full_levels.{suffix}", **save_kwargs)
                plt.close(fig)

                fig, ax = plt.subplots(figsize=(max(8.0, len(labels) * 1.2), 4.4))
                ax.bar(x, [float(r0.get("high_band_ratio", 0.0)) * 100.0 for r0 in full_rows], label="4.5-12 kHz")
                ax.bar(x, [float(r0.get("air_band_ratio", 0.0)) * 100.0 for r0 in full_rows], label="8-16 kHz")
                ax.set_xticks(x, labels=labels, rotation=25, ha="right")
                ax.set_ylabel("energy share (%)")
                ax.set_title("Adaptive full-section high-band / air energy")
                ax.grid(True, axis="y", alpha=0.3)
                ax.legend(fontsize=8)
                fig.savefig(plots_dir / f"adaptive_section_full_highband.{suffix}", **save_kwargs)
                plt.close(fig)

            if section_order:
                fig, ax = plt.subplots(figsize=(12, max(2.4, 0.5 * len(section_order) + 1.4)))
                y = 0
                for section in section_order:
                    times = section_times.get(section, {})
                    start = float(times.get("start_seconds", 0.0))
                    end = float(times.get("end_seconds", start))
                    ax.barh(y, end - start, left=start, height=0.34)
                    ax.text(start + 0.05, y, section, va="center", ha="left", fontsize=8)
                    y += 1
                for state in states:
                    sec = state.get("section")
                    if sec in section_times:
                        start = float(section_times[str(sec)].get("start_seconds", 0.0))
                        ax.text(start, y, str(state.get("state")), va="center", ha="left", fontsize=7, rotation=25)
                        y += 0.22
                ax.set_xlabel("absolute soundtrack time (s)")
                ax.set_yticks([])
                ax.set_title("Adaptive section/state flow")
                ax.grid(True, axis="x", alpha=0.3)
                fig.savefig(plots_dir / f"adaptive_section_state_flow.{suffix}", **save_kwargs)
                plt.close(fig)

            for section in section_order:
                sec_env = [r0 for r0 in envelope_rows if str(r0.get("section")) == section and str(r0.get("group")) != "full"]
                if not sec_env:
                    continue
                by_group: dict[str, list[dict[str, object]]] = {}
                for r0 in sec_env:
                    by_group.setdefault(str(r0.get("group")), []).append(r0)
                centers = sorted({
                    round((float(r0["time_start_s"]) + float(r0["time_end_s"])) * 0.5, 6)
                    for r0 in sec_env
                })
                if not centers:
                    continue
                idx = {v: i for i, v in enumerate(centers)}
                stack_values: list[list[float]] = []
                labels2: list[str] = []
                for group in sorted(by_group):
                    vals = [0.0 for _ in centers]
                    for r0 in by_group[group]:
                        x0 = round((float(r0["time_start_s"]) + float(r0["time_end_s"])) * 0.5, 6)
                        vals[idx[x0]] = float(r0.get("rms_linear", 0.0))
                    if max(vals) > 1e-9:
                        stack_values.append(vals)
                        labels2.append(group)
                if stack_values:
                    fig, ax = plt.subplots(figsize=(10, 4.0))
                    ax.stackplot(centers, stack_values, labels=labels2)
                    ax.set_xlabel(f"{section} local time (s)")
                    ax.set_ylabel("stem RMS magnitude")
                    ax.set_title(f"Adaptive section stem stack: {section}")
                    ax.legend(loc="best", fontsize=8)
                    ax.grid(True, alpha=0.3)
                    fig.savefig(plots_dir / f"adaptive_section_stack_{_safe_plot_name(section)}.{suffix}", **save_kwargs)
                    plt.close(fig)

                top_stems = sorted(
                    [r0 for r0 in stem_rows if str(r0.get("section")) == section],
                    key=lambda r0: float(r0.get("high_band_ratio", 0.0)),
                    reverse=True,
                )
                if top_stems:
                    labels3 = [str(r0.get("group")) for r0 in top_stems]
                    vals3 = [float(r0.get("high_band_ratio", 0.0)) * 100.0 for r0 in top_stems]
                    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.35 * len(labels3) + 1.2)))
                    pos = np.arange(len(labels3))
                    ax.barh(pos, vals3)
                    ax.set_yticks(pos, labels=labels3)
                    ax.invert_yaxis()
                    ax.set_xlabel("4.5-12 kHz energy share (%)")
                    ax.set_title(f"Bright/noisy stems: {section}")
                    ax.grid(True, axis="x", alpha=0.3)
                    fig.savefig(plots_dir / f"adaptive_section_highband_{_safe_plot_name(section)}.{suffix}", **save_kwargs)
                    plt.close(fig)
        except Exception as ex:  # noqa: BLE001
            (plots_dir / "adaptive_section_plots_skipped.txt").write_text(
                f"adaptive section plot generation skipped: {type(ex).__name__}: {ex}\n",
                encoding="utf8",
            )
    return json_path



def write_adaptive_composition_mastering_report(
    outdir: Path,
    spec: dict,
    manifest: dict,
    reports_dir: Path,
    plots_dir: Path | None = None,
    *,
    plot_format: str = "jpg",
    jpeg_quality: int = 84,
) -> Path:
    """Write composition-level mastering diagnostics for adaptive sections.

    This report is intentionally about the *shipped full-section assets* rather
    than authoring stems. It answers whether intro / waves / bridges / outro are
    behaving as one mastered adaptive composition before the Rust director
    crossfades them at near-unity gains.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    if plots_dir is not None:
        plots_dir.mkdir(parents=True, exist_ok=True)

    mastering_cfg = adaptive_section_mastering_config_from_spec(spec)
    spec_sections = [s0 for s0 in spec.get("sections", []) if isinstance(s0, dict)]
    spec_by_id = {str(s0.get("id")): s0 for s0 in spec_sections if s0.get("id") is not None}
    section_order = ordered_section_ids(manifest)
    adaptive = ((manifest.get("files") or {}).get("adaptive") or {})
    rows: list[dict[str, object]] = []
    for idx, section in enumerate(section_order):
        section_files = adaptive.get(section) if isinstance(adaptive, dict) else None
        rel = section_files.get("full") if isinstance(section_files, dict) else None
        row: dict[str, object] = {
            "section": section,
            "order": idx,
            "kind": spec_by_id.get(section, {}).get("kind", ""),
            "intensity": float(spec_by_id.get(section, {}).get("intensity", 0.0) or 0.0),
            "density": float(spec_by_id.get(section, {}).get("density", 0.0) or 0.0),
            "loopable": bool(spec_by_id.get(section, {}).get("loopable", False)),
            "has_section_postprocess": isinstance(spec_by_id.get(section, {}).get("postprocess"), dict),
            "path": rel or "",
            "error": "",
        }
        if isinstance(rel, str):
            try:
                import soundfile as sf

                audio, sr = sf.read(outdir / rel, always_2d=True, dtype="float32")
                audio = audio.astype("float32", copy=False)
                row.update(_head_tail_stats(audio, int(sr)))
                row.update(_spectral_band_features(audio, int(sr)))
            except Exception as ex:  # noqa: BLE001
                row["error"] = f"{type(ex).__name__}: {ex}"
        else:
            row["error"] = "missing full section file in manifest"
        rows.append(row)

    good = [r0 for r0 in rows if not r0.get("error")]
    warnings: list[str] = []
    section_post = [str(r0["section"]) for r0 in rows if r0.get("has_section_postprocess")]
    if mastering_cfg.get("mode") != "global_master_slices" and len(section_order) > 1:
        warnings.append(
            "adaptive full-section assets are not configured for global_master_slices; "
            "verify this is intentional before shipping a horizontally crossfaded cue"
        )
    if section_post and mastering_cfg.get("mode") == "global_master_slices":
        warnings.append(
            "section-local postprocess blocks exist but global_master_slices ignores them for full-section export: "
            + ", ".join(section_post)
        )
    if good:
        rms_values = [float(r0.get("rms_dbfs", DBFS_SILENCE_FLOOR)) for r0 in good]
        med_rms = float(np.median(rms_values))
        for r0 in good:
            section = str(r0.get("section"))
            rms_delta = float(r0.get("rms_dbfs", DBFS_SILENCE_FLOOR)) - med_rms
            high = float(r0.get("high_band_ratio", 0.0))
            flat = float(r0.get("high_band_flatness", 0.0))
            row_intensity = float(r0.get("intensity", 0.0))
            if rms_delta < -7.0 and row_intensity >= 0.3:
                warnings.append(
                    f"section {section} is {rms_delta:.1f} dB below median RMS despite intensity {row_intensity:.2f}; source balance may start too soft"
                )
            if high > 0.035 and flat > 0.18:
                warnings.append(
                    f"section {section} has bright/noise-like high band {high * 100:.2f}% flatness {flat:.2f}"
                )
        for first, second in adjacent_section_pairs(manifest):
            a = next((r0 for r0 in good if r0.get("section") == first), None)
            b = next((r0 for r0 in good if r0.get("section") == second), None)
            if not a or not b:
                continue
            tail_to_head = float(b.get("head_rms_dbfs", DBFS_SILENCE_FLOOR)) - float(a.get("tail_rms_dbfs", DBFS_SILENCE_FLOOR))
            full_delta = float(b.get("rms_dbfs", DBFS_SILENCE_FLOOR)) - float(a.get("rms_dbfs", DBFS_SILENCE_FLOOR))
            if abs(tail_to_head) > 5.0:
                warnings.append(
                    f"handoff {first}->{second} has {tail_to_head:+.1f} dB tail-to-head jump before runtime crossfade"
                )
            if full_delta < -6.0:
                warnings.append(
                    f"handoff {first}->{second} drops {full_delta:.1f} dB in full-section RMS; check adaptive energy plan"
                )

    payload = {
        "schema": "ambition.adaptive_composition_mastering.v1",
        "cue": manifest.get("id"),
        "hash": manifest.get("hash"),
        "mastering": mastering_cfg,
        "rows": rows,
        "warnings": warnings,
        "note": (
            "Rows describe the mastered full-section assets the game crossfades. "
            "Use this to check composition-level loudness/noise continuity, not stem arrangement balance."
        ),
    }
    json_path = reports_dir / "adaptive_composition_mastering.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    cols = [
        "section", "order", "kind", "intensity", "density", "rms_dbfs", "head_rms_dbfs",
        "tail_rms_dbfs", "peak_dbfs", "high_band_ratio", "air_band_ratio",
        "high_band_flatness", "has_section_postprocess", "path", "error",
    ]
    tsv = reports_dir / "adaptive_composition_mastering.tsv"
    lines = ["\t".join(cols)]
    for row in rows:
        cells = []
        for col in cols:
            val = row.get(col, "")
            cells.append(f"{val:.6g}" if isinstance(val, float) else str(val))
        lines.append("\t".join(cells))
    tsv.write_text("\n".join(lines) + "\n", encoding="utf8")

    summary = reports_dir / "adaptive_composition_mastering_summary.txt"
    text = [
        f"cue: {manifest.get('id')}",
        f"hash: {manifest.get('hash')}",
        f"mastering mode: {mastering_cfg.get('mode')}",
        "purpose: composition-level full-section loudness/noise continuity for horizontal adaptive music",
        "",
        "full-section plan:",
    ]
    for row in rows:
        if row.get("error"):
            text.append(f"  {row.get('section')}: ERROR {row.get('error')}")
        else:
            text.append(
                f"  {row.get('section')}: intensity {float(row.get('intensity', 0.0)):.2f}, "
                f"rms {_format_dbfs(row.get('rms_dbfs', DBFS_SILENCE_FLOOR))} dBFS, "
                f"head {_format_dbfs(row.get('head_rms_dbfs', DBFS_SILENCE_FLOOR))}, "
                f"tail {_format_dbfs(row.get('tail_rms_dbfs', DBFS_SILENCE_FLOOR))}, "
                f"high {float(row.get('high_band_ratio', 0.0)) * 100:.2f}%, "
                f"flat {float(row.get('high_band_flatness', 0.0)):.2f}"
            )
    if warnings:
        text.extend(["", "warnings:"])
        text.extend(f"  - {w}" for w in warnings)
    else:
        text.extend(["", "warnings: none"])
    summary.write_text("\n".join(text) + "\n", encoding="utf8")

    if plots_dir is not None and good:
        try:
            import matplotlib.pyplot as plt

            suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
            save_kwargs = report_plot_save_kwargs(
                plot_format=suffix,
                jpeg_quality=jpeg_quality,
            )
            labels = [str(r0.get("section")) for r0 in good]
            x = np.arange(len(labels))
            fig, ax1 = plt.subplots(figsize=(max(9.0, len(labels) * 1.25), 4.8))
            ax1.plot(x, [_plot_db(float(r0.get("rms_dbfs", DBFS_SILENCE_FLOOR))) for r0 in good], marker="o", label="full RMS")
            ax1.plot(x, [_plot_db(float(r0.get("head_rms_dbfs", DBFS_SILENCE_FLOOR))) for r0 in good], marker="o", label="head RMS")
            ax1.plot(x, [_plot_db(float(r0.get("tail_rms_dbfs", DBFS_SILENCE_FLOOR))) for r0 in good], marker="o", label="tail RMS")
            ax1.set_xticks(x, labels=labels, rotation=25, ha="right")
            ax1.set_ylabel("dBFS")
            ax1.set_title("Adaptive composition section loudness continuity")
            ax1.grid(True, axis="y", alpha=0.3)
            ax1.legend(loc="best", fontsize=8)
            fig.savefig(plots_dir / f"adaptive_composition_mastering_levels.{suffix}", **save_kwargs)
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(max(9.0, len(labels) * 1.25), 4.8))
            ax.plot(x, [float(r0.get("intensity", 0.0)) for r0 in good], marker="o", label="authored intensity")
            rms = np.asarray([_plot_db(float(r0.get("rms_dbfs", DBFS_SILENCE_FLOOR))) for r0 in good], dtype="float32")
            if np.max(rms) > np.min(rms):
                normalized_rms = (rms - np.min(rms)) / max(1e-6, float(np.max(rms) - np.min(rms)))
            else:
                normalized_rms = np.zeros_like(rms)
            ax.plot(x, normalized_rms, marker="o", label="normalized full RMS")
            ax.set_xticks(x, labels=labels, rotation=25, ha="right")
            ax.set_ylim(-0.05, 1.05)
            ax.set_title("Authored intensity vs rendered section loudness")
            ax.grid(True, alpha=0.3)
            ax.legend(loc="best", fontsize=8)
            fig.savefig(plots_dir / f"adaptive_composition_intensity_vs_loudness.{suffix}", **save_kwargs)
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(max(9.0, len(labels) * 1.25), 4.8))
            ax.bar(x, [float(r0.get("high_band_ratio", 0.0)) * 100.0 for r0 in good], label="4.5-12 kHz")
            ax.bar(x, [float(r0.get("air_band_ratio", 0.0)) * 100.0 for r0 in good], label="8-16 kHz")
            ax.set_xticks(x, labels=labels, rotation=25, ha="right")
            ax.set_ylabel("energy share (%)")
            ax.set_title("Adaptive composition high-band / air by full section")
            ax.grid(True, axis="y", alpha=0.3)
            ax.legend(loc="best", fontsize=8)
            fig.savefig(plots_dir / f"adaptive_composition_noise_floor.{suffix}", **save_kwargs)
            plt.close(fig)
        except Exception as ex:  # noqa: BLE001
            (plots_dir / "adaptive_composition_mastering_plots_skipped.txt").write_text(
                f"adaptive composition mastering plot generation skipped: {type(ex).__name__}: {ex}\n",
                encoding="utf8",
            )

    return json_path


def write_spectral_shrillness_report(
    outdir: Path,
    manifest: dict,
    reports_dir: Path,
    *,
    bucket_seconds: float = 0.5,
    max_candidates: int = 120,
) -> Path:
    """Write audio-derived shrillness candidates from rendered stems/previews.

    ``shrill_note_audit`` is score-level and only sees MIDI fundamentals. That
    deliberately avoids flagging normal distorted-guitar timbre, but it can miss
    the failure mode where a mid-register guitar note renders with a narrow,
    very audible 6-12 kHz harmonic/whistle. This report looks at rendered audio
    directly and flags isolated high-band spectral lines by time, source, and
    frequency. Treat rows as review candidates, not automatic delete commands.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    sample_rate = int(manifest.get("sample_rate", 48000))
    rows: list[dict[str, object]] = []
    warnings: list[str] = []

    try:
        from scipy import signal
    except Exception as ex:  # noqa: BLE001
        payload = {
            "schema": "ambition.audio_shrillness_audit.v1",
            "cue": manifest.get("id"),
            "hash": manifest.get("hash"),
            "error": f"scipy unavailable: {type(ex).__name__}: {ex}",
            "warnings": ["audio shrillness audit skipped; scipy unavailable"],
            "candidates": [],
        }
        path = reports_dir / "audio_shrillness_candidates.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf8")
        return path

    def _audio_candidates(label: str, kind: str, audio: np.ndarray) -> None:
        arr = coerce_stereo(audio).astype("float32", copy=False)
        mono = arr.mean(axis=1)
        if mono.size < 1024:
            return
        nperseg = min(8192, max(1024, int(2 ** math.floor(math.log2(max(1024, min(len(mono), 8192)))))))
        noverlap = int(nperseg * 0.75)
        freqs, times, spec = signal.spectrogram(
            mono,
            fs=sample_rate,
            nperseg=nperseg,
            noverlap=noverlap,
            scaling="spectrum",
            mode="magnitude",
        )
        spec_db = 20.0 * np.log10(spec + 1e-10)
        band_mask = (freqs >= 4000.0) & (freqs <= 12500.0)
        if not np.any(band_mask):
            return
        bucket = max(0.05, float(bucket_seconds))
        bucket_count = max(1, int(math.ceil(float(times[-1] if times.size else 0.0) / bucket)))
        focus_freqs = freqs[band_mask]
        focus = spec_db[band_mask, :]
        for bucket_idx in range(bucket_count):
            t0 = bucket_idx * bucket
            t1 = t0 + bucket
            tmask = (times >= t0) & (times < t1)
            if not np.any(tmask):
                continue
            chunk = focus[:, tmask]
            if chunk.size == 0:
                continue
            # Collapse time inside the bucket by max so short whistles are not
            # averaged away. Compare against the bucket's local high-band floor
            # to distinguish narrow standalone lines from broadband timbre.
            freq_profile = np.max(chunk, axis=1)
            finite = freq_profile[np.isfinite(freq_profile)]
            if finite.size == 0:
                continue
            idx = int(np.argmax(freq_profile))
            peak_db = float(freq_profile[idx])
            peak_hz = float(focus_freqs[idx])
            floor_db = float(np.percentile(finite, 35.0))
            p90_db = float(np.percentile(finite, 90.0))
            narrowness_db = peak_db - floor_db
            prominence_db = peak_db - p90_db
            severity = "review_4k_plus"
            if peak_hz >= 10000.0:
                severity = "extreme_10k_plus"
            elif peak_hz >= 8000.0:
                severity = "whistle_8k_plus"
            elif peak_hz >= 6000.0:
                severity = "piercing_6k_plus"
            # These thresholds intentionally catch rendered high harmonics, not
            # just literal high MIDI notes. Require both audibility and a narrow
            # spectral line so cymbal/noise-like brightness is less likely to
            # dominate the report.
            if peak_db < -68.0:
                continue
            if narrowness_db < 16.0 and prominence_db < 5.0:
                continue
            freq_weight = 1.0
            if peak_hz >= 6000.0:
                freq_weight += 0.45
            if peak_hz >= 8000.0:
                freq_weight += 0.55
            if peak_hz >= 10000.0:
                freq_weight += 0.40
            loud_weight = max(0.0, (peak_db + 68.0) / 22.0)
            narrow_weight = max(0.0, narrowness_db / 20.0)
            prom_weight = max(0.0, prominence_db / 8.0)
            score = freq_weight * (0.55 * loud_weight + 0.45 * narrow_weight + 0.25 * prom_weight)
            if score < 0.75:
                continue
            rows.append(
                {
                    "score": round(float(score), 3),
                    "severity": severity,
                    "kind": kind,
                    "source": label,
                    "time_start_s": round(float(t0), 3),
                    "time_end_s": round(float(t1), 3),
                    "peak_frequency_hz": round(float(peak_hz), 1),
                    "peak_db": round(float(peak_db), 2),
                    "floor_db": round(float(floor_db), 2),
                    "narrowness_db": round(float(narrowness_db), 2),
                    "prominence_db": round(float(prominence_db), 2),
                }
            )

    for npy in current_scratch_stem_paths(outdir, manifest):
        try:
            audio = np.load(npy).astype("float32", copy=False)
            _audio_candidates(npy.stem.split(".")[-1], "stem", audio)
        except Exception:
            continue

    files = manifest.get("files") or {}
    preview = files.get("preview") or {}
    if isinstance(preview, dict):
        for name, rel in sorted(preview.items()):
            if not isinstance(rel, str):
                continue
            try:
                import soundfile as sf

                audio, _sr = sf.read(outdir / rel, always_2d=True, dtype="float32")
                _audio_candidates(f"preview_{name}", "preview", audio)
            except Exception:
                continue

    rows.sort(key=lambda r0: (float(r0["score"]), float(r0["peak_frequency_hz"])), reverse=True)
    rows = rows[:max_candidates]
    if rows:
        worst = rows[0]
        warnings.append(
            f"audio shrillness candidates found; top {worst['source']} at {worst['time_start_s']}-{worst['time_end_s']}s "
            f"near {worst['peak_frequency_hz']} Hz ({worst['severity']})"
        )
    if sum(1 for r0 in rows if str(r0.get("source")) == "strings") >= 4:
        warnings.append("strings/guitar stem has repeated narrow high-band peaks; inspect guitar register or postprocess")

    payload = {
        "schema": "ambition.audio_shrillness_audit.v1",
        "cue": manifest.get("id"),
        "hash": manifest.get("hash"),
        "bucket_seconds": bucket_seconds,
        "thresholds": {
            "min_frequency_hz": 4000.0,
            "piercing_hz": 6000.0,
            "whistle_hz": 8000.0,
            "extreme_hz": 10000.0,
            "min_peak_db": -68.0,
            "min_narrowness_db": 16.0,
        },
        "candidate_count": len(rows),
        "warnings": warnings,
        "candidates": rows,
    }
    json_path = reports_dir / "audio_shrillness_candidates.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    tsv_path = reports_dir / "audio_shrillness_candidates.tsv"
    cols = [
        "score", "severity", "kind", "source", "time_start_s", "time_end_s",
        "peak_frequency_hz", "peak_db", "floor_db", "narrowness_db", "prominence_db",
    ]
    lines = ["\t".join(cols)]
    for row in rows:
        lines.append("\t".join(str(row.get(col, "")) for col in cols))
    tsv_path.write_text("\n".join(lines) + "\n", encoding="utf8")

    summary = reports_dir / "audio_shrillness_candidates_summary.txt"
    text = [
        f"cue: {manifest.get('id')}",
        f"hash: {manifest.get('hash')}",
        f"candidate_count: {len(rows)}",
        "purpose: audio-derived review candidates for narrow, standalone 4-12.5 kHz peaks",
        "",
        "warnings:",
    ]
    text.extend([f"  - {w}" for w in warnings] if warnings else ["  none"])
    text.extend(["", "top candidates:"])
    for row in rows[:16]:
        text.append(
            f"  {row['time_start_s']:>6}-{row['time_end_s']:<6}s {row['source']:<24} "
            f"{row['peak_frequency_hz']:>7} Hz {row['severity']} score {row['score']} "
            f"peak {row['peak_db']} dB narrow {row['narrowness_db']} dB"
        )
    summary.write_text("\n".join(text) + "\n", encoding="utf8")
    return json_path



