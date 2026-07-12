"""Bundle zip, rerun-script, terminal-summary, and audit subprocess helpers."""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

from .bundle_base import (
    REPORT_ZIP_EXCLUDED_SUFFIXES,
    CommandResult,
    adjacent_section_pairs,
    renderer_audit_command,
    run_logged,
    terminal_link,
)

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
        cmd = renderer_audit_command(
            "transition",
            analysis_root,
            "--sections",
            first,
            second,
            "--crossfade",
            crossfade_seconds,
            "--crossfade_shape",
            crossfade_shape,
            "--incoming_start",
            incoming_start,
            "--outdir",
            outdir,
        )
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



def print_bundle_summary(report: dict[str, object], *, stream=None) -> None:
    """Print human-friendly paths in addition to the machine-readable JSON."""
    if stream is None:
        stream = sys.stderr
    keys = [
        ("render output", "outdir"),
        ("generated", "generated_dir"),
        ("latest", "generated_latest"),
        ("building", "generated_building"),
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
    outdir: Path | None,
    publish: bool,
    runtime_stem_gain_mode: str,
    plot_format: str,
    runtime_stem_max_gain_db: float | None,
    zip_bundle: bool,
    zip_report_bundle: bool,
    render_audio_mode: str = "full",
    profile_render: bool = False,
    render_in_process: bool = False,
    spectrograms: bool = False,
    all_audits: bool = False,
    bundle_root: Path | None = None,
    jobs: int = 1,
) -> Path:
    script = bundle_dir / "rerun_bundle.sh"
    cmd = [
        "uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer cue bundle",
        str(cue),
        "--backend",
        str(backend),
        "--runtime_stem_gain_mode",
        str(runtime_stem_gain_mode),
        "--jobs",
        str(jobs),
    ]
    if runtime_stem_max_gain_db is not None:
        cmd.extend(["--runtime_stem_max_gain_db", str(runtime_stem_max_gain_db)])
    cmd.extend(["--plot_format", str(plot_format)])
    # Only pin --outdir when the original run used an explicit outdir. Default
    # runs use the versioned generated/ layout; pinning the old hash directory
    # would make a rerun after a spec edit write the new hash's outputs into
    # the old hash's directory.
    if outdir is not None:
        cmd.extend(["--outdir", str(outdir)])
    if bundle_root is not None:
        cmd.extend(["--bundle_root", str(bundle_root)])
    cmd.extend(["--force", "--render_audio_mode", str(render_audio_mode)])
    if profile_render:
        cmd.append("--profile_render")
    if render_in_process:
        cmd.append("--render_in_process")
    if spectrograms:
        cmd.append("--spectrograms")
    if all_audits:
        cmd.append("--all_audits")
    if publish:
        cmd.append("--publish")
    if zip_bundle:
        cmd.append("--zip")
    if zip_report_bundle:
        cmd.append("--zip_report")
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


