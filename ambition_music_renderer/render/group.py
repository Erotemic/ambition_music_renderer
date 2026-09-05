"""Group/stem rendering and manifest construction for MusicIR renders."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi

from ..profiler import profile
from ..instrument_resolution import (
    backend_prefers_procedural_fm,
    backend_prefers_sfizz,
    instrument_backend_spec,
    resolve_instrument_backend,
)
from ..audio_utils import coerce_stereo
from .backend_notes import apply_backend_note_remap
from .score_core import RENDERER_VERSION
from .synth import render_procedural_fm, render_synth_audio
from .foreground_protection import (
    apply_instrument_foreground_protection,
    foreground_protection_mode,
)

@profile
def copy_with_instruments(
    pm: pretty_midi.PrettyMIDI, instruments: list[pretty_midi.Instrument], bpm: float
) -> pretty_midi.PrettyMIDI:
    # Preserve the source score resolution when making per-group/per-instrument
    # render copies.  Falling back to PrettyMIDI's default 220 PPQ silently
    # re-quantizes absolute note and controller times whenever a backend (such
    # as sfizz_render) serializes the copy to MIDI.  Exact-score inputs commonly
    # use a much finer PPQ specifically to retain expressive timing.
    new_pm = pretty_midi.PrettyMIDI(initial_tempo=bpm, resolution=pm.resolution)
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


_WARNED_INSTRUMENT_BACKENDS: set[str] = set()


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


def _instrument_mix_gain_db(instrument_specs: dict[str, Any], inst_name: str) -> float:
    """Return post-synthesis mix trim for one instrument.

    MIDI velocity/CC7/CC11 are performance controls and may affect a sampled
    instrument's timbre as well as its amplitude.  ``mix_gain_db`` is a separate
    audio-domain calibration control used after synthesis so sample-library
    balance does not have to be encoded by distorting performance dynamics.
    """
    spec = instrument_specs.get(inst_name, {}) or {}
    return float(spec.get("mix_gain_db", 0.0))


def _apply_instrument_mix_gain(audio: np.ndarray, gain_db: float) -> np.ndarray:
    if abs(gain_db) < 1e-9:
        return audio.astype(np.float32, copy=False)
    return (audio * (10.0 ** (gain_db / 20.0))).astype(np.float32, copy=False)


def _finalize_instrument_mix_audio(
    audio: np.ndarray,
    *,
    mix_gain_db: float,
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    protection_spec: dict[str, Any],
    instrument_name: str,
    sample_rate: int,
) -> np.ndarray:
    audio = _apply_instrument_mix_gain(audio, mix_gain_db)
    return apply_instrument_foreground_protection(
        audio,
        pm,
        groups,
        protection_spec,
        instrument_name,
        sample_rate,
    )


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
    instrument_specs: dict[str, Any] | None = None,
) -> np.ndarray:
    insts = [inst for inst in pm.instruments if groups.get(inst.name) == group]
    render_cfg = render_cfg or {}
    if instrument_specs is None:
        # Compatibility path for callers that have not migrated to CompiledScore.
        instrument_specs = getattr(pm, "_ambition_instrument_specs", {}) or {}
    sfizz_cfg = dict(render_cfg.get("sfizz") or {})
    protection_spec = {
        "render": render_cfg,
        "instruments": list(instrument_specs.values()),
    }

    wants_sfizz = backend in {"sfizz", "sfizz-render"}
    has_instrument_sfizz = any(
        backend_prefers_sfizz(instrument_backend_spec(instrument_specs, inst.name))
        for inst in insts
    )
    has_instrument_procedural_fm = any(
        backend_prefers_procedural_fm(instrument_backend_spec(instrument_specs, inst.name))
        for inst in insts
    )
    has_instrument_mix_gain = any(
        abs(_instrument_mix_gain_db(instrument_specs, inst.name)) > 1e-9
        for inst in insts
    )
    protection_cfg = dict(render_cfg.get("foreground_protection") or {})
    configured_protection_groups = protection_cfg.get("groups")
    protected_group = (
        not configured_protection_groups or group in {str(item) for item in configured_protection_groups}
    )
    has_instrument_register_protection = (
        bool(protection_cfg.get("enabled", False))
        and foreground_protection_mode(protection_spec) in {"instrument_register", "register", "desk_register"}
        and protected_group
    )
    if (
        wants_sfizz
        or has_instrument_sfizz
        or has_instrument_procedural_fm
        or has_instrument_mix_gain
        or has_instrument_register_protection
    ):
        from ..backends.sfizz_backend import render_sfizz

        default_fallback_backend = str(
            sfizz_cfg.get(
                "fallback_backend",
                render_cfg.get(
                    "sfizz_fallback_backend",
                    "auto" if wants_sfizz or has_instrument_sfizz else backend,
                ),
            )
        )
        # Strict mode (render.strict_backends) turns every backend failure /
        # silent render into a hard error instead of warn-and-fallback. The
        # default is forgiving so one bad SFZ never silently drops a whole stem,
        # but it always warns loudly so the author can fix the SFZ or make the
        # fallback that instrument's real backend.
        strict_backends = bool(render_cfg.get("strict_backends", render_cfg.get("strict_instruments", False)))
        rendered: list[np.ndarray] = []
        for idx, inst in enumerate(insts):
            inst_backend = instrument_backend_spec(instrument_specs, inst.name)
            mix_gain_db = _instrument_mix_gain_db(instrument_specs, inst.name)
            plan = resolve_instrument_backend(
                inst_backend,
                base_dir=base_dir,
                sfizz_cfg=sfizz_cfg,
                default_fallback_backend=default_fallback_backend,
                force_sfz=wants_sfizz,
            )
            allow_fallback = plan.optional and not strict_backends
            fallback_backend_name = str(plan.fallback_backend or default_fallback_backend)
            inst_pm = copy_with_instruments(pm, [inst], bpm)
            if plan.wants_procedural_fm:
                rendered.append(
                    _finalize_instrument_mix_audio(
                        render_procedural_fm(
                            inst_pm,
                            inst_backend,
                            sample_rate,
                            minimum_duration,
                        ),
                        mix_gain_db=mix_gain_db,
                        pm=pm,
                        groups=groups,
                        protection_spec=protection_spec,
                        instrument_name=inst.name,
                        sample_rate=sample_rate,
                    )
                )
                continue
            sfz_path = plan.resolved_sfz
            if sfz_path is not None:
                sfz_pm = copy_with_instruments(pm, [inst], bpm)
                apply_backend_note_remap(sfz_pm, inst_backend)
                settings = dict(plan.sfizz_settings)
                try:
                    sfizz_audio = render_sfizz(
                        sfz_pm,
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
                    if _instrument_has_notes(sfz_pm) and _is_effectively_silent(sfizz_audio):
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
                        rendered.append(
                            _finalize_instrument_mix_audio(
                                sfizz_audio,
                                mix_gain_db=mix_gain_db,
                                pm=pm,
                                groups=groups,
                                protection_spec=protection_spec,
                                instrument_name=inst.name,
                                sample_rate=sample_rate,
                            )
                        )
                        continue
            elif plan.wants_sfz:
                requested = plan.requested
                if (wants_sfizz and not plan.optional) or strict_backends:
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
            rendered.append(
                _finalize_instrument_mix_audio(
                    inst_audio,
                    mix_gain_db=mix_gain_db,
                    pm=pm,
                    groups=groups,
                    protection_spec=protection_spec,
                    instrument_name=inst.name,
                    sample_rate=sample_rate,
                )
            )
        if not rendered:
            return np.zeros((max(1, int(sample_rate * minimum_duration)), 2), dtype=np.float32)
        # Normalize layout BEFORE any length math. `coerce_stereo` accepts
        # channel-first buffers and transposes them, so `len(x)` on a raw stem
        # can be the CHANNEL count, not the sample count — mixing the two
        # layouts sized `out` from one and added the other, and a single
        # channel-first stem took down the whole cue.
        stereo = [coerce_stereo(x) for x in rendered]
        max_len = max(len(x) for x in stereo)
        out = np.zeros((max_len, 2), dtype=np.float32)
        for x in stereo:
            out[: len(x), :] += x
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
    *,
    compiled_score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    manifest = {
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
    if compiled_score is not None:
        manifest["compiled_score"] = dict(compiled_score)
    return manifest
