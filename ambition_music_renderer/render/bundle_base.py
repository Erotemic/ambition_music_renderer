"""Bundle configuration, path helpers, command runners, and manifest helpers.

This module is intentionally an orchestration layer around the current renderer
rather than a replacement renderer.  Its job is to make one cue reproducible and
inspectable from a single command while the lower-level MusicIR internals are
refactored behind a stable workflow.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
import kwconf

from . import musicir_renderer as r
from .generated_layout import generated_manifest_search_roots
from .generated_layout import latest_manifest_in_roots
from ..audit.arrangement_audit import audit_file as audit_arrangement_file
from ..audit.arrangement_audit import write_reports as write_arrangement_reports
from ..audit.dissonance_audit import audit_file as audit_dissonance_file
from ..audit.dissonance_audit import write_reports as write_dissonance_reports
from ..audit.sour_note_audit import audit_file as audit_sour_note_file
from ..audit.sour_note_audit import write_reports as write_sour_note_reports
from ..audit.shrill_note_audit import audit_file as audit_shrill_note_file
from ..audit.shrill_note_audit import write_reports as write_shrill_note_reports
from ..profiler import profile
from ..kwconf_runner import KwconfCommand
from .._paths import bundles_root as _bundles_root
from .._paths import find_score as _find_score
from .._paths import generated_root as _generated_root
from .._paths import project_root as _project_root
from .._paths import repo_root as _repo_root
from .._paths import score_candidates as _score_candidates

DEFAULT_BACKEND = "pretty-midi"
BACKEND_CHOICES = ("pretty-midi", "fluidsynth-cli", "fallback", "auto")
RUNTIME_STEM_GAIN_MODES = ("native", "shared")
PLOT_FORMATS = ("jpg", "png")
RENDER_AUDIO_MODES = ("full", "full-mix-only", "simple-mix")
REPORT_ZIP_EXCLUDED_SUFFIXES = {".ogg", ".oga", ".wav", ".flac", ".mp3", ".npy", ".mid", ".midi"}
DBFS_SILENCE_FLOOR = -120.0
DBFS_PLOT_FLOOR = -100.0


class CueBundleConfig(kwconf.Config):
    """kwconf-backed configuration for ``cue_bundle``.

    This is the single source of truth for Python-callable and CLI bundle options.
    """


    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    backend: str = kwconf.Value(DEFAULT_BACKEND, choices=BACKEND_CHOICES)
    runtime_stem_gain_mode: str = kwconf.Value(
        "native",
        choices=RUNTIME_STEM_GAIN_MODES,
        help=(
            "runtime adaptive stem export mode: native preserves current raw "
            "levels; shared applies one shared reference gain across all stems"
        ),
    )
    runtime_stem_max_gain_db: float | None = kwconf.Value(
        None,
        help="cap shared runtime stem gain; default is renderer policy or YAML render.runtime_stems.max_gain_db",
    )
    outdir: Path | None = kwconf.Value(None, parser=Path)
    bundle_root: Path | None = kwconf.Value(None, parser=Path)
    force: bool = kwconf.Flag(False, help="force render regeneration")
    publish: bool = kwconf.Flag(False, help="publish full.ogg to game assets after rendering")
    dest_root: Path | None = kwconf.Value(None, parser=Path, help="game music generated asset root")
    zip_bundle: bool = kwconf.Flag(
        False,
        alias=["zip"],
        help="write a complete uploadable bundle zip including manifest-referenced audio",
    )
    zip_report_bundle: bool = kwconf.Flag(
        False,
        alias=["zip_report"],
        help="write a compact report zip excluding OGG/WAV/NPY/MIDI binaries",
    )
    plot_format: str = kwconf.Value(
        "jpg",
        choices=PLOT_FORMATS,
        help="spectrogram image format for bundles; jpg is much smaller and reports keep numeric values",
    )
    jpeg_quality: int = kwconf.Value(84, help="JPEG quality for spectrogram plots")
    jobs: int = kwconf.Value(1, short_alias=["j"], help="render worker count")
    include_scratch_stems: bool = kwconf.Flag(
        False,
        help="include raw scratch_stems/*.npy in the bundle zip; useful but can be large",
    )
    skip_render: bool = kwconf.Flag(False, help="bundle/analyze existing outdir")
    skip_spectrograms: bool = kwconf.Flag(False, help="skip spectrogram generation")
    render_audio_mode: str = kwconf.Value(
        "full",
        choices=RENDER_AUDIO_MODES,
        help=(
            "audio export scope for render_isolated. full preserves all adaptive "
            "stem/state preview OGGs; full-mix-only keeps scratch stems plus "
            "mastered preview and section full mixes; simple-mix writes only the "
            "mastered preview."
        ),
    )
    profile_render: bool = kwconf.Flag(
        False,
        help="enable LINE_PROFILE=1 and run render_isolated plus serial workers in-process for line_profiler",
    )
    render_in_process: bool = kwconf.Flag(
        False,
        help="debug/profiling mode: import and run render_isolated instead of launching it as a subprocess",
    )

    def __post_init__(self) -> None:
        self.jobs = int(self.jobs)
        self.jpeg_quality = int(self.jpeg_quality)
        for key in ("outdir", "bundle_root", "dest_root"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, Path):
                setattr(self, key, Path(value))

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        report = create_bundle_from_config(config)
        print_bundle_summary(report)
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("ok", True) else 1



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
    return _project_root()


def repo_root() -> Path:
    return _repo_root()


def default_generated_root() -> Path:
    return _generated_root()


def default_bundle_root() -> Path:
    return _bundles_root()


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
    return _find_score(cue)


def missing_score_debug(cue: str) -> str:
    candidates = _score_candidates(cue)
    lines = [
        f"cue not found: {cue}",
        f"renderer project root: {package_dir()}",
        "score candidates checked:",
    ]
    lines.extend(f"  - {candidate}" for candidate in candidates)
    return "\n".join(lines)


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected YAML mapping in {path}")
    return data


@profile
def latest_manifest(outdir: Path, cue_id: str) -> Path | None:
    """Find the newest manifest in either a flat or versioned output dir."""

    return latest_manifest_in_roots(generated_manifest_search_roots(outdir), cue_id)


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
def run_kwconf_logged(
    name: str,
    command: KwconfCommand,
    reports_dir: Path,
    *,
    mode: str,
    data: dict[str, object],
) -> CommandResult:
    """Run a kwconf command through the selected direct/subprocess boundary."""
    import time as _time

    reports_dir.mkdir(parents=True, exist_ok=True)
    stdout = reports_dir / f"{name}.stdout.txt"
    stderr = reports_dir / f"{name}.stderr.txt"
    start = _time.perf_counter()
    if mode == "direct":
        stdout.write_text("direct kwconf command; output streamed to terminal\n", encoding="utf8")
        stderr.write_text("direct kwconf command; stderr streamed to terminal\n", encoding="utf8")
        try:
            rc = int(command.run_direct(argv=False, data=data))
        except SystemExit as ex:
            code = ex.code
            rc = int(code) if isinstance(code, int) else 1
        shown_command = ["<direct>", command.config_cls.__module__, command.config_cls.__name__, *command.cli_argv(data)]
    elif mode == "subprocess":
        shown_command = command.python_command(data)
        with stdout.open("w", encoding="utf8") as out_f, stderr.open("w", encoding="utf8") as err_f:
            proc = command.run_subprocess(data=data, stdout=out_f, stderr=err_f, cwd=package_dir())
        rc = int(proc.returncode)
    else:
        raise KeyError(f"unknown kwconf command mode: {mode!r}")
    elapsed = _time.perf_counter() - start
    result = CommandResult(name, shown_command, rc, stdout, stderr, elapsed)
    if rc != 0:
        progress_line(f"command failed: {name} rc={rc} elapsed_s={elapsed:.3f}")
        progress_line(f"stdout: {terminal_link(stdout)}")
        progress_line(f"stderr: {terminal_link(stderr)}")
        tail = result.stderr_tail
        if tail:
            print(f"[music bundle] --- {name} stderr tail ---")
            print(tail)
    return result


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


