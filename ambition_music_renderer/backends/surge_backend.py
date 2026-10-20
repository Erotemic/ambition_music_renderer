"""Render an instrument's MIDI through Surge XT, on one of its factory patches.

MusicIR:

    instrument_backend: {kind: surge, patch: "Leads/Classic Lead 1"}

``patch`` names an ``.fxp`` under Surge's patch folders (``patches_factory``,
then ``patches_3rdparty``), with or without the extension. Optional
``parameters`` set plugin parameters by name after the patch loads.

Two things about Surge XT under Pedalboard are not obvious (measured
2026-10-20, Surge XT 1.3.4):

- It has no preset API that takes an ``.fxp``, and assigning the ``.fxp`` bytes
  to ``raw_state`` is accepted SILENTLY and changes nothing. The patch has to
  be spliced into the plugin's own VST3 state: JUCE wraps Surge's patch chunk
  (``sub3`` ...) in XML, base64-encoded in JUCE's own dialect.
- After a new state, the first ~0.25 s renders silence while Surge loads the
  patch, so every render starts with a silent pre-roll that is cut off.
"""

from __future__ import annotations

import os
import re
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi

from ..audio_utils import coerce_stereo
from .sfizz_backend import _midi_messages_for_pedalboard

#: Silence rendered before the first note while Surge loads the patch, then cut.
PRE_ROLL_SECONDS = 0.5
_JUCE_BASE64 = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def _juce_decode(text: str) -> bytes:
    """JUCE ``MemoryBlock::fromBase64Encoding``: ``"<size>."`` then 6-bit
    digits packed little-endian, bit by bit."""
    size_text, _, body = text.partition(".")
    size = int(size_text)
    out = bytearray(size)
    bit = 0
    for ch in body:
        value = _JUCE_BASE64.index(ch)
        for b in range(6):
            if value >> b & 1:
                byte, shift = divmod(bit + b, 8)
                if byte < size:
                    out[byte] |= 1 << shift
        bit += 6
    return bytes(out)


def _juce_encode(data: bytes) -> str:
    nbits = len(data) * 8
    digits = []
    for pos in range(0, nbits, 6):
        value = 0
        for b in range(6):
            p = pos + b
            if p < nbits and data[p // 8] >> (p % 8) & 1:
                value |= 1 << b
        digits.append(_JUCE_BASE64[value])
    return f"{len(data)}." + "".join(digits)


def state_with_patch(state: bytes, fxp: bytes) -> bytes:
    """Surge's VST3 state ``state`` with its patch replaced by the ``.fxp`` ``fxp``.

    The state is ``b"VC2!" + u32le(len(xml)) + xml + b"\\0"``; the xml's
    ``<IComponent>`` holds Surge's chunk (``sub3`` + u32le xml size + 24 bytes
    + patch xml) then JUCE's private trailer, which is kept. An ``.fxp``'s
    chunk starts at byte 60.
    """
    if state[:4] != b"VC2!":
        raise ValueError("not a JUCE VST3 state (no VC2! header)")
    if fxp[60:64] != b"sub3":
        raise ValueError("not a Surge patch (.fxp chunk does not start with sub3)")
    xml = state[8:8 + struct.unpack("<I", state[4:8])[0]].decode()
    match = re.search(r"<IComponent>(.*?)</IComponent>", xml)
    if match is None:
        raise ValueError("Surge state has no <IComponent>")
    component = _juce_decode(match.group(1))
    if component[:4] != b"sub3":
        raise ValueError("Surge state's component does not start with sub3")
    trailer = component[32 + struct.unpack("<I", component[4:8])[0]:]
    new_xml = (xml[:match.start(1)] + _juce_encode(fxp[60:] + trailer) + xml[match.end(1):]).encode()
    return b"VC2!" + struct.pack("<I", len(new_xml)) + new_xml + b"\0"


def surge_data_roots() -> list[Path]:
    roots = []
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    roots.append(Path(data_home) / "surge-xt")
    tools = os.environ.get("AMBITION_AUDIO_TOOLS_ROOT")
    if tools:
        roots.append(Path(tools) / "plugins" / "unpacked" / "SurgeXT" / "share" / "surge-xt")
    roots += [Path("/usr/share/surge-xt"), Path("/usr/local/share/surge-xt")]
    return [root for root in roots if root.is_dir()]


def resolve_surge_patch(name: str) -> Path:
    stem = name[:-4] if name.lower().endswith(".fxp") else name
    for root in surge_data_roots():
        for folder in ("patches_factory", "patches_3rdparty"):
            path = root / folder / f"{stem}.fxp"
            if path.is_file():
                return path
    known = sorted(
        str(p.relative_to(root / folder))[:-4]
        for root in surge_data_roots()
        for folder in ("patches_factory",)
        for p in (root / folder).rglob("*.fxp")
    )
    leaf = stem.rsplit("/", 1)[-1].lower()
    near = [k for k in known if leaf in k.lower()][:8]
    raise FileNotFoundError(
        f"Surge XT patch {name!r} not found under {[str(r) for r in surge_data_roots()]}"
        + (f"; did you mean {near}?" if near else "; run download_ambition_audio_tools.sh")
    )


def render_surge(
    pm: pretty_midi.PrettyMIDI,
    backend: dict[str, Any],
    sample_rate: int,
    minimum_duration: float = 0.0,
) -> np.ndarray:
    import pedalboard as pb  # type: ignore

    from ..audio_plugins import resolve_vst3_reference

    settings = dict(backend.get("settings") or {})
    plugin_path = resolve_vst3_reference(str(settings.get("plugin", "Surge XT")))
    if plugin_path is None:
        raise FileNotFoundError("Surge XT VST3 not found; run download_ambition_audio_tools.sh")
    patch = backend.get("patch")
    if not patch:
        raise ValueError("instrument_backend kind surge needs a `patch` (e.g. 'Leads/Classic Lead 1')")
    plugin = pb.load_plugin(str(plugin_path))
    plugin.raw_state = state_with_patch(plugin.raw_state, resolve_surge_patch(str(patch)).read_bytes())
    for key, value in dict(backend.get("parameters") or {}).items():
        setattr(plugin, key, value)

    messages = _midi_messages_for_pedalboard(pm)
    for msg in messages:
        msg.time = float(msg.time) + PRE_ROLL_SECONDS
    tail = float(settings.get("tail_seconds", 3.0))
    duration = max(float(minimum_duration), float(pm.get_end_time()) + tail) + PRE_ROLL_SECONDS
    audio = plugin(messages, duration=duration, sample_rate=int(sample_rate), num_channels=2,
                   buffer_size=int(settings.get("buffer_size", 512)), reset=False)
    audio = coerce_stereo(audio)
    return audio[int(round(PRE_ROLL_SECONDS * sample_rate)):]
