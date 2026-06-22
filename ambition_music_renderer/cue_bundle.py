"""Cue regeneration, diagnostics, and shareable debug bundles.

This module is intentionally an orchestration layer around the current renderer
rather than a replacement renderer.  Its job is to make one cue reproducible and
inspectable from a single command while the lower-level MusicIR internals are
refactored behind a stable workflow.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import yaml

from . import musicir_renderer as r
from .arrangement_audit import audit_file as audit_arrangement_file
from .arrangement_audit import write_reports as write_arrangement_reports
from .dissonance_audit import audit_file as audit_dissonance_file
from .dissonance_audit import write_reports as write_dissonance_reports
from .sour_note_audit import audit_file as audit_sour_note_file
from .sour_note_audit import write_reports as write_sour_note_reports
from .shrill_note_audit import audit_file as audit_shrill_note_file
from .shrill_note_audit import write_reports as write_shrill_note_reports
from .profiler import profile

DEFAULT_BACKEND = "pretty-midi"
BACKEND_CHOICES = ("pretty-midi", "fluidsynth-cli", "fallback", "auto")
RUNTIME_STEM_GAIN_MODES = ("native", "shared")
PLOT_FORMATS = ("jpg", "png")
RENDER_AUDIO_MODES = ("full", "full-mix-only", "simple-mix")
REPORT_ZIP_EXCLUDED_SUFFIXES = {".ogg", ".oga", ".wav", ".flac", ".mp3", ".npy", ".mid", ".midi"}
DBFS_SILENCE_FLOOR = -120.0
DBFS_PLOT_FLOOR = -100.0


def _plot_db(value: float) -> float:
    """Clamp dBFS values for plots so near-silence does not dominate axes."""
    try:
        return max(float(value), DBFS_PLOT_FLOOR)
    except Exception:
        return DBFS_PLOT_FLOOR


def _format_dbfs(value: object) -> str:
    """Human-friendly dBFS formatting with an inaudible floor marker."""
    try:
        v = float(value)
    except Exception:
        return "n/a"
    if v <= DBFS_PLOT_FLOOR:
        return f"< {DBFS_PLOT_FLOOR:.0f}"
    return f"{v:.1f}"


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    stdout: Path
    stderr: Path
    elapsed_s: float | None = None

    @property
    def stdout_tail(self) -> str:
        return _tail_text(self.stdout)

    @property
    def stderr_tail(self) -> str:
        return _tail_text(self.stderr)


def package_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_generated_root() -> Path:
    return package_dir() / "generated"


def default_bundle_root() -> Path:
    return package_dir() / "bundles"


def default_publish_dest_root() -> Path:
    return (
        repo_root()
        / "crates"
        / "ambition_gameplay_core"
        / "assets"
        / "audio"
        / "music"
        / "generated"
    )


def find_score(cue: str) -> Path | None:
    """Locate a MusicIR score by cue id or path.

    Kept local to avoid importing the top-level CLI from this lower-level helper.
    """
    p = Path(cue)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return p.resolve()
    for sub in ("active", "examples", "archive", "experiments"):
        for suffix in (".music.yaml", ".yaml", ".yml"):
            candidate = package_dir() / "scores" / sub / f"{cue}{suffix}"
            if candidate.exists():
                return candidate.resolve()
    return None


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected YAML mapping in {path}")
    return data


def latest_manifest(outdir: Path, cue_id: str) -> Path | None:
    candidates = sorted(
        outdir.glob(f"{cue_id}_*.adaptive_manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def safe_rel(path: Path, root: Path | None = None) -> str:
    path = Path(path)
    if root is None:
        root = repo_root()
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _tail_text(path: Path, *, max_lines: int = 80, max_chars: int = 12000) -> str:
    try:
        text = path.read_text(encoding="utf8", errors="replace")
    except Exception:
        return ""
    lines = text.splitlines()[-max_lines:]
    tail = "\n".join(lines)
    if len(tail) > max_chars:
        tail = tail[-max_chars:]
    return tail


@profile
def run_logged(name: str, command: list[str], reports_dir: Path, *, cwd: Path) -> CommandResult:
    import time as _time

    reports_dir.mkdir(parents=True, exist_ok=True)
    stdout = reports_dir / f"{name}.stdout.txt"
    stderr = reports_dir / f"{name}.stderr.txt"
    start = _time.perf_counter()
    with stdout.open("w", encoding="utf8") as out_f, stderr.open("w", encoding="utf8") as err_f:
        proc = subprocess.run(command, cwd=cwd, stdout=out_f, stderr=err_f)
    elapsed = _time.perf_counter() - start
    result = CommandResult(name, command, proc.returncode, stdout, stderr, elapsed)
    if proc.returncode != 0:
        progress_line(f"command failed: {name} rc={proc.returncode} elapsed_s={elapsed:.3f}")
        progress_line(f"stdout: {terminal_link(stdout)}")
        progress_line(f"stderr: {terminal_link(stderr)}")
        tail = result.stderr_tail
        if tail:
            print(f"[music bundle] --- {name} stderr tail ---")
            print(tail)
    return result


@profile
def run_render_in_process(name: str, argv: list[str], reports_dir: Path) -> CommandResult:
    """Run render_isolated in this interpreter for useful line-profiler output."""
    import time as _time
    from . import render_isolated

    reports_dir.mkdir(parents=True, exist_ok=True)
    stdout = reports_dir / f"{name}.stdout.txt"
    stderr = reports_dir / f"{name}.stderr.txt"
    stdout.write_text("in-process render; output streamed to terminal\n", encoding="utf8")
    stderr.write_text("in-process render; stderr streamed to terminal\n", encoding="utf8")
    start = _time.perf_counter()
    rc = 1
    try:
        rc = int(render_isolated.main(argv))
    except SystemExit as ex:
        code = ex.code
        rc = int(code) if isinstance(code, int) else 1
    elapsed = _time.perf_counter() - start
    return CommandResult(name, ["<in-process>", "ambition_music_renderer.render_isolated", *argv], rc, stdout, stderr, elapsed)


def _db(value: float) -> float:
    # dBFS is referenced to the digital full-scale ceiling: 0 dBFS is max
    # representable level, not silence. Silence trends toward -inf. We keep
    # analysis finite at -120 dBFS, and plots separately clamp at -100 dBFS
    # because lower values are almost always noise-floor/roundoff artifacts.
    value = max(float(value), 1e-6)
    return 20.0 * math.log10(value)


def _audio_stats(audio: np.ndarray, sample_rate: int) -> dict[str, float]:
    if audio.size == 0:
        return {
            "sample_rate": float(sample_rate),
            "duration_s": 0.0,
            "peak_dbfs": _db(0.0),
            "rms_dbfs": _db(0.0),
        }
    frames = audio.shape[0]
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    return {
        "sample_rate": float(sample_rate),
        "duration_s": float(frames / sample_rate) if sample_rate else 0.0,
        "peak_dbfs": _db(peak),
        "rms_dbfs": _db(rms),
    }


def _read_audio_stats(path: Path) -> tuple[dict[str, float] | None, str | None]:
    try:
        import soundfile as sf

        audio, sample_rate = sf.read(path, always_2d=True, dtype="float32")
        return _audio_stats(audio.astype("float32", copy=False), int(sample_rate)), None
    except Exception as ex:  # noqa: BLE001 - report diagnostics, do not fail the bundle.
        return None, f"{type(ex).__name__}: {ex}"


def manifest_duration(manifest: dict) -> float:
    sections = manifest.get("sections") or []
    ends = [float(sec.get("end_seconds", 0.0)) for sec in sections if isinstance(sec, dict)]
    return max(ends) if ends else 0.0


def section_time_offsets(manifest: dict) -> dict[str, float]:
    """Return manifest section start times keyed by section id.

    Dynamic section-stem cues render each section's audio from local time zero.
    Reports that concatenate diagnostics over the soundtrack must reapply these
    manifest offsets; otherwise every section overlays at t=0 and the plots are
    misleading for layered encounter music.
    """
    offsets: dict[str, float] = {}
    for section in manifest.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = section.get("id")
        if section_id is None:
            continue
        offsets[str(section_id)] = float(section.get("start_seconds", 0.0) or 0.0)
    return offsets


def ordered_section_ids(manifest: dict) -> list[str]:
    return [
        str(section.get("id"))
        for section in manifest.get("sections") or []
        if isinstance(section, dict) and section.get("id") is not None
    ]


def adjacent_section_pairs(manifest: dict) -> list[tuple[str, str]]:
    sections = ordered_section_ids(manifest)
    return list(zip(sections, sections[1:]))


def manifest_audio_entries(manifest: dict) -> list[dict[str, str]]:
    """Return audio files explicitly referenced by an adaptive manifest.

    This intentionally ignores any extra files sitting in preview/ or adaptive/.
    Bundles and reports must be hash/manifest scoped so stale renders do not
    contaminate diagnostics.
    """
    entries: list[dict[str, str]] = []
    files = manifest.get("files") or {}
    preview = files.get("preview") or {}
    if isinstance(preview, dict):
        for name, rel in sorted(preview.items()):
            if isinstance(rel, str):
                entries.append(
                    {
                        "kind": "preview_audio",
                        "section": "*",
                        "group": name,
                        "path": rel,
                    }
                )
    adaptive = files.get("adaptive") or {}
    if isinstance(adaptive, dict):
        for section_id, section_files in sorted(adaptive.items()):
            if not isinstance(section_files, dict):
                continue
            for group, rel in sorted(section_files.items()):
                if isinstance(rel, str):
                    entries.append(
                        {
                            "kind": "adaptive_audio",
                            "section": section_id,
                            "group": group,
                            "path": rel,
                        }
                    )
    return entries


def current_scratch_stem_paths(outdir: Path, manifest: dict) -> list[Path]:
    """Return scratch stem buffers for this manifest hash only."""
    scratch_dir = outdir / "scratch_stems"
    if not scratch_dir.is_dir():
        return []
    cue_id = str(manifest.get("id", ""))
    render_hash = str(manifest.get("hash", ""))
    if cue_id and render_hash:
        return sorted(scratch_dir.glob(f"{cue_id}_{render_hash}.*.npy"))
    return sorted(scratch_dir.glob("*.npy"))


def copy_current_scratch_stems(outdir: Path, manifest: dict, dest_root: Path) -> list[str]:
    copied: list[str] = []
    for src in current_scratch_stem_paths(outdir, manifest):
        rel = Path("scratch_stems") / src.name
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(rel))
        meta_src = src.with_name(src.name + ".metadata.json")
        if meta_src.exists():
            meta_dst = dst.with_name(dst.name + ".metadata.json")
            shutil.copy2(meta_src, meta_dst)
            copied.append(str(rel) + ".metadata.json")
    return copied


def copy_manifest_referenced_files(outdir: Path, manifest: dict, bundle_dir: Path) -> list[str]:
    copied: list[str] = []
    for entry in manifest_audio_entries(manifest):
        rel = Path(entry["path"])
        src = outdir / rel
        if not src.exists():
            continue
        dst = bundle_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(rel))
        meta_src = src.with_name(src.name + ".metadata.json")
        if meta_src.exists():
            meta_dst = dst.with_name(dst.name + ".metadata.json")
            shutil.copy2(meta_src, meta_dst)
            copied.append(str(rel) + ".metadata.json")
    return copied


def prepare_manifest_analysis_root(outdir: Path, manifest: dict, analysis_root: Path) -> Path:
    """Create a clean manifest-scoped tree for external diagnostic scripts.

    Several legacy analysis helpers scan entire ``preview/``, ``adaptive/`` or
    ``scratch_stems/`` directories. Running them directly on a long-lived output
    directory lets stale render hashes pollute reports. This helper builds the
    small tree those tools expect, but containing only files referenced by the
    current manifest plus scratch stems matching the current render hash.
    """
    if analysis_root.exists():
        shutil.rmtree(analysis_root)
    analysis_root.mkdir(parents=True, exist_ok=True)
    copy_manifest_referenced_files(outdir, manifest, analysis_root)
    copy_current_scratch_stems(outdir, manifest, analysis_root)
    return analysis_root


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
            arr = r._coerce_stereo(arr)
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
            save_kwargs: dict[str, object] = {"dpi": 130, "bbox_inches": "tight"}
            if suffix == "jpg":
                save_kwargs["format"] = "jpeg"
                save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality), "optimize": True}
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
                ax.set_title("Stem amplitude over absolute section time")
                ax.grid(True, alpha=0.3)
                ax.legend(loc="best", fontsize=8)
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




def adaptive_section_mastering_config_from_spec(spec: dict) -> dict[str, object]:
    render_cfg = spec.get("render", {}) or {}
    cfg = render_cfg.get("adaptive_section_mastering") or render_cfg.get("adaptive_sections") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    mode = str(cfg.get("mode", cfg.get("full_mix_mode", "section_postprocess")))
    return {
        "mode": mode,
        "ignore_section_postprocess_for_full_mix": bool(
            cfg.get("ignore_section_postprocess_for_full_mix", mode == "global_master_slices")
        ),
        "notes": str(cfg.get("notes", "")),
    }

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
    section_spec_by_id = {str(s0.get("id")): s0 for s0 in section_specs if s0.get("id") is not None}
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
            save_kwargs: dict[str, object] = {"dpi": 130, "bbox_inches": "tight"}
            if suffix == "jpg":
                save_kwargs["format"] = "jpeg"
                save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality), "optimize": True}

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
            save_kwargs: dict[str, object] = {"dpi": 130, "bbox_inches": "tight"}
            if suffix == "jpg":
                save_kwargs["format"] = "jpeg"
                save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality), "optimize": True}
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
        arr = r._coerce_stereo(audio).astype("float32", copy=False)
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

    def _spectrogram_db(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        mono = audio.mean(axis=1) if audio.ndim == 2 else audio.astype("float32")
        if mono.size == 0:
            return np.asarray([]), np.asarray([]), np.asarray([[]])
        nperseg = min(4096, max(256, int(2 ** math.floor(math.log2(max(256, min(len(mono), 4096)))))))
        noverlap = max(0, int(nperseg * 0.75))
        freqs, times, spec = signal.spectrogram(
            mono,
            fs=sample_rate,
            nperseg=nperseg,
            noverlap=noverlap,
            scaling="spectrum",
            mode="magnitude",
        )
        return freqs, times, 20 * np.log10(spec + 1e-10)

    def _save_kwargs(dest: Path) -> dict:
        save_kwargs = {"dpi": 120}
        if dest.suffix.lower() in {".jpg", ".jpeg"}:
            save_kwargs["format"] = "jpeg"
            save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality), "optimize": True}
        return save_kwargs

    def save_audio_plot(audio: np.ndarray, title: str, dest: Path) -> None:
        freqs, times, spec_db = _spectrogram_db(audio)
        if spec_db.size == 0:
            return
        plt.figure(figsize=(14, 5))
        plt.pcolormesh(times, freqs, spec_db, shading="auto", vmin=-110, vmax=-35, cmap="inferno")
        plt.yscale("log")
        plt.ylim(80, 12000)
        plt.axhspan(3000, 6000, alpha=0.15)
        plt.axhspan(6000, 12000, alpha=0.10)
        plt.title(title)
        plt.xlabel("time (s)")
        plt.ylabel("frequency (Hz)")
        plt.colorbar(label="dB, fixed -110..-35")
        plt.tight_layout()
        plt.savefig(dest, **_save_kwargs(dest))
        plt.close()

    def save_high_detail_plot(audio: np.ndarray, title: str, dest: Path) -> None:
        freqs, times, spec_db = _spectrogram_db(audio)
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
        plt.figure(figsize=(14, 5))
        plt.pcolormesh(times, freqs[mask], focus, shading="auto", vmin=vmin, vmax=vmax, cmap="inferno")
        plt.yscale("log")
        plt.ylim(2500, 16000)
        plt.axhline(4000, linestyle="--", linewidth=0.8)
        plt.axhline(8000, linestyle=":", linewidth=0.9)
        plt.title(f"{title} — high-frequency detail")
        plt.xlabel("time (s)")
        plt.ylabel("frequency (Hz)")
        plt.colorbar(label=f"relative dB, local percentile {vmin:.0f}..{vmax:.0f}")
        plt.tight_layout()
        plt.savefig(dest, **_save_kwargs(dest))
        plt.close()

    def save_shrill_detail_plot(audio: np.ndarray, title: str, dest: Path) -> None:
        freqs, times, spec_db = _spectrogram_db(audio)
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
        plt.figure(figsize=(14, 5))
        plt.pcolormesh(times, freqs[mask], focus, shading="auto", vmin=vmin, vmax=vmax, cmap="inferno")
        # Linear high-frequency axis makes isolated C8-C9 whistle lines easier
        # to see than the full log spectrogram. The percentile colorbar avoids
        # cymbal/drum maxima hiding quieter but audible standalone tones.
        plt.ylim(3500, 12500)
        for hz, label in ((4000, "4k review"), (6000, "6k piercing"), (8000, "8k whistle"), (10000, "10k extreme")):
            plt.axhline(hz, linestyle="--", linewidth=0.7)
            if times.size:
                plt.text(float(times[0]), hz * 1.01, label, fontsize=7, va="bottom")
        plt.title(f"{title} — shrill-band detail")
        plt.xlabel("time (s)")
        plt.ylabel("frequency (Hz, linear)")
        plt.colorbar(label=f"relative dB, local percentile {vmin:.0f}..{vmax:.0f}")
        plt.tight_layout()
        plt.savefig(dest, **_save_kwargs(dest))
        plt.close()

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
            save_audio_plot(audio, label, dest)
            if dest.exists():
                written.append(dest)
            high_dest = plots_dir / f"{label}.spectrogram_high_detail.{suffix}"
            save_high_detail_plot(audio, label, high_dest)
            if high_dest.exists():
                written.append(high_dest)
            shrill_dest = plots_dir / f"{label}.spectrogram_shrill_detail.{suffix}"
            save_shrill_detail_plot(audio, label, shrill_dest)
            if shrill_dest.exists():
                written.append(shrill_dest)
        except Exception as ex:  # noqa: BLE001
            (plots_dir / f"{label}.spectrogram.error.txt").write_text(
                f"failed to render {path}: {type(ex).__name__}: {ex}\n",
                encoding="utf8",
            )
    return written


def run_transition_audits(
    analysis_root: Path,
    manifest: dict,
    reports_dir: Path,
    tools_dir: Path,
    *,
    max_pairs: int = 8,
    crossfade_seconds: float = 0.65,
    crossfade_shape: str = "ambition_runtime",
) -> list[CommandResult]:
    """Run audio seam diagnostics for adjacent adaptive sections.

    The generated report zip omits WAV previews, but keeping transition metrics,
    envelopes, and spectrogram PNGs in the bundle makes dynamic encounter cues
    auditable without opening the game.
    """
    results: list[CommandResult] = []
    pairs = adjacent_section_pairs(manifest)[:max_pairs]
    if not pairs:
        return results
    section_meta = {str(sec.get("id")): sec for sec in manifest.get("sections") or [] if isinstance(sec, dict)}
    audit_script = (tools_dir / "transition_audit.py").resolve()
    if not audit_script.exists():
        return results
    audit_root = reports_dir / "transition_audit"
    audit_root.mkdir(parents=True, exist_ok=True)
    for first, second in pairs:
        outdir = audit_root / f"{first}_to_{second}"
        first_meta = section_meta.get(first, {})
        second_meta = section_meta.get(second, {})
        incoming_start = (
            "target"
            if str(first_meta.get("kind")) == "intro" and bool(second_meta.get("loopable", False))
            else "smooth"
        )
        cmd = [
            sys.executable,
            str(audit_script),
            str(analysis_root),
            "--sections",
            first,
            second,
            "--crossfade",
            str(crossfade_seconds),
            "--crossfade-shape",
            crossfade_shape,
            "--incoming-start",
            incoming_start,
            "--outdir",
            str(outdir),
        ]
        safe_name = f"transition_audit_{first}_to_{second}".replace("/", "_")
        results.append(run_logged(safe_name, cmd, reports_dir, cwd=tools_dir))
    return results


def copy_tree_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def should_include_in_report_zip(path: Path) -> bool:
    """Return True for compact, LLM-friendly bundle artifacts.

    Report zips are meant for chat/agent upload: keep source YAML, manifests,
    text/JSON/TSV diagnostics, rerun scripts, and spectrogram images, but omit
    heavyweight binary audio and raw NumPy/MIDI intermediates. The full bundle
    directory on disk remains complete either way.
    """
    return path.suffix.lower() not in REPORT_ZIP_EXCLUDED_SUFFIXES


def make_zip(src_dir: Path, zip_path: Path, *, report_only: bool = False) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path == zip_path or path.is_dir():
                continue
            if report_only and not should_include_in_report_zip(path):
                continue
            zf.write(path, path.relative_to(src_dir.parent))
    return zip_path


def file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def terminal_link(path: Path, label: str | None = None) -> str:
    """Return an OSC-8 terminal hyperlink with a plain absolute-path label.

    Terminals that do not support OSC-8 still show a ctrl-clickable absolute
    path. This keeps command output ergonomic without requiring a rich console
    dependency.
    """
    path = path.resolve()
    shown = label or str(path)
    return f"\033]8;;{path.as_uri()}\033\\{shown}\033]8;;\033\\"


def progress_line(message: str, *, stream=None) -> None:
    """Emit a visible progress update for long bundle workflows."""
    if stream is None:
        stream = sys.stderr
    print(f"[music bundle] {message}", file=stream, flush=True)


def print_bundle_summary(report: dict[str, object], *, stream=None) -> None:
    """Print human-friendly paths in addition to the machine-readable JSON."""
    if stream is None:
        stream = sys.stderr
    keys = [
        ("render output", "outdir"),
        ("bundle dir", "bundle_dir"),
        ("manifest", "manifest"),
        ("full zip", "zip"),
        ("report zip", "zip_report"),
        ("published", "published"),
    ]
    print("\nMusic bundle outputs:", file=stream)
    for label, key in keys:
        value = report.get(key)
        if not value or value == "publish failed":
            continue
        path = Path(str(value))
        print(f"  {label:13s}: {terminal_link(path)}", file=stream)
    if report.get("warnings"):
        print("  warnings     :", file=stream)
        for warning in report.get("warnings", []):
            print(f"    - {warning}", file=stream)
    print("", file=stream)


def build_rerun_script(
    bundle_dir: Path,
    cue: str,
    backend: str,
    outdir: Path,
    publish: bool,
    runtime_stem_gain_mode: str,
    plot_format: str,
    runtime_stem_max_gain_db: float | None,
    zip_bundle: bool,
    zip_report_bundle: bool,
    render_audio_mode: str = "full",
    profile_render: bool = False,
    render_in_process: bool = False,
) -> Path:
    script = bundle_dir / "rerun_bundle.sh"
    publish_flag = " --publish" if publish else ""
    cmd = [
        "uv run --project tools/ambition_music_renderer python -m ambition_music_renderer cue bundle",
        str(cue),
        "--backend",
        str(backend),
        "--runtime-stem-gain-mode",
        str(runtime_stem_gain_mode),
    ]
    if runtime_stem_max_gain_db is not None:
        cmd.extend(["--runtime-stem-max-gain-db", str(runtime_stem_max_gain_db)])
    cmd.extend(["--plot-format", str(plot_format)])
    cmd.extend(["--outdir", str(outdir), "--force", "--render-audio-mode", str(render_audio_mode)])
    if profile_render:
        cmd.append("--profile-render")
    if render_in_process:
        cmd.append("--render-in-process")
    if publish:
        cmd.append("--publish")
    if zip_bundle:
        cmd.append("--zip")
    if zip_report_bundle:
        cmd.append("--zip-report")
    wrapped = " \\\n  ".join(cmd)
    body = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cd \"$(git rev-parse --show-toplevel)\"\n"
        f"{wrapped}\n"
    )
    script.write_text(body, encoding="utf8")
    script.chmod(0o755)
    return script


@profile
def create_bundle(
    cue: str,
    *,
    backend: str = DEFAULT_BACKEND,
    runtime_stem_gain_mode: str = "native",
    outdir: Path | None = None,
    bundle_root: Path | None = None,
    force: bool = False,
    publish: bool = False,
    dest_root: Path | None = None,
    zip_bundle: bool = False,
    zip_report_bundle: bool = False,
    jobs: int = 1,
    include_scratch_stems: bool = False,
    skip_render: bool = False,
    skip_spectrograms: bool = False,
    plot_format: str = "jpg",
    jpeg_quality: int = 84,
    runtime_stem_max_gain_db: float | None = None,
    render_audio_mode: str = "full",
    profile_render: bool = False,
    render_in_process: bool = False,
) -> dict[str, object]:
    progress_line(f"locating score for {cue!r}")
    score_path = find_score(cue)
    if score_path is None:
        raise FileNotFoundError(f"cue not found: {cue}")
    spec = load_yaml(score_path)
    cue_id = str(spec.get("id", cue))
    progress_line(f"loaded {cue_id} from {terminal_link(score_path)}")
    if cue_id != Path(score_path.name).name.split(".music.yaml")[0] and score_path.name.endswith(".music.yaml"):
        # Warn in the final report without preventing compatibility renders.
        id_warning = f"score id {cue_id!r} does not match filename {score_path.name!r}"
    else:
        id_warning = ""
    if render_audio_mode not in RENDER_AUDIO_MODES:
        raise ValueError(f"render_audio_mode must be one of {RENDER_AUDIO_MODES}, got {render_audio_mode!r}")

    if outdir is None:
        outdir = default_generated_root() / cue_id
    else:
        outdir = Path(outdir)
    if bundle_root is None:
        bundle_root = default_bundle_root()
    else:
        bundle_root = Path(bundle_root)
    if dest_root is None:
        dest_root = default_publish_dest_root()
    else:
        dest_root = Path(dest_root)

    progress_line(f"render output directory: {terminal_link(outdir)}")
    progress_line(f"bundle root: {terminal_link(bundle_root)}")

    reports_dir = outdir / "reports"
    plots_dir = outdir / "plots"
    # Reports and plots are derived products for the current bundle. Clear them
    # up front so stale diagnostics from older hashes cannot contaminate a new
    # upload bundle. Audio output dirs are left alone; bundle copying is
    # manifest-scoped below.
    for derived_dir in (reports_dir, plots_dir):
        if derived_dir.exists():
            shutil.rmtree(derived_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    commands: list[CommandResult] = []

    progress_line("running arrangement preflight")
    arrangement_payload = audit_arrangement_file(score_path)
    write_arrangement_reports(arrangement_payload, reports_dir)

    if not skip_render:
        progress_line(f"rendering {cue_id} with backend={backend}, runtime_stems={runtime_stem_gain_mode}")
        render_args = [
            str(score_path),
            "--outdir",
            str(outdir),
            "--backend",
            backend,
            "--runtime-stem-gain-mode",
            runtime_stem_gain_mode,
            "--keep-debug-stems",
            "--jobs",
            str(jobs),
            "--timings-out",
            str(reports_dir / "render_isolated_timings.json"),
        ]
        if render_audio_mode == "full-mix-only":
            render_args.append("--full-mix-only")
        elif render_audio_mode == "simple-mix":
            render_args.append("--simple-mix")
        if profile_render:
            os.environ.setdefault("LINE_PROFILE", "1")
            render_in_process = True
            render_args.append("--profile-workers")
            progress_line("profiling enabled via line_profiler; running render_isolated in-process")
        if runtime_stem_max_gain_db is not None:
            render_args.extend(["--runtime-stem-max-gain-db", str(runtime_stem_max_gain_db)])
        if force:
            render_args.append("--force")
        if render_in_process:
            commands.append(run_render_in_process("render_isolated", render_args, reports_dir))
        else:
            render_cmd = [sys.executable, "-m", "ambition_music_renderer.render_isolated", *render_args]
            commands.append(run_logged("render_isolated", render_cmd, reports_dir, cwd=package_dir()))
        if commands[-1].returncode != 0:
            return {
                "cue": cue_id,
                "ok": False,
                "error": "render_isolated failed",
                "commands": [c.__dict__ for c in commands],
                "stderr_tail": commands[-1].stderr_tail if commands else "",
                "stdout_tail": commands[-1].stdout_tail if commands else "",
                "outdir": str(outdir),
            }

    if profile_render:
        copy_tree_if_exists(outdir / "profiles", reports_dir / "profiles")

    progress_line("loading adaptive manifest")
    manifest_path = latest_manifest(outdir, cue_id)
    if manifest_path is None:
        raise FileNotFoundError(f"no adaptive manifest found in {outdir} for {cue_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    render_hash = str(manifest.get("hash", "unknown"))
    duration = manifest_duration(manifest)

    # Diagnostics. These tools are report-only; a failure should not destroy the
    # bundle. Run directory-scanning legacy helpers against a clean manifest-
    # scoped analysis root so stale hashes in the real output dir cannot leak
    # into the reports.
    tools_dir = package_dir()
    progress_line("running manifest-scoped reports and plots")
    with tempfile.TemporaryDirectory(prefix=f"{cue_id}_{render_hash}_analysis_") as td:
        analysis_root = prepare_manifest_analysis_root(outdir, manifest, Path(td))
        commands.append(
            run_logged(
                "audit_cue_balance",
                [sys.executable, str(tools_dir / "audit_cue_balance.py"), str(analysis_root)],
                reports_dir,
                cwd=tools_dir,
            )
        )
        if (analysis_root / "scratch_stems").is_dir():
            hi = f"{duration:.3f}" if duration > 0 else "-1"
            commands.append(
                run_logged(
                    "spectral_compare",
                    [
                        sys.executable,
                        str(tools_dir / "spectral_compare.py"),
                        str(analysis_root),
                        "--window",
                        "0",
                        hi,
                        "--label",
                        cue_id,
                    ],
                    reports_dir,
                    cwd=tools_dir,
                )
            )
            commands.append(
                run_logged(
                    "spectral_localize",
                    [
                        sys.executable,
                        str(tools_dir / "spectral_localize.py"),
                        str(analysis_root),
                        "--window",
                        "0",
                        "-1",
                        "--bucket",
                        "0.25",
                    ],
                    reports_dir,
                    cwd=tools_dir,
                )
            )
        write_stem_export_report(analysis_root, manifest, reports_dir)
        write_manifest_audio_level_report(analysis_root, manifest, reports_dir)
        write_audio_metadata_report(analysis_root, manifest, reports_dir)
        write_stem_amplitude_report(
            analysis_root,
            spec,
            manifest,
            reports_dir,
            plots_dir=plots_dir,
            plot_format=plot_format,
            jpeg_quality=jpeg_quality,
        )
        write_adaptive_section_report(
            analysis_root,
            spec,
            manifest,
            reports_dir,
            plots_dir=plots_dir,
            plot_format=plot_format,
            jpeg_quality=jpeg_quality,
        )
        adaptive_composition_path = write_adaptive_composition_mastering_report(
            analysis_root,
            spec,
            manifest,
            reports_dir,
            plots_dir=plots_dir,
            plot_format=plot_format,
            jpeg_quality=jpeg_quality,
        )
        write_spectral_fingerprint(analysis_root, manifest, reports_dir)
        audio_shrillness_path = write_spectral_shrillness_report(analysis_root, manifest, reports_dir)
        write_state_mix_report(spec, manifest, reports_dir)
        progress_line("running adjacent-section transition audits")
        commands.extend(run_transition_audits(analysis_root, manifest, reports_dir, tools_dir))
        # Re-run arrangement preflight after render report cleanup so it is present in the final bundle.
        arrangement_payload = audit_arrangement_file(score_path)
        write_arrangement_reports(arrangement_payload, reports_dir)
        dissonance_payload = audit_dissonance_file(score_path)
        write_dissonance_reports(
            dissonance_payload,
            reports_dir,
            plots_dir=plots_dir,
            plot_format=plot_format,
            jpeg_quality=jpeg_quality,
        )
        sour_note_payload = audit_sour_note_file(score_path)
        write_sour_note_reports(
            sour_note_payload,
            reports_dir,
            plots_dir=plots_dir,
            plot_format=plot_format,
            jpeg_quality=jpeg_quality,
        )
        shrill_note_payload = audit_shrill_note_file(score_path)
        write_shrill_note_reports(
            shrill_note_payload,
            reports_dir,
            plots_dir=plots_dir,
            plot_format=plot_format,
            jpeg_quality=jpeg_quality,
        )
        mix_diag_path, mix_warnings = summarize_mix_diagnostics(manifest, reports_dir)
        dissonance_warnings = list(dissonance_payload.get("warnings") or [])
        sour_note_warnings = list(sour_note_payload.get("warnings") or [])
        shrill_note_warnings = list(shrill_note_payload.get("warnings") or [])
        adaptive_composition_warnings: list[str] = []
        audio_shrillness_warnings: list[str] = []
        try:
            adaptive_composition_warnings = list(json.loads(Path(adaptive_composition_path).read_text(encoding="utf8")).get("warnings") or [])
        except Exception:
            adaptive_composition_warnings = []
        try:
            audio_shrillness_warnings = list(json.loads(Path(audio_shrillness_path).read_text(encoding="utf8")).get("warnings") or [])
        except Exception:
            audio_shrillness_warnings = []
        if not skip_spectrograms:
            write_spectrograms(
                analysis_root,
                manifest,
                plots_dir,
                plot_format=plot_format,
                jpeg_quality=jpeg_quality,
            )

    published: str | None = None
    if publish:
        progress_line("publishing full.ogg to game assets")
        # Import lazily so this module can be used by tests without importing the CLI.
        from .cli import publish_cue

        ok = publish_cue(cue_id, outdir, dest_root)
        if ok:
            published = str(dest_root / cue_id / "full.ogg")
        else:
            published = "publish failed"

    progress_line("assembling shareable bundle directory")
    bundle_name = f"{cue_id}_{render_hash}_bundle"
    bundle_dir = bundle_root / bundle_name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    source_dir = bundle_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(score_path, source_dir / score_path.name)
    (source_dir / "normalized_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf8")
    copied_audio = copy_manifest_referenced_files(outdir, manifest, bundle_dir)
    copy_tree_if_exists(reports_dir, bundle_dir / "reports")
    copy_tree_if_exists(plots_dir, bundle_dir / "plots")
    shutil.copy2(manifest_path, bundle_dir / manifest_path.name)
    if include_scratch_stems:
        copy_current_scratch_stems(outdir, manifest, bundle_dir)

    rerun_script = build_rerun_script(
        bundle_dir,
        cue_id,
        backend,
        outdir,
        publish,
        runtime_stem_gain_mode,
        plot_format,
        runtime_stem_max_gain_db,
        zip_bundle,
        zip_report_bundle,
        render_audio_mode,
        profile_render,
        render_in_process,
    )

    command_rows = [
        {
            "name": c.name,
            "returncode": c.returncode,
            "command": c.command,
            "stdout": str(c.stdout),
            "stderr": str(c.stderr),
            "elapsed_s": c.elapsed_s,
        }
        for c in commands
    ]
    report = {
        "schema": "ambition.music_debug_bundle.v1",
        "cue": cue_id,
        "score": safe_rel(score_path),
        "backend": backend,
        "runtime_stem_gain_mode": runtime_stem_gain_mode,
        "runtime_stem_max_gain_db": runtime_stem_max_gain_db,
        "plot_format": plot_format,
        "render_audio_mode": render_audio_mode,
        "profile_render": profile_render,
        "render_in_process": render_in_process,
        "render_hash": render_hash,
        "outdir": str(outdir),
        "bundle_dir": str(bundle_dir),
        "manifest": str(manifest_path),
        "duration_s": duration,
        "published": published,
        "include_scratch_stems": include_scratch_stems,
        "copied_audio_files": copied_audio,
        "mix_diagnostics": str(mix_diag_path),
        "warnings": [
            w
            for w in [
                id_warning,
                *mix_warnings,
                *adaptive_composition_warnings,
                *audio_shrillness_warnings,
                *dissonance_warnings,
                *sour_note_warnings,
                *shrill_note_warnings,
            ]
            if w
        ],
        "commands": command_rows,
        "rerun_script": str(rerun_script),
    }
    (bundle_dir / "bundle_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf8")

    zip_path: Path | None = None
    zip_report_path: Path | None = None
    if zip_bundle:
        zip_path = make_zip(bundle_dir, bundle_root / f"{bundle_name}.zip")
        report["zip"] = str(zip_path)
    if zip_report_bundle:
        zip_report_path = make_zip(
            bundle_dir, bundle_root / f"{bundle_name}_report.zip", report_only=True
        )
        report["zip_report"] = str(zip_report_path)
    if zip_path or zip_report_path:
        (bundle_dir / "bundle_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf8")

    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cue", help="cue id or .music.yaml path")
    ap.add_argument("--backend", default=DEFAULT_BACKEND, choices=BACKEND_CHOICES)
    ap.add_argument(
        "--runtime-stem-gain-mode",
        choices=RUNTIME_STEM_GAIN_MODES,
        default="native",
        help=(
            "runtime adaptive stem export mode: native preserves current raw levels; "
            "shared applies one shared reference gain across all stems"
        ),
    )
    ap.add_argument(
        "--runtime-stem-max-gain-db",
        type=float,
        default=None,
        help="cap shared runtime stem gain; default is renderer policy or YAML render.runtime_stems.max_gain_db",
    )
    ap.add_argument("--outdir", type=Path, default=None)
    ap.add_argument("--bundle-root", type=Path, default=None)
    ap.add_argument("--force", action="store_true", help="force render regeneration")
    ap.add_argument("--publish", action="store_true", help="publish full.ogg to game assets after rendering")
    ap.add_argument("--dest-root", type=Path, default=None, help="game music generated asset root")
    ap.add_argument("--zip", dest="zip_bundle", action="store_true", help="write a complete uploadable bundle zip including manifest-referenced audio")
    ap.add_argument("--zip-report", dest="zip_report_bundle", action="store_true", help="write a compact report zip excluding OGG/WAV/NPY/MIDI binaries")
    ap.add_argument(
        "--plot-format",
        choices=PLOT_FORMATS,
        default="jpg",
        help="spectrogram image format for bundles; jpg is much smaller and reports keep numeric values",
    )
    ap.add_argument("--jpeg-quality", type=int, default=84, help="JPEG quality for spectrogram plots")
    ap.add_argument("--jobs", "-j", type=int, default=1, help="render worker count")
    ap.add_argument(
        "--include-scratch-stems",
        action="store_true",
        help="include raw scratch_stems/*.npy in the bundle zip; useful but can be large",
    )
    ap.add_argument("--skip-render", action="store_true", help="bundle/analyze existing outdir")
    ap.add_argument("--skip-spectrograms", action="store_true", help="skip PNG spectrogram generation")
    ap.add_argument(
        "--render-audio-mode",
        choices=RENDER_AUDIO_MODES,
        default="full",
        help=(
            "audio export scope for render_isolated. full preserves all adaptive stem/state preview OGGs; "
            "full-mix-only keeps scratch stems plus mastered preview and section full mixes; "
            "simple-mix writes only the mastered preview. Use full-mix-only for fast report bundles "
            "when you do not need per-stem runtime OGG exports."
        ),
    )
    ap.add_argument("--profile-render", action="store_true", help="enable LINE_PROFILE=1 and run render_isolated in-process for line_profiler")
    ap.add_argument("--render-in-process", action="store_true", help="debug/profiling mode: import and run render_isolated instead of launching it as a subprocess")
    return ap


@profile
def main(argv: list[str] | None = None) -> int:
    import time as _time

    total_start = _time.perf_counter()
    cue_name = "<parse-error>"
    rc = 1
    try:
        args = build_parser().parse_args(argv)
        cue_name = str(args.cue)
        report = create_bundle(
            args.cue,
            backend=args.backend,
            runtime_stem_gain_mode=args.runtime_stem_gain_mode,
            outdir=args.outdir,
            bundle_root=args.bundle_root,
            force=args.force,
            publish=args.publish,
            dest_root=args.dest_root,
            zip_bundle=args.zip_bundle,
            zip_report_bundle=args.zip_report_bundle,
            jobs=args.jobs,
            include_scratch_stems=args.include_scratch_stems,
            skip_render=args.skip_render,
            skip_spectrograms=args.skip_spectrograms,
            plot_format=args.plot_format,
            jpeg_quality=args.jpeg_quality,
            runtime_stem_max_gain_db=args.runtime_stem_max_gain_db,
            render_audio_mode=args.render_audio_mode,
            profile_render=args.profile_render,
            render_in_process=getattr(args, "render_in_process", False),
        )
        print_bundle_summary(report)
        print(json.dumps(report, indent=2, default=str))
        rc = 0 if report.get("ok", True) else 1
        return rc
    finally:
        elapsed = _time.perf_counter() - total_start
        print(f"[ambition_music_renderer.cue_bundle] cue={cue_name} total_elapsed_s={elapsed:.3f}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
