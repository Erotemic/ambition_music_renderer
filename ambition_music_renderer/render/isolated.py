#!/usr/bin/env python3
"""Render MusicIR using isolated stem worker processes.

This is the production-oriented entry point for long adaptive cues. It writes:
- adaptive/<section>/<section>.<stem>.ogg
- adaptive/<section>/<section>.full.ogg
- preview/<cue>.full_soundtrack_preview.ogg     (mastered full mix)
- preview/<cue>.runtime_<name>.ogg              (runtime stem mix, no audition normalization)
- preview/<cue>.audition_<name>.ogg             (same state mix normalized for comfortable A/B)
- <cue>.adaptive_manifest.json

For the current in-game goblin cue, the runtime consumes per-section full mixes
and not per-stem OGG files. Use --full-mix-only to skip those per-stem encodes
while still rendering the adaptive section full mixes that the game loads.
"""

from __future__ import annotations
import json
import math
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
import kwconf
import numpy as np
import yaml
from ..audio_utils import coerce_stereo
from .effects import post_process, soft_limit
from .export import section_chapter_metadata, timeline_markers_from_spec, write_ogg_from_audio
from .group import build_manifest, ensure_audio_length, slice_audio
from .score_core import choose_soundfont
from .score_layers import build_score
from .synth import spec_hash
from ..profiler import PhaseTimer, profile
from ..kwconf_runner import KwconfCommand
from .._paths import project_root


RUNTIME_STEM_GAIN_MODES = ("native", "shared")

SECTION_FULL_MASTERING_MODES = ("section_postprocess", "global_master_slices")



class RenderIsolatedConfig(kwconf.Config):
    """kwconf-backed config for the render-isolated entrypoint."""


    spec: Path = kwconf.Value(None, position=1, parser=Path, help="MusicIR YAML spec")
    outdir: Path = kwconf.Value(Path("output"), parser=Path, help="render output directory")
    backend: str = kwconf.Value(
        "pretty-midi",
        choices=["fallback", "auto", "fluidsynth-cli", "pretty-midi"],
        help="renderer backend",
    )
    simple_mix: bool = kwconf.Flag(
        False,
        help="Only emit the mastered preview/full_soundtrack_preview.ogg.",
    )
    full_mix_only: bool = kwconf.Flag(
        False,
        help="Emit mastered preview plus per-section full mixes, but skip per-stem OGGs.",
    )
    runtime_stem_gain_mode: str = kwconf.Value(
        "native",
        choices=RUNTIME_STEM_GAIN_MODES,
        help="How to export adaptive per-stem OGGs and runtime previews.",
    )
    runtime_stem_max_gain_db: float | None = kwconf.Value(None)
    keep_debug_stems: bool = kwconf.Flag(
        False,
        help="Keep intermediate .npy stem buffers under scratch_stems/.",
    )
    force: bool = kwconf.Flag(False, help="force regeneration")
    jobs: int = kwconf.Value(
        max(1, (os.cpu_count() or 2) // 2),
        short_alias=["j"],
        help="Parallel worker count. Pass 0 or 1 for serial rendering.",
    )
    timings_out: Path | None = kwconf.Value(None, parser=Path, help="write coarse render phase timings to JSON")
    profile_out: Path | None = kwconf.Value(
        None,
        parser=Path,
        help="deprecated compatibility flag; use LINE_PROFILE=1 with line_profiler instead",
    )
    profile_workers: bool = kwconf.Flag(
        False,
        help="write per-worker timings and make worker execution line-profiler friendly",
    )
    groups_in_process: bool = kwconf.Flag(
        False,
        help="debug/profiling mode: render groups by direct Python calls instead of worker subprocesses",
    )
    json: bool = kwconf.Flag(False, help="print render JSON payload to stdout")

    def __post_init__(self) -> None:
        if self.simple_mix and self.full_mix_only:
            raise ValueError("--simple-mix and --full-mix-only are mutually exclusive")
        self.jobs = int(self.jobs)
        for key in ("spec", "outdir", "timings_out", "profile_out"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, Path):
                setattr(self, key, Path(value))

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        if config.profile_out is not None:
            print("render_isolated: --profile-out is deprecated; use LINE_PROFILE=1 for line_profiler", file=sys.stderr)
        return _render_main(config)




@dataclass(frozen=True)
class RenderWorkerPlan:
    """Inputs needed to invoke one render group worker.

    Kept at module scope so line_profiler can see the direct/subprocess
    boundary without losing time inside nested closure frames.
    """

    spec_path: Path
    outdir: Path
    backend: str
    simple_mix: bool
    full_mix_only: bool
    profile_workers: bool


@profile
def worker_timings_path(plan: RenderWorkerPlan, group: str) -> Path | None:
    if plan.profile_workers:
        return plan.outdir / "profiles" / f"render_group_worker.{group}.timings.json"
    return None


@profile
def worker_data(plan: RenderWorkerPlan, group: str) -> dict[str, object]:
    return {
        "spec": plan.spec_path,
        "outdir": plan.outdir,
        "group": group,
        "backend": plan.backend,
        "skip_section_ogg": bool(plan.simple_mix or plan.full_mix_only),
        "timings_out": worker_timings_path(plan, group),
    }


@profile
def run_worker_direct(worker_command: KwconfCommand, plan: RenderWorkerPlan, group: str) -> None:
    rc = worker_command.run_direct(argv=False, data=worker_data(plan, group))
    if rc != 0:
        raise RuntimeError(f"render group {group!r} failed with rc={rc}")


@profile
def run_worker_subprocess(worker_command: KwconfCommand, plan: RenderWorkerPlan, group: str) -> None:
    proc = worker_command.run_subprocess(data=worker_data(plan, group))
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, proc.args)

def adaptive_section_mastering_config(spec: dict) -> dict[str, object]:
    """Return section-full export policy for adaptive cues.

    ``section_postprocess`` is legacy behavior: each section can run its own
    postprocess chain against its raw slice. That can be an intentional special
    effect, but it can also normalize quiet/noisy sections independently.

    ``global_master_slices`` masters the complete composition once and slices
    that master into full-section game assets. This is the preferred policy for
    horizontal adaptive music when the engine crossfades whole sections.
    """
    render_cfg = spec.get("render", {}) or {}
    cfg = render_cfg.get("adaptive_section_mastering") or render_cfg.get("adaptive_sections") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    mode = str(cfg.get("mode", cfg.get("full_mix_mode", "section_postprocess")))
    if mode not in SECTION_FULL_MASTERING_MODES:
        raise ValueError(
            f"render.adaptive_section_mastering.mode must be one of {SECTION_FULL_MASTERING_MODES}, got {mode!r}"
        )
    return {
        "mode": mode,
        "ignore_section_postprocess_for_full_mix": bool(
            cfg.get("ignore_section_postprocess_for_full_mix", mode == "global_master_slices")
        ),
        "notes": str(cfg.get("notes", "")),
    }



def _db(value: float) -> float:
    value = max(float(value), 1e-12)
    return 20.0 * math.log10(value)


@profile
def _audio_stats(audio: np.ndarray, sample_rate: int) -> dict[str, float]:
    audio = coerce_stereo(audio)  # internal renderer helper; keeps stats consistent.
    if audio.size == 0:
        return {
            "duration_s": 0.0,
            "peak_dbfs": _db(0.0),
            "rms_dbfs": _db(0.0),
            "peak_linear": 0.0,
            "rms_linear": 0.0,
        }
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    return {
        "duration_s": float(audio.shape[0] / sample_rate) if sample_rate else 0.0,
        "peak_dbfs": _db(peak),
        "rms_dbfs": _db(rms),
        "peak_linear": peak,
        "rms_linear": rms,
    }


@profile
def _scale_audio(audio: np.ndarray, gain_db: float) -> np.ndarray:
    if abs(gain_db) < 1e-9:
        return audio.astype("float32", copy=False)
    return (audio * (10.0 ** (gain_db / 20.0))).astype("float32", copy=False)


def in_game_preview_mixes(
    spec: dict, group_names: list[str]
) -> dict[str, dict[str, float]]:
    """Define named state mixes for runtime and audition previews.

    The returned weights are runtime/authored stem gains. The renderer writes
    two files for each mix:

    - ``runtime_<name>.ogg``: weighted stem sum with no upward normalization.
      This is the truthful preview for layered runtime playback.
    - ``audition_<name>.ogg``: the same weighted sum normalized for comfortable
      listening and A/B comparison. This is useful for composition review but
      must not be mistaken for actual runtime loudness.
    """
    out: dict[str, dict[str, float]] = {}

    bridge = (spec.get("playback", {}) or {}).get("exit_policy", {}).get(
        "bridge_stems"
    ) or []
    bridge = [s for s in bridge if s in group_names]
    if bridge:
        out["minimal"] = {s: 1.0 for s in bridge}
    out["maximal"] = {g: 1.0 for g in group_names}

    sm = spec.get("state_map", {}) or {}
    for name, cfg in sm.items():
        if not isinstance(cfg, dict):
            continue
        stems = cfg.get("stems")
        if not isinstance(stems, dict):
            continue
        weights = {
            k: float(v)
            for k, v in stems.items()
            if isinstance(v, (int, float)) and float(v) > 0.0
        }
        if weights:
            out[f"state_{name}"] = weights

    return out


def _manifest_paths(manifest: dict, outdir: Path) -> list[Path]:
    """Return output files referenced by an adaptive music manifest."""
    paths: list[Path] = []
    files = manifest.get("files") or {}
    preview = files.get("preview") or {}
    for rel in preview.values():
        if isinstance(rel, str):
            paths.append(outdir / rel)
    adaptive = files.get("adaptive") or {}
    if isinstance(adaptive, dict):
        for section in adaptive.values():
            if isinstance(section, dict):
                for rel in section.values():
                    if isinstance(rel, str):
                        paths.append(outdir / rel)
    return paths


def _current_manifest_path(outdir: Path, cue_id: str, cue_hash: str) -> Path:
    return outdir / f"{cue_id}_{cue_hash}.adaptive_manifest.json"


def is_render_current(
    spec_path: Path,
    outdir: Path,
    cue_id: str,
    cue_hash: str,
    *,
    simple_mix: bool,
    full_mix_only: bool,
    runtime_stem_gain_mode: str,
    runtime_stem_max_gain_db: float | None,
) -> tuple[bool, Path | None, str]:
    """Return whether rendered music is current for this spec + renderer version.

    The hash already includes the YAML text, renderer version, soundfont, and
    backend. The mtime check catches manual file copies or partially restored
    generated directories whose manifest happened to survive.
    """
    manifest_path = _current_manifest_path(outdir, cue_id, cue_hash)
    if not manifest_path.exists():
        return False, None, "missing manifest"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    except Exception as ex:  # noqa: BLE001 - malformed manifests should regenerate.
        return False, manifest_path, f"unreadable manifest: {ex}"
    if manifest.get("hash") != cue_hash:
        return False, manifest_path, "manifest hash/version does not match"
    if bool(manifest.get("simple_mix", False)) != simple_mix:
        return False, manifest_path, "manifest simple_mix mode does not match"
    if bool(manifest.get("full_mix_only", False)) != full_mix_only:
        return False, manifest_path, "manifest full_mix_only mode does not match"
    if manifest.get("runtime_stem_gain_mode", "native") != runtime_stem_gain_mode:
        return False, manifest_path, "manifest runtime stem gain mode does not match"
    if runtime_stem_gain_mode == "shared":
        manifest_cap = manifest.get("runtime_stem_max_gain_db")
        if manifest_cap is None:
            return False, manifest_path, "manifest runtime stem gain cap missing"
        if runtime_stem_max_gain_db is not None and abs(float(manifest_cap) - float(runtime_stem_max_gain_db)) > 1e-6:
            return False, manifest_path, "manifest runtime stem gain cap does not match"
    outputs = _manifest_paths(manifest, outdir)
    if not outputs:
        return False, manifest_path, "manifest lists no output files"
    missing = [path for path in outputs if not path.exists()]
    if missing:
        return False, manifest_path, f"missing output file: {missing[0]}"
    spec_mtime = spec_path.stat().st_mtime
    stale = [
        path for path in [manifest_path, *outputs] if path.stat().st_mtime < spec_mtime
    ]
    if stale:
        return False, manifest_path, f"output older than source: {stale[0]}"
    return True, manifest_path, "current"




@profile
def _render_main(ns) -> int:
    timings = PhaseTimer()
    spec_path = Path(ns.spec)
    with timings.phase("load_spec_and_hash"):
        spec = yaml.safe_load(spec_path.read_text())
        render_cfg = spec.get("render", {})
        sr = int(render_cfg.get("sample_rate", 48000))
        soundfont = choose_soundfont(render_cfg.get("soundfont"))
        cue_hash = spec_hash(spec_path, soundfont, ns.backend)
        quality = float(render_cfg.get("ogg_quality", 5.0))
        outdir = Path(ns.outdir)
        outdir.mkdir(parents=True, exist_ok=True)

    if not ns.force:
        current, manifest_path, reason = is_render_current(
            spec_path,
            outdir,
            spec["id"],
            cue_hash,
            simple_mix=ns.simple_mix,
            full_mix_only=ns.full_mix_only,
            runtime_stem_gain_mode=ns.runtime_stem_gain_mode,
            runtime_stem_max_gain_db=ns.runtime_stem_max_gain_db,
        )
        if current and manifest_path is not None:
            manifest = json.loads(manifest_path.read_text(encoding="utf8"))
            preview_rel = (manifest.get("files", {}).get("preview", {}) or {}).get(
                "full_soundtrack"
            )
            if getattr(ns, "json", False):
                print(
                    json.dumps(
                        {
                            "skipped": True,
                            "reason": reason,
                            "manifest": str(manifest_path),
                            "preview": str(outdir / preview_rel)
                            if isinstance(preview_rel, str)
                            else None,
                            "hash": cue_hash,
                        },
                        indent=2,
                    )
                )
            return 0
        if manifest_path is not None:
            print(
                f"render_isolated: regenerating {spec['id']}: {reason}", file=sys.stderr
            )

    with timings.phase("build_score"):
        pm, groups, meta = build_score(spec)
    cue_markers = timeline_markers_from_spec(spec, meta)
    cue_metadata = section_chapter_metadata(
        cue_id=str(spec.get("id", spec_path.stem)),
        title=str(spec.get("title", spec.get("id", spec_path.stem))),
        sections=cue_markers,
    )
    total = meta[-1]["end_seconds"]
    target = int(math.ceil(total * sr))
    group_names = sorted(set(groups.values()))

    # Run per-group workers. Production can keep subprocess isolation, but the
    # profiling/debug path uses direct Python calls so line_profiler sees below
    # the old worker process boundary. Serial/direct execution is also simpler
    # and avoids executor overhead for jobs=0/1.
    from .group_worker import RenderGroupWorkerConfig

    worker_command = KwconfCommand(
        RenderGroupWorkerConfig,
        module="ambition_music_renderer.render.group_worker",
        cwd=project_root(),
    )
    worker_plan = RenderWorkerPlan(
        spec_path=spec_path,
        outdir=outdir,
        backend=ns.backend,
        simple_mix=bool(ns.simple_mix),
        full_mix_only=bool(ns.full_mix_only),
        profile_workers=bool(ns.profile_workers),
    )

    groups_in_process = bool(getattr(ns, "groups_in_process", False) or ns.profile_workers)
    jobs = 1 if ns.jobs <= 1 else min(ns.jobs, len(group_names))
    if groups_in_process and jobs != 1:
        print(
            "render_isolated: forcing serial in-process group rendering for profiling/debug visibility",
            file=sys.stderr,
        )
        jobs = 1
    worker_mode = "direct" if groups_in_process else "subprocess"
    with timings.phase(
        "render_group_workers",
        groups=len(group_names),
        jobs=jobs,
        mode="in-process" if groups_in_process else "subprocess",
    ):
        if jobs == 1:
            for group in group_names:
                start_group = time.perf_counter()
                if groups_in_process:
                    run_worker_direct(worker_command, worker_plan, group)
                else:
                    run_worker_subprocess(worker_command, worker_plan, group)
                timings.add(
                    "render_group_worker",
                    time.perf_counter() - start_group,
                    group=group,
                    mode=worker_mode,
                )
        else:
            import time as _time
            import ubelt as ub

            with ub.Executor(mode="thread", max_workers=jobs) as pool:
                futures = {
                    pool.submit(run_worker_subprocess, worker_command, worker_plan, group): (group, _time.perf_counter())
                    for group in group_names
                }
                for future, (group, start_group) in futures.items():
                    future.result()
                    timings.add(
                        "render_group_worker",
                        _time.perf_counter() - start_group,
                        group=group,
                        mode=worker_mode,
                    )

    output_files: dict = {"preview": {}, "adaptive": {}}

    # Load all stems into memory once.  These scratch stems are the native
    # post-stem-bus buffers written by the worker.  The mastered full mix should
    # continue to use these native buffers; runtime per-stem exports may either
    # preserve them exactly or receive one shared gain below.
    stem_audio: dict[str, np.ndarray] = {}
    with timings.phase("load_scratch_stems", groups=len(group_names)):
        for group in group_names:
            npy = outdir / "scratch_stems" / f"{spec['id']}_{cue_hash}.{group}.npy"
            stem_audio[group] = ensure_audio_length(np.load(npy), target)
            for sec in meta:
                if not (ns.simple_mix or ns.full_mix_only):
                    path = (
                        outdir
                        / "adaptive"
                        / sec["id"]
                        / f"{spec['id']}_{cue_hash}.{sec['id']}.{group}.ogg"
                    )
                    output_files["adaptive"].setdefault(sec["id"], {})[group] = str(
                        path.relative_to(outdir)
                    )

    # ---- Full mastered preview (matches the YAML postprocess intent) ----
    with timings.phase("mix_master_preview"):
        raw_full = np.zeros((target, 2), dtype="float32")
        for arr in stem_audio.values():
            raw_full += arr
        master_settings = dict(spec.get("postprocess", {}) or {})
        master_settings.setdefault("normalize", True)
        master_settings.setdefault("target_peak_db", -1.2)
        master = post_process(raw_full, sr, master_settings)
        preview = (
            outdir / "preview" / f"{spec['id']}_{cue_hash}.full_soundtrack_preview.ogg"
        )
        write_ogg_from_audio(
            master,
            sr,
            preview,
            quality=quality,
            keep_wav=False,
            metadata=cue_metadata,
        )
        output_files["preview"]["full_soundtrack"] = str(preview.relative_to(outdir))

    stem_stats_native = {
        group: _audio_stats(audio, sr) for group, audio in sorted(stem_audio.items())
    }
    raw_full_stats = _audio_stats(raw_full, sr)
    master_stats = _audio_stats(master, sr)
    master_rms_lift_db = master_stats["rms_dbfs"] - raw_full_stats["rms_dbfs"]
    master_peak_lift_db = master_stats["peak_dbfs"] - raw_full_stats["peak_dbfs"]

    runtime_settings = dict(render_cfg.get("runtime_stems", {}) or {})
    runtime_target_peak_db = float(runtime_settings.get("target_peak_db", -8.0))
    runtime_max_gain_db = ns.runtime_stem_max_gain_db
    if runtime_max_gain_db is None:
        runtime_max_gain_db = float(runtime_settings.get("max_gain_db", 24.0))
    runtime_gain_db = 0.0
    runtime_gain_requested_db = 0.0
    runtime_gain_was_capped = False
    runtime_gain_reason = "native"
    if ns.runtime_stem_gain_mode == "shared":
        raw_peak = float(raw_full_stats["peak_linear"])
        target_peak = 10.0 ** (runtime_target_peak_db / 20.0)
        if raw_peak > 1e-12:
            runtime_gain_requested_db = 20.0 * math.log10(target_peak / raw_peak)
            runtime_gain_db = min(runtime_gain_requested_db, runtime_max_gain_db)
            runtime_gain_was_capped = runtime_gain_db < runtime_gain_requested_db - 1e-6
            if runtime_gain_was_capped:
                runtime_gain_reason = (
                    f"shared gain requested +{runtime_gain_requested_db:.1f} dB from raw "
                    f"all-stem peak {raw_full_stats['peak_dbfs']:.1f} dBFS to target "
                    f"{runtime_target_peak_db:.1f} dBFS, capped at +{runtime_max_gain_db:.1f} dB"
                )
            else:
                runtime_gain_reason = (
                    f"shared gain from raw all-stem peak {raw_full_stats['peak_dbfs']:.1f} "
                    f"dBFS to target {runtime_target_peak_db:.1f} dBFS"
                )
        else:
            runtime_gain_reason = "raw all-stem reference was silent; shared gain disabled"

    runtime_stem_audio = {
        group: _scale_audio(audio, runtime_gain_db)
        for group, audio in stem_audio.items()
    }
    stem_stats_runtime = {
        group: _audio_stats(audio, sr)
        for group, audio in sorted(runtime_stem_audio.items())
    }

    # If shared runtime gain is requested, rewrite the adaptive per-stem OGGs
    # after all native buffers are known.  The worker writes native stems before
    # the parent can know the shared reference gain; overwriting here preserves
    # the current worker isolation model while making runtime stem export useful.
    if ns.runtime_stem_gain_mode == "shared" and not (ns.simple_mix or ns.full_mix_only):
        for group, audio in runtime_stem_audio.items():
            for sec in meta:
                piece = slice_audio(audio, sr, sec["start_seconds"], sec["end_seconds"])
                path = (
                    outdir
                    / "adaptive"
                    / sec["id"]
                    / f"{spec['id']}_{cue_hash}.{sec['id']}.{group}.ogg"
                )
                write_ogg_from_audio(piece, sr, path, quality=quality, keep_wav=False)

    # Per-section full slices for horizontal adaptive playback.
    #
    # Legacy mode (section_postprocess) lets a section run its own mastering
    # chain against a raw slice. That can be an intentional special effect, but
    # it is dangerous for game sections that crossfade as one score: a quiet
    # intro can be normalized independently, lifting its SoundFont/reverb noise
    # floor and breaking composition-level balance.
    #
    # Preferred mode (global_master_slices) masters the whole composition once
    # and slices that result. This keeps intro/loops/outro in one loudness
    # system, which is what the Rust music director expects when it crossfades
    # full-section assets at near-unity runtime gains.
    section_mastering = adaptive_section_mastering_config(spec)
    section_full_mode = str(section_mastering["mode"])
    ignored_section_postprocess: list[str] = []
    sections_in_spec = {s["id"]: s for s in spec.get("sections", [])}
    if not ns.simple_mix:
        for sec in meta:
            sec_spec = sections_in_spec.get(sec["id"], {})
            section_pp = sec_spec.get("postprocess")
            if section_full_mode == "global_master_slices":
                if section_pp:
                    ignored_section_postprocess.append(str(sec["id"]))
                piece = slice_audio(
                    master, sr, sec["start_seconds"], sec["end_seconds"]
                )
            elif section_pp:
                # Legacy behavior: slice the raw stem sum (pre-master), apply
                # the section's postprocess chain to that slice.
                raw_piece = slice_audio(
                    raw_full, sr, sec["start_seconds"], sec["end_seconds"]
                )
                section_settings = dict(master_settings)
                section_settings.update(section_pp)
                piece = post_process(raw_piece, sr, section_settings)
            else:
                piece = slice_audio(
                    master, sr, sec["start_seconds"], sec["end_seconds"]
                )
            path = (
                outdir
                / "adaptive"
                / sec["id"]
                / f"{spec['id']}_{cue_hash}.{sec['id']}.full.ogg"
            )
            section_metadata = dict(cue_metadata)
            section_metadata.update(
                section_chapter_metadata(
                    cue_id=str(spec.get("id", spec_path.stem)),
                    title=f"{spec.get('title', spec.get('id', spec_path.stem))} — {sec['id']}",
                    section_id=str(sec["id"]),
                    section_start_s=float(sec.get("start_seconds", 0.0)),
                    section_end_s=float(sec.get("end_seconds", 0.0)),
                )
            )
            write_ogg_from_audio(
                piece,
                sr,
                path,
                quality=quality,
                keep_wav=False,
                metadata=section_metadata,
            )
            output_files["adaptive"].setdefault(sec["id"], {})["full"] = str(
                path.relative_to(outdir)
            )

    # ---- Runtime and audition previews ----
    # Runtime previews are the weighted sum of the exported runtime stems with no
    # upward normalization. Audition previews are the same weighted sums boosted
    # for comfortable A/B listening. Keeping both prevents normalized authoring
    # previews from masquerading as true in-engine loudness.
    runtime_preview_stats: dict[str, dict[str, dict[str, float]]] = {}
    if not (ns.simple_mix or ns.full_mix_only):
        state_mixes = in_game_preview_mixes(spec, group_names)

        for label, weights in state_mixes.items():
            mix = np.zeros((target, 2), dtype="float32")
            for group, weight in weights.items():
                if group in runtime_stem_audio and weight > 0.0:
                    mix += runtime_stem_audio[group] * float(weight)
            runtime_path = outdir / "preview" / f"{spec['id']}_{cue_hash}.runtime_{label}.ogg"
            runtime_meta = dict(cue_metadata)
            runtime_meta["PREVIEW_TYPE"] = "runtime"
            runtime_meta["STATE_ID"] = label
            write_ogg_from_audio(mix, sr, runtime_path, quality=quality, keep_wav=False, metadata=runtime_meta)
            output_files["preview"][f"runtime_{label}"] = str(runtime_path.relative_to(outdir))

            audition = soft_limit(mix, target_peak_db=-2.5, drive=1.0, normalize=True)
            audition_path = outdir / "preview" / f"{spec['id']}_{cue_hash}.audition_{label}.ogg"
            audition_meta = dict(cue_metadata)
            audition_meta["PREVIEW_TYPE"] = "audition"
            audition_meta["STATE_ID"] = label
            write_ogg_from_audio(audition, sr, audition_path, quality=quality, keep_wav=False, metadata=audition_meta)
            output_files["preview"][f"audition_{label}"] = str(audition_path.relative_to(outdir))
            runtime_preview_stats[label] = {
                "runtime": _audio_stats(mix, sr),
                "audition": _audio_stats(audition, sr),
            }

    diagnostics_warnings: list[str] = []
    if ignored_section_postprocess:
        diagnostics_warnings.append(
            "global adaptive section mastering sliced the composition master and ignored section-local postprocess for full mixes: "
            + ", ".join(ignored_section_postprocess)
        )
    if stem_stats_native:
        strongest_native = max(
            stem_stats_native.items(), key=lambda item: item[1]["rms_dbfs"]
        )
        if strongest_native[1]["rms_dbfs"] < -55.0:
            diagnostics_warnings.append(
                "native runtime stems are very quiet; per-stem OGGs may sound empty "
                f"without shared runtime gain (strongest {strongest_native[0]} "
                f"RMS {strongest_native[1]['rms_dbfs']:.1f} dBFS)"
            )
    if master_rms_lift_db > 24.0:
        diagnostics_warnings.append(
            "mastered full preview is much louder than the raw all-stem sum "
            f"(+{master_rms_lift_db:.1f} dB RMS); noise floors may be lifted"
        )
    if ns.runtime_stem_gain_mode == "shared" and runtime_gain_requested_db > 36.0:
        diagnostics_warnings.append(
            "shared runtime gain request is very large "
            f"(+{runtime_gain_requested_db:.1f} dB); source/layer velocities likely need a pass"
        )
    if runtime_gain_was_capped:
        diagnostics_warnings.append(
            "shared runtime gain was capped "
            f"(+{runtime_gain_db:.1f} dB applied, +{runtime_gain_requested_db:.1f} dB requested); "
            "runtime stems remain quieter by design to avoid exporting amplified noise floors"
        )

    manifest = build_manifest(spec, cue_hash, meta, group_names, output_files, sr)
    manifest["render_mode"] = "isolated_process_stem_warmmix"
    manifest["simple_mix"] = bool(ns.simple_mix)
    manifest["full_mix_only"] = bool(ns.full_mix_only)
    manifest["runtime_stem_gain_mode"] = ns.runtime_stem_gain_mode
    manifest["runtime_stem_max_gain_db"] = runtime_max_gain_db if ns.runtime_stem_gain_mode == "shared" else None
    manifest["diagnostics"] = {
        "raw_full": raw_full_stats,
        "mastered_full": master_stats,
        "master_rms_lift_db": master_rms_lift_db,
        "master_peak_lift_db": master_peak_lift_db,
        "native_stems": stem_stats_native,
        "runtime_stems": stem_stats_runtime,
        "runtime_gain_db": runtime_gain_db,
        "runtime_gain_requested_db": runtime_gain_requested_db,
        "runtime_gain_was_capped": runtime_gain_was_capped,
        "runtime_gain_reason": runtime_gain_reason,
        "runtime_target_peak_db": runtime_target_peak_db,
        "runtime_max_gain_db": runtime_max_gain_db,
        "runtime_previews": runtime_preview_stats,
        "adaptive_section_mastering": {
            **section_mastering,
            "ignored_section_postprocess_sections": ignored_section_postprocess,
        },
        "warnings": diagnostics_warnings,
    }
    manifest_path = outdir / f"{spec['id']}_{cue_hash}.adaptive_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf8")

    # Write a regen.sh into the output directory so the cue can be re-rendered
    # from the same inputs without remembering the CLI invocation. The script
    # activates a sibling .venv if one exists in the renderer dir, so users
    # can `bash regen.sh` from anywhere.
    renderer_dir = project_root()
    abs_spec = spec_path.resolve()
    abs_outdir = outdir.resolve()
    regen = outdir / "regen.sh"
    regen.write_text(
        "#!/usr/bin/env bash\n"
        "# Auto-generated by render_isolated.py — regenerates this cue from the\n"
        "# same spec + backend that produced the contents of this directory.\n"
        "set -euo pipefail\n"
        f"renderer_dir={shlex.quote(str(renderer_dir))}\n"
        f"spec={shlex.quote(str(abs_spec))}\n"
        f"outdir={shlex.quote(str(abs_outdir))}\n"
        f"backend={shlex.quote(ns.backend)}\n"
        f"full_mix_only={1 if ns.full_mix_only else 0}\n"
        f"keep_debug_stems={1 if ns.keep_debug_stems else 0}\n"
        f"runtime_stem_gain_mode={shlex.quote(ns.runtime_stem_gain_mode)}\n"
        f"runtime_stem_max_gain_db={shlex.quote(str(runtime_max_gain_db))}\n"
        'cd "$renderer_dir"\n'
        "if [ -d .venv ]; then source .venv/bin/activate; fi\n"
        'rm -rf "$outdir"\n'
        'args=("${spec}" --outdir "${outdir}" --backend "${backend}" --force --runtime-stem-gain-mode "${runtime_stem_gain_mode}")\n'
        'if [ "${full_mix_only}" -eq 1 ]; then args+=(--full-mix-only); fi\n'
        'if [ "${keep_debug_stems}" -eq 1 ]; then args+=(--keep-debug-stems); fi\n'
        'python -m ambition_music_renderer.render.isolated "${args[@]}"\n',
        encoding="utf8",
    )
    regen.chmod(0o755)

    if not ns.keep_debug_stems:
        with timings.phase("cleanup_scratch_stems"):
            for npy in (outdir / "scratch_stems").glob("*.npy"):
                npy.unlink()
            try:
                (outdir / "scratch_stems").rmdir()
            except OSError:
                pass

    if ns.timings_out is not None:
        timings.write_json(ns.timings_out)
        timings.write_tsv(ns.timings_out.with_suffix(".tsv"))
        timings.write_summary(ns.timings_out.with_suffix(".txt"))

    if getattr(ns, "json", False):
        print(
            json.dumps(
                {
                    "skipped": False,
                    "manifest": str(manifest_path),
                    "preview": str(preview),
                    "runtime_previews": [
                        v
                        for k, v in output_files["preview"].items()
                        if k.startswith("runtime_")
                    ],
                    "audition_previews": [
                        v
                        for k, v in output_files["preview"].items()
                        if k.startswith("audition_")
                    ],
                    "runtime_stem_gain_mode": ns.runtime_stem_gain_mode,
                    "runtime_stem_max_gain_db": runtime_max_gain_db if ns.runtime_stem_gain_mode == "shared" else None,
                    "full_mix_only": bool(ns.full_mix_only),
                    "kept_debug_stems": bool(ns.keep_debug_stems),
                    "hash": cue_hash,
                },
                indent=2,
            )
        )
    return 0


def render_isolated_main(
    argv: list[str] | str | bool | None = None,
    *,
    cmdline: bool | None = None,
    **kwargs: object,
) -> int:
    """kwconf-backed Python/CLI entrypoint for render_isolated."""
    if cmdline is False:
        argv = False
    elif cmdline is True and argv is None:
        argv = True
    config = RenderIsolatedConfig.cli(argv=argv, data=kwargs)
    if config.profile_out is not None:
        print("render_isolated: --profile-out is deprecated; use LINE_PROFILE=1 for line_profiler", file=sys.stderr)
    return _render_main(config)


@profile
def main(argv=None) -> int:
    import time as _time

    total_start = _time.perf_counter()
    rc = 1
    try:
        rc = render_isolated_main(argv=argv)
        return rc
    finally:
        elapsed = _time.perf_counter() - total_start
        print(f"[ambition_music_renderer.render.isolated] total_elapsed_s={elapsed:.3f}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
