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
from ..music_timeline import write_render_authoring_artifacts
from .effects import post_process, soft_limit
from .export import section_chapter_metadata, timeline_markers_from_spec, write_ogg_from_audio
from .group import build_manifest, ensure_audio_length, slice_audio
from .foreground_protection import apply_foreground_protection, foreground_protection_mode
from ..audit.spectral_masking_audit import analyze_spectral_masking, write_reports as write_spectral_masking_reports
from .score_core import choose_soundfont
from ..musicir.compile import compile_score
from ..musicir.model import compiled_score_fingerprint
from .synth import spec_hash
from .stem_cache import (
    restore_cached_stem,
    stem_cache_key,
    stem_cache_path,
    store_cached_stem,
)
from ..profiler import PhaseTimer, profile
from ..kwconf_runner import KwconfCommand
from .._paths import project_root


from .bundle_options import BACKEND_CHOICES, RUNTIME_STEM_GAIN_MODES

SECTION_FULL_MASTERING_MODES = ("section_postprocess", "global_master_slices")


def _spectral_masking_manifest_summary(masking_payload: dict) -> dict[str, int | None]:
    """Return manifest-safe masking counts for either protection mode.

    Register-aware desk protection is applied before group stems are summed, so
    there is intentionally no unprotected group-stem prepass in that mode.
    Preserve that distinction as ``None`` instead of reaching into branch-local
    variables that do not exist on the register-aware path.
    """
    pre_count = masking_payload.get("pre_protection_warning_count")
    post_count = masking_payload.get("post_protection_warning_count")
    return {
        "pre_protection_warning_count": (
            None if pre_count is None else int(pre_count)
        ),
        "post_protection_warning_count": int(post_count or 0),
    }



class RenderIsolatedConfig(kwconf.Config):
    """kwconf-backed config for the render-isolated entrypoint."""


    spec: Path = kwconf.Value(None, position=1, parser=Path, help="MusicIR YAML spec")
    outdir: Path = kwconf.Value(Path("output"), parser=Path, help="render output directory")
    backend: str = kwconf.Value(
        "pretty-midi",
        choices=list(BACKEND_CHOICES),
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
    audition_stems: bool = kwconf.Flag(
        False,
        help=(
            "Emit full-length per-group review stems under preview/: native-level "
            "files for recombination plus normalized solo audition files. Useful "
            "with --simple-mix for lean composition review."
        ),
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
    stem_cache: bool = kwconf.Flag(
        False,
        help=(
            "Reuse content-identical rendered stem groups across sibling A/B renders. "
            "The default cache lives at <outdir-parent>/.stem_cache."
        ),
    )
    stem_cache_dir: Path | None = kwconf.Value(
        None,
        parser=Path,
        help="Override the persistent stem cache directory; also enables stem caching.",
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
        for key in ("spec", "outdir", "timings_out", "profile_out", "stem_cache_dir"):
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


def section_mix_gain_envelope(
    spec: dict,
    meta: list[dict],
    sample_rate: int,
    frame_count: int,
) -> tuple[np.ndarray, dict[str, float]]:
    """Build a smooth composition-level gain rider from section metadata.

    ``mix_gain_db`` is deliberately an audio-domain mix control, not a note
    velocity or arrangement control.  It lets a sparse intro, dense hook, and
    loop handoff inhabit one loudness system before the global master chain.
    Transitions are interpolated in dB around section boundaries so a level
    correction cannot create an audible step.
    """
    if frame_count <= 0:
        return np.ones(0, dtype=np.float32), {}

    sections = {str(row.get("id")): row for row in spec.get("sections", [])}
    gains_db = {
        str(sec.get("id")): float(sections.get(str(sec.get("id")), {}).get("mix_gain_db", 0.0))
        for sec in meta
    }
    envelope_db = np.zeros(frame_count, dtype=np.float32)
    ordered: list[tuple[int, int, str, float]] = []
    for sec in meta:
        sec_id = str(sec.get("id"))
        start = max(0, min(frame_count, int(round(float(sec.get("start_seconds", 0.0)) * sample_rate))))
        end = max(start, min(frame_count, int(round(float(sec.get("end_seconds", 0.0)) * sample_rate))))
        gain_db = gains_db.get(sec_id, 0.0)
        envelope_db[start:end] = gain_db
        ordered.append((start, end, sec_id, gain_db))

    bpm = float((spec.get("tempo") or {}).get("bpm", 120.0))
    render_cfg = spec.get("render") or {}
    default_transition_beats = float(render_cfg.get("section_mix_transition_beats", 1.0))
    for idx in range(1, len(ordered)):
        prev_start, prev_end, prev_id, prev_gain = ordered[idx - 1]
        next_start, next_end, next_id, next_gain = ordered[idx]
        if abs(next_gain - prev_gain) < 1e-9:
            continue
        next_spec = sections.get(next_id, {})
        beats = float(next_spec.get("mix_gain_transition_beats", default_transition_beats))
        if beats <= 0.0 or bpm <= 0.0:
            continue
        transition_frames = max(2, int(round((beats * 60.0 / bpm) * sample_rate)))
        boundary = next_start
        left = max(prev_start, boundary - transition_frames // 2)
        right = min(next_end, boundary + transition_frames - transition_frames // 2)
        if right <= left:
            continue
        envelope_db[left:right] = np.linspace(
            prev_gain, next_gain, right - left, endpoint=False, dtype=np.float32
        )

    envelope = np.power(10.0, envelope_db / 20.0).astype(np.float32)
    return envelope, gains_db


def apply_section_mix_gains(
    stem_audio: dict[str, np.ndarray],
    spec: dict,
    meta: list[dict],
    sample_rate: int,
    frame_count: int,
) -> dict[str, float]:
    envelope, gains_db = section_mix_gain_envelope(spec, meta, sample_rate, frame_count)
    if envelope.size == 0 or not any(abs(value) > 1e-9 for value in gains_db.values()):
        return gains_db
    scale = envelope[:, None]
    for group, audio in list(stem_audio.items()):
        stem_audio[group] = (audio * scale).astype(np.float32, copy=False)
    return gains_db


def section_stem_mix_gain_envelopes(
    spec: dict,
    meta: list[dict],
    sample_rate: int,
    frame_count: int,
    group_names: list[str],
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, float]]]:
    """Build smooth per-section gain riders for individual stem families.

    Exact scores may author ``stem_mix_db`` on form regions, while v1 scores
    may put the same mapping on top-level ``sections``.  The control lives in
    the audio domain: it changes orchestral hierarchy without rewriting note
    velocity, CC expression, or the rendered sample attack.
    """
    groups = [str(group) for group in group_names]
    if frame_count <= 0:
        return {group: np.ones(0, dtype=np.float32) for group in groups}, {}

    authored_sections = {str(row.get("id")): row for row in spec.get("sections", [])}
    gains_db: dict[str, dict[str, float]] = {}
    ordered: list[tuple[int, int, str, dict[str, float], dict]] = []
    for sec in meta:
        sec_id = str(sec.get("id"))
        authored = authored_sections.get(sec_id, {})
        raw = sec.get("stem_mix_db", authored.get("stem_mix_db", {})) or {}
        sec_gains = {group: float(raw.get(group, 0.0)) for group in groups}
        gains_db[sec_id] = sec_gains
        start = max(0, min(frame_count, int(round(float(sec.get("start_seconds", 0.0)) * sample_rate))))
        end = max(start, min(frame_count, int(round(float(sec.get("end_seconds", 0.0)) * sample_rate))))
        ordered.append((start, end, sec_id, sec_gains, sec))

    envelopes_db = {group: np.zeros(frame_count, dtype=np.float32) for group in groups}
    for start, end, _sec_id, sec_gains, _sec in ordered:
        for group in groups:
            envelopes_db[group][start:end] = sec_gains[group]

    bpm = float((spec.get("tempo") or {}).get("bpm", 120.0))
    render_cfg = spec.get("render") or {}
    default_transition_beats = float(
        render_cfg.get(
            "section_stem_mix_transition_beats",
            render_cfg.get("section_mix_transition_beats", 1.0),
        )
    )
    for idx in range(1, len(ordered)):
        prev_start, _prev_end, _prev_id, prev_gains, _prev_sec = ordered[idx - 1]
        next_start, next_end, next_id, next_gains, next_sec = ordered[idx]
        authored = authored_sections.get(next_id, {})
        beats = float(
            next_sec.get(
                "stem_mix_transition_beats",
                authored.get("stem_mix_transition_beats", default_transition_beats),
            )
        )
        if beats <= 0.0 or bpm <= 0.0:
            continue
        transition_frames = max(2, int(round((beats * 60.0 / bpm) * sample_rate)))
        boundary = next_start
        left = max(prev_start, boundary - transition_frames // 2)
        right = min(next_end, boundary + transition_frames - transition_frames // 2)
        if right <= left:
            continue
        for group in groups:
            prev_gain = prev_gains[group]
            next_gain = next_gains[group]
            if abs(next_gain - prev_gain) < 1e-9:
                continue
            envelopes_db[group][left:right] = np.linspace(
                prev_gain, next_gain, right - left, endpoint=False, dtype=np.float32
            )

    envelopes = {
        group: np.power(10.0, envelope_db / 20.0).astype(np.float32)
        for group, envelope_db in envelopes_db.items()
    }
    return envelopes, gains_db


def apply_section_stem_mix_gains(
    stem_audio: dict[str, np.ndarray],
    spec: dict,
    meta: list[dict],
    sample_rate: int,
    frame_count: int,
) -> dict[str, dict[str, float]]:
    envelopes, gains_db = section_stem_mix_gain_envelopes(
        spec, meta, sample_rate, frame_count, list(stem_audio)
    )
    for group, audio in list(stem_audio.items()):
        envelope = envelopes.get(group)
        if envelope is None or envelope.size == 0:
            continue
        stem_audio[group] = (audio * envelope[:, None]).astype(np.float32, copy=False)
    return gains_db


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
    audition_stems: bool,
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
    if bool(manifest.get("audition_stems", False)) != audition_stems:
        return False, manifest_path, "manifest audition_stems mode does not match"
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
            audition_stems=ns.audition_stems,
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

    with timings.phase("compile_score"):
        compiled = compile_score(spec)
        pm = compiled.pm
        groups = compiled.groups
        meta = compiled.sections
        compiled_fingerprint = compiled_score_fingerprint(compiled)
    cue_markers = timeline_markers_from_spec(compiled.normalized_spec, meta)
    cue_metadata = section_chapter_metadata(
        cue_id=str(spec.get("id", spec_path.stem)),
        title=str(spec.get("title", spec.get("id", spec_path.stem))),
        sections=cue_markers,
    )
    total = meta[-1]["end_seconds"]
    target = int(math.ceil(total * sr))
    group_names = sorted(set(groups.values()))

    # A/B composition edits often change only one stem. The cue hash must still
    # identify the complete score, but an explicitly enabled stem cache can
    # restore any group whose expanded MIDI + render settings are byte-for-byte
    # equivalent to a prior variant. This remains safe in the presence of the
    # score's shared humanization RNG because the key is built after build_score.
    stem_cache_enabled = bool(ns.stem_cache or ns.stem_cache_dir is not None)
    cache_dir: Path | None = None
    cache_keys: dict[str, str] = {}
    cache_hits: list[str] = []
    groups_to_render = list(group_names)
    if stem_cache_enabled:
        cache_dir = (
            Path(ns.stem_cache_dir)
            if ns.stem_cache_dir is not None
            else outdir.parent / ".stem_cache"
        ).resolve()
        resolved_outdir = outdir.resolve()
        if cache_dir == resolved_outdir or resolved_outdir in cache_dir.parents:
            raise ValueError(
                "--stem-cache-dir must live outside the render outdir so regen/cleanup "
                "cannot delete the persistent cache"
            )
        bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
        cache_misses: list[str] = []
        with timings.phase("restore_stem_cache", groups=len(group_names)):
            for group in group_names:
                key = stem_cache_key(
                    spec=spec,
                    spec_path=spec_path,
                    pm=pm,
                    groups=groups,
                    group=group,
                    backend=ns.backend,
                    soundfont=soundfont,
                    sample_rate=sr,
                    bpm=bpm,
                    total_seconds=total,
                    instrument_specs=compiled.instrument_specs,
                )
                cache_keys[group] = key
                cached = stem_cache_path(cache_dir, str(spec["id"]), group, key)
                scratch = outdir / "scratch_stems" / f"{spec['id']}_{cue_hash}.{group}.npy"
                if cached.exists() and restore_cached_stem(
                    cached, scratch, expected_samples=target
                ):
                    cache_hits.append(group)
                else:
                    cache_misses.append(group)
        groups_to_render = cache_misses
        print(
            "render_isolated: stem cache "
            f"hits={len(cache_hits)}/{len(group_names)} "
            f"render={','.join(groups_to_render) if groups_to_render else 'none'}",
            file=sys.stderr,
        )

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
    if not groups_to_render:
        jobs = 0
    elif ns.jobs <= 1:
        jobs = 1
    else:
        jobs = min(ns.jobs, len(groups_to_render))
    if groups_in_process and jobs > 1:
        print(
            "render_isolated: forcing serial in-process group rendering for profiling/debug visibility",
            file=sys.stderr,
        )
        jobs = 1
    worker_mode = "direct" if groups_in_process else "subprocess"
    with timings.phase(
        "render_group_workers",
        groups=len(groups_to_render),
        jobs=jobs,
        mode="in-process" if groups_in_process else "subprocess",
    ):
        if jobs == 1:
            for group in groups_to_render:
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
        elif jobs > 1:
            import time as _time
            import ubelt as ub

            with ub.Executor(mode="thread", max_workers=jobs) as pool:
                futures = {
                    pool.submit(run_worker_subprocess, worker_command, worker_plan, group): (group, _time.perf_counter())
                    for group in groups_to_render
                }
                for future, (group, start_group) in futures.items():
                    future.result()
                    timings.add(
                        "render_group_worker",
                        _time.perf_counter() - start_group,
                        group=group,
                        mode=worker_mode,
                    )

    if stem_cache_enabled and cache_dir is not None:
        with timings.phase("store_stem_cache", groups=len(groups_to_render)):
            for group in groups_to_render:
                scratch = outdir / "scratch_stems" / f"{spec['id']}_{cue_hash}.{group}.npy"
                cached = stem_cache_path(
                    cache_dir, str(spec["id"]), group, cache_keys[group]
                )
                store_cached_stem(scratch, cached)

    output_files: dict = {"preview": {}, "adaptive": {}, "authoring": {}}

    # Store immutable semantic provenance for read-only authoring frontends.
    authoring = write_render_authoring_artifacts(
        score_path=spec_path,
        spec=spec,
        pm=pm,
        section_meta=meta,
        render_hash=cue_hash,
        run_dir=outdir,
        compiled=compiled,
    )
    output_files["authoring"] = authoring.manifest_files(outdir)

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

    section_stem_mix_gains_db = apply_section_stem_mix_gains(
        stem_audio, spec, meta, sr, target
    )
    section_mix_gains_db = apply_section_mix_gains(
        stem_audio, spec, meta, sr, target
    )

    # Audio-domain masking diagnostics run while the native group stems are
    # still in memory. This keeps diagnostic bundles lean: they can report
    # time-local spectral collisions without retaining large debug stem audio.
    reports_dir = outdir / "reports"
    protection_mode = foreground_protection_mode(spec)
    instrument_register_mode = protection_mode in {
        "instrument_register",
        "register",
        "desk_register",
    }

    if instrument_register_mode:
        # Register-aware protection was already applied to each rendered desk
        # before the group stems were summed. Re-applying a family-bus rider
        # here would double-duck the score, and a nominal "pre" analysis would
        # actually be looking at already-protected audio.
        with timings.phase("foreground_protection_report"):
            foreground_protection = apply_foreground_protection(
                stem_audio, pm, groups, spec, sr
            )
        with timings.phase("spectral_masking_post_protection"):
            masking_post = analyze_spectral_masking(stem_audio, pm, groups, spec, sr)
            masking_payload = dict(masking_post)
            masking_payload["pre_protection_warning_count"] = None
            masking_payload["post_protection_warning_count"] = int(
                masking_post.get("warning_count", 0)
            )
    else:
        with timings.phase("spectral_masking_pre_protection"):
            masking_pre = analyze_spectral_masking(stem_audio, pm, groups, spec, sr)
        with timings.phase("foreground_protection"):
            foreground_protection = apply_foreground_protection(
                stem_audio, pm, groups, spec, sr
            )
        with timings.phase("spectral_masking_post_protection"):
            masking_post = analyze_spectral_masking(stem_audio, pm, groups, spec, sr)
            masking_payload = dict(masking_post)
            masking_payload["pre_protection_warning_count"] = int(
                masking_pre.get("warning_count", 0)
            )
            masking_payload["post_protection_warning_count"] = int(
                masking_post.get("warning_count", 0)
            )

    masking_payload["foreground_protection"] = foreground_protection
    write_spectral_masking_reports(masking_payload, reports_dir)
    (reports_dir / "foreground_protection.json").write_text(
        json.dumps(foreground_protection, indent=2), encoding="utf8"
    )

    # ---- Full mastered preview (matches the YAML postprocess intent) ----
    with timings.phase("mix_master_preview"):
        raw_full = np.zeros((target, 2), dtype="float32")
        for arr in stem_audio.values():
            raw_full += arr
        master_settings = dict(spec.get("postprocess", {}) or {})
        master_settings.setdefault("normalize", True)
        master_settings.setdefault("target_peak_db", -1.2)
        master = post_process(raw_full, sr, master_settings, base_dir=spec_path.parent)
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

    # Optional full-length review stems for composition work. The native-level
    # files preserve relative stem balance and are compact enough to keep many
    # variants around for cross-version recombination. The normalized audition
    # files remain useful when soloing a quiet part.
    review_stem_stats: dict[str, dict[str, float]] = {}
    audition_stem_stats: dict[str, dict[str, float]] = {}
    review_stem_gain_db = 0.0
    if ns.audition_stems:
        # OGG encoders clip outside [-1, 1]. Apply at most one protective
        # attenuation shared by every review stem so their relative levels are
        # preserved across the whole version. Never boost quiet review stems.
        review_peak = max(
            (float(np.max(np.abs(audio))) for audio in stem_audio.values() if audio.size),
            default=0.0,
        )
        if review_peak > 0.98:
            review_stem_gain_db = 20.0 * math.log10(0.98 / review_peak)

        for group, audio in sorted(stem_audio.items()):
            review_audio = _scale_audio(audio, review_stem_gain_db)
            review_path = (
                outdir
                / "preview"
                / f"{spec['id']}_{cue_hash}.review_stem_{group}.ogg"
            )
            review_meta = dict(cue_metadata)
            review_meta["PREVIEW_TYPE"] = "review_stem"
            review_meta["STEM_GROUP"] = group
            write_ogg_from_audio(
                review_audio,
                sr,
                review_path,
                quality=quality,
                keep_wav=False,
                metadata=review_meta,
            )
            output_files["preview"][f"review_stem_{group}"] = str(
                review_path.relative_to(outdir)
            )
            review_stem_stats[group] = _audio_stats(review_audio, sr)

            audition = soft_limit(audio, target_peak_db=-2.5, drive=1.0, normalize=True)
            audition_path = (
                outdir
                / "preview"
                / f"{spec['id']}_{cue_hash}.audition_stem_{group}.ogg"
            )
            audition_meta = dict(cue_metadata)
            audition_meta["PREVIEW_TYPE"] = "audition_stem"
            audition_meta["STEM_GROUP"] = group
            write_ogg_from_audio(
                audition,
                sr,
                audition_path,
                quality=quality,
                keep_wav=False,
                metadata=audition_meta,
            )
            output_files["preview"][f"audition_stem_{group}"] = str(
                audition_path.relative_to(outdir)
            )
            audition_stem_stats[group] = _audio_stats(audition, sr)

    # If shared runtime gain is requested, rewrite the adaptive per-stem OGGs
    # after all native buffers are known.  The worker writes native stems before
    # the parent can know the shared reference gain; overwriting here preserves
    # the current worker isolation model while making runtime stem export useful.
    if not (ns.simple_mix or ns.full_mix_only):
        export_stems = (
            runtime_stem_audio
            if ns.runtime_stem_gain_mode == "shared"
            else stem_audio
        )
        for group, audio in export_stems.items():
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
                piece = post_process(
                    raw_piece, sr, section_settings, base_dir=spec_path.parent
                )
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

    manifest = build_manifest(
        spec,
        cue_hash,
        meta,
        group_names,
        output_files,
        sr,
        compiled_score={
            "schema": "ambition.compiled_score.v1",
            "fingerprint": compiled_fingerprint,
            "source_schema": compiled.source_schema,
            "canonical_schema": compiled.canonical_schema,
            "normalization_warnings": list(compiled.normalization_warnings),
        },
    )
    manifest["source_score_sha256"] = authoring.source_score_sha256
    manifest["render_mode"] = "isolated_process_stem_warmmix"
    manifest["simple_mix"] = bool(ns.simple_mix)
    manifest["full_mix_only"] = bool(ns.full_mix_only)
    manifest["audition_stems"] = bool(ns.audition_stems)
    manifest["stem_cache"] = {
        "enabled": stem_cache_enabled,
        "directory": str(cache_dir) if cache_dir is not None else None,
        "hits": list(cache_hits),
        "rendered": list(groups_to_render),
        "keys": dict(cache_keys),
    }
    manifest["runtime_stem_gain_mode"] = ns.runtime_stem_gain_mode
    manifest["runtime_stem_max_gain_db"] = runtime_max_gain_db if ns.runtime_stem_gain_mode == "shared" else None
    manifest["section_mix_gains_db"] = section_mix_gains_db
    manifest["section_stem_mix_gains_db"] = section_stem_mix_gains_db
    manifest["foreground_protection"] = foreground_protection
    manifest["spectral_masking"] = _spectral_masking_manifest_summary(
        masking_payload
    )
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
        "review_stems": review_stem_stats,
        "review_stem_gain_db": review_stem_gain_db,
        "audition_stems": audition_stem_stats,
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
        f"audition_stems={1 if ns.audition_stems else 0}\n"
        f"keep_debug_stems={1 if ns.keep_debug_stems else 0}\n"
        f"stem_cache={1 if stem_cache_enabled else 0}\n"
        f"stem_cache_dir={shlex.quote(str(cache_dir)) if cache_dir is not None else ''}\n"
        f"runtime_stem_gain_mode={shlex.quote(ns.runtime_stem_gain_mode)}\n"
        f"runtime_stem_max_gain_db={shlex.quote(str(runtime_max_gain_db))}\n"
        'cd "$renderer_dir"\n'
        "if [ -d .venv ]; then source .venv/bin/activate; fi\n"
        'rm -rf "$outdir"\n'
        'args=("${spec}" --outdir "${outdir}" --backend "${backend}" --force --runtime-stem-gain-mode "${runtime_stem_gain_mode}")\n'
        'if [ "${full_mix_only}" -eq 1 ]; then args+=(--full-mix-only); fi\n'
        'if [ "${audition_stems}" -eq 1 ]; then args+=(--audition-stems); fi\n'
        'if [ "${keep_debug_stems}" -eq 1 ]; then args+=(--keep-debug-stems); fi\n'
        'if [ "${stem_cache}" -eq 1 ]; then args+=(--stem-cache); fi\n'
        'if [ -n "${stem_cache_dir}" ]; then args+=(--stem-cache-dir "${stem_cache_dir}"); fi\n'
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
                        if k.startswith("audition_") and not k.startswith("audition_stem_")
                    ],
                    "review_stems": [
                        v
                        for k, v in output_files["preview"].items()
                        if k.startswith("review_stem_")
                    ],
                    "audition_stems": [
                        v
                        for k, v in output_files["preview"].items()
                        if k.startswith("audition_stem_")
                    ],
                    "runtime_stem_gain_mode": ns.runtime_stem_gain_mode,
                    "runtime_stem_max_gain_db": runtime_max_gain_db if ns.runtime_stem_gain_mode == "shared" else None,
                    "full_mix_only": bool(ns.full_mix_only),
                    "audition_stems_enabled": bool(ns.audition_stems),
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
