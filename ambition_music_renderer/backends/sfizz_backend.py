"""Optional SFZ rendering through sfizz command-line or VST3 backends."""

from __future__ import annotations

import logging
import re
import shlex
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import mido
import numpy as np
from ..audio_utils import coerce_stereo
import pretty_midi
import soundfile as sf
from scipy import signal

log = logging.getLogger("ambition_music_renderer.sfizz")

_NOTE_RE = re.compile(r"^([a-gA-G])([#b]?)(-?\d+)$")
_KEY_OPCODE_RE = re.compile(r"\b(lokey|hikey|key|pitch_keycenter)\s*=\s*([A-Ga-g#b\-0-9]+)")


def _note_to_midi(tok: str) -> int | None:
    """Parse an SFZ key value (a MIDI number or a note name like 'c3'/'f#2')."""
    tok = tok.strip()
    if not tok:
        return None
    if tok.lstrip("-").isdigit():
        return int(tok)
    m = _NOTE_RE.match(tok)
    if not m:
        return None
    step = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}[m.group(1).lower()]
    step += {"#": 1, "b": -1, "": 0}[m.group(2)]
    # SFZ/sfizz convention: c4 == MIDI 60 (so octave offset is +1).
    return step + (int(m.group(3)) + 1) * 12


@lru_cache(maxsize=64)
def sfz_key_span(sfz_path: str) -> tuple[int, int] | None:
    """The lowest..highest playable key across an SFZ's regions.

    Parsed leniently from the raw text (lokey/hikey/key/pitch_keycenter on any
    line, including ``#include`` bodies we can read).  Returns None if nothing
    parseable is found, so callers can skip range handling.
    """
    try:
        text = Path(sfz_path).read_text(errors="ignore")
    except OSError:
        return None
    base = Path(sfz_path).parent
    for inc in re.findall(r'#include\s+"([^"]+)"', text):
        try:
            text += "\n" + (base / inc.replace("\\", "/")).read_text(errors="ignore")
        except OSError:
            pass
    los: list[int] = []
    his: list[int] = []
    for op, val in _KEY_OPCODE_RE.findall(text):
        midi = _note_to_midi(val)
        if midi is None:
            continue
        if op in ("lokey", "key", "pitch_keycenter"):
            los.append(midi)
        if op in ("hikey", "key", "pitch_keycenter"):
            his.append(midi)
    if not los or not his:
        return None
    return (min(los), max(his))


def fold_pm_into_key_span(pm: pretty_midi.PrettyMIDI, span: tuple[int, int]) -> int:
    """Octave-fold notes that fall outside ``span`` back into it, in place.

    A sampled instrument only has samples across its real range; notes authored
    below the lowest string (or above the top) would otherwise drop to silence.
    Shifting them by whole octaves keeps the pitch class and the line intact —
    what a player does when a note is out of the instrument's reach.  Returns the
    number of notes shifted.
    """
    lo, hi = span
    if hi - lo < 11:  # too narrow to fold sensibly (e.g. a one-key percussion map)
        return 0
    shifted = 0
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for note in inst.notes:
            p = note.pitch
            while p < lo:
                p += 12
            while p > hi:
                p -= 12
            if p != note.pitch:
                note.pitch = p
                shifted += 1
    return shifted


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


def _short_process_text(value: bytes | str | None, *, limit: int = 1200) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf8", errors="replace")
    else:
        text = str(value)
    text = text.strip()
    if len(text) > limit:
        text = text[-limit:]
    return text


def _format_process_failure(cmd: list[str], proc: subprocess.CompletedProcess[str]) -> str:
    stderr = _short_process_text(proc.stderr)
    stdout = _short_process_text(proc.stdout)
    parts = [f"command exited {proc.returncode}: {shlex.join(cmd)}"]
    if stderr:
        parts.append(f"stderr: {stderr}")
    if stdout:
        parts.append(f"stdout: {stdout}")
    return "; ".join(parts)


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
    # Octave-fold notes that fall outside the SFZ's sampled key range, unless the
    # caller opts out. Sampled instruments only cover their real range, so an
    # authored sub-bass part (e.g. octave 1) would otherwise drop to silence on a
    # library whose lowest string is ~C2.
    if settings.get("fold_to_range", True):
        span = sfz_key_span(str(sfz))
        if span is not None:
            shifted = fold_pm_into_key_span(pm, span)
            if shifted:
                log.warning(
                    "%s: octave-folded %d note(s) into the SFZ range %s..%s (%s..%s); "
                    "the part was authored partly outside this sampled instrument's reach.",
                    output_name, shifted, span[0], span[1],
                    pretty_midi.note_number_to_name(span[0]),
                    pretty_midi.note_number_to_name(span[1]),
                )
    pm.write(str(midi_path))
    mapping = {
        "binary": binary,
        "sfz": str(sfz),
        "midi": str(midi_path),
        "wav": str(wav_path),
        "sample_rate": str(int(sample_rate)),
    }
    templates = []
    template = settings.get("command")
    if template:
        templates.append(template)
    else:
        # Try the modern long-option form first, then older positional forms.
        # Distro builds of sfizz_render have differed enough that a fallback
        # probe here is more reliable than asking score YAML to know the host.
        templates.extend([
            # Current distro builds accept named SFZ/MIDI/WAV options but do
            # not necessarily accept a sample-rate option.  Try this form
            # before older positional guesses so successful SFZ rendering does
            # not fall through to pretty-midi.
            [binary, "--sfz", "{sfz}", "--midi", "{midi}", "--wav", "{wav}"],
            [
                binary,
                "--sfz",
                "{sfz}",
                "--midi",
                "{midi}",
                "--wav",
                "{wav}",
                "--sample-rate",
                "{sample_rate}",
            ],
            [binary, "{sfz}", "{midi}", "{wav}"],
            [binary, "{sfz}", "{midi}", "{wav}", "{sample_rate}"],
        ])
    # A hung sfizz_render (e.g. a broken/pathological SFZ) must not run forever:
    # an orphaned one once wrote a ~100 GB WAV and filled the disk. Cap it; the
    # caller falls back to GM on failure. Override via settings/env if needed.
    import os
    timeout_s = float(settings.get("render_timeout_s",
                                   os.environ.get("AMBITION_SFIZZ_TIMEOUT_S", 120)))
    failures: list[str] = []
    for template_item in templates:
        cmd = _format_command(template_item, mapping)
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"timed out after {timeout_s:.0f}s: {shlex.join(cmd)}")
            continue
        if proc.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 0:
            break
        failures.append(_format_process_failure(cmd, proc))
    else:
        raise RuntimeError("sfizz_render failed. " + " | ".join(failures[-3:]))
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    if sr != int(sample_rate):
        audio = signal.resample_poly(audio, int(sample_rate), int(sr), axis=0).astype(np.float32)
    if minimum_duration > 0:
        target = int(round(float(minimum_duration) * int(sample_rate)))
        if len(audio) < target:
            audio = np.pad(audio, ((0, target - len(audio)), (0, 0)))
    return coerce_stereo(audio)


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
    plugin_name = settings.get("plugin_name", "sfizz")
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
    return coerce_stereo(audio)


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
    if renderer == "auto":
        if shutil.which(binary):
            try:
                return _render_sfizz_cli(
                    pm,
                    sfz=sfz,
                    sample_rate=sample_rate,
                    tempdir=tempdir,
                    output_name=output_name,
                    minimum_duration=minimum_duration,
                    settings=settings,
                )
            except Exception as cli_ex:
                try:
                    return _render_sfizz_vst3(
                        pm,
                        sfz=sfz,
                        sample_rate=sample_rate,
                        minimum_duration=minimum_duration,
                        settings=settings,
                    )
                except Exception as vst_ex:
                    raise RuntimeError(
                        f"sfizz_render CLI failed ({cli_ex}); sfizz VST3 fallback also failed ({vst_ex})"
                    ) from cli_ex
        return _render_sfizz_vst3(
            pm,
            sfz=sfz,
            sample_rate=sample_rate,
            minimum_duration=minimum_duration,
            settings=settings,
        )
    raise ValueError(f"unknown SFZ renderer mode: {renderer!r}")
