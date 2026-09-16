"""Ardour 9 session scaffolding for compiled MusicIR scores.

This module is intentionally an adapter around the DAW-neutral MusicIR
interchange.  MusicIR remains authoritative; the Ardour session is a working
editing surface.  The neutral multitrack MIDI + provenance sidecar are emitted
alongside the session so reverse reconciliation does not depend on Ardour XML.

The session XML deliberately contains only the simple ACE Reasonable Synth
configuration already validated against Ardour.  Real SFZ/SoundFont
instruments are applied by Ardour itself through its Lua/libardour API after
the scaffold is written.  This keeps plugin serialization, pin maps, control
ports, and LV2 state under Ardour's authority instead of reverse-engineering
those implementation details in Python.
"""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import mido

from . import instrument_libraries
from .instrument_resolution import instrument_backend_spec, resolve_instrument_backend
from .musicir.interchange import export_interchange_bundle
from .musicir.model import CompiledScore
from .render.score_core import choose_soundfont
from .ardour_processing import (
    COMPOSITION_BUS_NAME,
    ArdourProcessingTransportPlan,
    ArdourProcessorSpec,
    compile_processing_transport,
    group_bus_name,
)


ARDOUR_SESSION_VERSION = "7003"
ARDOUR_SUPERCLOCKS_PER_SECOND = 282_240_000
ARDOUR_BEAT_TICKS = 1920
# Ardour/Evoral writes internal MIDI sources at 10x its beat-tick resolution.
# Keeping generated source-event positions on that 10-tick lattice avoids a
# cumulative rounding loss in SMFSource::render(), which converts each SMF
# delta independently into Temporal::Beats.  A low/non-divisor PPQ such as
# PrettyMIDI's 220 can otherwise make dense tracks (especially drums) creep
# earlier by seconds over the course of a long cue.
ARDOUR_SMF_PPQN = 19_200
ARDOUR_SMF_TICKS_PER_BEAT_TICK = ARDOUR_SMF_PPQN // ARDOUR_BEAT_TICKS
ACE_REASONABLE_SYNTH_URI = "https://community.ardour.org/node/7596"
ACE_FLUID_SYNTH_URI = "urn:ardour:a-fluidsynth"
ACE_FLUID_SYNTH_FILE_PROPERTY = "urn:ardour:a-fluidsynth:sf2file"
SFIZZ_URI = "http://sfztools.github.io/sfizz"
SFIZZ_FILE_PROPERTY = "http://sfztools.github.io/sfizz:sfzfile"
ARDOUR_ASSET_SETTLE_SCHEDULE_SECONDS = (0.75, 3.0, 12.0)
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
    instrument_bootstrap: Path | None = None
    processing_bootstrap: Path | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "session_dir": str(self.session_dir),
            "session_file": str(self.session_file),
            "neutral_midi": str(self.neutral_midi),
            "interchange_manifest": str(self.interchange_manifest),
            "export_manifest": str(self.export_manifest),
            "instrument_bootstrap": (
                str(self.instrument_bootstrap) if self.instrument_bootstrap is not None else ""
            ),
            "processing_bootstrap": (
                str(self.processing_bootstrap) if self.processing_bootstrap is not None else ""
            ),
        }


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


def _ardour_smf_tick(absolute_tick: int, *, source_ppq: int) -> int:
    """Map one absolute source tick onto Ardour's lossless SMF lattice.

    Ardour's musical-time primitive has ``ARDOUR_BEAT_TICKS`` ticks per beat,
    while newly-created Ardour SMF sources use ``ARDOUR_SMF_PPQN``.  Evoral's
    SMFSource reader converts *delta* ticks independently and truncates during
    PPQ conversion.  If the source PPQ does not divide the internal beat grid
    (notably PrettyMIDI's default 220 PPQ), those tiny per-delta losses
    accumulate differently on tracks with different event density.

    Quantize absolute positions once onto Ardour's internal beat grid, then
    serialize them at 10x resolution.  Every emitted delta is therefore a
    multiple of 10 and converts back to Temporal::Beats exactly.
    """

    if source_ppq <= 0:
        raise ValueError("source_ppq must be positive")
    beat_tick = int(round(int(absolute_tick) * ARDOUR_BEAT_TICKS / source_ppq))
    return beat_tick * ARDOUR_SMF_TICKS_PER_BEAT_TICK


def _copy_track_to_ardour_ppq(
    track: mido.MidiTrack,
    *,
    source_ppq: int,
    end_beats: float,
) -> mido.MidiTrack:
    copied = mido.MidiTrack()
    absolute = 0
    non_eot: list[tuple[int, int, mido.Message | mido.MetaMessage]] = []
    order = 0
    for msg in track:
        absolute += int(msg.time)
        if msg.type != "end_of_track":
            target_tick = _ardour_smf_tick(absolute, source_ppq=source_ppq)
            non_eot.append((target_tick, order, msg.copy(time=0)))
            order += 1

    # Stable ordering matters for note-off/note-on pairs and controllers that
    # intentionally share a coordinate.  Python's sort is stable, but keep an
    # explicit order field so the invariant remains obvious.
    non_eot.sort(key=lambda row: (row[0], row[1]))
    previous = 0
    for tick, _order, msg in non_eot:
        copied.append(msg.copy(time=max(0, tick - previous)))
        previous = tick

    end_beat_tick = int(math.ceil(float(end_beats) * ARDOUR_BEAT_TICKS))
    end_tick = end_beat_tick * ARDOUR_SMF_TICKS_PER_BEAT_TICK
    copied.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - previous)))
    return copied


def _write_track_midis(
    full_midi_path: Path,
    destination: Path,
    *,
    track_names: list[str],
    track_is_drum: list[bool],
    end_beats: float,
) -> list[dict[str, Any]]:
    mid = mido.MidiFile(str(full_midi_path))
    if len(mid.tracks) != len(track_names) + 1:
        raise ArdourExportError(
            "compiled MIDI track count does not match compiled instruments: "
            f"{len(mid.tracks) - 1} MIDI tracks vs {len(track_names)} instruments"
        )
    if len(track_is_drum) != len(track_names):
        raise ArdourExportError(
            "track_is_drum count does not match compiled instruments: "
            f"{len(track_is_drum)} flags vs {len(track_names)} instruments"
        )
    destination.mkdir(parents=True, exist_ok=True)
    source_ppq = int(mid.ticks_per_beat)
    conductor = _copy_track_to_ardour_ppq(
        mid.tracks[0],
        source_ppq=source_ppq,
        end_beats=end_beats,
    )
    rows: list[dict[str, Any]] = []
    for index, (name, _is_drum, source_track) in enumerate(
        zip(track_names, track_is_drum, mid.tracks[1:]),
        start=1,
    ):
        filename = f"{index:02d}_{_safe_filename(name)}.mid"
        path = destination / filename
        one = mido.MidiFile(type=1, ticks_per_beat=ARDOUR_SMF_PPQN)
        # ``conductor`` is already on the Ardour SMF lattice.  Copy it without
        # re-quantizing by using the target PPQ as the source PPQ.
        one.tracks.append(
            _copy_track_to_ardour_ppq(
                conductor,
                source_ppq=ARDOUR_SMF_PPQN,
                end_beats=end_beats,
            )
        )
        track = _copy_track_to_ardour_ppq(
            source_track,
            source_ppq=source_ppq,
            end_beats=end_beats,
        )
        # Preserve the neutral export's authored/global MIDI channel exactly.
        # The first working Ardour proof used these channels successfully; a
        # later attempt to normalize every pitched route to channel 1 was an
        # unsupported inference from FluidSynth warnings and regressed the
        # known-good audition scaffold.  Track separation already prevents
        # cross-instrument MIDI leakage, so there is no reason to rewrite the
        # channel here.
        source_channels = sorted(
            {int(message.channel) for message in track if hasattr(message, "channel")}
        )
        for message in track:
            if message.type == "track_name":
                message.name = str(name)
        one.tracks.append(track)
        one.save(str(path))
        rows.append(
            {
                "name": name,
                "filename": filename,
                "path": path,
                "midi_channel": source_channels[0] if len(source_channels) == 1 else None,
                "midi_channels": source_channels,
                "source_ppq": source_ppq,
                "ardour_ppq": ARDOUR_SMF_PPQN,
            }
        )
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


def _db_to_gain(db: float) -> float:
    return 10.0 ** (float(db) / 20.0)


def _add_amp_processor(
    route: ET.Element,
    ids: _IdAllocator,
    *,
    kind: str,
    control_name: str,
    automation_id: str,
    interpolation: str,
    value: float = 1.0,
    automation_points: list[tuple[float, float]] | None = None,
) -> None:
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
    attrs = {
        "automation-id": automation_id,
        "id": ids.take(),
        "interpolation-style": interpolation,
        "time-domain": "AudioTime",
        "state": "Play" if automation_points else "Off",
    }
    alist = ET.SubElement(automation, "AutomationList", attrs)
    if automation_points:
        events = ET.SubElement(alist, "events")
        events.text = "\n".join(
            f"a{int(round(float(seconds) * ARDOUR_SUPERCLOCKS_PER_SECOND))} {_db_to_gain(db):.15g}"
            for seconds, db in automation_points
        )
    ET.SubElement(
        proc,
        "Controllable",
        {
            "name": control_name,
            "id": ids.take(),
            "flags": "GainLike",
            "value": f"{float(value):.15g}",
        },
    )


def _add_reasonable_synth(route: ET.Element, ids: _IdAllocator) -> str:
    """Insert the exact ACE Reasonable Synth shape validated in Ardour.

    Do not generalize this XML to arbitrary LV2 instruments.  Different LV2
    plugins have plugin-specific control/state and pin-map serialization.  The
    real-instrument pass uses Ardour's Lua API so Ardour creates that state.
    """

    plugin_id = ids.take()
    proc = ET.SubElement(
        route,
        "Processor",
        {
            "id": plugin_id,
            "name": "ACE Reasonable Synth",
            "active": "1",
            "user-latency": "0",
            "use-user-latency": "0",
            "type": "lv2",
            "unique-id": ACE_REASONABLE_SYNTH_URI,
            "count": "1",
            "custom": "0",
        },
    )
    configured_in = ET.SubElement(proc, "ConfiguredInput")
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
    ET.SubElement(
        proc,
        "lv2",
        {
            "last-preset-uri": "",
            "last-preset-label": "",
            "parameter-changed-since-last-preset": "0",
        },
    )
    return plugin_id


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


def _section_gain_automation_points(
    compiled: CompiledScore,
    *,
    bpm: float,
    group: str | None,
) -> list[tuple[float, float]]:
    """Return sparse dB automation points matching renderer section riders."""

    sections = list(compiled.sections)
    if not sections or bpm <= 0:
        return []
    render_cfg = dict(compiled.normalized_spec.get("render") or {})
    if group is None:
        default_beats = float(render_cfg.get("section_mix_transition_beats", 1.0))
    else:
        default_beats = float(
            render_cfg.get(
                "section_stem_mix_transition_beats",
                render_cfg.get("section_mix_transition_beats", 1.0),
            )
        )

    def value(row: Mapping[str, Any]) -> float:
        if group is None:
            return float(row.get("mix_gain_db") or 0.0)
        raw = row.get("stem_mix_db") or {}
        return float(raw.get(group, 0.0))

    gains = [value(row) for row in sections]
    if not any(abs(gain) > 1e-9 for gain in gains):
        return []

    points: list[tuple[float, float]] = [
        (max(0.0, float(sections[0].get("start_seconds", 0.0) or 0.0)), gains[0])
    ]
    for index in range(1, len(sections)):
        prev = sections[index - 1]
        nxt = sections[index]
        prev_gain = gains[index - 1]
        next_gain = gains[index]
        if abs(prev_gain - next_gain) < 1e-9:
            continue
        boundary = float(nxt.get("start_seconds", 0.0) or 0.0)
        if group is None:
            beats = float(nxt.get("mix_gain_transition_beats") or default_beats)
        else:
            beats = float(nxt.get("stem_mix_transition_beats") or default_beats)
        transition = max(0.0, beats * 60.0 / bpm)
        prev_start = float(prev.get("start_seconds", 0.0) or 0.0)
        next_end = float(nxt.get("end_seconds", boundary) or boundary)
        if transition <= 0.0:
            points.append((max(prev_start, boundary - 1e-6), prev_gain))
            points.append((boundary, next_gain))
        else:
            left = max(prev_start, boundary - transition * 0.5)
            right = min(next_end, boundary + transition * 0.5)
            points.append((left, prev_gain))
            points.append((right, next_gain))
    final_end = float(sections[-1].get("end_seconds", points[-1][0]) or points[-1][0])
    points.append((final_end, gains[-1]))

    # Ardour automation lists require strictly ordered coordinates.  Multiple
    # semantic boundaries may collapse to the same superclock; last writer wins.
    by_clock: dict[int, tuple[float, float]] = {}
    for seconds, db in points:
        clock = int(round(max(0.0, seconds) * ARDOUR_SUPERCLOCKS_PER_SECOND))
        by_clock[clock] = (clock / ARDOUR_SUPERCLOCKS_PER_SECOND, db)
    return [by_clock[key] for key in sorted(by_clock)]


def _build_audio_bus(
    ids: _IdAllocator,
    *,
    name: str,
    input_routes: list[str],
    output_route: str,
    order: int,
    gain_automation: list[tuple[float, float]] | None = None,
) -> tuple[ET.Element, str]:
    route_id = ids.take()
    route = ET.Element(
        "Route",
        {
            "version": ARDOUR_SESSION_VERSION,
            "id": route_id,
            "name": name,
            "default-type": "audio",
            "strict-io": "1",
            "active": "1",
            "denormal-protection": "0",
            "meter-point": "MeterPostFader",
            "disk-io-point": "DiskIOPreFader",
            "meter-type": "MeterPeak",
        },
    )
    ET.SubElement(route, "PresentationInfo", {"order": str(order), "flags": "AudioBus,OrderSet", "color": "3221225727"})
    ET.SubElement(route, "Controllable", {"name": "solo", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0", "self-solo": "0", "soloed-by-upstream": "0", "soloed-by-downstream": "0"})
    ET.SubElement(route, "Controllable", {"name": "solo-iso", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0", "solo-isolated": "0"})
    ET.SubElement(route, "Controllable", {"name": "solo-safe", "id": ids.take(), "flags": "Toggle", "value": "0", "solo-safe": "0"})
    inp = ET.SubElement(route, "IO", {"name": name, "id": ids.take(), "direction": "Input", "default-type": "audio"})
    for channel in (1, 2):
        port = ET.SubElement(inp, "Port", {"name": f"{name}/audio_in {channel}", "type": "audio", "direction": "Input"})
        for source in input_routes:
            ET.SubElement(port, "Connection", {"other": f"{source}/audio_out {channel}"})
    out = ET.SubElement(route, "IO", {"name": name, "id": ids.take(), "direction": "Output", "default-type": "audio"})
    for channel in (1, 2):
        port = ET.SubElement(out, "Port", {"name": f"{name}/audio_out {channel}", "type": "audio", "direction": "Output"})
        ET.SubElement(port, "Connection", {"other": f"{output_route}/audio_in {channel}"})
    ET.SubElement(route, "MuteMaster", {"mute-point": "PostFader,Listen,Main,SurroundSend", "muted": "0"})
    ET.SubElement(route, "Controllable", {"name": "mute", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0"})
    ET.SubElement(route, "Controllable", {"name": "phase", "id": ids.take(), "flags": "Toggle", "value": "0", "phase-invert": "00"})
    _add_automation(route, [("solo", "Discrete"), ("solo-iso", "Discrete"), ("solo-safe", "Discrete"), ("mute", "Discrete"), ("phase", "Discrete")], ids, time_domain="AudioTime")
    _add_pannable(route, ids)
    _add_musical_mode(route)
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": "Polarity", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "polarity"})
    _add_amp_processor(route, ids, kind="trim", control_name="trimcontrol", automation_id="trim", interpolation="Logarithmic")
    _add_amp_processor(
        route,
        ids,
        kind="amp",
        control_name="gaincontrol",
        automation_id="gain",
        interpolation="Exponential",
        automation_points=gain_automation,
    )
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": f"meter-{name}", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "meter"})
    main = ET.SubElement(route, "Processor", {"id": ids.take(), "name": name, "active": "1", "user-latency": "0", "use-user-latency": "0", "own-input": "1", "own-output": "0", "output": name, "type": "main-outs", "role": "Main"})
    ET.SubElement(main, "PannerShell", {"bypassed": "0", "user-panner": "", "linked-to-route": "1"})
    ET.SubElement(route, "Slavable")
    return route, route_id


def _build_midi_route(
    ids: _IdAllocator,
    *,
    name: str,
    playlist_id: str,
    order: int,
    add_synth: bool,
    output_route: str = "Master",
    mix_gain_db: float = 0.0,
) -> tuple[ET.Element, str, str | None]:
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
        ET.SubElement(port, "Connection", {"other": f"{output_route}/audio_in {channel}"})
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
    plugin_id = _add_reasonable_synth(route, ids) if add_synth else None
    _add_amp_processor(
        route,
        ids,
        kind="amp",
        control_name="gaincontrol",
        automation_id="gain",
        interpolation="Exponential",
        value=_db_to_gain(mix_gain_db),
    )
    ET.SubElement(route, "Processor", {"id": ids.take(), "name": f"meter-{name}", "active": "1", "user-latency": "0", "use-user-latency": "0", "type": "meter"})
    main = ET.SubElement(route, "Processor", {"id": ids.take(), "name": name, "active": "1", "user-latency": "0", "use-user-latency": "0", "own-input": "1", "own-output": "0", "output": name, "type": "main-outs", "role": "Main"})
    ET.SubElement(main, "PannerShell", {"bypassed": "0", "user-panner": "", "linked-to-route": "1"})
    ET.SubElement(route, "Slavable")
    ET.SubElement(route, "Controllable", {"name": "monitor", "id": ids.take(), "flags": "RealTime", "value": "0", "monitoring": ""})
    ET.SubElement(route, "Controllable", {"name": "rec-safe", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0"})
    ET.SubElement(route, "Controllable", {"name": "rec-enable", "id": ids.take(), "flags": "Toggle,RealTime", "value": "0"})
    return route, route_id, plugin_id

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
    bpm: float,
    numerator: int,
    denominator: int,
    end_beats: float,
    end_seconds: float,
    add_synth: bool,
    transport_processing: bool = False,
) -> tuple[ET.ElementTree, list[dict[str, Any]], dict[str, Any]]:
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
    groups_in_order = list(dict.fromkeys(str(compiled.groups.get(name, name)) for name in track_names))
    tracks_by_group: dict[str, list[str]] = {group: [] for group in groups_in_order}
    for name in track_names:
        tracks_by_group[str(compiled.groups.get(name, name))].append(name)

    # The on-disk scaffold deliberately remains the already-proven direct-to-Master
    # topology.  When processing transport is requested, libardour creates the
    # semantic audio buses later through Session:new_audio_route() and rewires the
    # live route ports.  Hand-authoring AudioBus XML produced routes that looked
    # connected in Ardour's UI but did not actually receive audio.
    master, _master_id = _build_master(ids, track_names)
    routes.append(master)

    region_length = f"b{int(math.ceil(end_beats * ARDOUR_BEAT_TICKS))}@b0"
    track_manifest: list[dict[str, Any]] = []
    mix_manifest: dict[str, Any] = {"enabled": bool(transport_processing), "groups": {}}
    pgroup_id = time.strftime("%Y-%m-%d %H.%M.%S")
    for order, (inst, midi_row) in enumerate(zip(compiled.pm.instruments, track_midis), start=1):
        name = str(inst.name)
        group = str(compiled.groups.get(name, name))
        mix_gain_db = float((compiled.instrument_specs.get(name, {}) or {}).get("mix_gain_db", 0.0))
        source_id = ids.take()
        playlist_id = ids.take()
        ET.SubElement(sources, "Source", {"name": midi_row["filename"], "take-id": "", "type": "midi", "flags": "Writable", "id": source_id, "origin": midi_row["filename"]})
        regions.append(_region_element(ids=ids, name=name, source_id=source_id, length=region_length, whole_file=True))
        route, route_id, plugin_id = _build_midi_route(
            ids,
            name=name,
            playlist_id=playlist_id,
            order=order,
            add_synth=add_synth,
            output_route="Master",
            mix_gain_db=(mix_gain_db if transport_processing else 0.0),
        )
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
                "midi_channel": midi_row.get("midi_channel"),
                "source_ppq": midi_row.get("source_ppq"),
                "ardour_source_ppq": midi_row.get("ardour_ppq"),
                "audition_plugin_id": plugin_id,
                "group": group,
                "mix_gain_db": mix_gain_db if transport_processing else 0.0,
                # Final semantic destination is recorded for the native routing
                # pass, while the safe scaffold itself remains direct-to-Master.
                "output_route": group_bus_name(group) if transport_processing else "Master",
                "scaffold_output_route": "Master",
            }
        )

    if transport_processing:
        # Only describe the intended semantic bus graph here.  The buses are
        # created by libardour in ``apply_processing.lua`` so their IO, main-outs,
        # panner and graph bookkeeping are all native from birth.
        bus_order = len(track_names) + 1
        for offset, group in enumerate(groups_in_order):
            automation = _section_gain_automation_points(compiled, bpm=bpm, group=group)
            bus_name = group_bus_name(group)
            mix_manifest["groups"][group] = {
                "route": bus_name,
                "route_id": None,
                "order": bus_order + offset,
                "tracks": list(tracks_by_group[group]),
                "section_gain_automation_db": [[seconds, db] for seconds, db in automation],
                "created_by": "libardour.Session:new_audio_route",
            }
        composition_automation = _section_gain_automation_points(compiled, bpm=bpm, group=None)
        mix_manifest["composition"] = {
            "route": COMPOSITION_BUS_NAME,
            "route_id": None,
            "order": bus_order + len(groups_in_order),
            "section_gain_automation_db": [[seconds, db] for seconds, db in composition_automation],
            "created_by": "libardour.Session:new_audio_route",
        }

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
    return ET.ElementTree(root), track_manifest, mix_manifest


def _soundfont_is_ace_portable(path: Path) -> bool:
    """Return whether a SoundFont is in the portable ACE Fluid Synth subset.

    Ardour's bundled ACE Fluid Synth is built against the FluidSynth library
    selected by that Ardour build.  In practice an installed ``.sf3`` may be
    newer than the bundled FluidSynth decoder (the source-build used for the
    Standing on Shoulders session rejects MuseScore_General_Full.sf3 v3.1).
    ``.sf2`` is the conservative interchange format that works across those
    builds, so the generated Ardour session never selects an SF3 implicitly.
    """

    return path.suffix.lower() == ".sf2"


def _resolve_gm_soundfont(
    compiled: CompiledScore,
    *,
    base_dir: Path | None,
) -> tuple[Path | None, str | None, str | None]:
    """Resolve an ACE-FluidSynth-compatible SoundFont for plain GM tracks.

    This is deliberately an Ardour-adapter decision, not a change to renderer
    semantics.  The renderer may prefer an SF3 that its own FluidSynth can
    decode; Ardour's bundled ACE Fluid Synth can be built without support for
    that SF3 revision.  Prefer an explicit/configured SF2, then the repository's
    GeneralUser-GS SF2, then other installed SF2s.  Never silently feed ACE a
    renderer-selected SF3 merely because it exists.
    """

    rejected: list[str] = []
    render_cfg = dict(compiled.normalized_spec.get("render") or {})

    def accept(candidate: Path, source: str) -> tuple[Path | None, str | None, str | None] | None:
        candidate = candidate.expanduser()
        if not candidate.is_absolute() and base_dir is not None:
            candidate = base_dir / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            rejected.append(f"{source} does not exist: {candidate}")
            return None
        if not _soundfont_is_ace_portable(candidate):
            rejected.append(
                f"{source} is {candidate.suffix or '<no extension>'}, but Ardour ACE Fluid Synth "
                "export uses the portable .sf2 subset"
            )
            return None
        return candidate, source, None

    explicit = render_cfg.get("soundfont")
    if explicit:
        accepted = accept(Path(str(explicit)), "render.soundfont")
        if accepted is not None:
            return accepted

    env_default = os.environ.get("AMBITION_MUSIC_DEFAULT_SOUNDFONT")
    if env_default:
        accepted = accept(Path(env_default), "AMBITION_MUSIC_DEFAULT_SOUNDFONT")
        if accepted is not None:
            return accepted

    # The standard Ambition asset install includes GeneralUser-GS.sf2.  Prefer
    # it before the renderer's system default because choose_soundfont() may
    # intentionally select MuseScore SF3, which is not portable to ACE.
    roots = instrument_libraries.configured_soundfont_roots()
    shallow_candidates: list[tuple[Path, str]] = []
    for root in roots:
        shallow_candidates.extend(
            [
                (root / "GeneralUser-GS.sf2", "audio-tools GeneralUser-GS"),
                (root / "default-GM.sf2", "configured default-GM.sf2"),
                (root / "soundfonts" / "GeneralUser-GS.sf2", "audio-tools GeneralUser-GS"),
                (root / "soundfonts" / "default-GM.sf2", "configured default-GM.sf2"),
            ]
        )
    shallow_candidates.extend(
        [
            (Path("/usr/share/sounds/sf2/FluidR3_GM.sf2"), "system FluidR3_GM.sf2"),
            (Path("/usr/share/sounds/sf2/TimGM6mb.sf2"), "system TimGM6mb.sf2"),
            (Path("/usr/share/sounds/sf2/default-GM.sf2"), "system default-GM.sf2"),
        ]
    )
    seen: set[Path] = set()
    for candidate, source in shallow_candidates:
        expanded = candidate.expanduser()
        if expanded in seen:
            continue
        seen.add(expanded)
        if expanded.is_file():
            return expanded.resolve(), source, None

    # Reuse the renderer preference only when it already happens to be SF2.
    renderer_default = choose_soundfont(None)
    if renderer_default:
        candidate = Path(renderer_default).expanduser().resolve()
        if candidate.is_file() and _soundfont_is_ace_portable(candidate):
            return candidate, "renderer default", None
        if candidate.is_file():
            rejected.append(
                f"renderer default is {candidate.name}, but Ardour ACE Fluid Synth export uses .sf2"
            )

    # Finally scan the configured SoundFont roots, which are normally small and
    # specific even when the overall audio-tools tree is large.
    try:
        discovered = instrument_libraries.discover_soundfont_files(roots)
    except OSError:
        discovered = []
    sf2s = sorted(path.resolve() for path in discovered if path.suffix.lower() == ".sf2")
    if sf2s:
        return sf2s[0], "configured SF2 discovery", None

    detail = "; ".join(rejected)
    return None, None, (
        "no ACE-FluidSynth-compatible .sf2 SoundFont was found"
        + (f" ({detail})" if detail else "")
    )

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
        exact_sfz: Path | None = None
        exact_soundfont: Path | None = None
        resolved_incompatible_soundfont: Path | None = None
        try:
            plan = resolve_instrument_backend(
                backend,
                base_dir=base_dir,
                sfizz_cfg=sfizz_cfg,
                default_fallback_backend=(str(default_fallback) if default_fallback is not None else None),
            )
            # Ardour's "real instrument" mode is intentionally stricter than
            # the forgiving renderer fallback path.  Re-resolve the authored
            # asset directly so render.sfizz.default_sfz (or another generic
            # fallback) can never masquerade as the requested instrument in a
            # DAW session.
            if plan.wants_sfz:
                exact_sfz = instrument_libraries.resolve_sfz_reference(
                    backend.get("sfz"),
                    library_ref=plan.library_ref,
                    prefer=plan.prefer,
                    base_dir=base_dir,
                    roots=(plan.roots or None),
                )
            elif plan.wants_soundfont:
                exact_soundfont = instrument_libraries.resolve_soundfont_reference(
                    backend.get("soundfont"),
                    library_ref=plan.library_ref,
                    prefer=plan.prefer,
                    base_dir=base_dir,
                    roots=(backend.get("library_roots") or None),
                )
                if exact_soundfont is not None and not _soundfont_is_ace_portable(exact_soundfont):
                    resolved_incompatible_soundfont = exact_soundfont
                    exact_soundfont = None
                else:
                    resolved_incompatible_soundfont = None
            else:
                resolved_incompatible_soundfont = None
            resolved_data = plan.to_dict()
            resolved_data["ardour_exact_resolved_sfz"] = (
                str(exact_sfz) if exact_sfz is not None else None
            )
            resolved_data["ardour_exact_resolved_soundfont"] = (
                str(exact_soundfont) if exact_soundfont is not None else None
            )
            resolved_data["ardour_incompatible_soundfont"] = (
                str(resolved_incompatible_soundfont)
                if resolved_incompatible_soundfont is not None
                else None
            )
            resolved: Mapping[str, Any] = resolved_data
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

        if realize_instruments and plan is not None and exact_sfz is not None:
            kind = "sfizz"
            plugin_name = "sfizz"
            plugin_uri = SFIZZ_URI
            asset_path = exact_sfz.resolve()
            property_uri = SFIZZ_FILE_PROPERTY
            source = "exact authored SFZ resolution"
        elif realize_instruments and plan is not None and exact_soundfont is not None:
            kind = "ace_fluidsynth"
            plugin_name = "ACE Fluid Synth"
            plugin_uri = ACE_FLUID_SYNTH_URI
            asset_path = exact_soundfont.resolve()
            property_uri = ACE_FLUID_SYNTH_FILE_PROPERTY
            source = "exact authored SoundFont resolution"
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
                if plan.resolved_sfz is not None:
                    fallback_reason = (
                        "authored SFZ did not resolve exactly; renderer fallback was rejected for Ardour: "
                        f"{plan.resolved_sfz}"
                    )
                else:
                    fallback_reason = f"SFZ backend did not resolve: {plan.requested or name}"
            elif plan is not None and plan.wants_soundfont:
                if resolved_incompatible_soundfont is not None:
                    fallback_reason = (
                        "SoundFont resolved, but Ardour ACE Fluid Synth export currently uses the portable .sf2 "
                        f"subset; rejected {resolved_incompatible_soundfont}"
                    )
                elif plan.resolved_soundfont is not None:
                    fallback_reason = (
                        "authored SoundFont did not resolve exactly; renderer fallback was rejected for Ardour: "
                        f"{plan.resolved_soundfont}"
                    )
                else:
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


def _lua_string(value: str) -> str:
    """Quote a Python string as a conservative Lua string literal."""

    return (
        '"'
        + str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        + '"'
    )


def _write_ardour_instrument_bootstrap(
    destination: Path,
    *,
    session_name: str,
    realizations: list[_TrackRealization],
) -> Path:
    """Write the libardour pass that owns real LV2 plugin serialization.

    ``get_plugin_insert_property`` is *not* a portable readiness probe.  In the
    user's Ardour/sfizz build it returned ``nil`` forever even though setting the
    property was accepted and earlier sessions later restored the requested
    SFZs.  The reliable boundary is Ardour's serialized LV2 state: ask Ardour to
    create the plugins and set their path properties, give worker threads a
    conservative settling window, save/close, then let Python inspect the state
    directories that Ardour actually wrote.  ``apply_ardour_instruments`` can
    retry from the pristine audition scaffold with a longer settle window if a
    large library (notably a drum kit) was still on its default asset.
    """

    script_path = destination / "ambition" / "apply_real_instruments.lua"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    specs: list[str] = []
    for realization in realizations:
        if not realization.has_real_instrument:
            continue
        assert realization.plugin_uri is not None
        assert realization.asset_path is not None
        assert realization.property_uri is not None
        specs.append(
            "  [%s] = { uri = %s, property = %s, asset = %s },"
            % (
                _lua_string(realization.instrument),
                _lua_string(realization.plugin_uri),
                _lua_string(realization.property_uri),
                _lua_string(str(realization.asset_path)),
            )
        )

    text = "\n".join(
        [
            "-- Generated by ambition_music_renderer. Do not hand-edit.",
            "-- Run with Ardour's gtk2_ardour/arlua so libardour owns plugin state.",
            "local session_dir = assert(arg[1], 'missing session directory')",
            "local snapshot = assert(arg[2], 'missing snapshot/session name')",
            "local settle_seconds = tonumber(arg[3] or '1.0')",
            "assert(settle_seconds >= 0, 'invalid settle time')",
            "",
            "local specs = {",
            *specs,
            "}",
            "",
            "load_session(session_dir, snapshot)",
            "assert(Session ~= nil, 'failed to load Ardour session')",
            "",
            "local pending = {}",
            "for route in Session:get_routes():iter() do",
            "  local spec = specs[route:name()]",
            "  if spec ~= nil then",
            "    local old = route:the_instrument()",
            "    assert(not old:isnil(), 'no instrument processor on route ' .. route:name())",
            "    local proc = ARDOUR.LuaAPI.new_plugin(Session, spec.uri, ARDOUR.PluginType.LV2, '')",
            "    assert(not proc:isnil(), 'LV2 plugin is unavailable: ' .. spec.uri)",
            "    table.insert(pending, { route = route, old = old, proc = proc, spec = spec })",
            "  end",
            "end",
            "",
            "-- Instantiate every plugin before mutating the routes so a missing plugin",
            "-- cannot leave a half-converted session.",
            "for _, item in ipairs(pending) do",
            "  item.route:replace_processor(item.old, item.proc, nil)",
            "  local insert = item.proc:to_insert()",
            "  assert(not insert:isnil(), 'new processor is not a plugin insert on ' .. item.route:name())",
            "  local ok = ARDOUR.LuaAPI.set_plugin_insert_property(insert, item.spec.property, item.spec.asset)",
            "  assert(ok, 'failed to set instrument asset on ' .. item.route:name())",
            "  print('Ambition Ardour instrument requested: ' .. item.route:name() .. ' -> ' .. item.spec.asset)",
            "end",
            "",
            "-- LV2 path changes can schedule worker-thread loads.  Sleeping here leaves",
            "-- the audio engine/workers running; Python verifies the *serialized* state",
            "-- after save and retries from the pristine scaffold with a longer delay when",
            "-- a large asset was not ready yet.",
            "sleep(settle_seconds)",
            "Session:save_state('')",
            "Session:close()",
            "",
        ]
    )
    script_path.write_text(text, encoding="utf8")
    return script_path

def _write_ardour_processing_bootstrap(
    destination: Path,
    *,
    transport: ArdourProcessingTransportPlan,
    mix_state: Mapping[str, Any],
) -> Path:
    """Write the libardour pass that creates buses, routing and processors.

    Audio buses are deliberately *not* hand-authored into the initial session
    XML.  Ardour's native ``Session:new_audio_route`` path performs additional
    route initialization (IO registration, internal-return creation, graph
    integration, processor configuration) that a plausible-looking Route XML
    element does not reproduce reliably.  The initial scaffold therefore stays
    on the already-proven track -> Master topology.  This pass creates the
    semantic buses in libardour and rewires live ports before saving them.
    """

    script_path = destination / "ambition" / "apply_processing.lua"
    script_path.parent.mkdir(parents=True, exist_ok=True)

    route_rows: list[str] = []
    plans = [*transport.groups.values(), transport.master]
    for plan in plans:
        processor_rows: list[str] = []
        for spec in plan.processors:
            param_rows = ", ".join(
                "{%d, %.17g}" % (index, value)
                for index, value in spec.parameters
            )
            processor_rows.append(
                "      { host = %s, plugin = %s, required = %s, params = {%s} },"
                % (
                    _lua_string(spec.host_kind),
                    _lua_string(spec.plugin),
                    "true" if spec.required else "false",
                    param_rows,
                )
            )
        route_rows.extend(
            [
                "  { route = %s, processors = {" % _lua_string(plan.route_name),
                *processor_rows,
                "    } },",
            ]
        )

    groups = dict(mix_state.get("groups") or {})
    group_rows: list[str] = []
    for group, raw_row in groups.items():
        row = dict(raw_row or {})
        tracks = ", ".join(_lua_string(str(name)) for name in row.get("tracks") or [])
        gain_points = ", ".join(
            "{%.17g, %.17g}" % (float(seconds), _db_to_gain(float(db)))
            for seconds, db in row.get("section_gain_automation_db") or []
        )
        group_rows.append(
            "    { group = %s, route = %s, order = %d, tracks = {%s}, gain_points = {%s} },"
            % (
                _lua_string(str(group)),
                _lua_string(str(row.get("route") or group_bus_name(str(group)))),
                int(row.get("order") or 0),
                tracks,
                gain_points,
            )
        )

    composition = dict(mix_state.get("composition") or {})
    composition_points = ", ".join(
        "{%.17g, %.17g}" % (float(seconds), _db_to_gain(float(db)))
        for seconds, db in composition.get("section_gain_automation_db") or []
    )
    composition_route = str(composition.get("route") or COMPOSITION_BUS_NAME)
    composition_order = int(composition.get("order") or 0)

    text = "\n".join(
        [
            "-- Generated by ambition_music_renderer. Do not hand-edit.",
            "-- Canonical ProcessingPlan -> Ardour-native buses/processors.",
            "local session_dir = assert(arg[1], 'missing session directory')",
            "local snapshot = assert(arg[2], 'missing snapshot/session name')",
            "",
            "local routespecs = {",
            *route_rows,
            "}",
            "",
            "local mixspec = {",
            "  composition = { route = %s, order = %d, gain_points = {%s} },"
            % (_lua_string(composition_route), composition_order, composition_points),
            "  groups = {",
            *group_rows,
            "  },",
            "}",
            "",
            "load_session(session_dir, snapshot)",
            "assert(Session ~= nil, 'failed to load Ardour session')",
            "",
            "-- new_audio_route() queues normal output auto-connect work.  This arlua",
            "-- process is disposable, so keep its process-local configuration in manual",
            "-- mode for the lifetime of the pass and establish every semantic edge below.",
            "ARDOUR.config():set_output_auto_connect(ARDOUR.AutoConnectOption.ManualConnect)",
            "",
            "local function require_route(name)",
            "  local route = Session:route_by_name(name)",
            "  assert(not route:isnil(), 'route is missing: ' .. name)",
            "  return route",
            "end",
            "",
            "local function create_bus(spec)",
            "  local existing = Session:route_by_name(spec.route)",
            "  assert(existing:isnil(), 'processing bus unexpectedly exists before native creation: ' .. spec.route)",
            "  local created = Session:new_audio_route(2, 2, ARDOUR.RouteGroup(), 1, spec.route, ARDOUR.PresentationInfo.Flag.AudioBus, spec.order)",
            "  assert(created:size() == 1, 'failed to create native processing bus: ' .. spec.route)",
            "  local route = created:front()",
            "  assert(not route:isnil(), 'native processing bus is nil: ' .. spec.route)",
            "  assert(route:name() == spec.route, 'native processing bus was renamed: expected ' .. spec.route .. ', got ' .. route:name())",
            "  assert(route:n_inputs():n_audio() == 2, 'native processing bus is not stereo at input: ' .. spec.route)",
            "  assert(route:n_outputs():n_audio() == 2, 'native processing bus is not stereo at output: ' .. spec.route)",
            "  return route",
            "end",
            "",
            "local function connect_stereo(source, destination)",
            "  for channel = 0, 1 do",
            "    local op = source:output():audio(channel)",
            "    local ip = destination:input():audio(channel)",
            "    assert(not op:isnil(), 'missing source audio port ' .. tostring(channel + 1) .. ' on ' .. source:name())",
            "    assert(not ip:isnil(), 'missing destination audio port ' .. tostring(channel + 1) .. ' on ' .. destination:name())",
            "    op:disconnect_all()",
            "    local rc = op:connect(ip:name())",
            "    assert(rc == 0, 'failed to connect ' .. op:name() .. ' -> ' .. ip:name())",
            "    assert(op:connected_to(ip:name()), 'connection did not become live: ' .. op:name() .. ' -> ' .. ip:name())",
            "  end",
            "end",
            "",
            "local function set_gain_automation(route, points)",
            "  if #points == 0 then return end",
            "  local ac = route:amp():gain_control()",
            "  local al = ac:alist()",
            "  al:clear_list()",
            "  al:set_interpolation(Evoral.InterpolationStyle.Exponential)",
            "  local sample_rate = Session:nominal_sample_rate()",
            "  for _, point in ipairs(points) do",
            "    local when = Temporal.timepos_t(math.floor(point[1] * sample_rate + 0.5))",
            "    al:add(when, point[2], false, true)",
            "  end",
            "  ac:set_automation_state(ARDOUR.AutoState.Play)",
            "end",
            "",
            "-- Create the receiving composition bus first, then each semantic group.",
            "local composition = create_bus(mixspec.composition)",
            "local group_routes = {}",
            "for _, spec in ipairs(mixspec.groups) do",
            "  group_routes[spec.route] = create_bus(spec)",
            "end",
            "",
            "-- Rewire the proven direct-to-Master scaffold through native buses using",
            "-- Ardour's live Port API.  This is the same mechanism used by Ardour's own",
            "-- Lua routing scripts; the saved XML is now an output of libardour, not input.",
            "for _, spec in ipairs(mixspec.groups) do",
            "  local bus = group_routes[spec.route]",
            "  for _, track_name in ipairs(spec.tracks) do",
            "    connect_stereo(require_route(track_name), bus)",
            "  end",
            "  connect_stereo(bus, composition)",
            "  set_gain_automation(bus, spec.gain_points)",
            "end",
            "local master = Session:master_out()",
            "assert(not master:isnil(), 'Master route is missing')",
            "connect_stereo(composition, master)",
            "set_gain_automation(composition, mixspec.composition.gain_points)",
            "",
            "-- Refresh route lookup after native buses have been added.",
            "local routes = {}",
            "for route in Session:get_routes():iter() do",
            "  routes[route:name()] = route",
            "end",
            "",
            "for _, routespec in ipairs(routespecs) do",
            "  local route = routes[routespec.route]",
            "  assert(route ~= nil, 'processing route is missing: ' .. routespec.route)",
            "  local position = 0",
            "  for _, spec in ipairs(routespec.processors) do",
            "    local proc",
            "    if spec.host == 'lv2' then",
            "      proc = ARDOUR.LuaAPI.new_plugin(Session, spec.plugin, ARDOUR.PluginType.LV2, '')",
            "    elseif spec.host == 'luaproc' then",
            "      proc = ARDOUR.LuaAPI.new_luaproc(Session, spec.plugin)",
            "    else",
            "      error('unknown processing host kind: ' .. tostring(spec.host))",
            "    end",
            "    if proc:isnil() then",
            "      if spec.required then",
            "        error('required processing plugin unavailable on ' .. routespec.route .. ': ' .. spec.plugin)",
            "      else",
            "        print('Ambition Ardour processing skipped optional plugin: ' .. spec.plugin)",
            "      end",
            "    else",
            "      local rc = route:add_processor_by_index(proc, position, nil, true)",
            "      assert(rc == 0, 'failed to add processor on ' .. routespec.route .. ': ' .. spec.plugin)",
            "      for _, param in ipairs(spec.params) do",
            "        local ok = ARDOUR.LuaAPI.set_processor_param(proc, param[1], param[2])",
            "        assert(ok, 'failed to set parameter ' .. tostring(param[1]) .. ' on ' .. spec.plugin)",
            "      end",
            "      position = position + 1",
            "      print('Ambition Ardour processing added: ' .. routespec.route .. ' -> ' .. spec.plugin)",
            "    end",
            "  end",
            "end",
            "",
            "Session:save_state('')",
            "print('Ambition Ardour native mix graph configured')",
            "print('Ambition Ardour processing configured')",
            "Session:close()",
            "",
        ]
    )
    script_path.write_text(text, encoding="utf8")
    return script_path

def detect_ardour_lua(explicit: Path | str | None = None) -> Path | None:
    """Find the command-line libardour Lua frontend used for post-processing."""

    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
        return candidate if candidate.is_file() else None
    env_value = os.environ.get("ARDOUR_LUA")
    if env_value:
        candidate = Path(env_value).expanduser().resolve()
        if candidate.is_file():
            return candidate
    for command in ("ardour-lua", "arlua"):
        found = shutil.which(command)
        if found:
            return Path(found).resolve()
    source_build = Path.home() / "code" / "ardour" / "gtk2_ardour" / "arlua"
    if source_build.is_file():
        return source_build.resolve()
    return None



def _expected_realization_rows(result: ArdourExportResult) -> list[dict[str, str]]:
    """Return the concrete LV2 asset requests recorded in the export marker."""

    data = json.loads(result.export_manifest.read_text(encoding="utf8"))
    rows: list[dict[str, str]] = []
    for track in data.get("tracks", []):
        realization = dict(track.get("ardour_realization") or {})
        plugin_uri = realization.get("plugin_uri")
        asset = realization.get("asset")
        if not plugin_uri or not asset:
            continue
        rows.append(
            {
                "instrument": str(track.get("instrument") or track.get("name") or ""),
                "plugin_uri": str(plugin_uri),
                "asset": str(asset),
            }
        )
    return rows


def _state_dir_mentions_asset(state_dir: Path, expected_asset: Path) -> tuple[bool, str]:
    """Verify one Ardour-owned LV2 state directory names the expected asset.

    Ardour's LV2 state mapper commonly creates a symlink/copy beside state.ttl;
    some plugins instead persist an abstract/absolute path in Turtle.  Accept
    either representation, but require the exact expected basename and reject a
    generic/default asset.  A symlink/hardlink is additionally checked against
    the original machine-local asset path when possible.
    """

    expected_asset = expected_asset.expanduser().resolve()
    candidate = state_dir / expected_asset.name
    wrong_symlink_target: Path | None = None
    copied_candidate = False
    if candidate.is_symlink():
        try:
            resolved_candidate = candidate.resolve()
            if resolved_candidate == expected_asset:
                return True, f"symlink {candidate.name} -> {expected_asset}"
            wrong_symlink_target = resolved_candidate
        except OSError:
            wrong_symlink_target = candidate
    elif candidate.exists():
        try:
            if os.path.samefile(candidate, expected_asset):
                return True, f"samefile {candidate.name}"
        except OSError:
            pass
        try:
            if candidate.is_file() and candidate.stat().st_size == expected_asset.stat().st_size:
                # LV2 state mappers are allowed to copy external assets.  The
                # exact basename plus exact byte size is sufficient here; the
                # adjacent Turtle check below still confirms this is the path
                # the plugin serialized rather than an unrelated file.
                copied_candidate = True
        except OSError:
            copied_candidate = False

    expected_name = expected_asset.name
    expected_path = str(expected_asset)
    turtle_hits: list[str] = []
    for path in sorted(state_dir.rglob("*.ttl")):
        try:
            raw = path.read_text(encoding="utf8", errors="replace")
        except OSError:
            continue
        decoded = unquote(raw)
        if expected_name in decoded or expected_path in decoded:
            turtle_hits.append(str(path.relative_to(state_dir)))
    if turtle_hits:
        if wrong_symlink_target is not None:
            return (
                False,
                f"state names {expected_name!r}, but its symlink resolves to "
                f"{wrong_symlink_target} instead of {expected_asset}",
            )
        if candidate.exists() and copied_candidate:
            return True, f"copied asset + Turtle reference ({', '.join(turtle_hits)})"
        # An absolute/abstract path can legitimately remain external, so a
        # Turtle reference to the exact path/name is itself valid state.
        return True, f"Turtle reference ({', '.join(turtle_hits)})"

    visible = []
    try:
        visible = sorted(path.name for path in state_dir.iterdir())[:12]
    except OSError:
        pass
    return False, f"state dir {state_dir} does not reference {expected_name!r}; contains {visible}"


def _serialized_instrument_state_errors(result: ArdourExportResult) -> list[str]:
    """Check the LV2 state Ardour actually persisted after the native pass."""

    expected_rows = _expected_realization_rows(result)
    if not expected_rows:
        return []
    try:
        root = ET.parse(result.session_file).getroot()
    except Exception as ex:
        return [f"cannot parse Ardour session after native save: {ex}"]

    routes_node = root.find("Routes")
    if routes_node is None:
        return ["Ardour session has no Routes node after native save"]
    routes = {str(route.get("name")): route for route in routes_node.findall("Route")}
    errors: list[str] = []
    for expected in expected_rows:
        name = expected["instrument"]
        route = routes.get(name)
        if route is None:
            errors.append(f"{name}: route missing after native save")
            continue
        processors = [
            proc
            for proc in route.findall("Processor")
            if proc.get("type") == "lv2" and proc.get("unique-id") == expected["plugin_uri"]
        ]
        if len(processors) != 1:
            found = [
                (proc.get("name"), proc.get("unique-id"), proc.get("id"))
                for proc in route.findall("Processor")
                if proc.get("type") == "lv2"
            ]
            errors.append(
                f"{name}: expected one LV2 {expected['plugin_uri']!r}, found {found}"
            )
            continue
        proc = processors[0]
        proc_id = proc.get("id")
        if not proc_id:
            errors.append(f"{name}: serialized LV2 processor has no id")
            continue
        plugin_root = result.session_dir / "plugins" / str(proc_id)
        state_name = proc.get("state-dir")
        if state_name:
            candidate_state_dirs = [plugin_root / state_name]
        else:
            candidate_state_dirs = sorted(path for path in plugin_root.glob("state*") if path.is_dir())
        if not candidate_state_dirs:
            errors.append(f"{name}: no serialized LV2 state directory under {plugin_root}")
            continue
        expected_asset = Path(expected["asset"])
        verified = False
        details: list[str] = []
        for state_dir in candidate_state_dirs:
            ok, detail = _state_dir_mentions_asset(state_dir, expected_asset)
            details.append(detail)
            if ok:
                verified = True
                break
        if not verified:
            errors.append(f"{name}: " + "; ".join(details))
    return errors


def _element_semantic_signature(element: ET.Element | None) -> tuple[Any, ...] | None:
    """Return a whitespace-insensitive XML signature for structural invariants."""

    if element is None:
        return None
    return (
        element.tag,
        tuple(sorted((str(key), str(value)) for key, value in element.attrib.items())),
        (element.text or "").strip(),
        tuple(_element_semantic_signature(child) for child in list(element)),
    )


def _session_timing_signature(root: ET.Element) -> tuple[Any, ...]:
    """Capture the session structures that define MIDI placement and tempo.

    Native libardour is allowed to own plugin serialization, but the instrument
    realization pass must not rewrite the already-auditioned MIDI scaffold.
    Keeping this signature stable prevents a plugin bootstrap/save cycle from
    changing source identity, region placement, playlists, locations, or tempo.
    """

    return tuple(
        (tag, _element_semantic_signature(root.find(tag)))
        for tag in ("Sources", "Regions", "Playlists", "Locations", "TempoMap")
    )


def _graft_native_instruments_onto_scaffold(
    result: ArdourExportResult,
    *,
    scaffold_bytes: bytes,
) -> None:
    """Keep pristine MIDI/session timing and copy only Ardour-owned instruments.

    ``arlua`` must save the session so Ardour can create valid LV2 processor and
    state objects.  Accepting that *entire* saved session is unnecessary, though,
    and lets a headless load/save normalize unrelated hand-authored scaffold
    state.  Instead, extract only the verified instrument processor from each
    route, restore the known-good scaffold, and graft those processors back at
    the exact Reasonable Synth slot.  The plugin state directories are already
    Ardour-owned and remain in place.
    """

    expected_rows = _expected_realization_rows(result)
    if not expected_rows:
        # No real instruments were requested; the native session has nothing
        # useful to contribute.  Preserve the known-good scaffold byte-for-byte.
        result.session_file.write_bytes(scaffold_bytes)
        return

    try:
        native_root = ET.parse(result.session_file).getroot()
        scaffold_root = ET.fromstring(scaffold_bytes)
    except Exception as ex:
        raise ArdourExportError(f"cannot parse Ardour session for instrument graft: {ex}") from ex

    scaffold_timing = _session_timing_signature(scaffold_root)
    native_routes_node = native_root.find("Routes")
    scaffold_routes_node = scaffold_root.find("Routes")
    if native_routes_node is None or scaffold_routes_node is None:
        raise ArdourExportError("cannot graft instruments: Ardour session has no Routes node")

    native_routes = {str(route.get("name")): route for route in native_routes_node.findall("Route")}
    scaffold_routes = {str(route.get("name")): route for route in scaffold_routes_node.findall("Route")}

    for expected in expected_rows:
        name = expected["instrument"]
        native_route = native_routes.get(name)
        scaffold_route = scaffold_routes.get(name)
        if native_route is None or scaffold_route is None:
            raise ArdourExportError(f"cannot graft instrument {name!r}: route missing")

        native_plugins = [
            proc
            for proc in native_route.findall("Processor")
            if proc.get("type") == "lv2" and proc.get("unique-id") == expected["plugin_uri"]
        ]
        if len(native_plugins) != 1:
            raise ArdourExportError(
                f"cannot graft instrument {name!r}: expected one native plugin "
                f"{expected['plugin_uri']!r}, found {len(native_plugins)}"
            )

        scaffold_plugins = [
            proc
            for proc in scaffold_route.findall("Processor")
            if proc.get("type") == "lv2" and proc.get("unique-id") == ACE_REASONABLE_SYNTH_URI
        ]
        if len(scaffold_plugins) != 1:
            raise ArdourExportError(
                f"cannot graft instrument {name!r}: expected one Reasonable Synth slot, "
                f"found {len(scaffold_plugins)}"
            )

        old = scaffold_plugins[0]
        children = list(scaffold_route)
        position = children.index(old)
        scaffold_route.remove(old)
        scaffold_route.insert(position, copy.deepcopy(native_plugins[0]))

    # The copied processor/state objects were allocated from the native
    # session's ID counter.  Carry only that allocator watermark forward so
    # future Ardour edits cannot reuse one of those IDs.
    try:
        scaffold_counter = int(scaffold_root.get("id-counter", "0"))
        native_counter = int(native_root.get("id-counter", "0"))
        scaffold_root.set("id-counter", str(max(scaffold_counter, native_counter)))
    except ValueError:
        pass

    if _session_timing_signature(scaffold_root) != scaffold_timing:
        raise ArdourExportError(
            "internal error: instrument graft changed MIDI/session timing structure"
        )

    tree = ET.ElementTree(scaffold_root)
    ET.indent(tree, space="  ")
    tree.write(result.session_file, encoding="UTF-8", xml_declaration=True)


def _ardour_midi_source_dir(result: ArdourExportResult) -> Path:
    return (
        result.session_dir
        / "interchange"
        / result.session_file.stem
        / "midifiles"
    )


def _snapshot_ardour_midi_sources(result: ArdourExportResult) -> dict[str, bytes]:
    """Capture generated MIDI sources before libardour is allowed to touch them."""

    midi_dir = _ardour_midi_source_dir(result)
    if not midi_dir.is_dir():
        raise ArdourExportError(f"generated Ardour MIDI source directory is missing: {midi_dir}")
    snapshot = {
        str(path.relative_to(midi_dir)): path.read_bytes()
        for path in sorted(midi_dir.rglob("*"))
        if path.is_file()
    }
    if not snapshot:
        raise ArdourExportError(f"generated Ardour MIDI source directory is empty: {midi_dir}")
    return snapshot


def _restore_ardour_midi_sources(
    result: ArdourExportResult,
    snapshot: Mapping[str, bytes],
) -> None:
    """Restore MIDI sources exactly, removing native-save scratch/take files."""

    midi_dir = _ardour_midi_source_dir(result)
    if midi_dir.exists():
        shutil.rmtree(midi_dir)
    midi_dir.mkdir(parents=True, exist_ok=True)
    for relative, payload in snapshot.items():
        path = midi_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _restore_ardour_scaffold(
    result: ArdourExportResult,
    scaffold_bytes: bytes,
    *,
    midi_snapshot: Mapping[str, bytes] | None = None,
) -> None:
    """Return a failed/retry attempt to the known-good audition baseline."""

    result.session_file.write_bytes(scaffold_bytes)
    if midi_snapshot is not None:
        _restore_ardour_midi_sources(result, midi_snapshot)
    plugins_dir = result.session_dir / "plugins"
    if plugins_dir.exists():
        shutil.rmtree(plugins_dir)
    plugins_dir.mkdir(parents=True, exist_ok=True)


def _update_realization_status(
    result: ArdourExportResult,
    *,
    status: str,
    ardour_lua: Path | None = None,
    error: str | None = None,
) -> None:
    """Record post-processing status without making session XML authoritative."""

    try:
        data = json.loads(result.export_manifest.read_text(encoding="utf8"))
        realization = data.setdefault("instrument_realization", {})
        realization["status"] = status
        if ardour_lua is not None:
            realization["ardour_lua"] = str(ardour_lua)
        if error is not None:
            realization["error"] = error
        else:
            realization.pop("error", None)
        result.export_manifest.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf8",
        )
    except (OSError, ValueError, TypeError):
        # Status reporting is diagnostic. Never turn a successfully generated
        # or successfully post-processed session into a failure because the
        # adjacent JSON marker could not be rewritten.
        pass


def apply_ardour_instruments(
    result: ArdourExportResult,
    *,
    ardour_lua: Path | str,
) -> subprocess.CompletedProcess[str]:
    """Ask Ardour to realize plugins, then verify Ardour's serialized LV2 state.

    Runtime property readback is not used: sfizz can accept a path change while
    ``get_plugin_insert_property`` remains nil in headless ``arlua``.  Instead
    each attempt starts from the exact known-good audition scaffold *and MIDI
    source bytes*, lets Ardour own plugin creation/state saving, and verifies the
    resulting ``plugins/...``
    state directories.  If a large asset was still on its default patch, retry
    with a longer settle window.  Any final failure restores the audible
    Reasonable Synth scaffold.
    """

    if result.instrument_bootstrap is None:
        raise ArdourExportError("Ardour export has no instrument bootstrap script")
    exe = Path(ardour_lua).expanduser().resolve()
    if not exe.is_file():
        raise ArdourExportError(f"Ardour Lua frontend does not exist: {exe}")

    scaffold_bytes = result.session_file.read_bytes()
    midi_snapshot = _snapshot_ardour_midi_sources(result)
    attempt_messages: list[str] = []
    last_completed: subprocess.CompletedProcess[str] | None = None

    for attempt_index, settle_seconds in enumerate(ARDOUR_ASSET_SETTLE_SCHEDULE_SECONDS, start=1):
        if attempt_index > 1:
            _restore_ardour_scaffold(
                result, scaffold_bytes, midi_snapshot=midi_snapshot
            )
        command = [
            str(exe),
            str(result.instrument_bootstrap),
            str(result.session_dir),
            result.session_file.stem,
            f"{settle_seconds:g}",
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        last_completed = completed
        details = "\n".join(part for part in (completed.stdout, completed.stderr) if part.strip())

        # The libardour/arlua process exit code is advisory here.  We have seen
        # headless Ardour return non-zero after it has nevertheless serialized
        # every requested LV2 instrument correctly.  Conversely, a zero exit
        # code does not prove that a large asynchronous SFZ/SF2 asset finished
        # loading.  The persisted plugin state is therefore the authoritative
        # postcondition: accept a non-zero process result when all requested
        # assets verify, and retry/rollback when they do not.
        verification_errors = _serialized_instrument_state_errors(result)
        if not verification_errors:
            # libardour treats generated MIDI sources as writable and may
            # normalize/rewrite them while saving plugin state.  Musical data
            # is not part of this native post-processing transaction: restore
            # the pristine generated sources before grafting only the verified
            # instrument processors onto the timing scaffold.
            _restore_ardour_midi_sources(result, midi_snapshot)
            # Keep Ardour-owned plugin serialization/state, but do not accept
            # unrelated session normalization from the headless load/save.
            # The audition scaffold is already our proven MIDI timing surface.
            _graft_native_instruments_onto_scaffold(
                result,
                scaffold_bytes=scaffold_bytes,
            )
            post_graft_errors = _serialized_instrument_state_errors(result)
            if post_graft_errors:
                _restore_ardour_scaffold(
                    result, scaffold_bytes, midi_snapshot=midi_snapshot
                )
                raise ArdourExportError(
                    "verified native instruments became invalid while grafting them onto "
                    "the timing-preserving scaffold: " + " | ".join(post_graft_errors)
                )
            _update_realization_status(result, status="applied", ardour_lua=exe)
            return completed

        attempt_summary = (
            f"attempt {attempt_index} settle={settle_seconds:g}s "
            f"exit={completed.returncode}: "
            + " | ".join(verification_errors)
        )
        if details:
            attempt_summary += "\n" + details
        attempt_messages.append(attempt_summary)

    _restore_ardour_scaffold(
        result, scaffold_bytes, midi_snapshot=midi_snapshot
    )
    error_text = "\n".join(attempt_messages)
    if last_completed is not None:
        native_output = "\n".join(
            part for part in (last_completed.stdout, last_completed.stderr) if part.strip()
        )
        if native_output:
            error_text = (error_text + "\n" + native_output).strip()
    _update_realization_status(
        result,
        status="failed",
        ardour_lua=exe,
        error=error_text or "serialized LV2 state did not match requested assets",
    )
    raise ArdourExportError(
        "Ardour saved instrument plugins, but their serialized LV2 state did not match the "
        "requested assets after all settle/retry windows. The generated session was rolled "
        "back to the working ACE Reasonable Synth scaffold.\n" + error_text
    )

def _expected_processing_routes(result: ArdourExportResult) -> list[dict[str, Any]]:
    data = json.loads(result.export_manifest.read_text(encoding="utf8"))
    transport = dict(data.get("processing_transport") or {})
    plan = dict(transport.get("plan") or {})
    rows: list[dict[str, Any]] = []
    groups = dict(plan.get("groups") or {})
    for group, route_plan in groups.items():
        rows.append({"group": group, **dict(route_plan)})
    master = plan.get("master")
    if isinstance(master, Mapping):
        rows.append({"group": None, **dict(master)})
    return rows


def _processor_matches_transport(proc: ET.Element, spec: Mapping[str, Any]) -> bool:
    host = str(spec.get("host_kind") or "")
    plugin = str(spec.get("plugin") or "")
    if host == "lv2":
        return proc.get("type") == "lv2" and proc.get("unique-id") == plugin
    if host == "luaproc":
        return proc.get("name") == plugin and proc.get("type") not in {
            "amp", "trim", "polarity", "meter", "main-outs", "diskreader", "diskwriter", "triggerbox"
        }
    return False


def _processing_processors_on_route(
    route: ET.Element,
    expected: list[Mapping[str, Any]],
) -> tuple[list[ET.Element], list[str]]:
    children = list(route.findall("Processor"))
    matched: list[ET.Element] = []
    errors: list[str] = []
    cursor = 0
    for spec in expected:
        found: ET.Element | None = None
        found_at = -1
        for index in range(cursor, len(children)):
            if _processor_matches_transport(children[index], spec):
                found = children[index]
                found_at = index
                break
        if found is None:
            if bool(spec.get("required", True)):
                errors.append(
                    f"missing required processor {spec.get('plugin')!r}"
                )
            continue
        matched.append(found)
        cursor = found_at + 1
    return matched, errors


def _route_output_connections(route: ET.Element) -> set[str]:
    """Return serialized destinations of a route's main Output IO."""

    return {
        str(connection.get("other"))
        for io in route.findall("IO")
        if io.get("direction") == "Output"
        for port in io.findall("Port")
        for connection in port.findall("Connection")
        if connection.get("other")
    }


def _route_has_native_internal_return(route: ET.Element) -> bool:
    """Native Ardour audio buses contain the InternalReturn processor."""

    return any(proc.get("type") == "intreturn" for proc in route.findall("Processor"))


def _serialized_mix_routing_errors(
    result: ArdourExportResult,
    *,
    root: ET.Element,
) -> list[str]:
    """Verify that libardour serialized the intended live audio graph.

    A destination shown in a hand-authored ``.ardour`` file is not sufficient
    evidence that the receiving bus was initialized as a real Ardour route.
    Require the native bus marker (InternalReturn) and the exact stereo edges
    that the live Port API established before accepting the processing pass.
    """

    routes_node = root.find("Routes")
    if routes_node is None:
        return ["Ardour session has no Routes node after processing pass"]
    routes = {str(route.get("name")): route for route in routes_node.findall("Route")}
    try:
        data = json.loads(result.export_manifest.read_text(encoding="utf8"))
    except Exception as ex:
        return [f"cannot read Ardour export manifest for mix verification: {ex}"]
    transport = dict(data.get("processing_transport") or {})
    mix = dict(transport.get("mix_routing") or {})
    groups = dict(mix.get("groups") or {})
    composition = dict(mix.get("composition") or {})
    composition_name = str(composition.get("route") or COMPOSITION_BUS_NAME)

    errors: list[str] = []

    def require_stereo_edge(source_name: str, target_name: str) -> None:
        source = routes.get(source_name)
        if source is None:
            errors.append(f"mix route missing: {source_name}")
            return
        connections = _route_output_connections(source)
        expected = {
            f"{target_name}/audio_in 1",
            f"{target_name}/audio_in 2",
        }
        missing = sorted(expected - connections)
        if missing:
            errors.append(
                f"{source_name}: missing serialized stereo edge to {target_name}: "
                + ", ".join(missing)
            )

    for raw_row in groups.values():
        if not isinstance(raw_row, Mapping):
            continue
        route_name = str(raw_row.get("route") or "")
        if not route_name:
            continue
        bus = routes.get(route_name)
        if bus is None:
            errors.append(f"native group bus missing: {route_name}")
        else:
            if not _route_has_native_internal_return(bus):
                errors.append(f"{route_name}: native InternalReturn processor is missing")
            presentation = bus.find("PresentationInfo")
            flags = presentation.get("flags", "") if presentation is not None else ""
            if "AudioBus" not in flags:
                errors.append(f"{route_name}: route is not serialized as an AudioBus")
        for track_name in raw_row.get("tracks") or []:
            require_stereo_edge(str(track_name), route_name)
        require_stereo_edge(route_name, composition_name)

    composition_route = routes.get(composition_name)
    if composition_route is None:
        errors.append(f"native composition bus missing: {composition_name}")
    else:
        if not _route_has_native_internal_return(composition_route):
            errors.append(f"{composition_name}: native InternalReturn processor is missing")
        presentation = composition_route.find("PresentationInfo")
        flags = presentation.get("flags", "") if presentation is not None else ""
        if "AudioBus" not in flags:
            errors.append(f"{composition_name}: route is not serialized as an AudioBus")
        require_stereo_edge(composition_name, "Master")

    if "Master" not in routes:
        errors.append("Master route missing after processing pass")
    return errors


def _serialized_processing_errors(result: ArdourExportResult) -> list[str]:
    try:
        root = ET.parse(result.session_file).getroot()
    except Exception as ex:
        return [f"cannot parse Ardour session after processing pass: {ex}"]
    routes_node = root.find("Routes")
    if routes_node is None:
        return ["Ardour session has no Routes node after processing pass"]
    routes = {str(route.get("name")): route for route in routes_node.findall("Route")}
    errors = _serialized_mix_routing_errors(result, root=root)
    for row in _expected_processing_routes(result):
        route_name = str(row.get("route") or "")
        route = routes.get(route_name)
        if route is None:
            errors.append(f"processing route missing: {route_name}")
            continue
        expected = [dict(spec) for spec in row.get("processors") or []]
        _matched, route_errors = _processing_processors_on_route(route, expected)
        errors.extend(f"{route_name}: {error}" for error in route_errors)
    return errors


def _processing_mix_route_names(result: ArdourExportResult) -> list[str]:
    """Return the audio routes whose live shape belongs to Ardour.

    Track MIDI/timing remains scaffold-owned.  The semantic audio-bus graph is
    different: libardour is the authority for a bus' IO, main-outs processor,
    panner, processor ordering and connection serialization.
    """

    data = json.loads(result.export_manifest.read_text(encoding="utf8"))
    transport = dict(data.get("processing_transport") or {})
    mix = dict(transport.get("mix_routing") or {})
    names: list[str] = []
    for row in dict(mix.get("groups") or {}).values():
        if isinstance(row, Mapping) and row.get("route"):
            names.append(str(row["route"]))
    composition = mix.get("composition")
    if isinstance(composition, Mapping) and composition.get("route"):
        names.append(str(composition["route"]))
    names.append("Master")
    return list(dict.fromkeys(names))


def _replace_route(routes_node: ET.Element, old: ET.Element, new: ET.Element) -> None:
    children = list(routes_node)
    position = children.index(old)
    routes_node.remove(old)
    routes_node.insert(position, copy.deepcopy(new))


def _replace_route_output_io(
    scaffold_route: ET.Element,
    native_route: ET.Element,
) -> None:
    """Copy only Ardour's live-routed Output IO onto a pristine MIDI route."""

    scaffold_output = next(
        (child for child in list(scaffold_route) if child.tag == "IO" and child.get("direction") == "Output"),
        None,
    )
    native_output = next(
        (child for child in list(native_route) if child.tag == "IO" and child.get("direction") == "Output"),
        None,
    )
    if scaffold_output is None or native_output is None:
        raise ArdourExportError(
            f"cannot graft native output routing for {scaffold_route.get('name')!r}: Output IO is missing"
        )
    position = list(scaffold_route).index(scaffold_output)
    scaffold_route.remove(scaffold_output)
    scaffold_route.insert(position, copy.deepcopy(native_output))


def _master_route_with_scaffold_output(
    native_route: ET.Element,
    scaffold_route: ET.Element,
) -> ET.Element:
    """Keep Ardour's native Master internals without pinning Dummy IO."""

    merged = copy.deepcopy(native_route)
    native_output = next(
        (child for child in list(merged) if child.tag == "IO" and child.get("direction") == "Output"),
        None,
    )
    scaffold_output = next(
        (child for child in list(scaffold_route) if child.tag == "IO" and child.get("direction") == "Output"),
        None,
    )
    if native_output is None or scaffold_output is None:
        raise ArdourExportError("cannot merge Master route: output IO is missing")
    position = list(merged).index(native_output)
    merged.remove(native_output)
    merged.insert(position, copy.deepcopy(scaffold_output))
    return merged


def _graft_native_processing_onto_scaffold(
    result: ArdourExportResult,
    *,
    scaffold_bytes: bytes,
) -> None:
    """Graft a libardour-created audio graph onto pristine musical state.

    The safe input scaffold contains only MIDI tracks routed directly to Master.
    The headless native pass creates every semantic audio bus through
    ``Session:new_audio_route`` and connects the live ports.  After that pass,
    preserve the complete native group/composition routes and the MIDI tracks'
    native Output IO, but keep all other MIDI route/region/source/timing state
    from the pristine scaffold.  Master keeps native receiving/processor state
    while retaining the scaffold's machine-neutral external Output IO.
    """

    try:
        native_root = ET.parse(result.session_file).getroot()
        scaffold_root = ET.fromstring(scaffold_bytes)
    except Exception as ex:
        raise ArdourExportError(f"cannot parse Ardour session for processing graft: {ex}") from ex
    timing_signature = _session_timing_signature(scaffold_root)
    native_routes_node = native_root.find("Routes")
    scaffold_routes_node = scaffold_root.find("Routes")
    if native_routes_node is None or scaffold_routes_node is None:
        raise ArdourExportError("cannot graft processing: Ardour session has no Routes node")
    native_routes = {str(route.get("name")): route for route in native_routes_node.findall("Route")}
    scaffold_routes = {str(route.get("name")): route for route in scaffold_routes_node.findall("Route")}

    # Verify the processing stages before accepting any native route state.
    for row in _expected_processing_routes(result):
        route_name = str(row.get("route") or "")
        native_route = native_routes.get(route_name)
        if native_route is None:
            raise ArdourExportError(f"cannot graft processing route {route_name!r}: native route missing")
        expected = [dict(spec) for spec in row.get("processors") or []]
        _matched, errors = _processing_processors_on_route(native_route, expected)
        if errors:
            raise ArdourExportError(
                f"cannot graft processing route {route_name!r}: " + " | ".join(errors)
            )

    # The live Port API rewired MIDI tracks to their semantic group buses.  Copy
    # only each track's Output IO; instrument/plugin/timing state stays pristine.
    data = json.loads(result.export_manifest.read_text(encoding="utf8"))
    mix = dict((data.get("processing_transport") or {}).get("mix_routing") or {})
    group_rows = dict(mix.get("groups") or {})
    routed_track_names = list(
        dict.fromkeys(
            str(track_name)
            for row in group_rows.values()
            if isinstance(row, Mapping)
            for track_name in (row.get("tracks") or [])
        )
    )
    for track_name in routed_track_names:
        native_route = native_routes.get(track_name)
        scaffold_route = scaffold_routes.get(track_name)
        if native_route is None or scaffold_route is None:
            raise ArdourExportError(
                f"cannot graft native track routing for {track_name!r}: route missing"
            )
        _replace_route_output_io(scaffold_route, native_route)

    # Native buses do not exist in the safe scaffold.  They are accepted only
    # after serialized topology verification and copied as complete Ardour-owned
    # routes, including InternalReturn/main-outs/panner/processor bookkeeping.
    for route_name in _processing_mix_route_names(result):
        if route_name == "Master":
            continue
        native_route = native_routes.get(route_name)
        if native_route is None:
            raise ArdourExportError(f"cannot graft native mix route {route_name!r}: native route missing")
        existing = next(
            (route for route in scaffold_routes_node.findall("Route") if route.get("name") == route_name),
            None,
        )
        if existing is None:
            scaffold_routes_node.append(copy.deepcopy(native_route))
        else:
            _replace_route(scaffold_routes_node, existing, native_route)

    native_master = native_routes.get("Master")
    scaffold_master = next(
        (route for route in scaffold_routes_node.findall("Route") if route.get("name") == "Master"),
        None,
    )
    if native_master is None or scaffold_master is None:
        raise ArdourExportError("cannot graft native Master route: route missing")
    _replace_route(
        scaffold_routes_node,
        scaffold_master,
        _master_route_with_scaffold_output(native_master, scaffold_master),
    )

    try:
        scaffold_counter = int(scaffold_root.get("id-counter", "0"))
        native_counter = int(native_root.get("id-counter", "0"))
        scaffold_root.set("id-counter", str(max(scaffold_counter, native_counter)))
    except ValueError:
        pass
    if _session_timing_signature(scaffold_root) != timing_signature:
        raise ArdourExportError("internal error: processing graft changed MIDI/session timing structure")
    tree = ET.ElementTree(scaffold_root)
    ET.indent(tree, space="  ")
    tree.write(result.session_file, encoding="UTF-8", xml_declaration=True)

def _update_processing_status(
    result: ArdourExportResult,
    *,
    status: str,
    ardour_lua: Path | None = None,
    error: str | None = None,
) -> None:
    try:
        data = json.loads(result.export_manifest.read_text(encoding="utf8"))
        processing = data.setdefault("processing_transport", {})
        processing["status"] = status
        if ardour_lua is not None:
            processing["ardour_lua"] = str(ardour_lua)
        if error is None:
            processing.pop("error", None)
        else:
            processing["error"] = error
        result.export_manifest.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf8")
    except (OSError, ValueError, TypeError):
        pass


def apply_ardour_processing(
    result: ArdourExportResult,
    *,
    ardour_lua: Path | str,
) -> subprocess.CompletedProcess[str]:
    """Instantiate editable processors without allowing Ardour to rewrite MIDI."""

    if result.processing_bootstrap is None:
        raise ArdourExportError("Ardour export has no processing bootstrap script")
    exe = Path(ardour_lua).expanduser().resolve()
    if not exe.is_file():
        raise ArdourExportError(f"Ardour Lua frontend does not exist: {exe}")
    scaffold_bytes = result.session_file.read_bytes()
    midi_snapshot = _snapshot_ardour_midi_sources(result)
    plugins_dir = result.session_dir / "plugins"
    plugin_dirs_before = {path.name for path in plugins_dir.iterdir()} if plugins_dir.is_dir() else set()
    command = [
        str(exe),
        str(result.processing_bootstrap),
        str(result.session_dir),
        result.session_file.stem,
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    details = "\n".join(part for part in (completed.stdout, completed.stderr) if part.strip())
    errors = _serialized_processing_errors(result)
    if "Ambition Ardour processing configured" not in completed.stdout:
        errors.append("processing bootstrap did not reach its post-save completion marker")
    if not errors:
        _restore_ardour_midi_sources(result, midi_snapshot)
        _graft_native_processing_onto_scaffold(result, scaffold_bytes=scaffold_bytes)
        post = _serialized_processing_errors(result)
        if not post:
            _update_processing_status(result, status="applied", ardour_lua=exe)
            return completed
        errors = post

    # Processing is deliberately a second transaction.  A failure must not
    # destroy the already-verified real instruments or the timing fix.
    result.session_file.write_bytes(scaffold_bytes)
    _restore_ardour_midi_sources(result, midi_snapshot)
    if plugins_dir.is_dir():
        for path in list(plugins_dir.iterdir()):
            if path.name not in plugin_dirs_before:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
    error_text = " | ".join(errors)
    if details:
        error_text = (error_text + "\n" + details).strip()
    _update_processing_status(result, status="failed", ardour_lua=exe, error=error_text)
    raise ArdourExportError(
        "Ardour mix/processing transport failed; the session was restored to the "
        "verified real-instrument mix-routing scaffold.\n" + error_text
    )


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
    realize_processing: bool = False,
    add_audition_synth: bool = True,
    force: bool = False,
) -> ArdourExportResult:
    """Create a ready-to-open Ardour 9 editing session for ``compiled``.

    The generated session is deliberately one-way scaffolding.  The adjacent
    neutral MIDI/interchange sidecar remain the round-trip boundary.
    """

    # ``add_audition_synth`` is retained for compatibility with the first
    # experimental CLI.  The safe architecture now requires exactly one
    # Reasonable Synth in the scaffold so libardour has one instrument to
    # replace atomically; serial backup instruments are deliberately gone.
    _ = add_audition_synth

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
        track_is_drum=[bool(inst.is_drum) for inst in compiled.pm.instruments],
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
    processing_transport = compile_processing_transport(compiled) if realize_processing else None
    # Always serialize the same single-instrument audition scaffold that was
    # validated interactively.  Real plugins are applied by libardour below.
    tree, track_state, mix_state = _build_session_xml(
        compiled,
        session_name=session_name,
        sample_rate=sample_rate,
        track_midis=track_midis,
        bpm=bpm,
        numerator=numerator,
        denominator=denominator,
        end_beats=end_beats,
        end_seconds=end_seconds,
        add_synth=True,
        transport_processing=bool(realize_processing),
    )
    ET.indent(tree, space="  ")
    session_file = destination / f"{session_name}.ardour"
    tree.write(session_file, encoding="UTF-8", xml_declaration=True)
    instrument_bootstrap = _write_ardour_instrument_bootstrap(
        destination,
        session_name=session_name,
        realizations=(realizations if realize_instruments else []),
    )
    processing_bootstrap = (
        _write_ardour_processing_bootstrap(destination, transport=processing_transport, mix_state=mix_state)
        if processing_transport is not None
        else None
    )

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
            "method": "ardour_lua_replace_single_instrument",
            "bootstrap": str(instrument_bootstrap.relative_to(destination)),
            "sfz_plugin": "sfizz",
            "sfz_plugin_uri": SFIZZ_URI,
            "soundfont_plugin": "ACE Fluid Synth",
            "soundfont_plugin_uri": ACE_FLUID_SYNTH_URI,
            "local_asset_paths": True,
            "asset_verification": "serialized_lv2_state_retry_verify",
            "session_merge": "plugin_processor_graft_onto_pristine_scaffold",
            "status": "pending" if realize_instruments else "audition_only",
        },
        "processing_transport": {
            "enabled": bool(realize_processing),
            "method": "canonical_processing_plan_to_libardour_native_group_buses",
            "session_merge": "libardour_native_bus_graph_onto_pristine_timing_scaffold",
            "bootstrap": (
                str(processing_bootstrap.relative_to(destination))
                if processing_bootstrap is not None
                else None
            ),
            "status": "pending" if realize_processing else "disabled",
            "mix_routing": mix_state,
            "plan": processing_transport.as_dict() if processing_transport is not None else None,
        },
        "audition": {
            "plugin": "ACE Reasonable Synth",
            "plugin_uri": ACE_REASONABLE_SYNTH_URI,
            "purpose": "known-good neutral MIDI composition audit and safe pre-realization scaffold",
        },
        "tracks": [
            {**state, **realization.to_manifest()}
            for state, realization in zip(track_state, realizations)
        ],
        "limitations": [
            "Ardour session tempo/meter scaffolding currently requires constant tempo and meter.",
            "The generated Ardour session references machine-local SFZ/SoundFont paths and is not a portable sample bundle.",
            "Real plugins are created and serialized by Ardour/libardour, then only the verified instrument Processor nodes are grafted onto the pristine timing scaffold.",
            "Ardour per-track MIDI preserves the neutral interchange channel assignment; route separation provides instrument isolation without rewriting channels.",
            "Procedural-FM and unsupported backend realizations remain on the neutral audition synth.",
            "ACE Fluid Synth realization uses SF2 only; SF3 compatibility depends on the FluidSynth version bundled into Ardour.",
            "Group/master processing is transported from canonical ProcessingPlan objects onto editable Ardour buses; the manifest records approximations and omitted operations.",
            "Renderer transient_tame, stereo_width, soft limiter/normalization, loudness, VST3/command effects, and renderer-level wet_mix are not yet exact Ardour equivalents.",
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
                "The XML scaffold starts with exactly one ACE Reasonable Synth per MIDI track.",
                "That is the known-good audible editing baseline.",
                "",
                "Real SFZ/SoundFont instruments are applied by Ardour's own Lua/libardour frontend",
                "using ambition/apply_real_instruments.lua. Ardour saves its own LV2 state; Python",
                "then verifies those serialized state directories and retries from the pristine",
                "audition scaffold with longer settle windows when a large asset is not ready yet.",
                "",
                "Once a real instrument is applied, swap it in Ardour's processor box without touching",
                "the MIDI region. Unsupported instruments remain on ACE Reasonable Synth.",
                "",
                "The Master bus intentionally has no instrument plugin.",
                "The session does not pin an audio backend or hardware device; Ardour should use your current setup.",
                "",
                "The `ambition/` directory contains the DAW-neutral MIDI + MusicIR provenance sidecar.",
                "Do not use this session XML as the future round-trip authority.",
                "",
                "When processing transport is enabled, tracks feed semantic group buses, then AMB Composition,",
                "then Master. Instrument mix_gain_db and section stem_mix_db riders are visible in the mixer,",
                "and canonical group/master processing is instantiated as editable Ardour processors.",
                "The export manifest records every approximation/omission (notably soft limiting/normalization,",
                "stereo-width/transient-tame, and renderer-level wet/dry blends).",
                f"See {EXPORT_MARKER} for instrument and processing transport status.",
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
        instrument_bootstrap=instrument_bootstrap,
        processing_bootstrap=processing_bootstrap,
    )
