"""Ardour 9 session scaffolding for compiled MusicIR scores.

This module is intentionally an adapter around the DAW-neutral MusicIR
interchange.  MusicIR remains authoritative; the Ardour session is a working
editing surface.  The neutral multitrack MIDI + provenance sidecar are emitted
alongside the session so reverse reconciliation does not depend on Ardour XML.

The adapter instantiates the sampled realization selected by the canonical
``InstrumentResolutionPlan`` when Ardour has a native LV2 counterpart:
``sfizz`` for SFZ and ACE Fluid Synth for SoundFonts/GM.  A bypassed
ACE Reasonable Synth can sit behind the real instrument as a deliberately
neutral composition-audition fallback.  MusicIR still owns the notes and
instrument identities; Ardour owns only this generated editing surface.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import mido

from . import instrument_libraries
from .instrument_resolution import instrument_backend_spec, resolve_instrument_backend
from .musicir.interchange import export_interchange_bundle
from .musicir.model import CompiledScore
from .render.score_core import choose_soundfont


ARDOUR_SESSION_VERSION = "7003"
ARDOUR_SUPERCLOCKS_PER_SECOND = 282_240_000
ARDOUR_BEAT_TICKS = 1920
ACE_REASONABLE_SYNTH_URI = "https://community.ardour.org/node/7596"
ACE_FLUID_SYNTH_URI = "urn:ardour:a-fluidsynth"
ACE_FLUID_SYNTH_FILE_PROPERTY = "urn:ardour:a-fluidsynth:sf2file"
SFIZZ_URI = "http://sfztools.github.io/sfizz"
SFIZZ_FILE_PROPERTY = "http://sfztools.github.io/sfizz:sfzfile"
EXPORT_SCHEMA = "ambition.ardour_export.v2"
EXPORT_MARKER = ".ambition-ardour-export.json"
SUPPORTED_EXPORT_MARKER_SCHEMAS = frozenset(
    {
        "ambition.ardour_export.v1",
        EXPORT_SCHEMA,
    }
)


class ArdourExportError(RuntimeError):
    """Raised when a compiled score cannot be scaffolded safely for Ardour."""


@dataclass(frozen=True)
class ArdourExportResult:
    session_dir: Path
    session_file: Path
    neutral_midi: Path
    interchange_manifest: Path
    export_manifest: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "session_dir": str(self.session_dir),
            "session_file": str(self.session_file),
            "neutral_midi": str(self.neutral_midi),
            "interchange_manifest": str(self.interchange_manifest),
            "export_manifest": str(self.export_manifest),
        }


@dataclass(frozen=True)
class _Lv2AssetState:
    """One LV2 path-valued state property that must be serialized on disk."""

    processor_id: str
    plugin_name: str
    plugin_uri: str
    property_uri: str
    asset_path: Path


@dataclass(frozen=True)
class _TrackRealization:
    """Ardour-specific realization of one canonical compiled instrument."""

    instrument: str
    group: str
    program: int
    is_drum: bool
    authored_backend: Mapping[str, Any]
    resolution: Mapping[str, Any]
    resolution_error: str | None
    kind: str
    plugin_name: str | None
    plugin_uri: str | None
    asset_path: Path | None
    property_uri: str | None
    source: str | None
    fallback_reason: str | None

    @property
    def has_real_instrument(self) -> bool:
        return self.plugin_uri is not None and self.kind != "reasonable_synth"

    def to_manifest(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "group": self.group,
            "program": self.program,
            "is_drum": self.is_drum,
            "authored_backend": dict(self.authored_backend),
            "resolution": dict(self.resolution),
            "resolution_error": self.resolution_error,
            "ardour_realization": {
                "kind": self.kind,
                "plugin": self.plugin_name,
                "plugin_uri": self.plugin_uri,
                "asset": str(self.asset_path) if self.asset_path is not None else None,
                "asset_property": self.property_uri,
                "source": self.source,
                "fallback_reason": self.fallback_reason,
            },
        }


class _IdAllocator:
    def __init__(self, start: int = 100) -> None:
        self._next = int(start)

    def take(self) -> str:
        value = self._next
        self._next += 1
        return str(value)

    @property
    def next_value(self) -> int:
        return self._next


def _safe_filename(text: str) -> str:
    chars = []
    for char in str(text):
        if char.isalnum() or char in {"-", "_"}:
            chars.append(char)
        else:
            chars.append("_")
    out = "".join(chars).strip("._")
    return out or "track"


def _absolute_track_end(track: mido.MidiTrack) -> int:
    return sum(int(msg.time) for msg in track)


def _absolute_meta(track: mido.MidiTrack, kind: str) -> list[tuple[int, mido.MetaMessage]]:
    tick = 0
    rows: list[tuple[int, mido.MetaMessage]] = []
    for msg in track:
        tick += int(msg.time)
        if msg.type == kind:
            rows.append((tick, msg))
    return rows


def _constant_conductor(mid: mido.MidiFile) -> tuple[float, int, int]:
    """Return BPM and meter for the Ardour 9 adapter's current safe subset."""

    conductor = mid.tracks[0] if mid.tracks else mido.MidiTrack()
    tempo_rows = _absolute_meta(conductor, "set_tempo")
    sig_rows = _absolute_meta(conductor, "time_signature")

    tempo_values = {int(msg.tempo) for _tick, msg in tempo_rows}
    sig_values = {
        (int(msg.numerator), int(msg.denominator)) for _tick, msg in sig_rows
    }
    if len(tempo_values) > 1:
        raise ArdourExportError(
            "Ardour session export currently supports a constant tempo map; "
            "use `cue daw_export` for this score until Ardour tempo-map serialization is extended."
        )
    if len(sig_values) > 1:
        raise ArdourExportError(
            "Ardour session export currently supports a constant meter; "
            "use `cue daw_export` for this score until Ardour meter-map serialization is extended."
        )

    if tempo_rows:
        tick, msg = tempo_rows[0]
        if tick != 0:
            raise ArdourExportError("Ardour session export requires the initial tempo at MIDI tick 0")
        bpm = float(mido.tempo2bpm(int(msg.tempo)))
    else:
        bpm = 120.0

    if sig_rows:
        tick, msg = sig_rows[0]
        if tick != 0:
            raise ArdourExportError("Ardour session export requires the initial meter at MIDI tick 0")
        numerator = int(msg.numerator)
        denominator = int(msg.denominator)
    else:
        numerator, denominator = 4, 4
    return bpm, numerator, denominator


def _score_end_beats(compiled: CompiledScore, full_mid: mido.MidiFile) -> float:
    midi_end = max((_absolute_track_end(track) for track in full_mid.tracks), default=0)
    end_beats = float(midi_end) / float(full_mid.ticks_per_beat or 1)
    for section in compiled.sections:
        value = section.get("end_beat")
        if value is not None:
            end_beats = max(end_beats, float(value))
    exact_end = (compiled.exact_metadata or {}).get("end_tick")
    if exact_end is not None:
        end_beats = max(end_beats, float(exact_end) / float(compiled.pm.resolution or 1))
    return max(end_beats, 1.0)


def _score_end_seconds(compiled: CompiledScore, end_beats: float, bpm: float) -> float:
    end_seconds = float(compiled.pm.get_end_time())
    for section in compiled.sections:
        value = section.get("end_seconds")
        if value is not None:
            end_seconds = max(end_seconds, float(value))
    # Constant-tempo adapter: ensure the session range covers the full beat-domain form.
    end_seconds = max(end_seconds, end_beats * 60.0 / bpm)
    return max(end_seconds, 1.0)


def _copy_track_to_end(track: mido.MidiTrack, end_tick: int) -> mido.MidiTrack:
    copied = mido.MidiTrack()
    absolute = 0
    non_eot: list[tuple[int, mido.Message | mido.MetaMessage]] = []
    for msg in track:
        absolute += int(msg.time)
        if msg.type != "end_of_track":
            non_eot.append((absolute, msg.copy(time=0)))
    previous = 0
    for tick, msg in non_eot:
        copied.append(msg.copy(time=max(0, tick - previous)))
        previous = tick
    copied.append(mido.MetaMessage("end_of_track", time=max(0, int(end_tick) - previous)))
    return copied


def _write_track_midis(
    full_midi_path: Path,
    destination: Path,
    *,
    track_names: list[str],
    end_beats: float,
) -> list[dict[str, Any]]:
    mid = mido.MidiFile(str(full_midi_path))
    if len(mid.tracks) != len(track_names) + 1:
        raise ArdourExportError(
            "compiled MIDI track count does not match compiled instruments: "
            f"{len(mid.tracks) - 1} MIDI tracks vs {len(track_names)} instruments"
        )
    destination.mkdir(parents=True, exist_ok=True)
    end_tick = int(math.ceil(end_beats * mid.ticks_per_beat))
    conductor = _copy_track_to_end(mid.tracks[0], end_tick)
    rows: list[dict[str, Any]] = []
    for index, (name, source_track) in enumerate(zip(track_names, mid.tracks[1:]), start=1):
        filename = f"{index:02d}_{_safe_filename(name)}.mid"
        path = destination / filename
        one = mido.MidiFile(type=1, ticks_per_beat=mid.ticks_per_beat)
        one.tracks.append(_copy_track_to_end(conductor, end_tick))
        track = _copy_track_to_end(source_track, end_tick)
        # Preserve the semantic CompiledScore instrument name even if an upstream
        # MIDI writer ever changes its default source-track naming.
        for message in track:
            if message.type == "track_name":
                message.name = str(name)
                break
        one.tracks.append(track)
        one.save(str(path))
        rows.append({"name": name, "filename": filename, "path": path})
    return rows


def _add_automation(parent: ET.Element, rows: list[tuple[str, str]], ids: _IdAllocator, *, time_domain: str) -> None:
    automation = ET.SubElement(parent, "Automation")
    for automation_id, interpolation in rows:
        ET.SubElement(
            automation,
            "AutomationList",
            {
                "automation-id": automation_id,
                "id": ids.take(),
                "interpolation-style": interpolation,
                "time-domain": time_domain,
                "state": "Off",
            },
        )


def _add_pannable(route: ET.Element, ids: _IdAllocator) -> None:
    pannable = ET.SubElement(route, "Pannable")
    controls = [
        ("pan-azimuth", "0.5"),
        ("pan-width", "0"),
        ("pan-elevation", "0"),
        ("pan-frontback", "0"),
        ("pan-lfe", "0"),
    ]
    for name, value in controls:
        ET.SubElement(pannable, "Controllable", {"name": name, "id": ids.take(), "flags": "", "value": value})
    _add_automation(
        pannable,
        [(name, "Linear") for name, _value in controls],
        ids,
        time_domain="AudioTime",
    )


def _add_musical_mode(route: ET.Element) -> None:
    ET.SubElement(
        route,
        "musical-mode",
        {
            "tuning": "TwelveTone",
            "ring": "0",
            "type": "PitchClass",
            "name": "Major",
            "elements": "0,2,4,5,7,9,11",
            "root": "0",
        },
    )


def _add_amp_processor(route: ET.Element, ids: _IdAllocator, *, kind: str, control_name: str, automation_id: str, interpolation: str) -> None:
    proc = ET.SubElement(
        route,
        "Processor",
        {
            "id": ids.take(),
            "name": "Amp",
            "active": "1",
            "user-latency": "0",
            "use-user-latency": "0",
            "type": kind,
        },
    )
    automation = ET.SubElement(proc, "Automation")
    ET.SubElement(
        automation,
        "AutomationList",
        {
            "automation-id": automation_id,
            "id": ids.take(),
            "interpolation-style": interpolation,
            "time-domain": "AudioTime",
            "state": "Off",
        },
    )
    ET.SubElement(proc, "Controllable", {"name": control_name, "id": ids.take(), "flags": "GainLike", "value": "1"})


def _add_lv2_instrument(
    route: ET.Element,
    ids: _IdAllocator,
    *,
    name: str,
    plugin_uri: str,
    active: bool,
    pass_audio: bool = False,
    asset_path: Path | None = None,
    asset_property: str | None = None,
) -> tuple[str, _Lv2AssetState | None]:
    """Add a MIDI-in/stereo-out LV2 instrument processor.

    Ardour stores path-valued LV2 state outside the session XML under
    ``plugins/<processor-id>/state1/state.ttl``.  ``asset_path`` is therefore
    returned as a state-writing request instead of being copied into the XML.

    ``pass_audio`` is used for the bypassed neutral audition synth that sits
    behind a real instrument.  Ardour then has enough configured channels to
    pass the real instrument's stereo audio while the audition synth is
    inactive, and enough MIDI to make the audition synth audible when the real
    instrument is bypassed.
    """

    if (asset_path is None) != (asset_property is None):
        raise ValueError("asset_path and asset_property must be provided together")
    plugin_id = ids.take()
    proc = ET.SubElement(
        route,
        "Processor",
        {
            "id": plugin_id,
            "name": name,
            "active": "1" if active else "0",
            "user-latency": "0",
            "use-user-latency": "0",
            "type": "lv2",
            "unique-id": plugin_uri,
            "count": "1",
            "custom": "0",
        },
    )
    configured_in = ET.SubElement(proc, "ConfiguredInput")
    if pass_audio:
        ET.SubElement(configured_in, "Channels", {"type": "audio", "count": "2"})
    ET.SubElement(configured_in, "Channels", {"type": "midi", "count": "1"})
    sinks = ET.SubElement(proc, "CustomSinks")
    ET.SubElement(sinks, "Channels", {"type": "midi", "count": "1"})
    configured_out = ET.SubElement(proc, "ConfiguredOutput")
    ET.SubElement(configured_out, "Channels", {"type": "audio", "count": "2"})
    ET.SubElement(configured_out, "Channels", {"type": "midi", "count": "1"})
    ET.SubElement(proc, "PresetOutput")
    input_map = ET.SubElement(proc, "InputMap-0")
    ET.SubElement(input_map, "Channelmap", {"type": "midi", "from": "0", "to": "0"})
    output_map = ET.SubElement(proc, "OutputMap-0")
    ET.SubElement(output_map, "Channelmap", {"type": "audio", "from": "0", "to": "0"})
    ET.SubElement(output_map, "Channelmap", {"type": "audio", "from": "1", "to": "1"})
    ET.SubElement(proc, "ThruMap")
    lv2_attrs = {
        "last-preset-uri": "",
        "last-preset-label": "",
        "parameter-changed-since-last-preset": "1" if asset_path is not None else "0",
    }
    if asset_path is not None:
        lv2_attrs["state-dir"] = "state1"
    ET.SubElement(proc, "lv2", lv2_attrs)
    state = None
    if asset_path is not None and asset_property is not None:
        state = _Lv2AssetState(
            processor_id=plugin_id,
            plugin_name=name,
            plugin_uri=plugin_uri,
            property_uri=asset_property,
            asset_path=asset_path,
        )
    return plugin_id, state


def _add_reasonable_synth(
    route: ET.Element,
    ids: _IdAllocator,
    *,
    active: bool = True,
    pass_audio: bool = False,
) -> str:
    plugin_id, _state = _add_lv2_instrument(
        route,
        ids,
        name="ACE Reasonable Synth",
        plugin_uri=ACE_REASONABLE_SYNTH_URI,
        active=active,
        pass_audio=pass_audio,
    )
    return plugin_id


def _add_real_instrument(
    route: ET.Element,
    ids: _IdAllocator,
    realization: _TrackRealization,
) -> tuple[str | None, _Lv2AssetState | None]:
    if not realization.has_real_instrument:
        return None, None
    assert realization.plugin_name is not None
    assert realization.plugin_uri is not None
    assert realization.asset_path is not None
    assert realization.property_uri is not None
    return _add_lv2_instrument(
        route,
        ids,
        name=realization.plugin_name,
        plugin_uri=realization.plugin_uri,
        active=True,
        pass_audio=False,
        asset_path=realization.asset_path,
        asset_property=realization.property_uri,
    )


def _add_trigger_box(route: ET.Element, ids: _IdAllocator, *, order: int) -> None:
    proc = ET.SubElement(
        route,
        "Processor",
        {
            "id": ids.take(),
            "name": "TriggerBox",
            "active": "1",
            "user-latency": "0",
            "use-user-latency": "0",
            "type": "triggerbox",
            "data-type": "midi",
            "order": str(order),
        },
    )
    triggers = ET.SubElement(proc, "Triggers")
    for index in range(16):
        ET.SubElement(
            triggers,
            "Trigger",
            {
                "name": "",
                "gain": "1",
                "color": "3200171775",
                "follow-count": "1",
                "use-follow-length": "0",
                "follow-length": "1|0|0",
                "capture-duration": "1|0|0",
                "legato": "0",
                "velocity-effect": "0",
                "follow-action-probability": "0",
                "quantization": "1|0|0",
                "launch-style": "OneShot",
                "follow-action-0": "Again:0",
                "follow-action-1": "Stop:0",
                "stretchable": "1",
                "cue_isolated": "0",
                "allow_patch_changes": "1",
                "stretch_mode": "Crisp",
                "index": str(index),
                "segment-tempo": "0",
                "start": "b0",
                "used-channels": "0",
                "channel-map": ",".join(["-1"] * 16),
            },
        )


def _build_master(ids: _IdAllocator, track_names: list[str]) -> tuple[ET.Element, str]:
    route_id = ids.take()
    route = ET.Element(
        "Route",
        {
            "version": ARDOUR_SESSION_VERSION,
            "id": route_id,
            "name": "Master",
            "default-type": "audio",
            "strict-io": "1",
            "volume-applies-to-output": "1",
            "active": "1",
            "denormal-protection": "0",
            "meter-point": "MeterOutput",
            "disk-io-point": "DiskIOPreFader",
            "meter-type": "MeterK14",
        },
    )
    ET.SubElement(route, "PresentationInfo", {"order": "0", "flags": "MasterOut,OrderSet", "color": "4289374975"})
    ET.SubElement(route, "Controllable", {"name": "solo", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0", "self-solo": "0", "soloed-by-upstream": "0", "soloed-by-downstream": "0"})
    ET.SubElement(route, "Controllable", {"name": "solo-iso", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0", "solo-isolated": "0"})
    ET.SubElement(route, "Controllable", {"name": "solo-safe", "id": ids.take(), "flags": "Toggle", "value": "0", "solo-safe": "0"})
    inp = ET.SubElement(route, "IO", {"name": "Master", "id": ids.take(), "direction": "Input", "default-type": "audio"})
    for channel in (1, 2):
        port = ET.SubElement(inp, "Port", {"name": f"Master/audio_in {channel}", "type": "audio", "direction": "Input"})
        for name in track_names:
            ET.SubElement(port, "Connection", {"other": f"{name}/audio_out {channel}"})
    out = ET.SubElement(route, "IO", {"name": "Master", "id": ids.take(), "direction": "Output", "default-type": "audio"})
    # Do not serialize a machine-specific external device. Ardour keeps the
    # user's selected backend/device authoritative when this session is opened.
    for channel in (1, 2):
        ET.SubElement(out, "Port", {"name": f"Master/audio_out {channel}", "type": "audio", "direction": "Output"})
    ET.SubElement(route, "MuteMaster", {"mute-point": "PostFader,Listen,Main,SurroundSend", "muted": "0"})
    ET.SubElement(route, "Controllable", {"name": "mute", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0"})
    ET.SubElement(route, "Controllable", {"name": "phase", "id": ids.take(), "flags": "Toggle", "value": "0", "phase-invert": "00"})
    ET.SubElement(route, "Controllable", {"name": "mastervolume", "id": ids.take(), "flags": "GainLike,NotAutomatable", "value": "1"})
    _add_automation(route, [("solo", "Discrete"), ("solo-iso", "Discrete"), ("solo-safe", "Discrete"), ("mute", "Discrete"), ("phase", "Discrete")], ids, time_domain="AudioTime")
    _add_pannable(route, ids)
    _add_musical_mode(route)
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": "Polarity", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "polarity"})
    _add_amp_processor(route, ids, kind="trim", control_name="trimcontrol", automation_id="trim", interpolation="Logarithmic")
    _add_amp_processor(route, ids, kind="amp", control_name="gaincontrol", automation_id="gain", interpolation="Exponential")
    # Intentionally no instrument plugin on Master. A synth here consumes the
    # already-rendered track audio path and was the source of the first manual
    # Ardour integration failure.
    main = ET.SubElement(route, "Processor", {"id": ids.take(), "name": "Master", "active": "1", "user-latency": "0", "use-user-latency": "0", "own-input": "1", "own-output": "0", "output": "Master", "type": "main-outs", "role": "Main"})
    ET.SubElement(main, "PannerShell", {"bypassed": "0", "user-panner": "", "linked-to-route": "1"})
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": "meter-Master", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "meter"})
    ET.SubElement(route, "Slavable")
    return route, route_id


def _build_midi_route(
    ids: _IdAllocator,
    *,
    name: str,
    playlist_id: str,
    order: int,
    realization: _TrackRealization,
    add_audition_synth: bool,
) -> tuple[ET.Element, str, dict[str, Any], list[_Lv2AssetState]]:
    route_id = ids.take()
    route = ET.Element(
        "Route",
        {
            "version": ARDOUR_SESSION_VERSION,
            "id": route_id,
            "name": name,
            "default-type": "midi",
            "strict-io": "1",
            "active": "1",
            "denormal-protection": "0",
            "meter-point": "MeterPostFader",
            "disk-io-point": "DiskIOPreFader",
            "meter-type": "MeterPeak",
            "midi-playlist": playlist_id,
            "alignment-choice": "Automatic",
            "playback-channel-mode": "AllChannels",
            "capture-channel-mode": "AllChannels",
            "playback-channel-mask": "0xffff",
            "capture-channel-mask": "0xffff",
            "note-mode": "Sustained",
            "step-editing": "0",
            "input-active": "1",
            "restore-pgm": "1",
            "chase-notes": "1",
        },
    )
    ET.SubElement(route, "PresentationInfo", {"order": str(order), "flags": "MidiTrack,OrderSet", "color": "2148865535"})
    ET.SubElement(route, "Controllable", {"name": "solo", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0", "self-solo": "0", "soloed-by-upstream": "0", "soloed-by-downstream": "0"})
    ET.SubElement(route, "Controllable", {"name": "solo-iso", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0", "solo-isolated": "0"})
    ET.SubElement(route, "Controllable", {"name": "solo-safe", "id": ids.take(), "flags": "Toggle", "value": "0", "solo-safe": "0"})
    inp = ET.SubElement(route, "IO", {"name": name, "id": ids.take(), "direction": "Input", "default-type": "midi"})
    ET.SubElement(inp, "Port", {"name": f"{name}/midi_in 1", "type": "midi", "direction": "Input"})
    out = ET.SubElement(route, "IO", {"name": name, "id": ids.take(), "direction": "Output", "default-type": "midi"})
    for channel in (1, 2):
        port = ET.SubElement(out, "Port", {"name": f"{name}/audio_out {channel}", "type": "audio", "direction": "Output"})
        ET.SubElement(port, "Connection", {"other": f"Master/audio_in {channel}"})
    ET.SubElement(out, "Port", {"name": f"{name}/midi_out 1", "type": "midi", "direction": "Output"})
    ET.SubElement(route, "MuteMaster", {"mute-point": "PostFader,Listen,Main,SurroundSend", "muted": "0"})
    ET.SubElement(route, "Controllable", {"name": "mute", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0"})
    ET.SubElement(route, "Controllable", {"name": "phase", "id": ids.take(), "flags": "Toggle", "value": "0", "phase-invert": ""})
    _add_automation(
        route,
        [("solo", "Discrete"), ("solo-iso", "Discrete"), ("solo-safe", "Discrete"), ("mute", "Discrete"), ("rec-enable", "Discrete"), ("rec-safe", "Discrete"), ("phase", "Discrete"), ("monitor", "Discrete"), ("midi-velocity", "Linear")],
        ids,
        time_domain="BeatTime",
    )
    _add_pannable(route, ids)
    _add_musical_mode(route)
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": f"recorder:{name}", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "diskwriter", "record-safe": "0"})
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": f"player:{name}", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "diskreader"})
    _add_trigger_box(route, ids, order=order - 1)
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": "Polarity", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "polarity"})
    lv2_states: list[_Lv2AssetState] = []
    real_plugin_id, real_state = _add_real_instrument(route, ids, realization)
    if real_state is not None:
        lv2_states.append(real_state)

    # A real instrument is the normal listening path.  The optional Reasonable
    # Synth behind it is deliberately inactive and serves as a neutral MIDI
    # composition debugger.  When no real realization is available, the same
    # synth becomes the active fallback so the generated session remains useful.
    audition_plugin_id: str | None = None
    audition_active = not realization.has_real_instrument
    if add_audition_synth or not realization.has_real_instrument:
        audition_plugin_id = _add_reasonable_synth(
            route,
            ids,
            active=audition_active,
            pass_audio=realization.has_real_instrument,
        )
    _add_amp_processor(route, ids, kind="amp", control_name="gaincontrol", automation_id="gain", interpolation="Exponential")
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": f"meter-{name}", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "meter"})
    main = ET.SubElement(route, "Processor", {"id": ids.take(), "name": name, "active": "1", "user-latency": "0", "use-user-latency": "0", "own-input": "1", "own-output": "0", "output": name, "type": "main-outs", "role": "Main"})
    ET.SubElement(main, "PannerShell", {"bypassed": "0", "user-panner": "", "linked-to-route": "1"})
    ET.SubElement(route, "Slavable")
    ET.SubElement(route, "Controllable", {"name": "monitor", "id": ids.take(), "flags": "RealTime", "value": "0", "monitoring": ""})
    ET.SubElement(route, "Controllable", {"name": "rec-safe", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0"})
    ET.SubElement(route, "Controllable", {"name": "rec-enable", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0"})
    plugin_state = {
        "instrument_plugin_id": real_plugin_id,
        "audition_plugin_id": audition_plugin_id,
        "audition_plugin_active": bool(audition_plugin_id and audition_active),
    }
    return route, route_id, plugin_state, lv2_states


def _region_element(*, ids: _IdAllocator, name: str, source_id: str, length: str, whole_file: bool) -> ET.Element:
    return ET.Element(
        "Region",
        {
            "name": name,
            "muted": "0",
            "opaque": "1",
            "locked": "0",
            "video-locked": "0",
            "automatic": "0",
            "whole-file": "1" if whole_file else "0",
            "import": "0",
            "external": "1",
            "sync-marked": "0",
            "left-of-split": "0",
            "right-of-split": "0",
            "hidden": "0",
            "position-locked": "0",
            "valid-transients": "0",
            "start": "b0",
            "length": length,
            "sync-position": "b0",
            "ancestral-start": "b0",
            "ancestral-length": "b0@b0",
            "stretch": "1",
            "shift": "1",
            "layering-index": "0",
            "tags": "",
            "contents": "0",
            "rgroup": "0",
            "id": ids.take(),
            "type": "midi",
            "first-edit": "nothing",
            "source-0": source_id,
            "master-source-0": source_id,
        },
    )


def _build_session_xml(
    compiled: CompiledScore,
    *,
    session_name: str,
    sample_rate: int,
    track_midis: list[dict[str, Any]],
    realizations: list[_TrackRealization],
    bpm: float,
    numerator: int,
    denominator: int,
    end_beats: float,
    end_seconds: float,
    add_audition_synth: bool,
) -> tuple[ET.ElementTree, list[dict[str, Any]], list[_Lv2AssetState]]:
    ids = _IdAllocator()
    root = ET.Element(
        "Session",
        {
            "version": ARDOUR_SESSION_VERSION,
            "uuid": str(uuid.uuid4()),
            "name": session_name,
            "sample-rate": str(int(sample_rate)),
            "session-range-is-free": "1",
            "id-counter": "0",
            "rg-counter": "1",
            "name-counter": "1",
            "event-counter": "1",
            "vca-counter": "1",
        },
    )
    ET.SubElement(root, "ProgramVersion", {"created-with": "Ardour 9.7", "modified-with": "Ardour 9.7"})
    ET.SubElement(root, "EngineHints")
    ET.SubElement(root, "EngineState")
    ET.SubElement(root, "MIDIPorts")
    config = ET.SubElement(root, "Config")
    config_options = {
        "use-region-fades": "1",
        "use-transport-fades": "1",
        "use-monitor-fades": "1",
        "native-file-data-format": "FormatFloat",
        "native-file-header-format": "RF64_WAV",
        "auto-play": "0",
        "auto-return": "0",
        "auto-input": "1",
        "record-mode": "RecLayered",
        "midi-copy-is-fork": "1",
        "track-name-number": "0",
        "track-name-take": "1",
        "take-name": "Take1",
        "show-summary": "1",
        "show-group-tabs": "1",
        "default-time-domain": "AudioTime",
    }
    for name, value in config_options.items():
        ET.SubElement(config, "Option", {"name": name, "value": value})
    ET.SubElement(root, "Metadata")

    sources = ET.SubElement(root, "Sources")
    ET.SubElement(root, "TriggerBindings")
    regions = ET.SubElement(root, "Regions")
    ET.SubElement(root, "Selection")
    locations = ET.SubElement(root, "Locations")
    end_superclock = int(round(end_seconds * ARDOUR_SUPERCLOCKS_PER_SECOND))
    ET.SubElement(locations, "Location", {"id": ids.take(), "name": "session", "start": "a0", "end": f"a{end_superclock}", "flags": "IsSessionRange", "locked": "0", "timestamp": str(int(time.time())), "cue": "0"})
    for section in compiled.sections:
        start_seconds = section.get("start_seconds")
        if start_seconds is None:
            continue
        pos = int(round(float(start_seconds) * ARDOUR_SUPERCLOCKS_PER_SECOND))
        ET.SubElement(locations, "Location", {"id": ids.take(), "name": str(section.get("label", section.get("id", "section"))), "start": f"a{pos}", "end": f"a{pos}", "flags": "IsMark,IsSection", "locked": "0", "timestamp": str(int(time.time())), "cue": "0"})
    ET.SubElement(root, "Bundles")
    ET.SubElement(root, "VCAManager")
    routes = ET.SubElement(root, "Routes")
    playlists = ET.SubElement(root, "Playlists")
    ET.SubElement(root, "UnusedPlaylists")
    ET.SubElement(root, "RouteGroups")
    speakers = ET.SubElement(root, "Speakers")
    ET.SubElement(speakers, "Speaker", {"azimuth": "240", "elevation": "0", "distance": "1"})
    ET.SubElement(speakers, "Speaker", {"azimuth": "120", "elevation": "0", "distance": "1"})

    track_names = [str(inst.name) for inst in compiled.pm.instruments]
    master, _master_id = _build_master(ids, track_names)
    routes.append(master)

    region_length = f"b{int(math.ceil(end_beats * ARDOUR_BEAT_TICKS))}@b0"
    track_manifest: list[dict[str, Any]] = []
    lv2_states: list[_Lv2AssetState] = []
    pgroup_id = time.strftime("%Y-%m-%d %H.%M.%S")
    if len(realizations) != len(track_midis):
        raise ArdourExportError(
            "instrument realization count does not match exported MIDI tracks: "
            f"{len(realizations)} realizations vs {len(track_midis)} tracks"
        )
    for order, (inst, midi_row, realization) in enumerate(
        zip(compiled.pm.instruments, track_midis, realizations),
        start=1,
    ):
        name = str(inst.name)
        if realization.instrument != name:
            raise ArdourExportError(
                f"instrument realization order mismatch: {realization.instrument!r} vs {name!r}"
            )
        source_id = ids.take()
        playlist_id = ids.take()
        ET.SubElement(sources, "Source", {"name": midi_row["filename"], "take-id": "", "type": "midi", "flags": "Writable", "id": source_id, "origin": midi_row["filename"]})
        regions.append(_region_element(ids=ids, name=name, source_id=source_id, length=region_length, whole_file=True))
        route, route_id, plugin_state, route_lv2_states = _build_midi_route(
            ids,
            name=name,
            playlist_id=playlist_id,
            order=order,
            realization=realization,
            add_audition_synth=add_audition_synth,
        )
        lv2_states.extend(route_lv2_states)
        routes.append(route)
        playlist = ET.SubElement(playlists, "Playlist", {"id": playlist_id, "name": name, "type": "midi", "orig-track-id": route_id, "pgroup-id": pgroup_id, "shared-with-ids": "", "frozen": "0", "combine-ops": "0"})
        playlist.append(_region_element(ids=ids, name=name, source_id=source_id, length=region_length, whole_file=False))
        track_manifest.append(
            {
                "name": name,
                "route_id": route_id,
                "playlist_id": playlist_id,
                "source_id": source_id,
                "midi_source": midi_row["filename"],
                **plugin_state,
            }
        )

    tempo_map = ET.SubElement(root, "TempoMap", {"superclocks-per-second": str(ARDOUR_SUPERCLOCKS_PER_SECOND)})
    tempos = ET.SubElement(tempo_map, "Tempos")
    ET.SubElement(tempos, "Tempo", {"npm": f"{bpm:.15g}", "enpm": f"{bpm:.15g}", "note-type": "4", "type": "Constant", "locked-to-meter": "0", "continuing": "0", "active": "1", "sclock": "0", "quarters": "0:0", "bbt": "1|1|0", "omega": "0"})
    meters = ET.SubElement(tempo_map, "Meters")
    ET.SubElement(meters, "Meter", {"note-value": str(denominator), "divisions-per-bar": str(numerator), "sclock": "0", "quarters": "0:0", "bbt": "1|1|0"})
    ET.SubElement(tempo_map, "MusicTimes")
    ET.SubElement(root, "ControlProtocols")
    extra = ET.SubElement(root, "Extra")
    ui = ET.SubElement(extra, "UI")
    gui = ET.SubElement(ui, "GUIObjectState")
    for row in track_manifest:
        attrs = {"id": f"rtav {row['route_id']}", "height": "82", "color-mode": "TrackColor"}
        ET.SubElement(gui, "Object", attrs)
    script = ET.SubElement(root, "Script", {"lua": "Lua 5.3"})
    script.text = "c2NyaXB0cyA9IHt9IA=="
    ET.SubElement(root, "IOPlugins")
    root.set("id-counter", str(ids.next_value + 1))
    return ET.ElementTree(root), track_manifest, lv2_states


def _resolve_gm_soundfont(
    compiled: CompiledScore,
    *,
    base_dir: Path | None,
) -> tuple[Path | None, str | None, str | None]:
    """Resolve the SoundFont used for plain GM instruments in Ardour.

    Score-authored ``render.soundfont`` remains authoritative.  Otherwise we
    reuse the renderer's normal system SoundFont preference, while also
    honoring the audio-tools environment used by this repository.  The latter
    is adapter configuration rather than MusicIR semantics and is recorded in
    the export manifest.
    """

    render_cfg = dict(compiled.normalized_spec.get("render") or {})
    explicit = render_cfg.get("soundfont")
    if explicit:
        candidate = Path(str(explicit)).expanduser()
        if not candidate.is_absolute() and base_dir is not None:
            candidate = base_dir / candidate
        candidate = candidate.resolve()
        if candidate.is_file():
            return candidate, "render.soundfont", None
        return None, None, f"authored render.soundfont does not exist: {candidate}"

    env_default = os.environ.get("AMBITION_MUSIC_DEFAULT_SOUNDFONT")
    if env_default:
        candidate = Path(env_default).expanduser().resolve()
        if candidate.is_file():
            return candidate, "AMBITION_MUSIC_DEFAULT_SOUNDFONT", None

    renderer_default = choose_soundfont(None)
    if renderer_default:
        return Path(renderer_default).expanduser().resolve(), "renderer default", None

    # The standard Ambition asset install includes GeneralUser-GS.sf2.  Check
    # only exact shallow candidates here: recursive discovery can traverse the
    # entire multi-gigabyte audio-tools tree when its root is configured.
    for root in instrument_libraries.configured_soundfont_roots():
        for candidate in (
            root / "GeneralUser-GS.sf2",
            root / "soundfonts" / "GeneralUser-GS.sf2",
        ):
            if candidate.is_file():
                return candidate.resolve(), "audio-tools GeneralUser-GS", None
    return None, None, "no GM SoundFont was found"


def _resolve_track_realizations(
    compiled: CompiledScore,
    *,
    base_dir: Path | None,
    realize_instruments: bool,
) -> list[_TrackRealization]:
    rows: list[_TrackRealization] = []
    render_cfg = dict(compiled.normalized_spec.get("render") or {})
    sfizz_cfg = dict(render_cfg.get("sfizz") or {})
    default_fallback = sfizz_cfg.get("fallback_backend", render_cfg.get("sfizz_fallback_backend"))
    gm_soundfont, gm_source, gm_error = _resolve_gm_soundfont(compiled, base_dir=base_dir)
    for inst in compiled.pm.instruments:
        name = str(inst.name)
        backend = instrument_backend_spec(compiled.instrument_specs, name)
        try:
            plan = resolve_instrument_backend(
                backend,
                base_dir=base_dir,
                sfizz_cfg=sfizz_cfg,
                default_fallback_backend=(str(default_fallback) if default_fallback is not None else None),
            )
            resolved: Mapping[str, Any] = plan.to_dict()
            resolution_error = None
        except Exception as ex:  # Export remains useful as an audition session.
            plan = None
            resolved = {"backend": dict(backend)}
            resolution_error = str(ex)

        kind = "audition_only"
        plugin_name: str | None = None
        plugin_uri: str | None = None
        asset_path: Path | None = None
        property_uri: str | None = None
        source: str | None = None
        fallback_reason: str | None = None

        if realize_instruments and plan is not None and plan.resolved_sfz is not None:
            kind = "sfizz"
            plugin_name = "sfizz"
            plugin_uri = SFIZZ_URI
            asset_path = plan.resolved_sfz.resolve()
            property_uri = SFIZZ_FILE_PROPERTY
            source = "InstrumentResolutionPlan.resolved_sfz"
        elif realize_instruments and plan is not None and plan.resolved_soundfont is not None:
            kind = "ace_fluidsynth"
            plugin_name = "ACE Fluid Synth"
            plugin_uri = ACE_FLUID_SYNTH_URI
            asset_path = plan.resolved_soundfont.resolve()
            property_uri = ACE_FLUID_SYNTH_FILE_PROPERTY
            source = "InstrumentResolutionPlan.resolved_soundfont"
        elif realize_instruments and plan is not None and not (
            plan.wants_sfz or plan.wants_soundfont or plan.wants_procedural_fm
        ):
            # A plain MusicIR/PrettyMIDI program is a GM instrument.  The MIDI
            # already contains its program change; ACE Fluid Synth only needs
            # the common GM SoundFont loaded.
            if gm_soundfont is not None:
                kind = "ace_fluidsynth_gm"
                plugin_name = "ACE Fluid Synth"
                plugin_uri = ACE_FLUID_SYNTH_URI
                asset_path = gm_soundfont
                property_uri = ACE_FLUID_SYNTH_FILE_PROPERTY
                source = gm_source
            else:
                kind = "reasonable_synth"
                fallback_reason = gm_error
        elif realize_instruments:
            kind = "reasonable_synth"
            if resolution_error:
                fallback_reason = resolution_error
            elif plan is not None and plan.wants_sfz:
                fallback_reason = f"SFZ backend did not resolve: {plan.requested or name}"
            elif plan is not None and plan.wants_soundfont:
                fallback_reason = f"SoundFont backend did not resolve: {plan.requested or name}"
            elif plan is not None and plan.wants_procedural_fm:
                fallback_reason = "procedural_fm has no Ardour LV2 realization yet"
            else:
                fallback_reason = "no supported Ardour realization was resolved"
        else:
            fallback_reason = "--audition-only requested"

        rows.append(
            _TrackRealization(
                instrument=name,
                group=str(compiled.groups.get(name, name)),
                program=int(inst.program),
                is_drum=bool(inst.is_drum),
                authored_backend=dict(backend),
                resolution=dict(resolved),
                resolution_error=resolution_error,
                kind=kind,
                plugin_name=plugin_name,
                plugin_uri=plugin_uri,
                asset_path=asset_path,
                property_uri=property_uri,
                source=source,
                fallback_reason=fallback_reason,
            )
        )
    return rows


def _lv2_asset_state_ttl(state: _Lv2AssetState) -> str:
    asset_uri = state.asset_path.expanduser().resolve().as_uri()
    return "\n".join(
        [
            "@prefix atom: <http://lv2plug.in/ns/ext/atom#> .",
            "@prefix lv2: <http://lv2plug.in/ns/lv2core#> .",
            "@prefix pset: <http://lv2plug.in/ns/ext/presets#> .",
            "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix state: <http://lv2plug.in/ns/ext/state#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
            "<>",
            "    a pset:Preset ;",
            f"    lv2:appliesTo <{state.plugin_uri}> ;",
            "    state:state [",
            f"        <{state.property_uri}> <{asset_uri}>",
            "    ] .",
            "",
        ]
    )


def _write_lv2_asset_states(destination: Path, states: list[_Lv2AssetState]) -> None:
    for state in states:
        state_dir = destination / "plugins" / state.processor_id / "state1"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.ttl").write_text(_lv2_asset_state_ttl(state), encoding="utf8")


def _prepare_destination(destination: Path, *, force: bool) -> None:
    if not destination.exists():
        destination.mkdir(parents=True, exist_ok=False)
        return
    if not any(destination.iterdir()):
        return
    if not force:
        raise ArdourExportError(
            f"destination already exists and is not empty: {destination}. "
            "Choose a new directory, or use --force only for a disposable generated session."
        )
    marker = destination / EXPORT_MARKER
    if not marker.is_file():
        raise ArdourExportError(
            f"refusing --force because {destination} is not marked as an Ambition-generated Ardour session"
        )
    try:
        data = json.loads(marker.read_text(encoding="utf8"))
    except Exception as ex:
        raise ArdourExportError(f"cannot validate generated-session marker {marker}: {ex}") from ex
    if data.get("schema") not in SUPPORTED_EXPORT_MARKER_SCHEMAS or not data.get("generated_session"):
        raise ArdourExportError(f"refusing --force because {marker} is not a valid Ambition export marker")
    shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)


def export_ardour_session(
    compiled: CompiledScore,
    destination: str | Path,
    *,
    session_name: str | None = None,
    sample_rate: int | None = None,
    base_dir: Path | None = None,
    source_score: Path | None = None,
    realize_instruments: bool = True,
    add_audition_synth: bool = True,
    force: bool = False,
) -> ArdourExportResult:
    """Create a ready-to-open Ardour 9 editing session for ``compiled``.

    The generated session is deliberately one-way scaffolding.  The adjacent
    neutral MIDI/interchange sidecar remain the round-trip boundary.
    """

    destination = Path(destination).expanduser().resolve()
    _prepare_destination(destination, force=force)
    cue_id = str(compiled.normalized_spec.get("id") or "score")
    session_name = _safe_filename(session_name or cue_id)
    sample_rate = int(sample_rate or (compiled.normalized_spec.get("render") or {}).get("sample_rate") or 48_000)

    ambition_dir = destination / "ambition"
    neutral = export_interchange_bundle(compiled, ambition_dir, stem=cue_id)
    full_mid = mido.MidiFile(str(neutral["midi"]))
    bpm, numerator, denominator = _constant_conductor(full_mid)
    end_beats = _score_end_beats(compiled, full_mid)
    end_seconds = _score_end_seconds(compiled, end_beats, bpm)

    midi_dir = destination / "interchange" / session_name / "midifiles"
    track_midis = _write_track_midis(
        neutral["midi"],
        midi_dir,
        track_names=[str(inst.name) for inst in compiled.pm.instruments],
        end_beats=end_beats,
    )
    (destination / "interchange" / session_name / "audiofiles").mkdir(parents=True, exist_ok=True)
    (destination / "analysis").mkdir(parents=True, exist_ok=True)
    (destination / "dead").mkdir(parents=True, exist_ok=True)
    (destination / "export").mkdir(parents=True, exist_ok=True)
    (destination / "peaks").mkdir(parents=True, exist_ok=True)
    (destination / "plugins").mkdir(parents=True, exist_ok=True)

    realizations = _resolve_track_realizations(
        compiled,
        base_dir=base_dir,
        realize_instruments=realize_instruments,
    )
    tree, track_state, lv2_states = _build_session_xml(
        compiled,
        session_name=session_name,
        sample_rate=sample_rate,
        track_midis=track_midis,
        realizations=realizations,
        bpm=bpm,
        numerator=numerator,
        denominator=denominator,
        end_beats=end_beats,
        end_seconds=end_seconds,
        add_audition_synth=add_audition_synth,
    )
    ET.indent(tree, space="  ")
    session_file = destination / f"{session_name}.ardour"
    tree.write(session_file, encoding="UTF-8", xml_declaration=True)
    _write_lv2_asset_states(destination, lv2_states)

    export_manifest = destination / EXPORT_MARKER
    manifest_data = {
        "schema": EXPORT_SCHEMA,
        "generated_session": True,
        "session_name": session_name,
        "session_file": session_file.name,
        "source_score": str(source_score) if source_score is not None else None,
        "sample_rate": sample_rate,
        "tempo_bpm": bpm,
        "meter": f"{numerator}/{denominator}",
        "duration_seconds": end_seconds,
        "neutral_interchange": {
            "midi": str(neutral["midi"].relative_to(destination)),
            "manifest": str(neutral["manifest"].relative_to(destination)),
        },
        "instrument_realization": {
            "enabled": bool(realize_instruments),
            "sfz_plugin": "sfizz",
            "sfz_plugin_uri": SFIZZ_URI,
            "soundfont_plugin": "ACE Fluid Synth",
            "soundfont_plugin_uri": ACE_FLUID_SYNTH_URI,
            "local_asset_paths": True,
        },
        "audition": {
            "plugin": "ACE Reasonable Synth",
            "plugin_uri": ACE_REASONABLE_SYNTH_URI,
            "backup_enabled": bool(add_audition_synth),
            "purpose": (
                "neutral MIDI composition audit; inactive behind resolved real instruments, "
                "active only when no real instrument realization is available"
            ),
        },
        "tracks": [
            {**state, **realization.to_manifest()}
            for state, realization in zip(track_state, realizations)
        ],
        "limitations": [
            "Ardour session tempo/meter scaffolding currently requires constant tempo and meter.",
            "The generated Ardour session references machine-local SFZ/SoundFont paths and is not a portable sample bundle.",
            "Procedural-FM and unsupported backend realizations fall back to the neutral audition synth.",
            "Renderer processing/mastering is not serialized into Ardour; use renderer audio as reference when timbral fidelity matters.",
        ],
    }
    export_manifest.write_text(json.dumps(manifest_data, indent=2, sort_keys=True), encoding="utf8")
    readme = destination / "README_AMBITION_ARDOUR.txt"
    readme.write_text(
        "\n".join(
            [
                "Ambition Music Renderer -> Ardour editing session",
                "",
                f"Open: {session_file}",
                "",
                "Resolved SFZ instruments use sfizz. SoundFont/GM instruments use ACE Fluid Synth.",
                "Their local SFZ/SF2 paths are restored through Ardour LV2 state files under plugins/.",
                "",
                "When a real instrument is resolved, ACE Reasonable Synth is inserted behind it inactive.",
                "For a neutral MIDI composition audit: deactivate/bypass the real instrument and activate",
                "ACE Reasonable Synth. This changes timbre only; the MIDI region stays the same.",
                "When a real instrument could not be resolved, Reasonable Synth is active as the fallback.",
                "",
                "To swap an SFZ without touching notes, open the sfizz processor and choose another SFZ.",
                "To swap a GM/SoundFont realization, change the ACE Fluid Synth SoundFont or replace the",
                "instrument processor. Ardour keeps the MIDI region independent of the instrument plugin.",
                "",
                "The Master bus intentionally has no instrument plugin.",
                "The session does not pin an audio backend or hardware device; Ardour should use your current setup.",
                "",
                "The `ambition/` directory contains the DAW-neutral MIDI + MusicIR provenance sidecar.",
                "Do not use this session XML as the future round-trip authority.",
                "",
                "Current fidelity limitation: renderer processing/mastering is not recreated in Ardour.",
                f"See {EXPORT_MARKER} for the resolved instrument path and fallback status of every track.",
                "",
            ]
        ),
        encoding="utf8",
    )
    return ArdourExportResult(
        session_dir=destination,
        session_file=session_file,
        neutral_midi=neutral["midi"],
        interchange_manifest=neutral["manifest"],
        export_manifest=export_manifest,
    )
