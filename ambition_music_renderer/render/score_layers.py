"""Layer renderers and full-score construction for MusicIR scores."""

from __future__ import annotations

import copy
import math
import sys
from typing import Any

import numpy as np
import pretty_midi

from ..profiler import profile
from .score_core import RenderContext, TempoMap
from .score_events import add_chord, add_drum, add_instrument, add_note, apply_automation, resolve_instruments, _layer_constraints, _layer_human
from .score_theory import chord_for_bar, chord_intervals, chord_pitches, motif_notes, note_to_midi, root_for_chord, section_starts
from .synth import sanitize_same_pitch_overlaps


def _positive_float(layer: dict[str, Any], key: str, default: float) -> float:
    """Read a strictly positive layer parameter with an actionable error."""
    value = float(layer.get(key, default))
    if not math.isfinite(value) or value <= 0.0:
        kind = layer.get("kind", "layer")
        raise ValueError(f"{kind} {key} must be finite and > 0; got {value!r}")
    return value

@profile
def render_layer_pad_chords(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    every = _positive_float(layer, "every_bars", 1.0)
    dur = float(layer.get("duration_beats", ctx.beats_per_bar * every))
    octave = int(layer.get("octave", 4))
    velocity = float(layer.get("velocity", 60)) * float(section.get("intensity", 1.0))
    articulation = layer.get("articulation", "pad")
    voicing = layer.get("voicing", "open")
    hk = _layer_human(layer, 8.0)
    constraints = _layer_constraints(ctx.spec, layer)
    local = 0.0
    section_bars = float(section["bars"])
    while local < section_bars - 1e-9:
        chord = chord_for_bar(section, int(math.floor(local + 1e-9)))
        for inst in insts:
            add_chord(
                ctx,
                inst,
                chord,
                section["start_bar"] + local,
                0.0,
                dur,
                velocity,
                octave=octave,
                articulation=articulation,
                voicing=voicing,
                constraints=constraints,
                **hk,
            )
        local += every


@profile
def render_layer_arpeggio(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    pattern = [int(x) for x in layer.get("pattern", [0, 2, 1, 2])]
    if not pattern:
        raise ValueError("arpeggio pattern must not be empty")
    step = _positive_float(layer, "step", 0.5)
    dur = float(layer.get("duration_beats", step))
    octave = int(layer.get("octave", 4))
    velocity = float(layer.get("velocity", 64))
    density = float(layer.get("density", section.get("density", 1.0)))
    articulation = layer.get("articulation", "staccato")
    inst_velocity_offsets = layer.get("instrument_velocity_offsets", {}) or {}
    inst_octave_offsets = layer.get("instrument_octave_offsets", {}) or {}
    hk = _layer_human(layer, 4.0)
    for local in range(int(section["bars"])):
        if "every" in layer and local % int(layer["every"]) != int(
            layer.get("offset", 0)
        ):
            continue
        tones = chord_pitches(
            chord_for_bar(section, local),
            octave=octave,
            voicing=layer.get("voicing", "closed"),
        )
        count = int(ctx.beats_per_bar / step)
        for i in range(count):
            if ctx.rng.random() > density:
                continue
            base_pitch = tones[pattern[i % len(pattern)] % len(tones)]
            for inst in insts:
                p = base_pitch + 12 * int(inst_octave_offsets.get(inst, 0))
                v = velocity + float(inst_velocity_offsets.get(inst, 0.0))
                add_note(
                    ctx,
                    inst,
                    p,
                    section["start_bar"] + local,
                    i * step,
                    dur,
                    v * float(section.get("intensity", 1.0)),
                    articulation=articulation,
                    **hk,
                )


@profile
def render_layer_ostinato(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    intervals = [int(x) for x in layer.get("intervals", [0, 7, 12, 7])]
    if not intervals:
        raise ValueError("ostinato intervals must not be empty")
    rhythm = [float(x) for x in layer.get("rhythm", [0.5] * len(intervals))]
    if not rhythm:
        raise ValueError("ostinato rhythm must not be empty")
    if any(not math.isfinite(dur) or dur <= 0.0 for dur in rhythm):
        raise ValueError(
            f"ostinato rhythm durations must be finite and > 0; got {rhythm!r}"
        )
    root_octave = int(layer.get("octave", 3))
    velocity = float(layer.get("velocity", 60))
    articulation = layer.get("articulation", "spiccato")
    bars = int(section["bars"])
    hk = _layer_human(layer, 4.0)
    for local in range(bars):
        root = root_for_chord(chord_for_bar(section, local), root_octave)
        beat = 0.0
        idx = 0
        while beat < ctx.beats_per_bar - 1e-6:
            dur = rhythm[idx % len(rhythm)]
            p = root + intervals[idx % len(intervals)]
            for inst in insts:
                add_note(
                    ctx,
                    inst,
                    p,
                    section["start_bar"] + local,
                    beat,
                    dur,
                    velocity * float(section.get("intensity", 1.0)),
                    articulation=articulation,
                    **hk,
                )
            beat += dur
            idx += 1


@profile
def render_layer_bassline(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    inst = resolve_instruments(ctx, layer)[0]
    pattern = layer.get(
        "pattern", [[0, 0.0, 0.75], [7, 1.5, 0.5], [12, 2.5, 0.5], [7, 3.25, 0.4]]
    )
    octave = int(layer.get("octave", 2))
    velocity = float(layer.get("velocity", 74))
    articulation = layer.get("articulation", "marcato")
    hk = _layer_human(layer, 5.0)
    for local in range(int(section["bars"])):
        root = root_for_chord(chord_for_bar(section, local), octave)
        for item in pattern:
            interval, beat, dur = int(item[0]), float(item[1]), float(item[2])
            add_note(
                ctx,
                inst,
                root + interval,
                section["start_bar"] + local,
                beat,
                dur,
                velocity * float(section.get("intensity", 1.0)),
                articulation=articulation,
                **hk,
            )


@profile
def render_layer_motif(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    roots = layer.get("roots") or [layer.get("root", None)]
    starts = layer.get("starts") or [[0, 0.0]]
    repeats = int(layer.get("repeats", 1))
    every_bars = float(layer.get("every_bars", 2.0))
    velocity = float(layer.get("velocity", 78))
    articulation = layer.get("articulation", "normal")
    gate_value = layer.get("gate")
    gate = float(gate_value) if gate_value is not None else None
    transpose = int(layer.get("transpose", 0))
    transform = layer.get("transform")
    inst_velocity_offsets = layer.get("instrument_velocity_offsets", {}) or {}
    inst_octave_offsets = layer.get("instrument_octave_offsets", {}) or {}
    inst_pitch_scoop = layer.get("instrument_pitch_scoop_cents", {}) or {}
    inst_pitch_bend_curves = layer.get("instrument_pitch_bend_curves", {}) or {}
    note_velocity_pattern = layer.get("note_velocity_pattern", None)
    hk = _layer_human(layer, 6.0)
    for rep in range(repeats):
        root = roots[rep % len(roots)]
        for start in starts:
            local_bar, start_beat = float(start[0]) + rep * every_bars, float(start[1])
            if local_bar >= section["bars"]:
                continue
            notes, rhythm, velocities = motif_notes(
                ctx, layer["motif"], root=root, transform=transform, transpose=transpose
            )
            beat = start_beat
            for i, p0 in enumerate(notes):
                dur = rhythm[i % len(rhythm)] * float(layer.get("rhythm_scale", 1.0))
                vel_scale = velocities[i % len(velocities)]
                if note_velocity_pattern:
                    vel_scale *= float(
                        note_velocity_pattern[i % len(note_velocity_pattern)]
                    )
                for j, inst in enumerate(insts):
                    p = p0 + 12 * int(inst_octave_offsets.get(inst, 0))
                    v = velocity + float(inst_velocity_offsets.get(inst, -8 * j))
                    scoop = float(
                        inst_pitch_scoop.get(inst, layer.get("pitch_scoop_cents", 0.0))
                    )
                    bend_curve = inst_pitch_bend_curves.get(
                        inst, layer.get("pitch_bend_curve")
                    )
                    bend_curve_pairs = (
                        [(float(x[0]), float(x[1])) for x in bend_curve]
                        if bend_curve
                        else None
                    )
                    add_note(
                        ctx,
                        inst,
                        p,
                        section["start_bar"] + local_bar,
                        beat,
                        dur,
                        v * vel_scale * float(section.get("intensity", 1.0)),
                        articulation=articulation,
                        gate=gate,
                        pitch_scoop_cents=scoop,
                        pitch_bend_curve=bend_curve_pairs,
                        **hk,
                    )
                beat += dur


@profile
def render_layer_chord_hits(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    hits = layer.get("hits", [[0, 0.0], [4, 0.0], [8, 0.0], [12, 0.0]])
    velocity = float(layer.get("velocity", 90))
    octave = int(layer.get("octave", 3))
    inst_octave_offsets = {
        str(k): int(v) for k, v in (layer.get("instrument_octave_offsets") or {}).items()
    }
    inst_velocity_offsets = {
        str(k): float(v) for k, v in (layer.get("instrument_velocity_offsets") or {}).items()
    }
    hk = _layer_human(layer, 6.0)
    constraints = _layer_constraints(ctx.spec, layer)
    for local, beat in hits:
        if float(local) >= section["bars"]:
            continue
        chord = chord_for_bar(section, int(local))
        for inst in insts:
            add_chord(
                ctx,
                inst,
                chord,
                section["start_bar"] + float(local),
                float(beat),
                float(layer.get("duration_beats", 0.75)),
                (velocity + float(inst_velocity_offsets.get(inst, 0.0))) * float(section.get("intensity", 1.0)),
                octave=octave + int(inst_octave_offsets.get(inst, 0)),
                articulation=layer.get("articulation", "marcato"),
                voicing=layer.get("voicing", "closed"),
                constraints=constraints,
                **hk,
            )


def render_layer_drums(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    kit = resolve_instruments(ctx, layer)[0]
    events = layer.get("events", [])
    if not events:
        return
    for local in range(int(section["bars"])):
        for ev in events:
            if "bars" in ev and local not in set(int(b) for b in ev["bars"]):
                continue
            if "every" in ev and local % int(ev["every"]) != int(ev.get("offset", 0)):
                continue
            beats = ev.get("beats", [ev.get("beat", 0.0)])
            for beat in beats:
                if ctx.rng.random() > float(ev.get("probability", 1.0)):
                    continue
                add_drum(
                    ctx,
                    kit,
                    ev["drum"],
                    section["start_bar"] + local,
                    float(beat),
                    float(ev.get("velocity", layer.get("velocity", 70)))
                    * float(section.get("intensity", 1.0)),
                    dur_beats=float(ev.get("duration_beats", 0.1)),
                    humanize_ms=float(
                        ev.get("humanize_ms", layer.get("humanize_ms", 2.0))
                    ),
                )


def render_layer_texture(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    scale = [int(x) for x in layer.get("scale", [0, 2, 3, 5, 7, 10, 12])]
    root = note_to_midi(layer.get("root", "D5"))
    count_per_bar = float(layer.get("events_per_bar", 1.0))
    velocity = float(layer.get("velocity", 38))
    hk = _layer_human(layer, 2.0)
    for local in range(int(section["bars"])):
        count = int(math.floor(count_per_bar)) + (
            1 if ctx.rng.random() < count_per_bar % 1 else 0
        )
        for _ in range(count):
            beat = float(ctx.rng.uniform(0.0, ctx.beats_per_bar))
            p = root + int(ctx.rng.choice(scale)) + 12 * int(ctx.rng.integers(-1, 2))
            inst = str(ctx.rng.choice(insts))
            add_note(
                ctx,
                inst,
                p,
                section["start_bar"] + local,
                beat,
                float(layer.get("duration_beats", 0.25)),
                velocity * float(section.get("intensity", 1.0)),
                articulation=layer.get("articulation", "bell"),
                **hk,
            )


def render_layer_pedal(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    pitch = layer.get("note")
    if pitch is None:
        pitch = root_for_chord(chord_for_bar(section, 0), int(layer.get("octave", 2)))
    velocity = float(layer.get("velocity", 45)) * float(section.get("intensity", 1.0))
    hk = _layer_human(layer, 8.0)
    for inst in insts:
        add_note(
            ctx,
            inst,
            pitch,
            section["start_bar"],
            0.0,
            section["bars"] * ctx.beats_per_bar,
            velocity,
            articulation=layer.get("articulation", "pad"),
            **hk,
        )


def render_layer_root_hits(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    insts = resolve_instruments(ctx, layer)
    hits = layer.get("hits", [[0, 0.0, 0, 0.75]])
    velocity = float(layer.get("velocity", 76))
    octave = int(layer.get("octave", 2))
    articulation = layer.get("articulation", "marcato")
    hk = _layer_human(layer, 2.0)
    for item in hits:
        local = float(item[0])
        beat = float(item[1])
        interval = int(item[2]) if len(item) > 2 else 0
        dur = (
            float(item[3])
            if len(item) > 3
            else float(layer.get("duration_beats", 0.75))
        )
        if local >= section["bars"]:
            continue
        root = root_for_chord(chord_for_bar(section, int(local)), octave)
        for inst in insts:
            add_note(
                ctx,
                inst,
                root + interval,
                section["start_bar"] + local,
                beat,
                dur,
                velocity * float(section.get("intensity", 1.0)),
                articulation=articulation,
                **hk,
            )



@profile
def render_layer_guitar_strum(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    """Render playable guitar strums instead of piano-block chords.

    YAML sketch:

    kind: guitar_strum
    instrument: acoustic_guitar
    hits: [[0, 0.0, down], [0, 2.0, up]]
    duration_beats: 1.75
    spread_ms: 42
    tuning: standard
    max_span: 5
    """
    from .. import guitar_performance as gp

    insts = resolve_instruments(ctx, layer)
    tuning = gp.tuning_from_spec(layer.get("tuning", "standard"))
    octave = int(layer.get("octave", 3))
    velocity = float(layer.get("velocity", 82))
    duration = float(layer.get("duration_beats", layer.get("dur_beats", 1.5)))
    articulation = layer.get("articulation", "pluck")
    gate = layer.get("gate")
    gate_f = None if gate is None else float(gate)
    spread_ms = float(layer.get("spread_ms", 38.0))
    max_span = int(layer.get("max_span", 5))
    max_fret = int(layer.get("max_fret", 17))
    max_notes = int(layer.get("max_notes", 6))
    prefer_open = bool(layer.get("prefer_open", True))
    velocity_slope = float(layer.get("velocity_slope", -2.0))
    hk = _layer_human(layer, 1.5)
    hits = layer.get("hits")
    if not hits:
        every = _positive_float(layer, "every_bars", 1.0)
        beats = layer.get("beats", [0.0])
        hits = []
        local = 0.0
        while local < float(section["bars"]) - 1e-9:
            for beat in beats:
                hits.append([local, float(beat)])
            local += every
    elif "every_bars" in layer or bool(layer.get("repeat_hits", False)):
        # Treat explicit hits as a per-period pattern when every_bars is present.
        # This lets authors define one-bar down/up strums and repeat them across
        # the section without spelling out every local bar.
        base_hits = [list(item) for item in hits]
        every = _positive_float(layer, "every_bars", 1.0)
        expanded = []
        period = 0.0
        while period < float(section["bars"]) - 1e-9:
            for item in base_hits:
                clone = list(item)
                clone[0] = float(clone[0]) + period
                if float(clone[0]) < float(section["bars"]):
                    expanded.append(clone)
            period += every
        hits = expanded
    dirs = list(layer.get("directions", []))
    default_direction = str(layer.get("direction", "down"))
    for hit_idx, item in enumerate(hits):
        local = float(item[0])
        if local >= float(section["bars"]):
            continue
        beat = float(item[1])
        direction = str(item[2]) if len(item) > 2 else (str(dirs[hit_idx % len(dirs)]) if dirs else default_direction)
        chord = chord_for_bar(section, int(local))
        hit_duration = duration
        if len(item) > 3:
            # Backwards-compatible extension: a fourth hit field may be either
            # an explicit chord symbol or a per-hit duration.  Per-hit
            # durations let authors write full downbeat rings and short
            # upbeat strums without letting the upbeat smear into the next bar.
            try:
                hit_duration = float(item[3])
            except (TypeError, ValueError):
                chord = str(item[3])
        if len(item) > 4:
            hit_duration = float(item[4])
        notes = chord_pitches(chord, octave=octave, voicing=layer.get("voicing", "closed"))
        for inst in insts:
            previous = ctx.last_guitar_voicing.get(inst)
            events, assignment = gp.strum_plan(
                notes,
                bpm=ctx.bpm,
                direction=direction,
                spread_ms=spread_ms,
                velocity=velocity * float(section.get("intensity", 1.0)),
                velocity_slope=velocity_slope,
                tuning=tuning,
                max_fret=max_fret,
                max_span=max_span,
                max_notes=max_notes,
                prefer_open=prefer_open,
                previous=previous,
            )
            ctx.last_guitar_voicing[inst] = assignment
            for ev in events:
                add_note(
                    ctx,
                    inst,
                    int(ev["pitch"]),
                    section["start_bar"] + local,
                    beat + float(ev["beat_offset"]),
                    hit_duration,
                    float(ev["velocity"]),
                    articulation=articulation,
                    gate=gate_f,
                    **hk,
                )


@profile
def render_layer_guitar_chug(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    """Render tight power-chord / palm-muted guitar rhythms.

    This is meant to replace generic ostinato for distorted rhythm guitar.  It
    emits separate take performances when ``takes`` are supplied instead of
    relying on stereo widening.
    """
    from .. import guitar_performance as gp

    if any(k in layer for k in ("instrument", "instruments", "group")):
        default_insts = resolve_instruments(ctx, layer)
    else:
        default_insts = []
    takes = gp.take_specs(layer, default_insts)
    if not takes:
        # Every other layer kind errors on an unresolvable instrument; a chug
        # layer with neither takes nor instrument(s)/group used to silently
        # render nothing.
        raise KeyError(
            "guitar_chug layer needs `takes` or `instrument`/`instruments`/`group`"
        )
    pattern = layer.get("pattern", [[0, 0.0, 0.5], [0, 0.5, 0.5], [7, 1.0, 0.5], [0, 1.5, 0.5]])
    root_octave = int(layer.get("octave", 2))
    velocity = float(layer.get("velocity", 92))
    shape = str(layer.get("shape", "fifth_octave"))
    articulation = str(layer.get("articulation", "staccato"))
    gate = float(layer.get("gate", 0.48))
    strum_spread_ms = float(layer.get("spread_ms", 8.0))
    beat_per_second = ctx.bpm / 60.0
    root_policy = str(layer.get("root_policy", layer.get("bass_policy", "bass"))).lower().replace("-", "_")
    min_pitch = layer.get("min_pitch")
    min_pitch_i = int(min_pitch) if min_pitch is not None else None
    hk = _layer_human(layer, 1.0)
    for local in range(int(section["bars"])):
        chord = chord_for_bar(section, local)
        if root_policy in {"chord_root", "root"}:
            chord_root, _intervals, _slash = chord_intervals(chord)
            root_base = note_to_midi(f"{chord_root}{root_octave}")
        else:
            root_base = root_for_chord(chord, root_octave)
        for event_idx, item in enumerate(pattern):
            interval = int(item[0])
            beat = float(item[1])
            dur = float(item[2])
            accent = float(item[3]) if len(item) > 3 else 1.0
            root = root_base + interval
            if min_pitch_i is not None:
                while root < min_pitch_i:
                    root += 12
            pitches = gp.power_chord_pitches(root, shape=shape)
            for take_idx, take in enumerate(takes):
                inst = str(take.get("instrument"))
                if inst not in ctx.instruments:
                    raise KeyError(f"guitar_chug take references unknown instrument {inst!r}")
                timing_ms = float(take.get("timing_offset_ms", take.get("offset_ms", 0.0)))
                take_beat = beat + timing_ms / 1000.0 * beat_per_second
                vel_offset = float(take.get("velocity_offset", -2.0 * take_idx))
                for p_idx, p in enumerate(pitches):
                    note_offset = p_idx * (strum_spread_ms / 1000.0 * beat_per_second / max(1, len(pitches) - 1))
                    add_note(
                        ctx,
                        inst,
                        p,
                        section["start_bar"] + local,
                        take_beat + note_offset,
                        dur,
                        (velocity + vel_offset - p_idx * 2.0) * accent * float(section.get("intensity", 1.0)),
                        articulation=articulation,
                        gate=gate,
                        **hk,
                    )


@profile
def render_layer_guitar_lead(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    """Render a motif as a mostly monophonic guitar lead performance.

    This intentionally mirrors the plain ``motif`` layer's authoring
    conveniences (``root``, ``starts``, and per-instrument octave/velocity
    offsets), then adds fretboard-aware pitch choices and position-dependent
    scoops.  That keeps existing lead templates easy to convert to
    ``guitar_lead`` without forcing score authors to rewrite every section
    override as a ``roots`` list.
    """
    from .. import guitar_performance as gp

    insts = resolve_instruments(ctx, layer)
    roots = layer.get("roots") or [layer.get("root", None)]
    starts = layer.get("starts") or [[0, 0.0]]
    repeats = int(layer.get("repeats", 1))
    every_bars = float(layer.get("every_bars", 2.0))
    velocity = float(layer.get("velocity", 76))
    articulation = layer.get("articulation", "pluck")
    gate = float(layer.get("gate", 0.78))
    transform = layer.get("transform")
    transpose = int(layer.get("transpose", 0))
    inst_velocity_offsets = layer.get("instrument_velocity_offsets", {}) or {}
    inst_octave_offsets = layer.get("instrument_octave_offsets", {}) or {}
    inst_pitch_scoop = layer.get("instrument_pitch_scoop_cents", {}) or {}
    inst_pitch_bend_curves = layer.get("instrument_pitch_bend_curves", {}) or {}
    hk = _layer_human(layer, 3.0)
    default_scoop = float(layer.get("pitch_scoop_cents", 12.0))
    # Scale (or disable) the position-dependent attack scoop. The fret/string-jump
    # scoop models a plucked-guitar pick attack and assumes a fast-decaying
    # envelope; on sustained voices (fiddle, organ) or soundfonts with longer
    # guitar samples it reads as an audible out-of-tune bend. Set this to 0.0 to
    # turn the position scoop off entirely (a fixed pitch_scoop_cents still
    # applies), or below 1.0 to tame it.
    position_scoop_scale = float(layer.get("position_scoop_scale", 1.0))
    vibrato_cents = float(layer.get("pitch_vibrato_cents", layer.get("vibrato_cents", 0.0)))
    vibrato_rate_hz = float(layer.get("pitch_vibrato_rate_hz", layer.get("vibrato_rate_hz", 5.4)))
    vibrato_delay_beats = float(layer.get("pitch_vibrato_delay_beats", layer.get("vibrato_delay_beats", 0.45)))
    note_velocity_pattern = layer.get("note_velocity_pattern")
    # Use the fretboard allocator to choose a plausible string/fret for each
    # note.  The current version only uses that to vary scoops on jumps; future
    # noise events can reuse the same assignment.
    tuning = gp.tuning_from_spec(layer.get("tuning", "standard"))
    max_fret = int(layer.get("max_fret", 19))
    prev_assign: dict[str, gp.StringFret | None] = {inst: None for inst in insts}
    for rep in range(repeats):
        root = roots[rep % len(roots)]
        for start in starts:
            local_bar, start_beat = float(start[0]) + rep * every_bars, float(start[1])
            if local_bar >= section["bars"]:
                continue
            notes, rhythm, velocities = motif_notes(
                ctx, layer["motif"], root=root, transform=transform, transpose=transpose
            )
            beat = start_beat
            for i, p0 in enumerate(notes):
                dur = rhythm[i % len(rhythm)] * float(layer.get("rhythm_scale", 1.0))
                vel_scale = velocities[i % len(velocities)]
                if note_velocity_pattern:
                    vel_scale *= float(note_velocity_pattern[i % len(note_velocity_pattern)])
                for j, inst in enumerate(insts):
                    p = int(p0) + 12 * int(inst_octave_offsets.get(inst, 0))
                    choices = gp.positions_for_pitch(p, tuning=tuning, max_fret=max_fret)
                    chosen = choices[0] if choices else None
                    scoop = float(inst_pitch_scoop.get(inst, default_scoop))
                    local_scoop = scoop
                    prev = prev_assign.get(inst)
                    if prev is not None and chosen is not None and position_scoop_scale:
                        # Larger position jumps get a slightly stronger attack scoop.
                        local_scoop = scoop + position_scoop_scale * min(
                            28.0,
                            abs(chosen.fret - prev.fret) * 2.0
                            + abs(chosen.string_index - prev.string_index) * 3.0,
                        )
                    if chosen is not None:
                        prev_assign[inst] = chosen
                    bend_curve = inst_pitch_bend_curves.get(
                        inst, layer.get("pitch_bend_curve")
                    )
                    bend_curve_pairs = (
                        [(float(x[0]), float(x[1])) for x in bend_curve]
                        if bend_curve
                        else None
                    )
                    add_note(
                        ctx,
                        inst,
                        int(chosen.pitch if chosen is not None else p),
                        section["start_bar"] + local_bar,
                        beat,
                        dur,
                        (velocity + float(inst_velocity_offsets.get(inst, -8 * j)))
                        * vel_scale
                        * float(section.get("intensity", 1.0)),
                        articulation=articulation,
                        gate=gate,
                        pitch_scoop_cents=local_scoop,
                        pitch_bend_curve=bend_curve_pairs,
                        pitch_vibrato_cents=vibrato_cents,
                        pitch_vibrato_rate_hz=vibrato_rate_hz,
                        pitch_vibrato_delay_beats=vibrato_delay_beats,
                        **hk,
                    )
                beat += dur

def render_layer_automation(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    # Note-free layer used to express section-wide CC ramps in YAML.
    apply_automation(ctx, section, layer)


@profile
def render_layer_notes(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    """Literal note events — the full-control escape hatch.

    Every other layer kind generates notes from harmony and patterns; this one
    plays exactly what is written.  Compact list form is
    ``[local_bar, beat, note, dur_beats, velocity]`` (velocity optional);
    dict form adds per-note ``gate``/``articulation``/``bend``/``vibrato_cents``
    etc.  ``note`` may be a list of pitches to voice a chord::

        - kind: notes
          instrument: storyteller
          notes:
            - [0, 0.0, G4, 2.0, 62]
            - [1, 3.0, [G3, B3, D4, A4], 6.0, 54]
            - {bar: 2, beat: 0.0, note: B4, dur: 3.0, vel: 58, gate: 0.8,
               bend: [[0.0, 0], [0.5, 100]]}
    """
    insts = resolve_instruments(ctx, layer)
    default_vel = float(layer.get("velocity", 64))
    default_art = layer.get("articulation", "normal")
    hk = _layer_human(layer, 0.0)
    intensity = float(section.get("intensity", 1.0))
    for row in layer.get("notes", []):
        if isinstance(row, dict):
            bar = float(row.get("bar", 0))
            beat = float(row.get("beat", 0.0))
            pitches = row.get("note", row.get("notes"))
            dur = float(row.get("dur", row.get("duration_beats", 1.0)))
            vel = float(row.get("vel", row.get("velocity", default_vel)))
            extra = {
                "articulation": row.get("articulation", default_art),
                "gate": row.get("gate", layer.get("gate")),
                "pitch_bend_curve": [
                    (float(b), float(c)) for b, c in (row.get("bend") or [])
                ] or None,
                "pitch_scoop_cents": float(row.get("scoop_cents", 0.0)),
                "pitch_vibrato_cents": float(row.get("vibrato_cents", 0.0)),
                "pitch_vibrato_rate_hz": float(row.get("vibrato_rate_hz", 5.4)),
            }
        else:
            if len(row) < 4:
                raise ValueError(
                    f"notes rows need [bar, beat, note, dur_beats(, velocity)]; got {row!r}"
                )
            bar, beat, pitches, dur = float(row[0]), float(row[1]), row[2], float(row[3])
            vel = float(row[4]) if len(row) > 4 else default_vel
            extra = {"articulation": default_art, "gate": layer.get("gate")}
        if not isinstance(pitches, list):
            pitches = [pitches]
        for inst in insts:
            for pitch in pitches:
                add_note(
                    ctx,
                    inst,
                    pitch,
                    section["start_bar"] + bar,
                    beat,
                    dur,
                    vel * intensity,
                    **{k: v for k, v in extra.items() if v is not None},
                    **hk,
                )


def _dynamics_scale_fn(
    section: dict[str, Any], layer: dict[str, Any], beats_per_bar: float
):
    """Build a velocity-scale function of absolute beat from `dynamics:` curves.

    Backend-independent phrase dynamics: unlike CC automation (which only
    moves instruments whose SFZ maps that CC), this scales the authored note
    velocities themselves::

        dynamics:
          - {start_bar: 8, bars: 8, from: 0.7, to: 1.0, curve: smooth}

    Bars are local to the section; outside all curves the scale is 1.0.
    """
    curves = layer.get("dynamics") or []
    if not curves:
        return None
    section_start_beat = float(section["start_bar"]) * beats_per_bar
    spans = []
    for cfg in curves:
        b0 = section_start_beat + float(cfg.get("start_bar", 0.0)) * beats_per_bar
        b1 = b0 + float(cfg.get("bars", section["bars"])) * beats_per_bar
        spans.append((b0, b1, float(cfg.get("from", 1.0)), float(cfg.get("to", 1.0)),
                      str(cfg.get("curve", "linear"))))

    def scale(beat: float) -> float:
        for b0, b1, lo, hi, curve in spans:
            if b0 <= beat <= b1:
                a = (beat - b0) / max(b1 - b0, 1e-9)
                if curve == "smooth":
                    a = a * a * (3 - 2 * a)
                elif curve == "exp":
                    a = a * a
                return lo * (1 - a) + hi * a
        return 1.0

    return scale


@profile
def render_layer(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    kind = layer["kind"]
    ctx.dynamics_scale = _dynamics_scale_fn(section, layer, ctx.beats_per_bar)
    if kind == "pad_chords":
        render_layer_pad_chords(ctx, section, layer)
    elif kind == "arpeggio":
        render_layer_arpeggio(ctx, section, layer)
    elif kind == "ostinato":
        render_layer_ostinato(ctx, section, layer)
    elif kind == "bassline":
        render_layer_bassline(ctx, section, layer)
    elif kind == "motif":
        render_layer_motif(ctx, section, layer)
    elif kind == "chord_hits":
        render_layer_chord_hits(ctx, section, layer)
    elif kind == "drums":
        render_layer_drums(ctx, section, layer)
    elif kind == "texture":
        render_layer_texture(ctx, section, layer)
    elif kind == "pedal":
        render_layer_pedal(ctx, section, layer)
    elif kind == "root_hits":
        render_layer_root_hits(ctx, section, layer)
    elif kind == "guitar_strum":
        render_layer_guitar_strum(ctx, section, layer)
    elif kind == "guitar_chug":
        render_layer_guitar_chug(ctx, section, layer)
    elif kind == "guitar_lead":
        render_layer_guitar_lead(ctx, section, layer)
    elif kind == "notes":
        render_layer_notes(ctx, section, layer)
    elif kind == "automation":
        render_layer_automation(ctx, section, layer)
        ctx.dynamics_scale = None
        return
    else:
        ctx.dynamics_scale = None
        raise KeyError(f"unknown layer kind {kind!r}")
    ctx.dynamics_scale = None
    apply_automation(ctx, section, layer)


def merged_layers(
    spec: dict[str, Any], section: dict[str, Any]
) -> list[dict[str, Any]]:
    templates = spec.get("layer_templates", {})
    out: list[dict[str, Any]] = []
    for item in section.get("layers", []):
        if isinstance(item, str):
            layer = copy.deepcopy(templates[item])
            layer.setdefault("_source_layer", item)
        elif "template" in item:
            layer = copy.deepcopy(templates[item["template"]])
            layer.update({k: v for k, v in item.items() if k != "template"})
            layer.setdefault("_source_layer", str(item["template"]))
        else:
            layer = copy.deepcopy(item)
            layer.setdefault("_source_layer", str(layer.get("id", layer.get("kind", "inline"))))
        out.append(layer)
    return out


@profile
def build_score(
    spec: dict[str, Any],
) -> tuple[pretty_midi.PrettyMIDI, dict[str, str], list[dict[str, Any]]]:
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    tempo_map = TempoMap.from_spec(spec) if (spec.get("tempo", {}) or {}).get("map") else None
    ctx = RenderContext(
        spec=spec,
        sample_rate=int(spec.get("render", {}).get("sample_rate", 48000)),
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        rng=np.random.default_rng(int(spec.get("seed", 1))),
        pm=pm,
        instruments={},
        groups={},
        section_starts={},
        motifs={m["id"]: m for m in spec.get("motifs", [])},
        instrument_specs={},
        tempo=tempo_map,
    )
    if tempo_map is not None:
        # A tempo ramp inside a loopable section makes the loop seam jump
        # tempo audibly; ramps belong in intros/outros/transitions.
        cursor_bar = 0
        for section in spec["sections"]:
            bars = int(section["bars"])
            if section.get("loopable"):
                b0 = cursor_bar * beats_per_bar
                b1 = (cursor_bar + bars) * beats_per_bar
                v0, v1 = tempo_map.bpm_at(b0), tempo_map.bpm_at(b1)
                if abs(v1 - v0) > 0.01 * max(v0, v1):
                    print(
                        f"[ambition_music_renderer] WARNING: loopable section "
                        f"{section.get('id')!r} starts at {v0:.1f} bpm but ends at "
                        f"{v1:.1f} bpm; the loop seam will audibly jump tempo.",
                        file=sys.stderr,
                    )
            cursor_bar += bars
    for inst_spec in spec.get("instruments", []):
        add_instrument(ctx, inst_spec)
    starts = section_starts(spec["sections"])
    ctx.section_starts = starts
    section_meta = section_metadata_from_spec(spec)
    for section in spec["sections"]:
        for layer in merged_layers(spec, section):
            ctx.active_section_id = str(section.get("id", ""))
            ctx.active_layer_id = str(layer.get("_source_layer", layer.get("kind", "layer")))
            ctx.active_layer_kind = str(layer.get("kind", ""))
            render_layer(ctx, section, layer)
    pm._ambition_note_events = list(ctx.note_events)  # type: ignore[attr-defined]
    pm._ambition_instrument_specs = copy.deepcopy(ctx.instrument_specs)  # type: ignore[attr-defined]
    # Sanitize here so every consumer (isolated worker, legacy path, audits
    # rendering audio) gets the same-pitch overlap fix; callers used to have to
    # remember to call it and the production worker path forgot.
    sanitize_same_pitch_overlaps(pm)
    return pm, ctx.groups, section_meta




def section_metadata_from_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    tempo = TempoMap.from_spec(spec)
    cursor = 0
    out = []
    for section in spec["sections"]:
        bars = int(section["bars"])
        start_beat = cursor * beats_per_bar
        end_beat = (cursor + bars) * beats_per_bar
        start_seconds = tempo.beat_to_time(start_beat)
        end_seconds = tempo.beat_to_time(end_beat)
        out.append(
            {
                "id": section["id"],
                "label": section.get("label", section["id"]),
                "kind": section.get("kind", "section"),
                "start_bar": cursor,
                "bars": bars,
                "start_beat": start_beat,
                "end_beat": end_beat,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "duration_seconds": end_seconds - start_seconds,
                "loopable": bool(section.get("loopable", False)),
                "valid_exit_local_bars": section.get("valid_exit_local_bars", []),
            }
        )
        cursor += bars
    return out
