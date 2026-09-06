"""Optional SFZ rendering through sfizz command-line or VST3 backends."""

from __future__ import annotations

import logging
import re
import shlex
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import mido
import numpy as np
from ..audio_utils import coerce_stereo
from ..subprocess_progress import communicate_with_heartbeat, wav_growth_status
import pretty_midi
import soundfile as sf
from scipy import signal

log = logging.getLogger("ambition_music_renderer.sfizz")

_NOTE_RE = re.compile(r"^([a-gA-G])([#b]?)(-?\d+)$")
_KEY_OPCODE_RE = re.compile(r"\b(lokey|hikey|key|pitch_keycenter)\s*=\s*([A-Ga-g#b\-0-9]+)")
_SFZ_INCLUDE_RE = re.compile(r'#include\s+["<]([^">]+)[">]', re.IGNORECASE)
_SFZ_DEFINE_RE = re.compile(r"#define\s+(\$[A-Za-z0-9_]+)\s+([^\s]+)", re.IGNORECASE)


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
    root = Path(sfz_path).resolve()
    chunks: list[str] = []
    seen: set[Path] = set()

    include_base = root.parent

    def read_recursive(path: Path) -> None:
        path = path.resolve()
        if path in seen:
            return
        try:
            body = path.read_text(errors="ignore")
        except OSError:
            return
        seen.add(path)
        chunks.append(body)
        for include in _SFZ_INCLUDE_RE.findall(body):
            # The distributed ARIA/SFZ Level 2 kits resolve all includes from
            # the top-level program directory, even when an include fragment
            # lives below ``Data/stereo`` or ``Programs/modules``.
            read_recursive(include_base / include.replace("\\", "/"))

    read_recursive(root)
    text = "\n".join(chunks)
    macros = dict(_SFZ_DEFINE_RE.findall(text))

    def expand_macro(value: str) -> str:
        for _ in range(8):
            expanded = re.sub(r"\$[A-Za-z0-9_]+", lambda m: macros.get(m.group(0), m.group(0)), value)
            if expanded == value:
                break
            value = expanded
        return value

    # The distributed drum kits frequently hide their GM key map in a .txt
    # include and refer to it through #define macros. Resolve those aliases so
    # the range audit reflects the actual map instead of returning ``None``.
    text = re.sub(
        r"\b(lokey|hikey|key|pitch_keycenter)\s*=\s*([^\s]+)",
        lambda m: f"{m.group(1)}={expand_macro(m.group(2))}",
        text,
        flags=re.IGNORECASE,
    )
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


def _requested_sfizz_buffer_size(stderr: bytes | str | None) -> int | None:
    """Return a larger callback buffer requested by sfizz, if reported."""
    if stderr is None:
        return None
    text = stderr.decode("utf8", errors="replace") if isinstance(stderr, bytes) else str(stderr)
    requested = [
        int(match.group(1))
        for match in re.finditer(
            r"(?:stereo\s+)?buffer of size\s+(\d+);\s+only\s+(\d+)\s+available",
            text,
            flags=re.IGNORECASE,
        )
        if int(match.group(1)) > int(match.group(2))
    ]
    return max(requested) if requested else None


def _bound_midi_end_of_track(
    midi_path: Path,
    pm: pretty_midi.PrettyMIDI,
    *,
    end_time_s: float,
) -> None:
    """Move every SMF End-of-Track marker to a bounded final time.

    ``sfizz_render`` only has a deterministic stopping point when invoked with
    ``--use-eot``.  Without it, the CLI keeps rendering until the output power
    falls below its internal silence threshold.  Sample libraries with a noise
    floor, long release, or looping release region can therefore render forever
    and grow an unbounded WAV.

    PrettyMIDI writes an End-of-Track marker per track.  Put all of them at the
    same requested absolute tick so sfizz sees one unambiguous final boundary
    after tracks are joined.  Never move an EOT before real MIDI data.
    """
    mid = mido.MidiFile(str(midi_path))
    target_tick = int(pm.time_to_tick(max(0.0, float(end_time_s))))
    for track in mid.tracks:
        absolute_tick = 0
        events: list[tuple[int, mido.Message | mido.MetaMessage]] = []
        for msg in track:
            absolute_tick += int(msg.time)
            if msg.type != "end_of_track":
                events.append((absolute_tick, msg))

        last_event_tick = max((tick for tick, _msg in events), default=0)
        eot_tick = max(target_tick, last_event_tick)
        rebuilt = []
        previous_tick = 0
        for tick, msg in events:
            rebuilt.append(msg.copy(time=max(0, tick - previous_tick)))
            previous_tick = tick
        rebuilt.append(
            mido.MetaMessage(
                "end_of_track",
                time=max(0, eot_tick - previous_tick),
            )
        )
        track[:] = rebuilt
    mid.save(str(midi_path))


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
    block_size = int(settings.get("block_size", settings.get("blocksize", 1024)))
    if block_size <= 0:
        raise ValueError("sfizz block_size must be positive")
    use_eot = bool(settings.get("use_eot", True))
    if use_eot:
        # sfizz_render's default tail policy is unbounded: after the final MIDI
        # event it renders until signal power reaches an extremely low silence
        # threshold.  Real sampled instruments can have a persistent noise floor
        # or looping release and never cross it.  Give the CLI a deterministic
        # EOT just beyond the audio duration the caller actually needs.
        eot_padding_s = max(0.0, float(settings.get("eot_padding_seconds", 1.0)))
        _bound_midi_end_of_track(
            midi_path,
            pm,
            # ``minimum_duration`` is the destination stem length, not the
            # amount of musical material in this one instrument. Sparse
            # orchestral instruments legitimately end before the cue.
            end_time_s=float(pm.get_end_time()) + eot_padding_s,
        )
    mapping = {
        "binary": binary,
        "sfz": str(sfz),
        "midi": str(midi_path),
        "wav": str(wav_path),
        "sample_rate": str(int(sample_rate)),
        "block_size": str(block_size),
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
            # sfizz-render's documented option names are --samplerate and
            # --blocksize.  In particular, keep the callback block at 1024 by
            # default: some packaged sfizz_render builds otherwise request
            # 2048-frame temporary buffers from an engine configured for a
            # 1024-frame maximum.  Also opt into --use-eot: without it sfizz
            # renders an open-ended tail until its own silence detector fires.
            [
                binary,
                "--sfz",
                "{sfz}",
                "--midi",
                "{midi}",
                "--wav",
                "{wav}",
                "--samplerate",
                "{sample_rate}",
                "--blocksize",
                "{block_size}",
            ] + (["--use-eot"] if use_eot else []),
            [
                binary,
                "--sfz",
                "{sfz}",
                "--midi",
                "{midi}",
                "--wav",
                "{wav}",
                "--blocksize",
                "{block_size}",
            ] + (["--use-eot"] if use_eot else []),
            [
                binary,
                "--sfz",
                "{sfz}",
                "--midi",
                "{midi}",
                "--wav",
                "{wav}",
                "-s",
                "{sample_rate}",
                "-b",
                "{block_size}",
            ] + (["--use-eot"] if use_eot else []),
        ])
    # A hung sfizz_render (e.g. a broken/pathological SFZ) must not run forever:
    # an orphaned one once wrote a ~100 GB WAV and filled the disk. Cap it; the
    # caller falls back to GM on failure. Override via settings/env if needed.
    import os
    timeout_s = float(settings.get("render_timeout_s",
                                   os.environ.get("AMBITION_SFIZZ_TIMEOUT_S", 120)))
    failures: list[str] = []
    negotiated_block_size = block_size
    auto_block_size = bool(settings.get("auto_block_size", True))
    max_auto_block_size = int(settings.get("max_auto_block_size", 8192))
    content_duration = max(0.0, float(pm.get_end_time()))
    succeeded = False
    for template_item in templates:
        attempt_block_size = negotiated_block_size
        block_retry_count = 0
        while True:
            mapping["block_size"] = str(attempt_block_size)
            cmd = _format_command(template_item, mapping)
            wav_path.unlink(missing_ok=True)
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                stdout, stderr = communicate_with_heartbeat(
                    proc,
                    label=f"sfizz {output_name}",
                    timeout_s=timeout_s,
                    status_fn=lambda: wav_growth_status(wav_path, sample_rate=sample_rate),
                    emit=lambda message: print(f"[music render] {message}", file=sys.stderr, flush=True),
                )
            except subprocess.TimeoutExpired as ex:
                failures.append(
                    f"timed out after {timeout_s:.0f}s: {shlex.join(cmd)}"
                    + (f"; stderr: {_short_process_text(ex.stderr)}" if ex.stderr else "")
                )
                break
            completed = subprocess.CompletedProcess(
                cmd,
                int(proc.returncode),
                stdout=stdout,
                stderr=stderr,
            )

            # A callback-buffer exhaustion can leave holes in a WAV even when
            # sfizz_render exits zero. Negotiate the larger size it explicitly
            # requested before accepting the render.
            requested_block = _requested_sfizz_buffer_size(completed.stderr)
            if (
                auto_block_size
                and requested_block is not None
                and requested_block > attempt_block_size
                and requested_block <= max_auto_block_size
                and block_retry_count < 2
            ):
                failures.append(
                    f"sfizz requested callback buffer {requested_block} while configured for "
                    f"{attempt_block_size}; retrying with the requested block size"
                )
                attempt_block_size = requested_block
                negotiated_block_size = requested_block
                block_retry_count += 1
                continue

            if completed.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 0:
                # Validate against this instrument's own MIDI content, not the
                # final padded stem duration. A sparse orchestral part can end
                # early and still be complete; a piano WAV ending before later
                # piano notes is genuinely truncated.
                try:
                    info = sf.info(wav_path)
                    wav_duration = float(info.frames) / float(info.samplerate) if info.samplerate else 0.0
                except Exception as ex:
                    failures.append(f"could not inspect rendered WAV {wav_path}: {type(ex).__name__}: {ex}")
                    break
                shortfall_tolerance_s = max(0.05, float(attempt_block_size) / float(sample_rate))
                if content_duration > 0 and wav_duration + shortfall_tolerance_s < content_duration:
                    failures.append(
                        f"sfizz_render produced a truncated WAV: duration={wav_duration:.3f}s "
                        f"content_end={content_duration:.3f}s command={shlex.join(cmd)}"
                    )
                    break
                succeeded = True
                break
            failures.append(_format_process_failure(cmd, completed))
            break
        if succeeded:
            break
    if not succeeded:
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
    # Standard same-timestamp ordering: note_off BEFORE note_on. With the old
    # on-before-off ordering, when repeated notes abut exactly the previous
    # note's off arrived after the new note's on and could choke the note that
    # just started (hosts release by key number).
    return sorted(messages, key=lambda msg: (float(msg.time), 0 if msg.type == "note_off" else 1))


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
