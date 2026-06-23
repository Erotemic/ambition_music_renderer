"""Group/stem rendering and manifest construction for MusicIR renders."""

from __future__ import annotations

import copy
import gc
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi

from ..profiler import profile
from ..instrument_libraries import resolve_sfz_reference
from ..audio_utils import coerce_stereo
from .effects import post_process
from .export import write_ogg_from_audio
from .score_core import RENDERER_VERSION, choose_soundfont, load_yaml
from .score_layers import build_score
from .synth import render_synth_audio, sanitize_same_pitch_overlaps, spec_hash

@profile
def copy_with_instruments(
    pm: pretty_midi.PrettyMIDI, instruments: list[pretty_midi.Instrument], bpm: float
) -> pretty_midi.PrettyMIDI:
    new_pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    new_pm.instruments = [copy.deepcopy(inst) for inst in instruments]
    return new_pm


@profile
def ensure_audio_length(audio: np.ndarray, target_samples: int) -> np.ndarray:
    if len(audio) < target_samples:
        audio = np.pad(audio, ((0, target_samples - len(audio)), (0, 0)))
    elif len(audio) > target_samples:
        audio = audio[:target_samples]
    return audio.astype(np.float32, copy=False)


@profile
def slice_audio(
    audio: np.ndarray, sample_rate: int, start_seconds: float, end_seconds: float
) -> np.ndarray:
    a = max(0, int(round(start_seconds * sample_rate)))
    b = max(a, int(round(end_seconds * sample_rate)))
    return audio[a:b]


def section_metadata_from_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    seconds_per_beat = 60.0 / bpm
    cursor = 0
    out = []
    for section in spec["sections"]:
        bars = int(section["bars"])
        start_beat = cursor * beats_per_bar
        end_beat = (cursor + bars) * beats_per_bar
        out.append(
            {
                "id": section["id"],
                "label": section.get("label", section["id"]),
                "kind": section.get("kind", "section"),
                "start_bar": cursor,
                "bars": bars,
                "start_beat": start_beat,
                "end_beat": end_beat,
                "start_seconds": start_beat * seconds_per_beat,
                "end_seconds": end_beat * seconds_per_beat,
                "duration_seconds": (end_beat - start_beat) * seconds_per_beat,
                "loopable": bool(section.get("loopable", False)),
                "valid_exit_local_bars": section.get("valid_exit_local_bars", []),
            }
        )
        cursor += bars
    return out



@profile
def instrument_backend_spec(instrument_specs: dict[str, Any], inst_name: str) -> dict[str, Any]:
    """Return normalized backend metadata for one instrument.

    Module-level for profiling and reuse by render backends; this used to be a
    nested closure inside ``render_group_audio``.
    """
    spec = dict(instrument_specs.get(inst_name, {}) or {})
    raw = spec.get("instrument_backend", spec.get("backend", {}))
    if isinstance(raw, str):
        raw = {"kind": raw}
    if not isinstance(raw, dict):
        raw = {}
    if "sfz" in spec and "sfz" not in raw:
        raw = {**raw, "sfz": spec["sfz"]}
    return raw

_WARNED_INSTRUMENT_BACKENDS: set[str] = set()


def _is_optional_instrument_backend(spec: dict[str, Any]) -> bool:
    if "required" in spec:
        return not bool(spec.get("required"))
    return bool(spec.get("optional", True))


def _warn_instrument_backend_once(key: str, message: str) -> None:
    if key in _WARNED_INSTRUMENT_BACKENDS:
        return
    _WARNED_INSTRUMENT_BACKENDS.add(key)
    print(f"[ambition_music_renderer] {message}", file=sys.stderr)


# A noted instrument that renders below this peak is treated as a failed render
# (missing SFZ samples, an unmet keyswitch/CC, or an out-of-range part), not as
# legitimately quiet audio: even a ppp note peaks well above -70 dBFS. This is a
# cheap guard on the in-memory buffer; deeper analysis belongs in a post-render
# audit.
_SILENT_RENDER_PEAK = 10 ** (-70.0 / 20.0)


def _instrument_has_notes(pm: pretty_midi.PrettyMIDI) -> bool:
    return any(inst.notes for inst in pm.instruments)


def _is_effectively_silent(audio: np.ndarray) -> bool:
    return audio.size == 0 or float(np.max(np.abs(audio))) < _SILENT_RENDER_PEAK


def _instrument_prefers_sfizz(inst_backend: dict[str, Any]) -> bool:
    kind = str(inst_backend.get("kind", "")).lower().strip()
    return kind in {"sfz", "sfizz", "sample", "sampled"} or any(
        key in inst_backend for key in ("sfz", "library_ref", "library", "sfz_glob")
    )


def _resolve_instrument_sfz(
    inst_backend: dict[str, Any],
    *,
    base_dir: Path | None,
    sfizz_cfg: dict[str, Any],
) -> Path | None:
    raw_sfz = inst_backend.get("sfz") or inst_backend.get("path") or inst_backend.get("sfz_path")
    raw_sfz = raw_sfz or inst_backend.get("sfz_glob")
    library_ref = inst_backend.get("library_ref") or inst_backend.get("library")
    prefer = inst_backend.get("prefer") or inst_backend.get("prefer_keywords") or []
    roots = []
    roots.extend(sfizz_cfg.get("library_roots") or [])
    roots.extend(inst_backend.get("library_roots") or [])
    resolved = resolve_sfz_reference(
        raw_sfz,
        library_ref=str(library_ref) if library_ref else None,
        prefer=[str(item) for item in prefer],
        base_dir=base_dir,
        roots=roots,
    )
    if resolved is not None:
        return resolved
    default_sfz = sfizz_cfg.get("default_sfz")
    if default_sfz:
        return resolve_sfz_reference(default_sfz, base_dir=base_dir, roots=roots)
    return None


@profile
def render_group_audio(
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    group: str,
    backend: str,
    soundfont: str,
    sample_rate: int,
    tempdir: Path,
    minimum_duration: float,
    bpm: float,
    *,
    base_dir: Path | None = None,
    render_cfg: dict[str, Any] | None = None,
) -> np.ndarray:
    insts = [inst for inst in pm.instruments if groups.get(inst.name) == group]
    render_cfg = render_cfg or {}
    instrument_specs = getattr(pm, "_ambition_instrument_specs", {}) or {}
    sfizz_cfg = dict(render_cfg.get("sfizz") or {})

    wants_sfizz = backend in {"sfizz", "sfizz-render"}
    has_instrument_sfizz = any(
        _instrument_prefers_sfizz(instrument_backend_spec(instrument_specs, inst.name))
        for inst in insts
    )
    if wants_sfizz or has_instrument_sfizz:
        from ..backends.sfizz_backend import render_sfizz

        default_fallback_backend = str(sfizz_cfg.get("fallback_backend", render_cfg.get("sfizz_fallback_backend", "auto")))
        # Strict mode (render.strict_backends) turns every backend failure /
        # silent render into a hard error instead of warn-and-fallback. The
        # default is forgiving so one bad SFZ never silently drops a whole stem,
        # but it always warns loudly so the author can fix the SFZ or make the
        # fallback that instrument's real backend.
        strict_backends = bool(render_cfg.get("strict_backends", render_cfg.get("strict_instruments", False)))
        rendered: list[np.ndarray] = []
        for idx, inst in enumerate(insts):
            inst_backend = instrument_backend_spec(instrument_specs, inst.name)
            allow_fallback = _is_optional_instrument_backend(inst_backend) and not strict_backends
            fallback_backend_name = str(inst_backend.get("fallback_backend", default_fallback_backend))
            inst_pm = copy_with_instruments(pm, [inst], bpm)
            sfz_path = _resolve_instrument_sfz(inst_backend, base_dir=base_dir, sfizz_cfg=sfizz_cfg)
            if sfz_path is not None:
                settings = dict(sfizz_cfg)
                settings.update(dict(inst_backend.get("settings") or {}))
                if "command" in inst_backend:
                    settings["command"] = inst_backend["command"]
                if "binary" in inst_backend:
                    settings["binary"] = inst_backend["binary"]
                try:
                    sfizz_audio = render_sfizz(
                        inst_pm,
                        sfz_path=sfz_path,
                        sample_rate=sample_rate,
                        tempdir=tempdir,
                        output_name=f"group_{group}.{idx}.{inst.name}",
                        minimum_duration=minimum_duration,
                        base_dir=base_dir,
                        settings=settings,
                    )
                except Exception as ex:
                    if not allow_fallback:
                        raise
                    _warn_instrument_backend_once(
                        f"sfizz-render-failed:{inst.name}:{sfz_path}",
                        f"instrument {inst.name!r} requested SFZ {sfz_path}, but rendering failed; "
                        f"using {fallback_backend_name!r} fallback. reason: {ex}",
                    )
                else:
                    # sfizz exits 0 even when it drops every region (missing
                    # samples) or nothing matches (unmet keyswitch/CC/range),
                    # yielding silence. Treat that like a failure so the stem is
                    # not silently lost.
                    if _instrument_has_notes(inst_pm) and _is_effectively_silent(sfizz_audio):
                        msg = (
                            f"instrument {inst.name!r} SFZ {sfz_path} rendered SILENCE despite active "
                            f"notes (missing samples, or an unmet keyswitch/CC/range)"
                        )
                        if not allow_fallback:
                            raise RuntimeError(msg)
                        _warn_instrument_backend_once(
                            f"sfizz-silent:{inst.name}:{sfz_path}",
                            f"{msg}; using {fallback_backend_name!r} fallback. Fix the SFZ choice or make "
                            f"{fallback_backend_name!r} this instrument's backend.",
                        )
                    else:
                        rendered.append(sfizz_audio)
                        continue
            elif wants_sfizz or _instrument_prefers_sfizz(inst_backend):
                requested = inst_backend.get("library_ref") or inst_backend.get("library") or inst_backend.get("sfz") or sfizz_cfg.get("default_sfz")
                if (wants_sfizz and not _is_optional_instrument_backend(inst_backend)) or strict_backends:
                    raise FileNotFoundError(
                        f"instrument {inst.name!r} requested SFZ library {requested!r}, but no matching .sfz was "
                        f"found (backend={backend!r}); set render.sfizz.default_sfz or "
                        f"instrument_backend.sfz/library_ref, or disable render.strict_backends"
                    )
                _warn_instrument_backend_once(
                    f"sfz-not-found:{inst.name}:{requested}",
                    f"instrument {inst.name!r} requested SFZ library {requested!r}, but no matching .sfz was found; "
                    f"using {fallback_backend_name!r} fallback.",
                )

            midi_path = tempdir / f"group_{group}.{idx}.{inst.name}.mid"
            dry_wav = tempdir / f"group_{group}.{idx}.{inst.name}.dry.wav"
            if fallback_backend_name != "fallback":
                inst_pm.write(str(midi_path))
            inst_audio = render_synth_audio(
                inst_pm,
                fallback_backend_name,
                soundfont,
                sample_rate,
                midi_path,
                dry_wav,
                minimum_duration,
            )
            # Last-resort guard: even the fallback can render silence if a GM
            # program is absent from the soundfont. Never drop a noted stem quietly.
            if _instrument_has_notes(inst_pm) and _is_effectively_silent(inst_audio):
                msg = (
                    f"instrument {inst.name!r} rendered SILENCE despite active notes via "
                    f"{fallback_backend_name!r} backend (check program/soundfont coverage)"
                )
                if strict_backends:
                    raise RuntimeError(msg)
                _warn_instrument_backend_once(f"instrument-silent:{inst.name}", msg)
            rendered.append(inst_audio)
        if not rendered:
            return np.zeros((max(1, int(sample_rate * minimum_duration)), 2), dtype=np.float32)
        max_len = max(len(x) for x in rendered)
        out = np.zeros((max_len, 2), dtype=np.float32)
        for x in rendered:
            out[: len(x), :] += coerce_stereo(x)
        return out.astype(np.float32)

    sub_pm = copy_with_instruments(pm, insts, bpm)
    midi_path = tempdir / f"group_{group}.mid"
    dry_wav = tempdir / f"group_{group}.dry.wav"
    # The built-in fallback renderer consumes PrettyMIDI objects directly. Avoid
    # serializing stem MIDI unless an external backend actually needs it; this
    # keeps adaptive section x stem export snappy and avoids rare pretty_midi
    # writer stalls on sparse/empty instrument groups.
    if backend != "fallback":
        sub_pm.write(str(midi_path))
    return render_synth_audio(
        sub_pm, backend, soundfont, sample_rate, midi_path, dry_wav, minimum_duration
    )


def build_manifest(
    spec: dict[str, Any],
    cue_hash: str,
    section_meta: list[dict[str, Any]],
    group_names: list[str],
    output_files: dict[str, Any],
    sample_rate: int,
) -> dict[str, Any]:
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    return {
        "schema": "ambition.adaptive_music_manifest.v2",
        "renderer_version": RENDERER_VERSION,
        "id": spec["id"],
        "title": spec.get("title", spec["id"]),
        "hash": cue_hash,
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "sample_rate": sample_rate,
        "stems": group_names,
        "sections": section_meta,
        "files": output_files,
        "playback": spec.get("playback", {}),
        "state_map": spec.get("state_map", {}),
        "notes": spec.get("notes", ""),
    }




SECTION_FULL_MASTERING_MODES = ("section_postprocess", "global_master_slices")


def adaptive_section_mastering_config(spec: dict[str, Any]) -> dict[str, Any]:
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


def render_all(args) -> dict[str, Any]:
    spec_path = Path(args.spec).resolve()
    spec = load_yaml(spec_path)
    render_cfg = spec.get("render", {})
    sample_rate = int(render_cfg.get("sample_rate", 48000))
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    output_root = Path(args.outdir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    soundfont = choose_soundfont(args.soundfont or render_cfg.get("soundfont"))
    backend = args.backend or render_cfg.get("backend", "auto")
    cue_hash = spec_hash(spec_path, soundfont, backend)
    quality = float(render_cfg.get("ogg_quality", 5.0))
    pm, groups, section_meta = build_score(spec)
    sanitize_same_pitch_overlaps(pm)
    total_seconds = (
        section_meta[-1]["end_seconds"] if section_meta else pm.get_end_time()
    )
    target_samples = int(math.ceil(total_seconds * sample_rate))
    group_names = sorted(set(groups.values()))
    output_files: dict[str, Any] = {"preview": {}, "adaptive": {}}

    with tempfile.TemporaryDirectory() as d:
        tempdir = Path(d)
        # Render stems first, apply stem/bus tone controls without normalizing
        # them upward, write adaptive stem pieces, and sum the exact processed
        # stems to build the full preview. This guarantees that bus EQ and stem
        # gains affect both adaptive playback and the full soundtrack preview.
        full_stem_sum = np.zeros((target_samples, 2), dtype=np.float32)
        stem_base_settings = copy.deepcopy(spec.get("stem_postprocess", {}))
        group_post = spec.get("group_postprocess", {}) or {}
        for group in group_names:
            if getattr(args, "verbose", False):
                print(f"[render] stem {group}", flush=True)
            group_raw = render_group_audio(
                pm,
                groups,
                group,
                backend,
                soundfont,
                sample_rate,
                tempdir,
                total_seconds,
                bpm,
                base_dir=spec_path.parent,
                render_cfg=render_cfg,
            )
            group_raw = ensure_audio_length(group_raw, target_samples)
            group_settings = copy.deepcopy(stem_base_settings)
            group_settings.update(group_post.get(group, {}))
            # Stems should preserve authored relative gain. The default is no
            # upward normalization unless YAML explicitly asks for it.
            group_settings.setdefault("normalize", False)
            group_settings.setdefault("target_peak_db", -2.5)
            if getattr(args, "verbose", False):
                print(f"[post] stem {group} settings={group_settings}", flush=True)
            import time as _time

            _t0 = _time.time()
            group_audio = post_process(group_raw, sample_rate, group_settings, base_dir=spec_path.parent)
            if getattr(args, "verbose", False):
                print(
                    f"[post-done] stem {group} elapsed={_time.time() - _t0:.2f}s shape={group_audio.shape}",
                    flush=True,
                )
            _t0 = _time.time()
            full_stem_sum += ensure_audio_length(group_audio, target_samples)
            if getattr(args, "verbose", False):
                print(
                    f"[sum-done] stem {group} elapsed={_time.time() - _t0:.2f}s",
                    flush=True,
                )
            for meta in section_meta:
                piece = slice_audio(
                    group_audio, sample_rate, meta["start_seconds"], meta["end_seconds"]
                )
                path = (
                    output_root
                    / "adaptive"
                    / meta["id"]
                    / f"{spec['id']}_{cue_hash}.{meta['id']}.{group}.ogg"
                )
                if getattr(args, "verbose", False):
                    print(f"[write] stem {group} section {meta['id']}", flush=True)
                _t0 = _time.time()
                write_ogg_from_audio(
                    piece, sample_rate, path, quality=quality, keep_wav=args.keep_wav
                )
                if getattr(args, "verbose", False):
                    print(
                        f"[write-done] stem {group} section {meta['id']} elapsed={_time.time() - _t0:.2f}s",
                        flush=True,
                    )
                output_files["adaptive"].setdefault(meta["id"], {})[group] = str(
                    path.relative_to(output_root)
                )
            del group_raw, group_audio
            gc.collect()

        if getattr(args, "verbose", False):
            print("[post] master from processed stems", flush=True)
        full_audio = post_process(
            full_stem_sum, sample_rate, spec.get("postprocess", {}), base_dir=spec_path.parent
        )
        preview_path = (
            output_root
            / "preview"
            / f"{spec['id']}_{cue_hash}.full_soundtrack_preview.ogg"
        )
        if getattr(args, "verbose", False):
            print("[write] preview", flush=True)
        write_ogg_from_audio(
            full_audio,
            sample_rate,
            preview_path,
            quality=quality,
            keep_wav=args.keep_wav,
        )
        output_files["preview"]["full_soundtrack"] = str(
            preview_path.relative_to(output_root)
        )

        # Full section renders. Prefer global-master slices for adaptive full
        # sections when requested; legacy render_all has no section-local full
        # postprocess path, so both modes slice the mastered stem sum.
        section_mastering = adaptive_section_mastering_config(spec)
        ignored_section_postprocess = []
        if section_mastering["mode"] == "global_master_slices":
            sections_by_id = {s0.get("id"): s0 for s0 in spec.get("sections", [])}
            ignored_section_postprocess = [
                str(meta["id"])
                for meta in section_meta
                if isinstance(sections_by_id.get(meta["id"], {}), dict)
                and sections_by_id.get(meta["id"], {}).get("postprocess")
            ]
        for meta in section_meta:
            section_dir = output_root / "adaptive" / meta["id"]
            section_dir.mkdir(parents=True, exist_ok=True)
            piece = slice_audio(
                full_audio, sample_rate, meta["start_seconds"], meta["end_seconds"]
            )
            path = section_dir / f"{spec['id']}_{cue_hash}.{meta['id']}.full.ogg"
            if getattr(args, "verbose", False):
                print(f"[write] section full {meta['id']}", flush=True)
            write_ogg_from_audio(
                piece, sample_rate, path, quality=quality, keep_wav=args.keep_wav
            )
            output_files["adaptive"].setdefault(meta["id"], {})["full"] = str(
                path.relative_to(output_root)
            )

        if args.keep_midi:
            midi_out = output_root / "debug" / f"{spec['id']}_{cue_hash}.mid"
            midi_out.parent.mkdir(parents=True, exist_ok=True)
            pm.write(str(midi_out))
            output_files["debug_midi"] = str(midi_out.relative_to(output_root))

    manifest = build_manifest(
        spec, cue_hash, section_meta, group_names, output_files, sample_rate
    )
    manifest.setdefault("diagnostics", {})["adaptive_section_mastering"] = {
        **adaptive_section_mastering_config(spec),
        "ignored_section_postprocess_sections": locals().get("ignored_section_postprocess", []),
    }
    manifest_path = output_root / f"{spec['id']}_{cue_hash}.adaptive_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf8")
    return {
        "manifest": str(manifest_path),
        "preview": str(preview_path),
        "hash": cue_hash,
    }


