"""Cue regeneration, diagnostics, and shareable debug bundles."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from ..audit.arrangement_audit import audit_file as audit_arrangement_file
from ..audit.arrangement_audit import write_reports as write_arrangement_reports
from ..audit.dissonance_audit import audit_file as audit_dissonance_file
from ..audit.dissonance_audit import render_pianoroll as render_dissonance_pianoroll
from ..audit.dissonance_audit import write_harmony_diagnostics
from ..audit.dissonance_audit import write_reports as write_dissonance_reports
from ..audit.mix_balance_audit import audit_spec as audit_mix_balance
from ..audit.mix_balance_audit import write_reports as write_mix_balance_reports
from ..audit.instrument_resolution import audit_spec as audit_instrument_resolution
from ..audit.instrument_resolution import write_reports as write_instrument_resolution_reports
from ..audit.shrill_note_audit import audit_file as audit_shrill_note_file
from ..audit.shrill_note_audit import write_reports as write_shrill_note_reports
from ..audit.sour_note_audit import audit_file as audit_sour_note_file
from ..audit.sour_note_audit import render_pianoroll as render_sour_pianoroll
from ..audit.sour_note_audit import write_reports as write_sour_note_reports
from ..kwconf_runner import KwconfCommand
from ..profiler import profile
from .bundle_adaptive_reports import (
    write_adaptive_composition_mastering_report,
    write_adaptive_section_report,
    write_spectral_shrillness_report,
)
from .bundle_archive import build_rerun_script, copy_tree_if_exists, make_zip, print_bundle_summary, run_transition_audits
from .bundle_audio_reports import (
    summarize_mix_diagnostics,
    write_audio_metadata_report,
    write_manifest_audio_level_report,
    write_state_mix_report,
    write_stem_export_report,
)
from .bundle_options import DEFAULT_BACKEND, RENDER_AUDIO_MODES
from .bundle_base import (
    CommandResult,
    CueBundleConfig,
    copy_current_scratch_stems,
    copy_manifest_referenced_files,
    default_bundle_root,
    default_generated_root,
    default_publish_dest_root,
    find_score,
    latest_manifest,
    load_yaml,
    manifest_audio_entries,
    manifest_duration,
    missing_score_debug,
    package_dir,
    prepare_manifest_analysis_root,
    progress_line,
    renderer_audit_command,
    run_kwconf_logged,
    run_logged,
    safe_rel,
    terminal_link,
)
from .bundle_spectral_reports import (
    write_spectral_fingerprint,
    write_stem_amplitude_report,
    write_stem_loudness_report,
)
from .bundle_spectrograms import write_spectrograms
from .bundle_quality_brief import write_quality_brief
from .generated_layout import (
    begin_generated_run,
    clear_generated_building,
    generated_run_layout,
    mark_generated_run_latest,
    resolve_latest_generated_dir,
)

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
    spectrograms: bool = False,
    all_audits: bool = False,
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
        message = missing_score_debug(cue)
        progress_line(message)
        raise FileNotFoundError(message)
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

    generated_layout = None
    explicit_outdir = Path(outdir) if outdir is not None else None
    explicit_bundle_root = Path(bundle_root) if bundle_root is not None else None
    if outdir is None:
        cue_generated_dir = default_generated_root() / cue_id
        if skip_render:
            outdir = resolve_latest_generated_dir(cue_generated_dir)
        else:
            generated_layout = generated_run_layout(cue_generated_dir, score_path, backend, spec=spec)
            outdir = begin_generated_run(generated_layout)
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

    if all_audits:
        progress_line("running arrangement preflight")
        arrangement_payload = audit_arrangement_file(score_path)
        write_arrangement_reports(arrangement_payload, reports_dir)

    if not skip_render:
        progress_line(f"rendering {cue_id} with backend={backend}, runtime_stems={runtime_stem_gain_mode}")
        from .isolated import RenderIsolatedConfig

        render_data: dict[str, object] = {
            "spec": score_path,
            "outdir": outdir,
            "backend": backend,
            "runtime_stem_gain_mode": runtime_stem_gain_mode,
            "keep_debug_stems": True,
            "jobs": jobs,
            "timings_out": reports_dir / "render_isolated_timings.json",
            "runtime_stem_max_gain_db": runtime_stem_max_gain_db,
            "force": force,
            "simple_mix": render_audio_mode == "simple-mix",
            "full_mix_only": render_audio_mode == "full-mix-only",
        }
        line_profile_requested = bool(os.environ.get("LINE_PROFILE"))
        command_mode = "direct" if render_in_process else "subprocess"
        if profile_render or line_profile_requested:
            if profile_render and not line_profile_requested:
                # profiler.py binds line_profiler (or the identity decorator)
                # at import time, long before this flag is seen — setting the
                # env var here cannot retroactively enable line profiling.
                progress_line(
                    "WARNING: --profile_render without LINE_PROFILE=1 in the "
                    "environment runs in-process but produces no .lprof output; "
                    "prepend LINE_PROFILE=1 to the command to get line profiles"
                )
            render_in_process = True
            command_mode = "direct"
            render_data["profile_workers"] = True
            reason = "--profile_render" if profile_render else "LINE_PROFILE"
            progress_line(f"profiling/debug requested by {reason}; running render_isolated and group workers in-process")
        render_command = KwconfCommand(RenderIsolatedConfig, module="ambition_music_renderer.render.isolated", cwd=package_dir())
        commands.append(
            run_kwconf_logged(
                "render_isolated",
                render_command,
                reports_dir,
                mode=command_mode,
                data=render_data,
            )
        )
        if commands[-1].returncode != 0:
            if generated_layout is not None:
                clear_generated_building(generated_layout)
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
        if generated_layout is not None:
            clear_generated_building(generated_layout)
        raise FileNotFoundError(f"no adaptive manifest found in {outdir} for {cue_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    # Relative paths inside the manifest are relative to the directory the
    # manifest lives in (the versioned run dir). With --skip_render and no
    # `latest` link, `outdir` can resolve to the flat cue dir while the newest
    # manifest is found under .versioned/<hash>/ — anchoring file resolution to
    # the manifest keeps them paired instead of silently producing an empty
    # analysis tree.
    manifest_root = manifest_path.parent
    render_hash = str(manifest.get("hash", "unknown"))
    duration = manifest_duration(manifest)

    # Diagnostics. Normal listening renders keep this intentionally light; the
    # full DAW-style audit suite is available through --all_audits.  Spectrograms
    # are opt-in via --spectrograms (or included by --all_audits) because they
    # are useful but visually noisy and slow for iteration.
    tools_dir = package_dir()
    write_spectrogram_plots = bool(spectrograms or all_audits)
    progress_line(
        "running bundle reports"
        + (" with full audits" if all_audits else " with fast default audits")
    )
    dissonance_warnings: list[str] = []
    sour_note_warnings: list[str] = []
    shrill_note_warnings: list[str] = []
    adaptive_composition_warnings: list[str] = []
    audio_shrillness_warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"{cue_id}_{render_hash}_analysis_") as td:
        analysis_root = prepare_manifest_analysis_root(manifest_root, manifest, Path(td))
        if all_audits:
            commands.append(
                run_logged(
                    "audit_cue_balance",
                    renderer_audit_command("cue_balance", analysis_root),
                    reports_dir,
                    cwd=tools_dir,
                )
            )
            if (analysis_root / "scratch_stems").is_dir():
                hi = f"{duration:.3f}" if duration > 0 else "-1"
                commands.append(
                    run_logged(
                        "spectral_compare",
                        renderer_audit_command(
                            "spectral_compare",
                            analysis_root,
                            "--window",
                            "0",
                            hi,
                            "--label",
                            cue_id,
                        ),
                        reports_dir,
                        cwd=tools_dir,
                    )
                )
                commands.append(
                    run_logged(
                        "spectral_localize",
                        renderer_audit_command(
                            "spectral_localize",
                            analysis_root,
                            "--window",
                            "0",
                            "-1",
                            "--bucket",
                            "0.25",
                        ),
                        reports_dir,
                        cwd=tools_dir,
                    )
                )
        write_stem_export_report(analysis_root, manifest, reports_dir)
        write_manifest_audio_level_report(analysis_root, manifest, reports_dir)
        write_audio_metadata_report(analysis_root, manifest, reports_dir)
        write_state_mix_report(spec, manifest, reports_dir)
        mix_diag_path, mix_warnings = summarize_mix_diagnostics(manifest, reports_dir)
        # Stem loudness is the README's "start here when a mix sounds obviously
        # wrong" report; it reads only manifest diagnostics, so it belongs in
        # every bundle, not just --all_audits.
        write_stem_loudness_report(
            manifest,
            reports_dir,
            plots_dir=plots_dir,
            plot_format=plot_format,
            jpeg_quality=jpeg_quality,
        )
        # Mix-balance / lead-audibility audit runs by DEFAULT (it is spec-static and
        # cheap) so a buried lead instrument — a lead whose group is allocated far
        # less mix budget than the bed — is caught on every listening render, not
        # just under --all_audits.
        mix_balance_warnings: list[str] = []
        try:
            mix_balance_payload = audit_mix_balance(spec)
            write_mix_balance_reports(
                mix_balance_payload,
                reports_dir,
                plots_dir=plots_dir,
                plot_format=plot_format,
                jpeg_quality=jpeg_quality,
            )
            mix_balance_warnings = list(mix_balance_payload.get("warnings") or [])
        except Exception as exc:  # never let a diagnostic break a render
            mix_balance_warnings = [f"mix_balance audit failed: {exc}"]
        # Lead-vs-lead collisions run by DEFAULT (spec-static, milliseconds):
        # two foreground melodies a second apart is the mistake a listener
        # hears immediately, and rows carry wall-clock timestamps so an ear
        # note like "1:27" maps straight to a line in the report.
        lead_collision_warnings: list[str] = []
        try:
            from ..audit.lead_collision import audit_spec as audit_lead_collision

            lead_payload = audit_lead_collision(spec)
            (reports_dir / "lead_collision.json").write_text(
                json.dumps(lead_payload, indent=2), encoding="utf8"
            )
            for row in (lead_payload.get("collisions") or [])[:4]:
                lead_collision_warnings.append(
                    f"lead collision at {row['time']}: {row['notes'][0]}+{row['notes'][1]} "
                    f"({row['layers'][0]} vs {row['layers'][1]}, {row['interval_semitones']} st, "
                    f"section {row['section']})"
                )
        except Exception as exc:  # never let a diagnostic break a render
            lead_collision_warnings = [f"lead_collision audit failed: {exc}"]
        # Instrument resolution provenance: records exactly what every library_ref /
        # GM program resolved to on disk, plus octave-folds / unmapped drums /
        # fallbacks — so "asked for X, got Y" is never invisible.
        resolution_warnings: list[str] = []
        try:
            resolution_payload = audit_instrument_resolution(spec)
            write_instrument_resolution_reports(resolution_payload, reports_dir)
            resolution_warnings = list(resolution_payload.get("warnings") or [])
        except Exception as exc:
            resolution_warnings = [f"instrument_resolution audit failed: {exc}"]
        # Harmony piano-roll plots + the LLM-readable harmony_diagnostics.md are
        # spec-static and cheap, so generate them on every render — they are the
        # primary visual debugging artifacts for sour / dissonant notes.
        dissonance_payload = audit_dissonance_file(score_path)
        sour_note_payload = audit_sour_note_file(score_path)
        try:
            render_dissonance_pianoroll(
                spec, plots_dir / f"dissonance_pianoroll.{plot_format}",
                plot_format=plot_format, jpeg_quality=jpeg_quality,
            )
            render_sour_pianoroll(
                spec, plots_dir / f"sour_note_pianoroll.{plot_format}",
                plot_format=plot_format, jpeg_quality=jpeg_quality,
            )
            write_harmony_diagnostics(
                dissonance_payload, sour_note_payload, reports_dir / "harmony_diagnostics.md"
            )
        except Exception as exc:  # plotting is best-effort
            progress_line(f"harmony plots skipped: {exc}")
        dissonance_warnings = list(dissonance_payload.get("warnings") or [])
        sour_note_warnings = list(sour_note_payload.get("warnings") or [])
        if all_audits:
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
            progress_line("running adjacent-section transition audits")
            commands.extend(run_transition_audits(analysis_root, manifest, reports_dir, tools_dir))
            # Re-run arrangement preflight after render report cleanup so it is present in the final bundle.
            arrangement_payload = audit_arrangement_file(score_path)
            write_arrangement_reports(arrangement_payload, reports_dir)
            # dissonance_payload / sour_note_payload + their piano-rolls and
            # harmony_diagnostics.md are already produced in the default block
            # above; here we add the heavier full TSV/markdown report tables.
            write_dissonance_reports(
                dissonance_payload,
                reports_dir,
                plots_dir=plots_dir,
                plot_format=plot_format,
                jpeg_quality=jpeg_quality,
            )
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
            dissonance_warnings = list(dissonance_payload.get("warnings") or [])
            sour_note_warnings = list(sour_note_payload.get("warnings") or [])
            shrill_note_warnings = list(shrill_note_payload.get("warnings") or [])
            try:
                adaptive_composition_warnings = list(json.loads(Path(adaptive_composition_path).read_text(encoding="utf8")).get("warnings") or [])
            except Exception:
                adaptive_composition_warnings = []
            try:
                audio_shrillness_warnings = list(json.loads(Path(audio_shrillness_path).read_text(encoding="utf8")).get("warnings") or [])
            except Exception:
                audio_shrillness_warnings = []
        if write_spectrogram_plots:
            write_spectrograms(
                analysis_root,
                manifest,
                plots_dir,
                plot_format=plot_format,
                jpeg_quality=jpeg_quality,
            )
        quality_brief_path, quality_brief_warnings = write_quality_brief(
            reports_dir,
            cue_id=cue_id,
            render_hash=render_hash,
            all_audits=all_audits,
            spectrograms=write_spectrogram_plots,
        )
    published: str | None = None
    if publish:
        progress_line("publishing full.ogg to game assets")
        # Import lazily so this module can be used by tests without importing the CLI.
        from ..cli import publish_cue

        ok = publish_cue(cue_id, manifest_root, dest_root)
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
    copied_audio = copy_manifest_referenced_files(manifest_root, manifest, bundle_dir)
    if manifest_audio_entries(manifest) and not copied_audio:
        progress_line(
            f"WARNING: none of the audio files referenced by {manifest_path.name} "
            f"exist under {manifest_root}; the bundle contains reports only"
        )
    copy_tree_if_exists(reports_dir, bundle_dir / "reports")
    copy_tree_if_exists(plots_dir, bundle_dir / "plots")
    shutil.copy2(manifest_path, bundle_dir / manifest_path.name)
    if include_scratch_stems:
        copy_current_scratch_stems(manifest_root, manifest, bundle_dir)

    rerun_script = build_rerun_script(
        bundle_dir,
        cue_id,
        backend,
        # Only pin --outdir for explicit-outdir runs; default versioned-layout
        # runs should re-resolve their layout so a spec edit gets a fresh hash
        # directory instead of writing into this one.
        explicit_outdir,
        publish,
        runtime_stem_gain_mode,
        plot_format,
        runtime_stem_max_gain_db,
        zip_bundle,
        zip_report_bundle,
        render_audio_mode,
        profile_render,
        render_in_process,
        write_spectrogram_plots,
        all_audits,
        bundle_root=explicit_bundle_root,
    )

    if generated_layout is not None:
        mark_generated_run_latest(generated_layout)

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
        "all_audits": bool(all_audits),
        "spectrograms": bool(write_spectrogram_plots),
        "outdir": str(outdir),
        "generated_dir": str(generated_layout.cue_dir) if generated_layout is not None else str(outdir),
        "generated_latest": str(generated_layout.latest_link) if generated_layout is not None else None,
        "generated_building": str(generated_layout.building_link) if generated_layout is not None else None,
        "bundle_dir": str(bundle_dir),
        "manifest": str(manifest_path),
        "duration_s": duration,
        "published": published,
        "include_scratch_stems": include_scratch_stems,
        "copied_audio_files": copied_audio,
        "mix_diagnostics": str(mix_diag_path),
        "quality_brief": str(quality_brief_path),
        "warnings": [
            w
            for w in [
                id_warning,
                *resolution_warnings,
                *mix_balance_warnings,
                *lead_collision_warnings,
                *mix_warnings,
                *quality_brief_warnings,
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


def create_bundle_from_config(config: CueBundleConfig) -> dict[str, object]:
    """Run bundle creation from a kwconf ``CueBundleConfig`` instance."""
    return create_bundle(
        config.cue,
        backend=config.backend,
        runtime_stem_gain_mode=config.runtime_stem_gain_mode,
        outdir=config.outdir,
        bundle_root=config.bundle_root,
        force=config.force,
        publish=config.publish,
        dest_root=config.dest_root,
        zip_bundle=config.zip_bundle,
        zip_report_bundle=config.zip_report_bundle,
        jobs=config.jobs,
        include_scratch_stems=config.include_scratch_stems,
        skip_render=config.skip_render,
        spectrograms=config.spectrograms,
        all_audits=config.all_audits,
        plot_format=config.plot_format,
        jpeg_quality=config.jpeg_quality,
        runtime_stem_max_gain_db=config.runtime_stem_max_gain_db,
        render_audio_mode=config.render_audio_mode,
        profile_render=config.profile_render,
        render_in_process=config.render_in_process,
    )



@profile
def main(argv: list[str] | None = None) -> int:
    import time as _time

    total_start = _time.perf_counter()
    cue_name = "<parse-error>"
    rc = 1
    try:
        config = CueBundleConfig.cli(argv=argv)
        cue_name = str(config.cue)
        report = create_bundle_from_config(config)
        if config.json:
            print(json.dumps(report, indent=2, default=str))
        rc = 0 if report.get("ok", True) else 1
        return rc
    finally:
        elapsed = _time.perf_counter() - total_start
        print(f"[ambition_music_renderer.render.bundle] cue={cue_name} total_elapsed_s={elapsed:.3f}", flush=True)
        if 'report' in locals():
            print_bundle_summary(report)


if __name__ == "__main__":
    raise SystemExit(main())
