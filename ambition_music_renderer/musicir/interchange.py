"""DAW-oriented MIDI interchange for compiled MusicIR scores.

The interchange format is deliberately DAW-neutral.  Ardour and REAPER both
understand Standard MIDI Files, while the JSON sidecar preserves MusicIR-only
identity/provenance that SMF cannot represent reliably.  Export is useful now;
source reconciliation/import is implemented against this stable contract rather
than against DAW-specific project XML.
"""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import mido

from .model import CompiledScore, compiled_score_fingerprint
from .normalize import MUSICIR_V2_SCHEMA, MUSICIR_V3_SCHEMA
from ..render.exact_score import ExactTempoMap, ScoreClock
from ..render.export import timeline_markers_from_spec, write_marked_midi


INTERCHANGE_SCHEMA = "ambition.musicir.daw_interchange.v1"


def _timing_score(compiled: CompiledScore) -> dict[str, Any] | None:
    """Recover the exact clock description for v2/v3 compiled scores."""

    if compiled.canonical_schema == MUSICIR_V2_SCHEMA:
        return copy.deepcopy(compiled.normalized_spec.get("score") or {})
    if compiled.canonical_schema == MUSICIR_V3_SCHEMA and compiled.authoring_graph:
        graph = compiled.authoring_graph
        score: dict[str, Any] = {
            "timebase": {"ppq": int(graph.get("ppq", compiled.pm.resolution))},
            "meter": copy.deepcopy(graph.get("meter") or []),
            "tempo": copy.deepcopy(graph.get("tempo") or []),
            "form": copy.deepcopy(graph.get("form") or []),
        }
        if graph.get("end") is not None:
            score["end"] = copy.deepcopy(graph["end"])
        if compiled.exact_metadata and compiled.exact_metadata.get("end_tick") is not None:
            score["end_tick"] = int(compiled.exact_metadata["end_tick"])
        return score
    return None


def _append_absolute_track(
    track: mido.MidiTrack,
    events: Iterable[tuple[int, int, int, mido.Message | mido.MetaMessage]],
    *,
    end_tick: int = 0,
) -> None:
    rows = sorted(events, key=lambda item: (item[0], item[1], item[2]))
    previous = 0
    for tick, _priority, _order, message in rows:
        tick = max(0, int(tick))
        track.append(message.copy(time=max(0, tick - previous)))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=max(0, int(end_tick) - previous)))


def _tempo_points(tempo: ExactTempoMap, *, ppq: int, end_tick: int) -> list[tuple[int, float]]:
    """Sample exact MusicIR tempo curves into ordinary SMF tempo events."""

    points: dict[int, float] = {}
    ramp_step = max(1, int(ppq) // 4)  # sixteenth-note sampling for DAW previews
    for seg in tempo.segments:
        start = max(0, int(seg.start_tick))
        stop = int(seg.end_tick) if seg.end_tick is not None else int(end_tick)
        stop = max(start, min(stop, int(end_tick)))
        if seg.curve == "step" or abs(float(seg.start_bpm) - float(seg.end_bpm)) < 1e-12:
            points[start] = float(seg.start_bpm)
            continue
        tick = start
        while tick < stop:
            points[tick] = float(tempo.bpm_at_tick(tick))
            tick += ramp_step
        points[stop] = float(tempo.bpm_at_tick(stop))
    if 0 not in points:
        points[0] = float(tempo.bpm_at_tick(0))
    return sorted(points.items())


def _instrument_channel(index: int, *, is_drum: bool) -> int:
    if is_drum:
        return 9
    melodic = [channel for channel in range(16) if channel != 9]
    return melodic[index % len(melodic)]


def write_compiled_midi(compiled: CompiledScore, midi_path: str | Path) -> Path:
    """Write a DAW-friendly MIDI file from the canonical compiled score.

    V2/v3 scores are written from their exact tick clock instead of asking
    PrettyMIDI to reconstruct one from seconds.  V1 keeps the historical writer
    because its source model is beat/seconds based rather than tick-authoritative.
    """

    midi_path = Path(midi_path)
    midi_path.parent.mkdir(parents=True, exist_ok=True)
    timing = _timing_score(compiled)
    if timing is None:
        markers = timeline_markers_from_spec(compiled.normalized_spec, compiled.sections)
        write_marked_midi(compiled.pm, midi_path, markers)
        return midi_path

    clock = ScoreClock(timing)
    tempo = ExactTempoMap(timing, clock).bind_ppq(clock.ppq)
    end_tick = int((compiled.exact_metadata or {}).get("end_tick", 0) or 0)
    if end_tick <= 0:
        end_tick = max(
            [0]
            + [
                tempo.time_to_tick(note.end, hint_max_tick=clock.ppq * 16)
                for inst in compiled.pm.instruments
                for note in inst.notes
            ]
        )

    mid = mido.MidiFile(type=1, ticks_per_beat=clock.ppq)
    conductor = mido.MidiTrack()
    conductor_events: list[tuple[int, int, int, mido.MetaMessage]] = []
    order = 0
    conductor_events.append((0, 0, order, mido.MetaMessage("track_name", name="MusicIR conductor", time=0)))
    order += 1
    for change in clock.meter_changes:
        conductor_events.append(
            (
                int(change.start_tick),
                10,
                order,
                mido.MetaMessage(
                    "time_signature",
                    numerator=int(change.numerator),
                    denominator=int(change.denominator),
                    time=0,
                ),
            )
        )
        order += 1
    last_tempo: int | None = None
    for tick, bpm in _tempo_points(tempo, ppq=clock.ppq, end_tick=end_tick):
        micros = int(mido.bpm2tempo(float(bpm)))
        if micros == last_tempo:
            continue
        conductor_events.append((int(tick), 20, order, mido.MetaMessage("set_tempo", tempo=micros, time=0)))
        order += 1
        last_tempo = micros
    for section in compiled.sections:
        conductor_events.append(
            (
                int(section.get("start_tick", 0)),
                30,
                order,
                mido.MetaMessage("marker", text=str(section.get("label", section.get("id", "section"))), time=0),
            )
        )
        order += 1
    for hold in (compiled.exact_metadata or {}).get("holds", []) or []:
        conductor_events.append(
            (
                int(hold["tick"]),
                31,
                order,
                mido.MetaMessage(
                    "text",
                    text=f"MusicIR hold {float(hold['seconds']):.6f}s (SMF sidecar-authoritative)",
                    time=0,
                ),
            )
        )
        order += 1
    _append_absolute_track(conductor, conductor_events, end_tick=end_tick)
    mid.tracks.append(conductor)

    hint = max(end_tick, clock.ppq * 16)
    for inst_index, inst in enumerate(compiled.pm.instruments):
        channel = _instrument_channel(inst_index, is_drum=bool(inst.is_drum))
        track = mido.MidiTrack()
        events: list[tuple[int, int, int, mido.Message | mido.MetaMessage]] = []
        local_order = 0
        events.append((0, 0, local_order, mido.MetaMessage("track_name", name=str(inst.name), time=0)))
        local_order += 1
        if not inst.is_drum:
            events.append(
                (0, 10, local_order, mido.Message("program_change", channel=channel, program=int(inst.program), time=0))
            )
            local_order += 1
        for cc in inst.control_changes:
            tick = tempo.time_to_tick(float(cc.time), hint_max_tick=hint)
            events.append(
                (
                    tick,
                    20,
                    local_order,
                    mido.Message(
                        "control_change",
                        channel=channel,
                        control=int(cc.number),
                        value=int(cc.value),
                        time=0,
                    ),
                )
            )
            local_order += 1
        for bend in inst.pitch_bends:
            tick = tempo.time_to_tick(float(bend.time), hint_max_tick=hint)
            events.append(
                (
                    tick,
                    25,
                    local_order,
                    mido.Message("pitchwheel", channel=channel, pitch=int(bend.pitch), time=0),
                )
            )
            local_order += 1
        for note in inst.notes:
            start = tempo.time_to_tick(float(note.start), hint_max_tick=hint)
            stop = tempo.time_to_tick(float(note.end), hint_max_tick=hint)
            stop = max(start + 1, stop)
            # note_off sorts before a new note_on at the same coordinate.
            events.append(
                (
                    stop,
                    30,
                    local_order,
                    mido.Message("note_off", channel=channel, note=int(note.pitch), velocity=0, time=0),
                )
            )
            local_order += 1
            events.append(
                (
                    start,
                    40,
                    local_order,
                    mido.Message(
                        "note_on",
                        channel=channel,
                        note=int(note.pitch),
                        velocity=int(note.velocity),
                        time=0,
                    ),
                )
            )
            local_order += 1
        _append_absolute_track(track, events, end_tick=end_tick)
        mid.tracks.append(track)

    mid.save(str(midi_path))
    return midi_path


def read_midi_snapshot(midi_path: str | Path) -> dict[str, Any]:
    """Read the stable SMF subset used by DAW reconciliation.

    Notes/controllers are kept per track while conductor data is normalized into
    one top-level record. This accepts Ardour/Reaper exports that change SMF PPQ;
    the reconciler rescales coordinates back onto the interchange baseline.
    """

    mid = mido.MidiFile(str(midi_path))
    tracks: list[dict[str, Any]] = []
    conductor: dict[str, list[dict[str, Any]]] = {
        "tempos": [],
        "time_signatures": [],
        "markers": [],
    }
    for track_index, track in enumerate(mid.tracks):
        tick = 0
        name = f"track_{track_index}"
        active: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        notes: list[dict[str, int]] = []
        controls: list[dict[str, int]] = []
        bends: list[dict[str, int]] = []
        programs: list[dict[str, int]] = []
        for msg in track:
            tick += int(msg.time)
            if msg.type == "track_name":
                name = str(msg.name)
            elif msg.type == "note_on" and int(msg.velocity) > 0:
                active[(int(msg.channel), int(msg.note))].append((tick, int(msg.velocity)))
            elif msg.type in {"note_off", "note_on"}:
                key = (int(msg.channel), int(msg.note))
                if active[key]:
                    start, velocity = active[key].pop(0)
                    notes.append(
                        {
                            "start_tick": start,
                            "end_tick": tick,
                            "pitch": int(msg.note),
                            "velocity": velocity,
                            "channel": int(msg.channel),
                        }
                    )
            elif msg.type == "control_change":
                controls.append(
                    {
                        "tick": tick,
                        "controller": int(msg.control),
                        "value": int(msg.value),
                        "channel": int(msg.channel),
                    }
                )
            elif msg.type == "pitchwheel":
                bends.append({"tick": tick, "pitch": int(msg.pitch), "channel": int(msg.channel)})
            elif msg.type == "program_change":
                programs.append({"tick": tick, "program": int(msg.program), "channel": int(msg.channel)})
            elif msg.type == "set_tempo":
                conductor["tempos"].append({"tick": tick, "tempo": int(msg.tempo)})
            elif msg.type == "time_signature":
                conductor["time_signatures"].append(
                    {
                        "tick": tick,
                        "numerator": int(msg.numerator),
                        "denominator": int(msg.denominator),
                    }
                )
            elif msg.type == "marker":
                conductor["markers"].append({"tick": tick, "text": str(msg.text)})
        tracks.append(
            {
                "index": track_index,
                "name": name,
                "notes": sorted(notes, key=lambda row: (row["start_tick"], row["pitch"], row["end_tick"])),
                "controls": controls,
                "pitch_bends": bends,
                "program_changes": programs,
            }
        )
    for rows in conductor.values():
        rows.sort(key=lambda row: (int(row["tick"]), tuple(sorted(row.items()))))
    return {
        "ticks_per_beat": int(mid.ticks_per_beat),
        "tracks": tracks,
        "conductor": conductor,
    }


def _event_lookup(compiled: CompiledScore) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
    lookup: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    ppq = int(compiled.pm.resolution)
    for event in compiled.note_events:
        if str(event.get("event_type", "note")) not in {"note", "keyswitch"}:
            continue
        start_tick = event.get("start_tick")
        if start_tick is None:
            start_tick = int(round(float(event.get("start_beat", 0.0)) * ppq))
        key = (str(event.get("instrument")), int(event.get("pitch", -1)), int(start_tick))
        lookup[key].append(event)
    return lookup


def _controller_event_lookup(
    compiled: CompiledScore,
) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    """Index provenance-bearing controller events by their rendered MIDI identity."""

    lookup: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for event in compiled.controller_events:
        kind = str(event.get("event_type", ""))
        if kind == "control_change":
            key = (
                str(event.get("instrument")),
                kind,
                int(event.get("tick", 0)),
                int(event.get("controller", -1)),
                int(event.get("value", -1)),
            )
        elif kind == "pitch_bend":
            key = (
                str(event.get("instrument")),
                kind,
                int(event.get("tick", 0)),
                int(event.get("pitch", 0)),
            )
        else:
            continue
        lookup[key].append(event)
    return lookup


def _source_regions_from_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize v3 clip-owned MIDI spans for assigning newly drawn DAW notes."""

    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for track in tracks:
        instrument = str(track.get("instrument", ""))
        for kind in ("notes", "controls", "pitch_bends"):
            for event in track.get(kind, []) or []:
                ref = event.get("source_ref") or {}
                if not ref.get("clip_id"):
                    continue
                key = (
                    str(ref.get("part_id", "")),
                    str(ref.get("voice_id", "")),
                    str(ref.get("clip_id", "")),
                    instrument,
                )
                start = int(event.get("start_tick", event.get("tick", 0)))
                end = int(event.get("end_tick", start + 1))
                source_kind = (
                    f"generator:{ref['generator_kind']}"
                    if ref.get("generator_kind")
                    else "material" if ref.get("material_id")
                    else "events"
                )
                row = grouped.setdefault(
                    key,
                    {
                        "part_id": key[0],
                        "voice_id": key[1],
                        "clip_id": key[2],
                        "instrument": key[3],
                        "source_kind": source_kind,
                        "start_tick": start,
                        "end_tick": max(start + 1, end),
                    },
                )
                row["start_tick"] = min(int(row["start_tick"]), start)
                row["end_tick"] = max(int(row["end_tick"]), max(start + 1, end))
    return sorted(
        grouped.values(),
        key=lambda row: (row["instrument"], row["start_tick"], row["clip_id"]),
    )


def _baseline_conductor(compiled: CompiledScore, timing: dict[str, Any] | None) -> dict[str, Any] | None:
    if timing is None:
        return None
    clock = ScoreClock(timing)
    tempo = ExactTempoMap(timing, clock).bind_ppq(clock.ppq)
    end_tick = int((compiled.exact_metadata or {}).get("end_tick", 0) or 0)
    tempos: list[dict[str, int]] = []
    last_tempo: int | None = None
    for tick, bpm in _tempo_points(tempo, ppq=clock.ppq, end_tick=end_tick):
        micros = int(mido.bpm2tempo(float(bpm)))
        if micros == last_tempo:
            continue
        tempos.append({"tick": int(tick), "tempo": micros})
        last_tempo = micros
    time_signatures = [
        {
            "tick": int(change.start_tick),
            "numerator": int(change.numerator),
            "denominator": int(change.denominator),
        }
        for change in clock.meter_changes
    ]
    markers = [
        {
            "tick": int(section.get("start_tick", 0)),
            "text": str(section.get("label", section.get("id", "section"))),
        }
        for section in compiled.sections
    ]
    return {"tempos": tempos, "time_signatures": time_signatures, "markers": markers}


def build_interchange_manifest(compiled: CompiledScore, *, midi_filename: str) -> dict[str, Any]:
    """Build the source-provenance sidecar paired with a DAW MIDI export."""

    timing = _timing_score(compiled)
    tempo: ExactTempoMap | None = None
    hint = int((compiled.exact_metadata or {}).get("end_tick", 0) or 0)
    if timing is not None:
        clock = ScoreClock(timing)
        tempo = ExactTempoMap(timing, clock).bind_ppq(clock.ppq)
        hint = max(hint, clock.ppq * 16)
    event_lookup = _event_lookup(compiled)
    controller_lookup = _controller_event_lookup(compiled)
    tracks: list[dict[str, Any]] = []
    all_source_mapped = True
    source_mapped_controllers = 0
    authored_controllers = sum(
        1 for event in compiled.controller_events if event.get("source_ref")
    )
    for inst in compiled.pm.instruments:
        notes: list[dict[str, Any]] = []
        for ordinal, note in enumerate(inst.notes):
            if tempo is not None:
                start_tick = tempo.time_to_tick(note.start, hint_max_tick=hint)
                end_tick = tempo.time_to_tick(note.end, hint_max_tick=hint)
            else:
                start_tick = int(round(compiled.pm.time_to_tick(note.start)))
                end_tick = int(round(compiled.pm.time_to_tick(note.end)))
            key = (str(inst.name), int(note.pitch), int(start_tick))
            source = event_lookup[key].pop(0) if event_lookup.get(key) else None
            row: dict[str, Any] = {
                "ordinal": ordinal,
                "start_tick": start_tick,
                "end_tick": max(start_tick + 1, end_tick),
                "pitch": int(note.pitch),
                "velocity": int(note.velocity),
            }
            if source and source.get("event_id"):
                row["event_id"] = str(source["event_id"])
                row["source_ref"] = copy.deepcopy(source.get("source_ref"))
            else:
                all_source_mapped = False
                row["event_id"] = f"compiled/{inst.name}/{ordinal:06d}"
            notes.append(row)
        controls: list[dict[str, Any]] = []
        for ordinal, cc in enumerate(inst.control_changes):
            if tempo is not None:
                tick = tempo.time_to_tick(cc.time, hint_max_tick=hint)
            else:
                tick = int(round(compiled.pm.time_to_tick(cc.time)))
            key = (str(inst.name), "control_change", int(tick), int(cc.number), int(cc.value))
            source = controller_lookup[key].pop(0) if controller_lookup.get(key) else None
            row = {
                "ordinal": ordinal,
                "tick": int(tick),
                "controller": int(cc.number),
                "value": int(cc.value),
            }
            if source is not None:
                row["compiled_source"] = True
            if source and source.get("event_id"):
                row["event_id"] = str(source["event_id"])
                row["source_ref"] = copy.deepcopy(source.get("source_ref"))
                if source.get("source_ref"):
                    source_mapped_controllers += 1
            controls.append(row)
        pitch_bends: list[dict[str, Any]] = []
        for ordinal, bend in enumerate(inst.pitch_bends):
            if tempo is not None:
                tick = tempo.time_to_tick(bend.time, hint_max_tick=hint)
            else:
                tick = int(round(compiled.pm.time_to_tick(bend.time)))
            key = (str(inst.name), "pitch_bend", int(tick), int(bend.pitch))
            source = controller_lookup[key].pop(0) if controller_lookup.get(key) else None
            row = {"ordinal": ordinal, "tick": int(tick), "pitch": int(bend.pitch)}
            if source is not None:
                row["compiled_source"] = True
            if source and source.get("event_id"):
                row["event_id"] = str(source["event_id"])
                row["source_ref"] = copy.deepcopy(source.get("source_ref"))
                if source.get("source_ref"):
                    source_mapped_controllers += 1
            pitch_bends.append(row)
        tracks.append(
            {
                "track_id": str(inst.name),
                "midi_track_index": len(tracks) + 1,
                "instrument": str(inst.name),
                "group": compiled.groups.get(str(inst.name), str(inst.name)),
                "program": int(inst.program),
                "is_drum": bool(inst.is_drum),
                "notes": notes,
                "controls": controls,
                "pitch_bends": pitch_bends,
            }
        )
    holds = list((compiled.exact_metadata or {}).get("holds", []) or [])
    return {
        "schema": INTERCHANGE_SCHEMA,
        "score_id": str(compiled.normalized_spec.get("id", "")),
        "source_schema": compiled.source_schema,
        "canonical_schema": compiled.canonical_schema,
        "compiled_score_fingerprint": compiled_score_fingerprint(compiled),
        "authoring_graph_fingerprint": compiled.authoring_graph_fingerprint,
        "midi": {
            "filename": str(midi_filename),
            "ppq": int(compiled.pm.resolution),
            "exact_clock": timing is not None,
            "tempo_ramps_sampled_to_smf": bool(
                timing
                and any(
                    seg.get("curve") != "step" and seg.get("start_bpm") != seg.get("end_bpm")
                    for seg in (compiled.exact_metadata or {}).get("tempo_segments", []) or []
                )
            ),
            "holds_sidecar_authoritative": bool(holds),
            "conductor": _baseline_conductor(compiled, timing),
        },
        "tracks": tracks,
        "source_regions": _source_regions_from_tracks(tracks),
        "form": copy.deepcopy(compiled.sections),
        "roundtrip": {
            "source_mapping": "stable" if all_source_mapped else "compiled-event",
            "controller_source_mapping": (
                "stable"
                if authored_controllers and source_mapped_controllers == authored_controllers
                else "none" if not authored_controllers else "partial"
            ),
            "automatic_musicir_import": True,
            "notes": (
                "V3 clip/event provenance is preserved in this sidecar. MIDI cannot carry these ids "
                "portably, so the importer reconciles edited MIDI against this saved baseline and "
                "lowers only affected v3 clips when applying note edits."
            ),
        },
    }


def export_interchange_bundle(
    compiled: CompiledScore,
    destination: str | Path,
    *,
    stem: str | None = None,
) -> dict[str, Path]:
    """Write ``.mid`` + MusicIR provenance sidecar for DAW editing."""

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    base = stem or str(compiled.normalized_spec.get("id", "score"))
    midi_path = destination / f"{base}.mid"
    manifest_path = destination / f"{base}.musicir-interchange.json"
    write_compiled_midi(compiled, midi_path)
    manifest = build_interchange_manifest(compiled, midi_filename=midi_path.name)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf8")
    return {"midi": midi_path, "manifest": manifest_path}
