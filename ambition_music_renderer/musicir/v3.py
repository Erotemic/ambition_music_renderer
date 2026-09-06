"""MusicIR v3 compiler: exact clips + reusable material + procedural generators.

V3 is an authoring graph above ``CompiledScore``.  Exact material and procedural
material may coexist in the same voice.  Procedural generators currently reuse
the proven v1 layer implementations through a compatibility bridge; their
expanded MIDI is then placed on the exact v3 clock.  This keeps musical behavior
stable while the authoring model evolves independently of those implementations.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict, deque
from typing import Any, Iterable, Mapping

import pretty_midi

from .automation import expand_automation
from .graph import (
    NormalizedScoreGraph,
    SourceRef,
    authoring_graph_fingerprint,
    fraction_to_ticks,
    normalize_v3_score_graph,
)
from .midi import add_initial_controls, create_midi_instrument
from .model import CompiledScore
from .generators import get_generator_spec, public_generator_names, validate_generator_mapping
from .pitch import resolve_pitch
from .transforms import ClipTransform, clip_transform
from ..technique_catalog import technique_default_gate
from ..render.exact_score import ExactTempoMap, ScoreClock, _form_metadata
from ..render.score_layers import compile_procedural_score
from ..render.score_theory import midi_to_note
from ..render.synth import sanitize_same_pitch_overlaps


MUSICIR_V3_SCHEMA = "ambition.musicir.v3"

# Compatibility/readability view derived from the checked-in generator catalog.
# The JSON catalog remains the authority; do not hand-maintain another map here.
GENERATOR_KINDS = {
    name: get_generator_spec(name).bridge_kind for name in public_generator_names()
}


def _stable_seed(seed: int, *parts: str) -> int:
    text = "\0".join([str(seed), *parts]).encode("utf8")
    digest = hashlib.sha256(text).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFF


def _clip_semantic_seed(seed: int, clip: Mapping[str, Any], part: Mapping[str, Any], repeat_index: int) -> int:
    payload = copy.deepcopy(dict(clip))
    payload.pop("id", None)
    payload["_resolved_part_instrument"] = part.get("instrument", part.get("id"))
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return _stable_seed(seed, text, str(repeat_index))


def _event_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return copy.deepcopy(dict(raw))
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        raise ValueError(
            "MusicIR v3 compact events need [at, dur, pitch-or-pitches, velocity]"
        )
    row: dict[str, Any] = {
        "at": copy.deepcopy(raw[0]),
        "dur": copy.deepcopy(raw[1]),
        "pitch": copy.deepcopy(raw[2]),
        "velocity": raw[3],
    }
    if len(raw) >= 5:
        row["technique"] = raw[4]
    return row


def _pitch_values(row: Mapping[str, Any]) -> list[Any]:
    if "pitches" in row:
        values = row["pitches"]
    else:
        values = row.get("pitch")
    if isinstance(values, (list, tuple)):
        return list(values)
    if values is None:
        raise ValueError(f"MusicIR v3 event is missing pitch/pitches: {row}")
    return [values]



def _expand_event_material(
    graph: NormalizedScoreGraph,
    material_id: str,
    *,
    stack: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Expand event/sequence material while preserving its derivation chain."""

    if material_id in stack:
        chain = " -> ".join([*stack, material_id])
        raise ValueError(f"MusicIR v3 material cycle: {chain}")
    material = graph.materials[material_id]
    kind = str(material.get("kind"))
    if kind == "motif":
        raise ValueError(
            f"MusicIR v3 material {material_id!r} is a motif; use a motif-aware generator instead"
        )
    if kind == "events":
        rows: list[dict[str, Any]] = []
        for raw in material.get("events") or []:
            row = _event_mapping(raw)
            row.setdefault("_material_chain", [material_id])
            rows.append(row)
        return rows
    if kind != "sequence":
        raise ValueError(f"unsupported MusicIR v3 event material kind {kind!r}")

    out: list[dict[str, Any]] = []
    for item_index, item_raw in enumerate(material.get("items") or []):
        item = copy.deepcopy(dict(item_raw))
        child_id = str(item["use"])
        if child_id not in graph.materials:
            raise KeyError(f"MusicIR v3 sequence material {material_id!r} references unknown material {child_id!r}")
        child_rows = _expand_event_material(graph, child_id, stack=(*stack, material_id))
        transform = clip_transform(item)
        item_at = fraction_to_ticks(item.get("at", 0), ppq=graph.ppq)
        child_span = _event_span_ticks(child_rows, ppq=graph.ppq)
        transformed_span = transform.transform_tick_offset(child_span)
        repeat = item.get("repeat", 1)
        if isinstance(repeat, Mapping):
            count = int(repeat.get("count", 1))
            every_raw = repeat.get("every")
            every = (
                fraction_to_ticks(every_raw, ppq=graph.ppq)
                if every_raw is not None
                else transformed_span
            )
        else:
            count = int(repeat)
            every = transformed_span
        if count <= 0:
            raise ValueError(f"MusicIR v3 sequence material {material_id!r} repeat count must be > 0")
        item_name = str(item.get("id", f"item{item_index:03d}"))
        for repeat_index in range(count):
            instance_base = item_at + repeat_index * every
            for child in child_rows:
                row = copy.deepcopy(child)
                child_at = fraction_to_ticks(row.get("at", 0), ppq=graph.ppq)
                child_dur = fraction_to_ticks(row.get("dur", row.get("duration")), ppq=graph.ppq)
                row["at"] = {"ticks": instance_base + transform.transform_tick_offset(child_at)}
                row["dur"] = {"ticks": transform.transform_duration_ticks(child_dur)}
                row["velocity"] = transform.transform_velocity(row.get("velocity", 80))
                row["_material_semitones"] = int(row.get("_material_semitones", 0)) + transform.semitones
                row["_material_gate"] = float(row.get("_material_gate", 1.0)) * transform.gate
                row["_material_chain"] = [material_id, *list(row.get("_material_chain") or [child_id])]
                source_id = str(row.get("id", f"e{len(out):04d}"))
                row["_material_source_event_id"] = f"{item_name}.r{repeat_index:03d}.{source_id}"
                authored_technique = item.get("technique", item.get("articulation"))
                if authored_technique is not None and "technique" not in row and "articulation" not in row:
                    row["technique"] = copy.deepcopy(authored_technique)
                out.append(row)
    return out


def _material_event_rows(graph: NormalizedScoreGraph, clip: Mapping[str, Any]) -> tuple[list[Any], str | None]:
    if "events" in clip:
        return list(clip.get("events") or []), None
    material_id = str(clip["use"])
    return _expand_event_material(graph, material_id), material_id


def _event_span_ticks(rows: Iterable[Any], *, ppq: int) -> int:
    end = 0
    for raw in rows:
        row = _event_mapping(raw)
        start = fraction_to_ticks(row.get("at", 0), ppq=ppq)
        dur = fraction_to_ticks(row.get("dur", row.get("duration")), ppq=ppq)
        end = max(end, start + dur)
    return end


def _shift_position_bars(clock: ScoreClock, position: Any, bars: int) -> int:
    if not isinstance(position, Mapping) or "bar" not in position:
        raise ValueError("repeat.every: {bars: N} requires a clip `at` position with a bar")
    shifted = copy.deepcopy(dict(position))
    shifted["bar"] = int(shifted["bar"]) + int(bars)
    return clock.position_to_tick(shifted)


def _repeat_bases(
    clip: Mapping[str, Any],
    *,
    clock: ScoreClock,
    default_span_ticks: int,
) -> list[int]:
    at = clip.get("at", {"tick": 0})
    base = clock.position_to_tick(at)
    repeat = clip.get("repeat", 1)
    if isinstance(repeat, Mapping):
        count = int(repeat.get("count", 1))
        every = repeat.get("every")
    else:
        count = int(repeat)
        every = None
    if count <= 0:
        raise ValueError(f"MusicIR v3 clip {clip['id']!r} repeat count must be > 0")
    if count == 1:
        return [base]
    if every is None:
        if default_span_ticks <= 0:
            raise ValueError(
                f"MusicIR v3 clip {clip['id']!r} needs repeat.every because its source has no duration"
            )
        return [base + i * default_span_ticks for i in range(count)]
    if isinstance(every, Mapping) and "bars" in every:
        bar_step = int(every["bars"])
        return [_shift_position_bars(clock, at, i * bar_step) for i in range(count)]
    step = fraction_to_ticks(every, ppq=clock.ppq)
    return [base + i * step for i in range(count)]



def _automation_rows_for_clip(
    graph: NormalizedScoreGraph,
    *,
    part: Mapping[str, Any],
    voice_id: str,
    clip: Mapping[str, Any],
    clock: ScoreClock,
) -> list[dict[str, Any]]:
    """Lower v3 clip-local controller points onto the exact score clock."""

    authored_automation = clip.get("automation") or []
    if not authored_automation:
        return []
    raw_points = expand_automation(authored_automation, ppq=graph.ppq)
    transform = clip_transform(clip)
    if "generate" in clip:
        bars = _generator_bars(clip)
        bases = _generator_instance_bases(clip, clock=clock, bars=bars)
    else:
        raw_events, _material_id = _material_event_rows(graph, clip)
        source_span = _event_span_ticks(raw_events, ppq=graph.ppq)
        # Automation can define the useful span even for an event-light clip.
        automation_span = 0
        for point in raw_points:
            if not isinstance(point, Mapping):
                raise TypeError(
                    f"MusicIR v3 clip {clip['id']!r} automation points must be mappings"
                )
            automation_span = max(
                automation_span,
                fraction_to_ticks(point.get("at", 0), ppq=graph.ppq) + 1,
            )
        span = transform.transform_tick_offset(max(source_span, automation_span))
        bases = _repeat_bases(clip, clock=clock, default_span_ticks=span)

    part_id = str(part["id"])
    default_instrument = str(
        clip.get("instrument", part.get("instrument", part_id))
    )
    out: list[dict[str, Any]] = []
    for repeat_index, base_tick in enumerate(bases):
        for point_index, raw_point in enumerate(raw_points):
            if not isinstance(raw_point, Mapping):
                raise TypeError(
                    f"MusicIR v3 clip {clip['id']!r} automation[{point_index}] must be a mapping"
                )
            point = copy.deepcopy(dict(raw_point))
            has_cc = "cc" in point or "controller" in point
            has_bend = "pitch_bend" in point or "bend" in point
            if has_cc == has_bend:
                raise ValueError(
                    f"MusicIR v3 clip {clip['id']!r} automation[{point_index}] must define "
                    "exactly one of cc/controller or pitch_bend/bend"
                )
            if has_cc and "value" not in point:
                raise ValueError(
                    f"MusicIR v3 clip {clip['id']!r} automation[{point_index}] CC needs value"
                )
            local_tick = fraction_to_ticks(point.get("at", 0), ppq=graph.ppq)
            tick = base_tick + transform.transform_tick_offset(local_tick)
            source_event_id = (
                str(point["id"]) if point.get("id") is not None else f"automation_{point_index:04d}"
            )
            source_ref = SourceRef(
                score_id=graph.score_id,
                part_id=part_id,
                voice_id=voice_id,
                clip_id=str(clip["id"]),
                repeat_index=repeat_index,
                event_index=point_index,
                source_event_id=source_event_id,
            )
            ref = source_ref.as_dict()
            ref["source_kind"] = "automation_curve" if point.get("_curve_id") else "automation"
            if point.get("_curve_id"):
                ref["curve_id"] = str(point["_curve_id"])
                ref["curve_interpolation"] = str(point.get("_curve_interpolation", "linear"))
            row: dict[str, Any] = {
                "tick": tick,
                "instrument": str(point.get("instrument", default_instrument)),
                "_source_ref": ref,
            }
            event_base = source_ref.event_id(pitch_index=0).rsplit("/p00", 1)[0]
            if has_cc:
                row["cc"] = copy.deepcopy(point.get("cc", point.get("controller")))
                row["value"] = point["value"]
                row["_event_id"] = f"{event_base}/cc"
            else:
                row["pitch_bend"] = point.get("pitch_bend", point.get("bend"))
                row["_event_id"] = f"{event_base}/bend"
            out.append(row)
    return out

def _lower_exact_clips(
    graph: NormalizedScoreGraph,
    *,
    clock: ScoreClock,
) -> tuple[list[dict[str, Any]], int]:
    parts_out: list[dict[str, Any]] = []
    max_end_tick = 0
    for part in graph.parts:
        part_id = str(part["id"])
        part_out: dict[str, Any] = {
            "id": part_id,
            "instrument": str(part.get("instrument", part_id)),
        }
        for key in ("group", "technique_map", "controls"):
            if key in part:
                part_out[key] = copy.deepcopy(part[key])
        voices_out: list[dict[str, Any]] = []
        for voice in part.get("voices", []) or []:
            voice_id = str(voice["id"])
            rows_out: list[dict[str, Any]] = []
            for clip in voice.get("clips", []) or []:
                if "generate" in clip:
                    continue
                raw_rows, material_id = _material_event_rows(graph, clip)
                transform = clip_transform(clip)
                source_span = _event_span_ticks(raw_rows, ppq=graph.ppq)
                span = transform.transform_tick_offset(source_span)
                repeat_bases = _repeat_bases(clip, clock=clock, default_span_ticks=span)
                for repeat_index, base_tick in enumerate(repeat_bases):
                    for event_index, raw in enumerate(raw_rows):
                        row = _event_mapping(raw)
                        source_rel_tick = fraction_to_ticks(row.get("at", 0), ppq=graph.ppq)
                        source_dur_ticks = fraction_to_ticks(
                            row.get("dur", row.get("duration")), ppq=graph.ppq
                        )
                        rel_tick = transform.transform_tick_offset(source_rel_tick)
                        dur_ticks = transform.transform_duration_ticks(source_dur_ticks)
                        event_tick = base_tick + rel_tick
                        material_semitones = int(row.get("_material_semitones", 0))
                        pitches = [
                            transform.transform_pitch(
                                resolve_pitch(
                                    value, graph=graph, clock=clock, tick=event_tick
                                ) + material_semitones
                            )
                            for value in _pitch_values(row)
                        ]
                        velocity = transform.transform_velocity(row.get("velocity", 80))
                        source_ref = SourceRef(
                            score_id=graph.score_id,
                            part_id=part_id,
                            voice_id=voice_id,
                            clip_id=str(clip["id"]),
                            material_id=material_id,
                            material_chain=(
                                tuple(map(str, row.get("_material_chain") or [])) or None
                            ),
                            repeat_index=repeat_index,
                            event_index=event_index,
                            source_event_id=(
                                str(row.get("_material_source_event_id"))
                                if row.get("_material_source_event_id") is not None
                                else (str(row["id"]) if row.get("id") is not None else None)
                            ),
                        )
                        authored_technique = row.get(
                            "technique",
                            row.get(
                                "articulation",
                                clip.get("technique", clip.get("articulation")),
                            ),
                        )
                        # No authored technique means exact v3 events retain the
                        # v2/exact-score duration contract. Technique-specific
                        # gates are opt-in authoring semantics, not an implicit
                        # reinterpretation of otherwise literal notes.
                        technique_gate = (
                            technique_default_gate(
                                str(authored_technique), allow_custom=True
                            )
                            if authored_technique is not None
                            else 1.0
                        )
                        out: dict[str, Any] = {
                            "tick": event_tick,
                            "dur_ticks": dur_ticks,
                            "velocity": velocity,
                            "gate": (
                                float(row.get("gate", technique_gate))
                                * float(row.get("_material_gate", 1.0))
                                * transform.gate
                            ),
                            "_source_ref": source_ref.as_dict(),
                            "_event_id_base": source_ref.event_id(pitch_index=0).rsplit("/p00", 1)[0],
                        }
                        if len(pitches) == 1:
                            out["pitch"] = pitches[0]
                        else:
                            out["pitches"] = pitches
                        for key in ("technique", "articulation", "instrument"):
                            if key in row:
                                out[key] = copy.deepcopy(row[key])
                            elif key in clip:
                                out[key] = copy.deepcopy(clip[key])
                        rows_out.append(out)
                        max_end_tick = max(max_end_tick, event_tick + dur_ticks)
            voices_out.append({"id": voice_id, "events": rows_out})
        part_out["voices"] = voices_out
        controls = list(copy.deepcopy(part.get("controls") or []))
        for voice in part.get("voices", []) or []:
            voice_id = str(voice["id"])
            for clip in voice.get("clips", []) or []:
                controls.extend(
                    _automation_rows_for_clip(
                        graph, part=part, voice_id=voice_id, clip=clip, clock=clock
                    )
                )
        if controls:
            part_out["controls"] = controls
        parts_out.append(part_out)
    return parts_out, max_end_tick


def _generator_bars(clip: Mapping[str, Any]) -> int:
    duration = clip.get("duration")
    if duration is None and "bars" in clip:
        duration = {"bars": clip["bars"]}
    if isinstance(duration, Mapping) and "bars" in duration:
        bars = int(duration["bars"])
    else:
        raise ValueError(
            f"MusicIR v3 generator clip {clip['id']!r} currently requires duration: {{bars: N}}"
        )
    if bars <= 0:
        raise ValueError(f"MusicIR v3 generator clip {clip['id']!r} duration bars must be > 0")
    return bars


def _generator_instance_bases(
    clip: Mapping[str, Any], *, clock: ScoreClock, bars: int
) -> list[int]:
    at = clip.get("at", {"bar": 1, "beat": 1})
    base = clock.position_to_tick(at)
    source_span = _shift_position_bars(clock, at, bars) - base
    transformed_span = clip_transform(clip).transform_tick_offset(source_span)
    return _repeat_bases(clip, clock=clock, default_span_ticks=transformed_span)


def _require_generator_region(
    *,
    clip: Mapping[str, Any],
    clock: ScoreClock,
    tempo: ExactTempoMap,
    base_tick: int,
    bars: int,
) -> tuple[int, float, float]:
    position = clock.tick_to_position(base_tick)
    start_bar = int(position["bar"])
    if int(position.get("beat", 1)) != 1 or position.get("offset"):
        raise ValueError(
            f"MusicIR v3 generator clip {clip['id']!r} must currently start on a bar boundary"
        )
    end_tick = clock.bar_start_tick(start_bar + bars)
    meter = clock.meter_at_bar(start_bar)
    for bar in range(start_bar, start_bar + bars):
        current = clock.meter_at_bar(bar)
        if (current.numerator, current.denominator) != (meter.numerator, meter.denominator):
            raise ValueError(
                f"MusicIR v3 generator clip {clip['id']!r} crosses a meter change; "
                "split it into clips at the meter boundary"
            )
    start_bpm = float(tempo.bpm_at_tick(base_tick))
    # The bridge intentionally preserves v1 millisecond-humanization semantics.
    # A changing tempo would require the generator to emit clock-domain events
    # directly, which is a later migration step.
    for seg in tempo.segments:
        if seg.start_tick >= end_tick or (seg.end_tick is not None and seg.end_tick <= base_tick):
            continue
        if abs(float(seg.start_bpm) - start_bpm) > 1e-9 or abs(float(seg.end_bpm) - start_bpm) > 1e-9:
            raise ValueError(
                f"MusicIR v3 generator clip {clip['id']!r} crosses a tempo change/ramp; "
                "split it into constant-tempo clips for now"
            )
    if any(base_tick <= tick < end_tick for tick, _seconds in tempo.holds):
        raise ValueError(
            f"MusicIR v3 generator clip {clip['id']!r} crosses a score hold; split it at the hold"
        )
    quarter_beats_per_bar = float(meter.ticks_per_bar) / float(clock.ppq)
    return start_bar, start_bpm, quarter_beats_per_bar


def _baseline_control_counter(spec: Mapping[str, Any]) -> Counter[tuple[float, int, int]]:
    inst = create_midi_instrument(dict(spec))
    add_initial_controls(inst, dict(spec))
    return Counter(
        (round(float(cc.time), 9), int(cc.number), int(cc.value))
        for cc in inst.control_changes
    )


def _copy_generator_controls(
    *,
    generated: CompiledScore,
    target_instruments: Mapping[str, pretty_midi.Instrument],
    instrument_specs: Mapping[str, Mapping[str, Any]],
    base_tick: int,
    bpm: float,
    ppq: int,
    tempo: ExactTempoMap,
    transform: ClipTransform,
) -> None:
    generated_by_name = {str(inst.name): inst for inst in generated.pm.instruments}
    for name, source_inst in generated_by_name.items():
        if name not in target_instruments:
            continue
        target = target_instruments[name]
        remaining_baseline = _baseline_control_counter(instrument_specs[name])
        for cc in source_inst.control_changes:
            key = (round(float(cc.time), 9), int(cc.number), int(cc.value))
            if remaining_baseline[key] > 0:
                remaining_baseline[key] -= 1
                continue
            local_beat = float(cc.time) * bpm / 60.0
            local_tick = int(round(local_beat * ppq))
            tick = base_tick + transform.transform_tick_offset(local_tick)
            target.control_changes.append(
                pretty_midi.ControlChange(
                    number=int(cc.number),
                    value=int(cc.value),
                    time=tempo.tick_to_time(tick),
                )
            )
        for bend in source_inst.pitch_bends:
            local_beat = float(bend.time) * bpm / 60.0
            local_tick = int(round(local_beat * ppq))
            tick = base_tick + transform.transform_tick_offset(local_tick)
            target.pitch_bends.append(
                pretty_midi.PitchBend(
                    pitch=int(bend.pitch),
                    time=tempo.tick_to_time(tick),
                )
            )


def _generator_layer_and_motifs(
    graph: NormalizedScoreGraph,
    *,
    clip: Mapping[str, Any],
    part: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    generator = copy.deepcopy(dict(clip["generate"]))
    public_kind = str(generator.pop("kind", ""))
    registry_spec = validate_generator_mapping(dict(clip["generate"]))
    layer = generator
    layer["kind"] = registry_spec.bridge_kind
    if public_kind == "guitar.lead":
        # V3 pitch semantics are exact unless the author explicitly transforms
        # them.  The historical v1 guitar_lead helper may search neighboring
        # octaves for a convenient fretboard position; opt v3 out of that
        # revoicing so a motif such as B-A-G-E remains B-A-G-E.
        layer.setdefault("fretboard_octave_shifts", [0])
    authored_technique = clip.get("technique", clip.get("articulation"))
    if authored_technique is not None and "articulation" not in layer:
        # V1 generators already have mature articulation/gate behavior. A v3
        # clip-level technique is therefore lowered into that existing input.
        layer["articulation"] = str(authored_technique)
    if not any(key in layer for key in ("instrument", "instruments", "group")):
        technique_map = dict(part.get("technique_map") or {})
        mapped = technique_map.get(str(authored_technique)) if authored_technique is not None else None
        layer["instrument"] = str(
            mapped or clip.get("instrument", part.get("instrument", part["id"]))
        )
    motifs: list[dict[str, Any]] = []
    if public_kind in {"melody.motif", "guitar.lead"}:
        material_id = str(layer.pop("material", layer.get("motif", "")))
        if not material_id or material_id not in graph.materials:
            raise KeyError(
                f"MusicIR v3 motif-aware generator {clip['id']!r} references unknown material {material_id!r}"
            )
        material = graph.materials[material_id]
        if str(material.get("kind")) != "motif":
            raise ValueError(
                f"MusicIR v3 motif-aware generator {clip['id']!r} needs a kind: motif material"
            )
        motif = copy.deepcopy(material)
        motif.pop("kind", None)
        motif["id"] = material_id
        motifs.append(motif)
        layer["motif"] = material_id
    return layer, motifs, public_kind


def _expand_generator_clips(
    graph: NormalizedScoreGraph,
    *,
    clock: ScoreClock,
    tempo: ExactTempoMap,
    compiled: CompiledScore,
) -> int:
    instrument_map = {str(inst.name): inst for inst in compiled.pm.instruments}
    max_end_tick = int((compiled.exact_metadata or {}).get("end_tick", 0) or 0)
    form_ranges = [
        (int(row.get("start_tick", 0)), int(row.get("end_tick", 0)), str(row["id"]))
        for row in compiled.sections
    ]
    for part in graph.parts:
        part_id = str(part["id"])
        for voice in part.get("voices", []) or []:
            voice_id = str(voice["id"])
            for clip in voice.get("clips", []) or []:
                if "generate" not in clip:
                    continue
                bars = _generator_bars(clip)
                transform = clip_transform(clip)
                bases = _generator_instance_bases(clip, clock=clock, bars=bars)
                layer, motifs, public_kind = _generator_layer_and_motifs(
                    graph, clip=clip, part=part
                )
                for repeat_index, base_tick in enumerate(bases):
                    start_bar, bpm, quarter_beats_per_bar = _require_generator_region(
                        clip=clip,
                        clock=clock,
                        tempo=tempo,
                        base_tick=base_tick,
                        bars=bars,
                    )
                    if get_generator_spec(public_kind).harmony == "none":
                        harmony = ["C"] * bars
                    elif clip.get("harmony") is not None:
                        harmony = list(clip.get("harmony") or [])
                        if len(harmony) < bars:
                            raise ValueError(
                                f"MusicIR v3 generator clip {clip['id']!r} harmony override has "
                                f"{len(harmony)} entries for {bars} bars"
                            )
                    else:
                        harmony = [graph.chord_for_bar(start_bar + i) for i in range(bars)]
                    synthetic_section: dict[str, Any] = {
                        "id": str(clip["id"]),
                        "bars": bars,
                        "harmony": harmony,
                        "layers": [layer],
                    }
                    form_region = graph.form_region_at_tick(clock, base_tick)
                    if form_region:
                        energy = form_region.get("energy", form_region.get("intensity"))
                        if energy is not None:
                            synthetic_section["intensity"] = float(energy)
                        if form_region.get("density") is not None:
                            synthetic_section["density"] = float(form_region["density"])
                    synthetic = {
                        "schema": "ambition.musicir.v1",
                        "id": f"{graph.score_id}__{clip['id']}__{repeat_index}",
                        "seed": _clip_semantic_seed(graph.seed, clip, part, repeat_index),
                        "tempo": {"bpm": bpm},
                        "meter": {"beats_per_bar": quarter_beats_per_bar, "beat_unit": 4},
                        "instruments": copy.deepcopy(graph.instruments),
                        "motifs": motifs,
                        "sections": [synthetic_section],
                    }
                    constraints = graph.source_spec.get("constraints")
                    if constraints:
                        synthetic["constraints"] = copy.deepcopy(constraints)
                    generated = compile_procedural_score(synthetic)
                    _copy_generator_controls(
                        generated=generated,
                        target_instruments=instrument_map,
                        instrument_specs=compiled.instrument_specs,
                        base_tick=base_tick,
                        bpm=bpm,
                        ppq=clock.ppq,
                        tempo=tempo,
                        transform=transform,
                    )

                    # Copy the generator's *post-sanitization* MIDI rather than
                    # reconstructing notes from diagnostic note_events.  The v1
                    # compiler may shorten same-pitch overlaps after generating
                    # its note-event census.  Preserving the rendered MIDI here
                    # makes the v3 bridge behaviorally identical to the proven
                    # generator while provenance remains attached separately.
                    event_queues: dict[tuple[str, int, int, float], deque[tuple[int, Mapping[str, Any]]]] = defaultdict(deque)
                    for source_index, source_event in enumerate(generated.note_events):
                        event_queues[(
                            str(source_event["instrument"]),
                            int(source_event["pitch"]),
                            int(source_event.get("velocity", 1)),
                            round(float(source_event.get("start_time", 0.0)), 9),
                        )].append((source_index, source_event))

                    generated_by_name = {str(inst.name): inst for inst in generated.pm.instruments}
                    fallback_index = len(generated.note_events)
                    for target, source_inst in generated_by_name.items():
                        if target not in instrument_map:
                            continue
                        for source_note in source_inst.notes:
                            key = (
                                target,
                                int(source_note.pitch),
                                int(source_note.velocity),
                                round(float(source_note.start), 9),
                            )
                            matched = event_queues[key].popleft() if event_queues[key] else None
                            if matched is None:
                                event_index = fallback_index
                                fallback_index += 1
                                event: Mapping[str, Any] = {}
                            else:
                                event_index, event = matched

                            local_start_beat = float(source_note.start) * bpm / 60.0
                            local_end_beat = float(source_note.end) * bpm / 60.0
                            source_start_tick = int(round(local_start_beat * clock.ppq))
                            source_end_tick = int(round(local_end_beat * clock.ppq))
                            source_sounding_ticks = max(1, source_end_tick - source_start_tick)
                            start_tick = base_tick + transform.transform_tick_offset(source_start_tick)
                            sounding_ticks = transform.transform_sounding_duration_ticks(source_sounding_ticks)
                            sounding_end_tick = start_tick + sounding_ticks
                            nominal_beats = float(
                                event.get(
                                    "nominal_duration_beats",
                                    max(0.0, local_end_beat - local_start_beat),
                                )
                            )
                            source_nominal_ticks = max(1, int(round(nominal_beats * clock.ppq)))
                            nominal_ticks = transform.transform_duration_ticks(source_nominal_ticks)
                            nominal_end_tick = start_tick + nominal_ticks
                            pitch = transform.transform_pitch(int(source_note.pitch))
                            velocity = transform.transform_velocity(int(source_note.velocity))
                            start_time = tempo.tick_to_time(start_tick)
                            end_time = tempo.tick_to_time(sounding_end_tick)
                            instrument_map[target].notes.append(
                                pretty_midi.Note(
                                    velocity=velocity,
                                    pitch=pitch,
                                    start=start_time,
                                    end=max(start_time + 0.001, end_time),
                                )
                            )
                            source_ref = SourceRef(
                                score_id=graph.score_id,
                                part_id=part_id,
                                voice_id=voice_id,
                                clip_id=str(clip["id"]),
                                generator_kind=public_kind,
                                repeat_index=repeat_index,
                                event_index=event_index,
                            )
                            position = clock.tick_to_position(start_tick)
                            section_id = next(
                                (
                                    section
                                    for section_start, section_end, section in form_ranges
                                    if section_start <= start_tick < section_end
                                ),
                                None,
                            )
                            compiled.note_events.append(
                                {
                                    "event_type": str(event.get("event_type", "note")),
                                    "event_id": source_ref.event_id(),
                                    "source_ref": source_ref.as_dict(),
                                    "instrument": target,
                                    "group": compiled.groups.get(target, target),
                                    "part": part_id,
                                    "voice": voice_id,
                                    "section": section_id,
                                    "layer": str(clip["id"]),
                                    "layer_kind": f"generator:{public_kind}",
                                    "pitch": pitch,
                                    "note": midi_to_note(pitch),
                                    "velocity": velocity,
                                    "start_tick": start_tick,
                                    "duration_ticks": nominal_ticks,
                                    "end_tick": nominal_end_tick,
                                    "start_time": start_time,
                                    "end_time": max(start_time + 0.001, end_time),
                                    "start_beat": start_tick / clock.ppq,
                                    "end_beat": sounding_end_tick / clock.ppq,
                                    "nominal_bar": int(position["bar"]) - 1,
                                    "nominal_beat": float(position["beat"]) - 1.0,
                                    "position": position,
                                }
                            )
                            max_end_tick = max(
                                max_end_tick, nominal_end_tick, sounding_end_tick
                            )
    return max_end_tick


def _form_end_tick(clock: ScoreClock, form: list[dict[str, Any]]) -> int:
    result = 0
    for item in form:
        if "to" in item:
            result = max(result, clock.position_to_tick(item["to"]))
        elif "end_tick" in item:
            result = max(result, int(item["end_tick"]))
        elif "bars" in item and isinstance(item["bars"], (list, tuple)):
            result = max(result, clock.bar_start_tick(int(item["bars"][1]) + 1))
    return result


def compile_v3_score(
    spec: dict[str, Any],
    *,
    source_schema: str | None = MUSICIR_V3_SCHEMA,
    normalization_warnings: tuple[str, ...] = (),
) -> CompiledScore:
    """Compile MusicIR v3 authoring graph into the canonical renderer contract."""

    if spec.get("schema") != MUSICIR_V3_SCHEMA:
        raise ValueError(
            f"MusicIR v3 compiler requires schema {MUSICIR_V3_SCHEMA!r}; got {spec.get('schema')!r}"
        )
    graph = normalize_v3_score_graph(spec)
    timing = graph.timing_score()
    clock = ScoreClock(timing)
    tempo = ExactTempoMap(timing, clock).bind_ppq(clock.ppq)
    exact_parts, exact_end = _lower_exact_clips(graph, clock=clock)

    # Determine a conservative score end before exact compilation so form
    # metadata already encloses generator clips. Generator placement itself is
    # verified again while expanding.
    generator_end = 0
    for part in graph.parts:
        for voice in part.get("voices", []) or []:
            for clip in voice.get("clips", []) or []:
                if "generate" not in clip:
                    continue
                bars = _generator_bars(clip)
                transform = clip_transform(clip)
                for base in _generator_instance_bases(clip, clock=clock, bars=bars):
                    pos = clock.tick_to_position(base)
                    source_end = clock.bar_start_tick(int(pos["bar"]) + bars)
                    generator_end = max(
                        generator_end,
                        base + transform.transform_duration_ticks(source_end - base),
                    )
    inferred_end = max(exact_end, generator_end, _form_end_tick(clock, graph.form))
    if graph.end is not None:
        inferred_end = max(inferred_end, clock.position_to_tick(graph.end))
    timing["end_tick"] = inferred_end

    # Reuse the mature exact frontend for literal v3 clips.  The lowered v2
    # document is an implementation detail; source/provenance stay v3.
    from ..render.exact_score import compile_exact_score

    lowered = {
        "schema": "ambition.musicir.v2",
        "id": graph.score_id,
        "instruments": copy.deepcopy(graph.instruments),
        "score": timing,
        "parts": exact_parts,
    }
    compiled = compile_exact_score(
        lowered,
        source_schema=source_schema,
        normalization_warnings=normalization_warnings,
        canonical_schema=MUSICIR_V3_SCHEMA,
        normalized_spec_override=copy.deepcopy(spec),
        authoring_graph=graph.as_dict(),
    )
    # Exact metadata was computed with the conservative end above.
    _expand_generator_clips(graph, clock=clock, tempo=tempo, compiled=compiled)
    sanitize_same_pitch_overlaps(compiled.pm)
    compiled.authoring_graph = graph.as_dict()
    compiled.authoring_graph_fingerprint = authoring_graph_fingerprint(graph)
    compiled.assert_internal_consistency()
    compiled.attach_legacy_metadata()
    return compiled
