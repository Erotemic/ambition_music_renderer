"""Manifest audio metadata, level, mix, state, and stem export reports."""

from __future__ import annotations

from . import bundle_base as _bundle_base

globals().update({k: v for k, v in vars(_bundle_base).items() if not k.startswith("__")})

def write_audio_metadata_report(outdir: Path, manifest: dict, reports_dir: Path) -> Path:
    """Record which audio metadata/chapter tags were written for manifest files."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for entry in manifest_audio_entries(manifest):
        rel = Path(entry["path"])
        sidecar = outdir / rel.with_name(rel.name + ".metadata.json")
        row: dict[str, object] = {
            "kind": entry.get("kind", ""),
            "section": entry.get("section", ""),
            "group": entry.get("group", ""),
            "audio_path": str(rel),
            "metadata_sidecar": str(sidecar.relative_to(outdir)) if sidecar.exists() else "",
            "marker_count": 0,
            "title": "",
            "cue_id": "",
            "section_id": "",
            "markers": "",
            "error": "",
        }
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf8"))
                row["title"] = str(meta.get("TITLE", ""))
                row["marker_count"] = int(meta.get("AMBITION_MARKER_COUNT", 0) or 0)
                row["cue_id"] = str(meta.get("CUE_ID", ""))
                row["section_id"] = str(meta.get("SECTION_ID", ""))
                row["markers"] = ",".join(
                    str(meta.get(f"CHAPTER{idx:03d}NAME", meta.get(f"CHAPTER{idx:03d}ID", "")))
                    for idx in range(1, int(row["marker_count"]) + 1)
                )
            except Exception as ex:  # noqa: BLE001
                row["error"] = f"{type(ex).__name__}: {ex}"
        else:
            row["error"] = "metadata sidecar missing; audio player may not show cue/section breadcrumbs"
        rows.append(row)

    json_path = reports_dir / "audio_metadata.json"
    json_path.write_text(
        json.dumps({"schema": "ambition.audio_metadata_report.v1", "rows": rows}, indent=2),
        encoding="utf8",
    )
    columns = [
        "kind", "section", "group", "audio_path", "metadata_sidecar", "marker_count",
        "title", "cue_id", "section_id", "markers", "error",
    ]
    tsv = reports_dir / "audio_metadata.tsv"
    lines = ["\t".join(columns)]
    for row in rows:
        lines.append("\t".join(str(row.get(c, "")).replace("\t", " ").replace("\n", " ") for c in columns))
    tsv.write_text("\n".join(lines) + "\n", encoding="utf8")
    summary = reports_dir / "audio_metadata_summary.txt"
    text = [f"manifest audio files: {len(rows)}", "", "metadata/chapter sidecars:"]
    for row in rows:
        marker_count = int(row.get("marker_count", 0) or 0)
        status = f"{marker_count} marker(s)" if marker_count else str(row.get("error", "no markers"))
        text.append(f"  {row.get('audio_path')}: {status}")
    summary.write_text("\n".join(text) + "\n", encoding="utf8")
    return json_path


def write_manifest_audio_level_report(outdir: Path, manifest: dict, reports_dir: Path) -> Path:
    """Write level stats for manifest-referenced audio only."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    columns = [
        "kind",
        "section",
        "group",
        "duration_s",
        "rms_dbfs",
        "peak_dbfs",
        "sample_rate",
        "path",
        "error",
    ]
    rows: list[dict[str, object]] = []
    for entry in manifest_audio_entries(manifest):
        path = outdir / entry["path"]
        stats, error = _read_audio_stats(path)
        rows.append({**entry, **(stats or {}), "error": error or ""})

    out = reports_dir / "manifest_audio_levels.tsv"
    lines = ["\t".join(columns)]
    for row in rows:
        cells: list[str] = []
        for col in columns:
            value = row.get(col, "")
            cells.append(f"{value:.3f}" if isinstance(value, float) else str(value))
        lines.append("\t".join(cells))
    out.write_text("\n".join(lines) + "\n", encoding="utf8")
    (reports_dir / "manifest_audio_levels.json").write_text(
        json.dumps({"rows": rows}, indent=2), encoding="utf8"
    )
    return out


def summarize_mix_diagnostics(manifest: dict, reports_dir: Path) -> tuple[Path, list[str]]:
    """Write human-readable mix diagnostics from manifest renderer stats."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = manifest.get("diagnostics") or {}
    warnings = list(diagnostics.get("warnings") or []) if isinstance(diagnostics, dict) else []
    lines: list[str] = []
    lines.append(f"cue: {manifest.get('id', 'unknown')}")
    lines.append(f"hash: {manifest.get('hash', 'unknown')}")
    lines.append(f"runtime_stem_gain_mode: {manifest.get('runtime_stem_gain_mode', 'native')}")
    if isinstance(diagnostics, dict):
        raw = diagnostics.get("raw_full") or {}
        mastered = diagnostics.get("mastered_full") or {}
        lines.append("")
        lines.append("raw all-stem reference:")
        lines.append(f"  rms_dbfs: {raw.get('rms_dbfs', 'n/a')}")
        lines.append(f"  peak_dbfs: {raw.get('peak_dbfs', 'n/a')}")
        lines.append("mastered full preview:")
        lines.append(f"  rms_dbfs: {mastered.get('rms_dbfs', 'n/a')}")
        lines.append(f"  peak_dbfs: {mastered.get('peak_dbfs', 'n/a')}")
        lines.append(f"master_rms_lift_db: {diagnostics.get('master_rms_lift_db', 'n/a')}")
        lines.append(f"runtime_gain_db: {diagnostics.get('runtime_gain_db', 'n/a')}")
        lines.append(f"runtime_gain_reason: {diagnostics.get('runtime_gain_reason', 'n/a')}")
        section_mastering = diagnostics.get("adaptive_section_mastering") or {}
        if isinstance(section_mastering, dict) and section_mastering:
            lines.append("")
            lines.append("adaptive section mastering:")
            lines.append(f"  mode: {section_mastering.get('mode', 'n/a')}")
            ignored = section_mastering.get("ignored_section_postprocess_sections") or []
            if ignored:
                lines.append("  ignored section-local postprocess for full mixes: " + ", ".join(map(str, ignored)))
            notes = section_mastering.get("notes")
            if notes:
                lines.append(f"  notes: {notes}")
        native = diagnostics.get("native_stems") or {}
        runtime = diagnostics.get("runtime_stems") or {}
        if isinstance(native, dict) and native:
            lines.append("")
            lines.append("native stem rms/peak:")
            for group, stats in sorted(native.items()):
                if isinstance(stats, dict):
                    lines.append(
                        f"  {group}: rms {stats.get('rms_dbfs', 'n/a')} dBFS, "
                        f"peak {stats.get('peak_dbfs', 'n/a')} dBFS"
                    )
        if isinstance(runtime, dict) and runtime and runtime != native:
            lines.append("")
            lines.append("runtime export stem rms/peak:")
            for group, stats in sorted(runtime.items()):
                if isinstance(stats, dict):
                    lines.append(
                        f"  {group}: rms {stats.get('rms_dbfs', 'n/a')} dBFS, "
                        f"peak {stats.get('peak_dbfs', 'n/a')} dBFS"
                    )
    if warnings:
        lines.append("")
        lines.append("warnings:")
        for warning in warnings:
            lines.append(f"  - {warning}")
    else:
        lines.append("")
        lines.append("warnings: none")
    out = reports_dir / "mix_diagnostics.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf8")
    (reports_dir / "mix_diagnostics.json").write_text(
        json.dumps({"diagnostics": diagnostics, "warnings": warnings}, indent=2),
        encoding="utf8",
    )
    return out, warnings


def write_state_mix_report(spec: dict, manifest: dict, reports_dir: Path) -> Path:
    """Describe how different preview states differ.

    State previews can sound nearly identical when they use the same section and
    only scale the same stems by small amounts. This report makes that explicit
    so normalized audition previews are not mistaken for distinct adaptive music.

    Dynamic cues often use ``preferred_section`` rather than ``section`` and may
    include event-style states with ``fade_in`` overlays. Keep those visible so
    the report remains useful for encounter music with intro/wave/fallback/outro
    states.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    state_map = spec.get("state_map") or {}
    groups = sorted({inst.get("group", inst.get("name")) for inst in spec.get("instruments", [])})
    rows: list[dict[str, object]] = []
    for name, cfg in sorted(state_map.items()):
        if not isinstance(cfg, dict):
            continue
        section = cfg.get("section") or cfg.get("preferred_section") or cfg.get("outro")
        weight_source = "stems"
        stems = cfg.get("stems")
        if not isinstance(stems, dict):
            stems = cfg.get("fade_in")
            weight_source = "fade_in" if isinstance(stems, dict) else "none"
        if not isinstance(stems, dict):
            stems = {}
        vector = {g: float(stems.get(g, 0.0)) for g in groups}
        rows.append(
            {
                "state": name,
                "section": section,
                "weights": vector,
                "weight_source": weight_source,
                "active_stems": [g for g, v in vector.items() if v > 0.0],
                "weight_sum": sum(vector.values()),
                "transition": cfg.get("transition"),
                "fade_beats": cfg.get("fade_beats"),
            }
        )

    by_state = {str(row["state"]): row for row in rows}
    default = by_state.get("default")
    baseline_note = "default state"
    if default is None:
        default = next((row for row in rows if float(row.get("weight_sum", 0.0)) > 0.0), None)
        if default is not None:
            baseline_note = f"first state with explicit stem weights: {default.get('state')}"
    if default is None and rows:
        default = rows[0]
        baseline_note = f"first listed state: {default.get('state')}"

    distances: list[dict[str, object]] = []
    if default is not None:
        base = default["weights"]
        assert isinstance(base, dict)
        base_norm = math.sqrt(sum(float(v) * float(v) for v in base.values()))
        for row in rows:
            vec = row["weights"]
            assert isinstance(vec, dict)
            diff = {g: float(vec.get(g, 0.0)) - float(base.get(g, 0.0)) for g in groups}
            l2 = math.sqrt(sum(v * v for v in diff.values()))
            denom = max(base_norm, 1.0)
            distances.append(
                {
                    "state": row["state"],
                    "section": row["section"],
                    "distance_from_baseline": l2,
                    "relative_distance_from_baseline": l2 / denom,
                    # Backward-compatible keys.
                    "distance_from_default": l2,
                    "relative_distance_from_default": l2 / denom,
                    "changed_stems": {g: round(v, 4) for g, v in diff.items() if abs(v) > 1e-9},
                }
            )

    preview_stats = (((manifest.get("diagnostics") or {}).get("runtime_previews") or {}))
    payload = {
        "schema": "ambition.music_state_mix_report.v1",
        "cue": spec.get("id"),
        "states": rows,
        "baseline_state": default.get("state") if isinstance(default, dict) else None,
        "baseline_note": baseline_note,
        "distances_from_default": distances,
        "runtime_preview_stats": preview_stats,
        "note": (
            "runtime_* previews are weighted stem sums without upward audition normalization; "
            "audition_* previews are normalized for comfortable listening and may collapse loudness differences. "
            "States using fade_in are overlay events, not full replacement mixes."
        ),
    }
    json_path = reports_dir / "state_mix_report.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    tsv_path = reports_dir / "state_mix_report.tsv"
    columns = ["state", "section", "weight_source", "weight_sum", "distance_from_baseline", "relative_distance_from_baseline", "weights"]
    distance_by_state = {str(row["state"]): row for row in distances}
    lines = ["\t".join(columns)]
    for row in rows:
        dist = distance_by_state.get(str(row["state"]), {})
        weights = row.get("weights", {})
        weight_text = ",".join(f"{g}:{float(v):.3f}" for g, v in sorted(weights.items())) if isinstance(weights, dict) else ""
        lines.append(
            "\t".join(
                [
                    str(row.get("state", "")),
                    str(row.get("section", "")),
                    str(row.get("weight_source", "")),
                    f"{float(row.get('weight_sum', 0.0)):.3f}",
                    f"{float(dist.get('distance_from_baseline', 0.0)):.3f}",
                    f"{float(dist.get('relative_distance_from_baseline', 0.0)):.3f}",
                    weight_text,
                ]
            )
        )
    tsv_path.write_text("\n".join(lines) + "\n", encoding="utf8")

    summary = reports_dir / "state_mix_report_summary.txt"
    text: list[str] = [
        f"cue: {spec.get('id')}",
        "runtime previews are native weighted sums; audition previews are normalized.",
        f"baseline: {baseline_note}",
        "",
        "state distances from default/baseline:",
    ]
    for dist in distances:
        text.append(
            f"  {dist.get('state')}: rel {float(dist.get('relative_distance_from_baseline', 0.0)):.2f} "
            f"section {dist.get('section')} changed {dist.get('changed_stems')}"
        )
    if not by_state.get("default"):
        text.append("")
        text.append("note: no explicit default state; reports use the first state with explicit stem weights as the baseline.")
    if rows:
        no_stem_states = [str(row["state"]) for row in rows if float(row.get("weight_sum", 0.0)) <= 0.0]
        if no_stem_states:
            text.append("note: states without explicit stem weights: " + ", ".join(no_stem_states))
    if distances:
        non_base = [d for d in distances if d.get("state") != (default or {}).get("state")]
        if non_base and max(float(d.get("relative_distance_from_baseline", 0.0)) for d in non_base) < 0.35:
            text.append("")
            text.append("warning: state maps are close together; previews may sound mostly like level variants.")
    summary.write_text("\n".join(text) + "\n", encoding="utf8")
    return json_path


def write_stem_export_report(outdir: Path, manifest: dict, reports_dir: Path) -> Path:
    """Compare retained .npy stem buffers with exported per-stem audio files.

    This is the report we wanted during the Emmy debugging session: it answers
    whether scratch stem buffers, adaptive stem OGGs, and section full mixes have
    matching durations and plausible levels.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    sample_rate = int(manifest.get("sample_rate", 48000))
    cue_id = manifest.get("id", "unknown")
    rows: list[dict[str, object]] = []

    for npy in current_scratch_stem_paths(outdir, manifest):
        group = npy.stem.split(".")[-1]
        try:
            arr = np.load(npy).astype("float32", copy=False)
            stats = _audio_stats(arr, sample_rate)
            error = ""
        except Exception as ex:  # noqa: BLE001
            stats = {}
            error = f"{type(ex).__name__}: {ex}"
        rows.append(
            {
                "kind": "scratch_npy",
                "section": "*",
                "group": group,
                "path": str(npy.relative_to(outdir)),
                **stats,
                "error": error,
            }
        )

    for entry in manifest_audio_entries(manifest):
        path = outdir / entry["path"]
        stats, error = _read_audio_stats(path)
        rows.append({**entry, **(stats or {}), "error": error or ""})

    columns = [
        "kind",
        "section",
        "group",
        "duration_s",
        "rms_dbfs",
        "peak_dbfs",
        "sample_rate",
        "path",
        "error",
    ]
    out = reports_dir / "stem_export_report.tsv"
    lines = ["\t".join(columns)]
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, float):
                cells.append(f"{value:.3f}")
            else:
                cells.append(str(value))
        lines.append("\t".join(cells))
    out.write_text("\n".join(lines) + "\n", encoding="utf8")

    summary = {
        "cue_id": cue_id,
        "outdir": str(outdir),
        "rows": rows,
    }
    (reports_dir / "stem_export_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf8"
    )
    return out



