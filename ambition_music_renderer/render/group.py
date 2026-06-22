"""Group/stem rendering and manifest construction for MusicIR renders."""

from __future__ import annotations

from . import score as _score
from . import synth as _synth
from . import effects as _effects
from . import export as _export

globals().update({k: v for k, v in vars(_score).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_synth).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_effects).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_export).items() if not k.startswith("__")})

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
        str(instrument_backend_spec(instrument_specs, inst.name).get("kind", "")).lower() in {"sfz", "sfizz"}
        or bool(instrument_backend_spec(instrument_specs, inst.name).get("sfz"))
        for inst in insts
    )
    if wants_sfizz or has_instrument_sfizz:
        from ..backends.sfizz_backend import render_sfizz

        fallback_backend_name = str(sfizz_cfg.get("fallback_backend", render_cfg.get("sfizz_fallback_backend", "auto")))
        rendered: list[np.ndarray] = []
        for idx, inst in enumerate(insts):
            inst_backend = instrument_backend_spec(instrument_specs, inst.name)
            sfz_path = inst_backend.get("sfz") or sfizz_cfg.get("default_sfz")
            inst_pm = copy_with_instruments(pm, [inst], bpm)
            if sfz_path:
                settings = dict(sfizz_cfg)
                settings.update(dict(inst_backend.get("settings") or {}))
                if "command" in inst_backend:
                    settings["command"] = inst_backend["command"]
                if "binary" in inst_backend:
                    settings["binary"] = inst_backend["binary"]
                rendered.append(
                    render_sfizz(
                        inst_pm,
                        sfz_path=sfz_path,
                        sample_rate=sample_rate,
                        tempdir=tempdir,
                        output_name=f"group_{group}.{idx}.{inst.name}",
                        minimum_duration=minimum_duration,
                        base_dir=base_dir,
                        settings=settings,
                    )
                )
            elif wants_sfizz:
                raise FileNotFoundError(
                    f"backend={backend!r} requires render.sfizz.default_sfz or instrument {inst.name!r} instrument_backend.sfz"
                )
            else:
                midi_path = tempdir / f"group_{group}.{idx}.{inst.name}.mid"
                dry_wav = tempdir / f"group_{group}.{idx}.{inst.name}.dry.wav"
                if fallback_backend_name != "fallback":
                    inst_pm.write(str(midi_path))
                rendered.append(
                    render_synth_audio(
                        inst_pm,
                        fallback_backend_name,
                        soundfont,
                        sample_rate,
                        midi_path,
                        dry_wav,
                        minimum_duration,
                    )
                )
        if not rendered:
            return np.zeros((max(1, int(sample_rate * minimum_duration)), 2), dtype=np.float32)
        max_len = max(len(x) for x in rendered)
        out = np.zeros((max_len, 2), dtype=np.float32)
        for x in rendered:
            out[: len(x), :] += _coerce_stereo(x)
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


