"""Optional SFZ rendering through sfizz command-line or VST3 backends."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import mido
import numpy as np
import pretty_midi
import soundfile as sf
from scipy import signal


def _coerce_stereo(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim == 1:
        x = np.column_stack([x, x])
    # Pedalboard returns channel-first audio; SoundFile returns sample-first.
    if x.ndim == 2 and x.shape[0] in (1, 2) and x.shape[1] > x.shape[0]:
        x = x.T
    if x.shape[1] == 1:
        x = np.column_stack([x[:, 0], x[:, 0]])
    if x.shape[1] > 2:
        x = x[:, :2]
    return x.astype(np.float32, copy=False)


def resolve_path(path: str | Path, *, base_dir: Path | None = None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    return p.resolve()


def _format_command(template: str | list[str], mapping: dict[str, str]) -> list[str]:
    if isinstance(template, str):
        parts = shlex.split(template)
    else:
        parts = [str(x) for x in template]
    return [part.format(**mapping) for part in parts]


def _render_sfizz_cli(
    pm: pretty_midi.PrettyMIDI,
    *,
    sfz: Path,
    sample_rate: int,
    tempdir: Path,
    output_name: str,
    minimum_duration: float,
    settings: dict[str, Any],
) -> np.ndarray:
    binary = str(settings.get("binary", "sfizz_render"))
    if not shutil.which(binary):
        raise FileNotFoundError(
            f"{binary!r} not found. Install sfizz_render or choose another backend."
        )
    midi_path = tempdir / f"{output_name}.sfizz.mid"
    wav_path = tempdir / f"{output_name}.sfizz.wav"
    pm.write(str(midi_path))
    mapping = {
        "binary": binary,
        "sfz": str(sfz),
        "midi": str(midi_path),
        "wav": str(wav_path),
        "sample_rate": str(int(sample_rate)),
    }
    template = settings.get("command")
    if template:
        cmd = _format_command(template, mapping)
    else:
        # sfizz_render's CLI has changed across builds.  This is the documented
        # long-option form for recent versions; use command override if needed.
        cmd = [
            binary,
            "--sfz",
            str(sfz),
            "--midi",
            str(midi_path),
            "--wav",
            str(wav_path),
            "--sample-rate",
            str(int(sample_rate)),
        ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    if sr != int(sample_rate):
        audio = signal.resample_poly(audio, int(sample_rate), int(sr), axis=0).astype(np.float32)
    if minimum_duration > 0:
        target = int(round(float(minimum_duration) * int(sample_rate)))
        if len(audio) < target:
            audio = np.pad(audio, ((0, target - len(audio)), (0, 0)))
    return _coerce_stereo(audio)


def _midi_messages_for_pedalboard(pm: pretty_midi.PrettyMIDI) -> list[mido.Message]:
    messages: list[mido.Message] = []
    for inst in pm.instruments:
        channel = 9 if inst.is_drum else 0
        for cc in getattr(inst, "control_changes", []):
            messages.append(
                mido.Message(
                    "control_change",
                    control=int(cc.number),
                    value=max(0, min(127, int(cc.value))),
                    channel=channel,
                    time=float(cc.time),
                )
            )
        for bend in getattr(inst, "pitch_bends", []):
            messages.append(
                mido.Message(
                    "pitchwheel",
                    pitch=max(-8192, min(8191, int(bend.pitch))),
                    channel=channel,
                    time=float(bend.time),
                )
            )
        for note in inst.notes:
            velocity = max(1, min(127, int(note.velocity)))
            messages.append(
                mido.Message(
                    "note_on",
                    note=max(0, min(127, int(note.pitch))),
                    velocity=velocity,
                    channel=channel,
                    time=float(note.start),
                )
            )
            messages.append(
                mido.Message(
                    "note_off",
                    note=max(0, min(127, int(note.pitch))),
                    velocity=0,
                    channel=channel,
                    time=float(note.end),
                )
            )
    # Place note_on before note_off at the same timestamp to avoid zero-length
    # cancellations when repeated notes abut exactly.
    return sorted(messages, key=lambda msg: (float(msg.time), 0 if msg.type == "note_on" else 1))


def _set_plugin_parameter(plugin: Any, key: str, value: Any) -> bool:
    try:
        setattr(plugin, key, value)
        return True
    except Exception:
        pass
    params = getattr(plugin, "parameters", {}) or {}
    if key not in params:
        return False
    param = params[key]
    for attr in ("raw_value", "value"):
        try:
            setattr(param, attr, value)
            return True
        except Exception:
            pass
    try:
        params[key] = value
        return True
    except Exception:
        return False


def _find_sfz_parameter_key(plugin: Any, candidates: list[str]) -> str | None:
    params = getattr(plugin, "parameters", {}) or {}
    exact = [str(c) for c in candidates]
    for key in exact:
        if key in params:
            return key
    lowered_candidates = [key.lower() for key in exact]
    for key in params:
        norm = str(key).lower().replace("_", " ").replace("-", " ")
        if any(candidate.lower().replace("_", " ") in norm for candidate in lowered_candidates):
            return str(key)
    for key in params:
        norm = str(key).lower()
        if "sfz" in norm or "file" in norm or "path" in norm:
            return str(key)
    return None


def _render_sfizz_vst3(
    pm: pretty_midi.PrettyMIDI,
    *,
    sfz: Path,
    sample_rate: int,
    minimum_duration: float,
    settings: dict[str, Any],
) -> np.ndarray:
    try:
        import pedalboard as pb  # type: ignore
    except Exception as ex:  # pragma: no cover - environment dependent
        raise RuntimeError("pedalboard is required for sfizz VST3 rendering") from ex

    from ..audio_plugins import resolve_vst3_reference

    plugin_ref = settings.get("vst3_plugin") or settings.get("plugin") or settings.get("path") or "sfizz"
    plugin_path = resolve_vst3_reference(str(plugin_ref))
    if plugin_path is None:
        raise FileNotFoundError(f"sfizz VST3 plugin not found: {plugin_ref}")
    parameter_values = dict(settings.get("parameters") or {})
    plugin_name = settings.get("plugin_name")
    plugin = pb.load_plugin(
        str(plugin_path),
        parameter_values=parameter_values,
        plugin_name=str(plugin_name) if plugin_name else None,
        initialization_timeout=float(settings.get("initialization_timeout", 15.0)),
    )
    if not getattr(plugin, "is_instrument", False):
        raise RuntimeError(f"VST3 plugin is not an instrument: {plugin_path}")
    sfz_key = settings.get("sfz_parameter")
    candidates = list(settings.get("sfz_parameter_candidates") or [])
    candidates.extend(["sfz_file", "sfz", "file", "path", "instrument", "sample_file"])
    if sfz_key is None:
        sfz_key = _find_sfz_parameter_key(plugin, [str(item) for item in candidates])
    if sfz_key is None or not _set_plugin_parameter(plugin, str(sfz_key), str(sfz)):
        raise RuntimeError(
            "could not set an SFZ file parameter on the sfizz VST3 plugin; "
            "install sfizz_render or specify instrument_backend.settings.sfz_parameter"
        )
    duration = max(float(minimum_duration), float(pm.get_end_time()) + float(settings.get("tail_seconds", 2.0)))
    audio = plugin(
        _midi_messages_for_pedalboard(pm),
        duration=duration,
        sample_rate=int(sample_rate),
        num_channels=int(settings.get("num_channels", 2)),
        buffer_size=int(settings.get("buffer_size", 8192)),
        reset=True,
    )
    return _coerce_stereo(audio)


def render_sfizz(
    pm: pretty_midi.PrettyMIDI,
    *,
    sfz_path: str | Path,
    sample_rate: int,
    tempdir: Path,
    output_name: str,
    minimum_duration: float = 0.0,
    base_dir: Path | None = None,
    settings: dict[str, Any] | None = None,
) -> np.ndarray:
    """Render a PrettyMIDI object using an SFZ file.

    Default mode uses the external ``sfizz_render`` command.  ``renderer: auto``
    falls back to the sfizz VST3 instrument when ``sfizz_render`` is absent and
    Pedalboard can load ``sfizz.vst3``.  YAML may still override the command via
    ``render.sfizz.command`` or ``instrument_backend.settings.command``.
    """
    settings = settings or {}
    sfz = resolve_path(sfz_path, base_dir=base_dir)
    if not sfz.exists():
        raise FileNotFoundError(f"SFZ instrument does not exist: {sfz}")
    renderer = str(settings.get("renderer", "auto")).lower().strip()
    binary = str(settings.get("binary", "sfizz_render"))
    if renderer in {"cli", "sfizz_render", "command"}:
        return _render_sfizz_cli(
            pm,
            sfz=sfz,
            sample_rate=sample_rate,
            tempdir=tempdir,
            output_name=output_name,
            minimum_duration=minimum_duration,
            settings=settings,
        )
    if renderer in {"vst3", "pedalboard", "sfizz_vst3"}:
        return _render_sfizz_vst3(
            pm,
            sfz=sfz,
            sample_rate=sample_rate,
            minimum_duration=minimum_duration,
            settings=settings,
        )
    if renderer == "auto" and not shutil.which(binary):
        return _render_sfizz_vst3(
            pm,
            sfz=sfz,
            sample_rate=sample_rate,
            minimum_duration=minimum_duration,
            settings=settings,
        )
    return _render_sfizz_cli(
        pm,
        sfz=sfz,
        sample_rate=sample_rate,
        tempdir=tempdir,
        output_name=output_name,
        minimum_duration=minimum_duration,
        settings=settings,
    )
