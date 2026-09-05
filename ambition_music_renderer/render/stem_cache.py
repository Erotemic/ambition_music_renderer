"""Content-addressed cache keys for rendered stem-group audio.

The full cue hash intentionally changes for every score edit. Composition A/B
work benefits from a narrower identity: if one expanded stem group has exactly
the same MIDI events and render settings as a previous variant, its synthesized
and postprocessed scratch audio can be reused while the edited groups render.

Keys are built from expanded PrettyMIDI events, not from source YAML fragments.
That is important because score-wide deterministic humanization can make a
seemingly unrelated source edit perturb later event timing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi

from .score_core import RENDERER_VERSION

_REGISTER_PROTECTION_MODES = {"instrument_register", "register", "desk_register"}


def _event_payload(inst: pretty_midi.Instrument) -> dict[str, Any]:
    """Return the audio-relevant expanded MIDI state for one instrument."""
    return {
        "name": str(inst.name),
        "program": int(inst.program),
        "is_drum": bool(inst.is_drum),
        "notes": [
            [float(note.start), float(note.end), int(note.pitch), int(note.velocity)]
            for note in inst.notes
        ],
        "control_changes": [
            [float(cc.time), int(cc.number), int(cc.value)]
            for cc in inst.control_changes
        ],
        "pitch_bends": [
            [float(pb.time), int(pb.pitch)]
            for pb in inst.pitch_bends
        ],
    }


def _file_identity(path: str | Path) -> dict[str, Any]:
    """Return path plus cheap content-change identity for one local render input."""
    resolved = Path(path).expanduser()
    payload: dict[str, Any] = {"path": str(resolved)}
    try:
        stat = resolved.stat()
    except OSError:
        return payload
    payload.update({"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)})
    return payload


def _resolved_sfz_identities(
    instrument_specs: dict[str, Any],
    instrument_names: list[str],
    *,
    base_dir: Path,
    render_cfg: dict[str, Any],
) -> dict[str, dict[str, Any] | None]:
    """Record the exact SFZ file each cached instrument would resolve today."""
    # Keep renderer resolution authoritative. A library_ref can choose a different
    # file after an audio-library install/update even when the score text is
    # unchanged, and that must invalidate a cached stem. Import locally to avoid
    # making the lightweight cache module part of group.py's import surface.
    from .group import _resolve_instrument_sfz, instrument_backend_spec

    sfizz_cfg = dict(render_cfg.get("sfizz") or {})
    out: dict[str, dict[str, Any] | None] = {}
    for name in instrument_names:
        inst_backend = instrument_backend_spec(instrument_specs, name)
        resolved = _resolve_instrument_sfz(
            inst_backend, base_dir=base_dir, sfizz_cfg=sfizz_cfg
        )
        out[name] = _file_identity(resolved) if resolved is not None else None
    return out


def stem_cache_key(
    *,
    spec: dict[str, Any],
    spec_path: Path,
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    group: str,
    backend: str,
    soundfont: str,
    sample_rate: int,
    bpm: float,
    total_seconds: float,
) -> str:
    """Return a stable content key for one postprocessed scratch stem.

    The key is intentionally conservative. Global render settings invalidate all
    groups. Instrument-register foreground protection also makes one group's
    audio depend on other groups, so that mode includes the complete expanded
    score event payload. In the common independent-stem path, only instruments
    assigned to ``group`` contribute event/backend state.
    """
    instrument_specs = getattr(pm, "_ambition_instrument_specs", {}) or {}
    render_cfg = dict(spec.get("render") or {})
    protection_cfg = dict(render_cfg.get("foreground_protection") or {})
    protection_mode = str(protection_cfg.get("mode", "group_density")).strip().lower().replace("-", "_")
    register_coupled = bool(protection_cfg.get("enabled", False)) and protection_mode in _REGISTER_PROTECTION_MODES

    group_instruments = [inst for inst in pm.instruments if groups.get(inst.name) == group]
    if register_coupled:
        event_instruments = list(pm.instruments)
        backend_specs = dict(instrument_specs)
        group_map = dict(groups)
    else:
        event_instruments = group_instruments
        backend_specs = {
            str(inst.name): instrument_specs.get(inst.name)
            for inst in group_instruments
        }
        group_map = {str(inst.name): str(group) for inst in group_instruments}

    relevant_names = [str(inst.name) for inst in event_instruments]
    resolved_sfz = _resolved_sfz_identities(
        instrument_specs,
        relevant_names,
        base_dir=Path(spec_path).resolve().parent,
        render_cfg=render_cfg,
    )

    payload = {
        "schema": "ambition.stem_cache_key.v1",
        "renderer_version": RENDERER_VERSION,
        "group": str(group),
        "backend": str(backend),
        "soundfont": _file_identity(str(soundfont)),
        "sample_rate": int(sample_rate),
        "bpm": float(bpm),
        "total_seconds": float(total_seconds),
        "midi_resolution": int(pm.resolution),
        "spec_base_dir": str(Path(spec_path).resolve().parent),
        "audio_tools_root": os.environ.get("AMBITION_AUDIO_TOOLS_ROOT"),
        "render": render_cfg,
        "stem_postprocess": dict(spec.get("stem_postprocess") or {}),
        "group_postprocess": dict((spec.get("group_postprocess") or {}).get(group, {}) or {}),
        "instrument_specs": backend_specs,
        "resolved_sfz": resolved_sfz,
        "groups": group_map,
        "events": [_event_payload(inst) for inst in event_instruments],
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf8")).hexdigest()[:24]


def stem_cache_path(cache_dir: Path, cue_id: str, group: str, cache_key: str) -> Path:
    """Return the cache filename for one group/key."""
    safe_group = str(group).replace("/", "_")
    safe_cue = str(cue_id).replace("/", "_")
    return Path(cache_dir) / safe_cue / safe_group / f"{cache_key}.npy"


def restore_cached_stem(source: Path, target: Path, *, expected_samples: int) -> bool:
    """Link/copy one valid cached stereo stem into the current scratch area."""
    try:
        cached = np.load(source, mmap_mode="r")
        valid = (
            cached.ndim == 2
            and cached.shape[0] == int(expected_samples)
            and cached.shape[1] == 2
        )
    except (OSError, ValueError):
        return False
    if not valid:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    return True


def store_cached_stem(source: Path, target: Path) -> None:
    """Atomically populate a persistent cache entry from one scratch stem."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        shutil.copy2(source, temp)
        os.replace(temp, target)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
