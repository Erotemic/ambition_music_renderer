"""MIDI event construction and automation helpers for MusicIR score expansion."""

from __future__ import annotations

import copy
import itertools
import math
from typing import Any

import pretty_midi

from .score_core import ARTICULATION_GATE, CC_NUMBERS, DRUMS, GM_PROGRAMS, RenderContext
from .score_theory import chord_pitches, clamp, fit_midi_pitch, midi_to_note, note_to_midi

def add_cc(inst: pretty_midi.Instrument, number: int, value: int, time: float) -> None:
    inst.control_changes.append(
        pretty_midi.ControlChange(
            number=int(number), value=int(clamp(value, 0, 127)), time=float(time)
        )
    )


def add_instrument(ctx: RenderContext, spec: dict[str, Any]) -> None:
    name = spec["name"]
    if spec.get("is_drum", False):
        inst = pretty_midi.Instrument(program=0, is_drum=True, name=name)
    else:
        program_name = spec.get("program", "string_ensemble_1")
        if isinstance(program_name, int):
            program = int(program_name)
        elif program_name in GM_PROGRAMS:
            program = GM_PROGRAMS[program_name]
        else:
            raise ValueError(
                f"instrument {name!r}: unknown program {program_name!r}. "
                f"Use a GM program name (e.g. lead_saw, pad_warm, synth_brass_1) "
                f"or an int 0-127. Valid names: {', '.join(sorted(GM_PROGRAMS))}"
            )
        inst = pretty_midi.Instrument(program=program, is_drum=False, name=name)
    ctx.pm.instruments.append(inst)
    ctx.instruments[name] = inst
    ctx.instrument_specs[name] = copy.deepcopy(spec)
    ctx.groups[name] = spec.get("group", name)
    add_cc(inst, 7, int(spec.get("volume", 100)), 0.0)
    add_cc(inst, 10, int(spec.get("pan", 64)), 0.0)
    add_cc(inst, 11, int(spec.get("expression", 100)), 0.0)
    for key, cc_num in CC_NUMBERS.items():
        if key in spec and key not in {"volume", "pan", "expression"}:
            add_cc(inst, cc_num, int(spec[key]), 0.0)
    # Arbitrary CC init for sample banks with custom control schemes, e.g.
    # Karoryfer's Shinyguitar is silent until its CC100 "Blend" control is
    # mid-position. Keys may be CC numbers or CC_NUMBERS names:
    #   controls: {100: 64, sustain: 0}
    for key, value in dict(spec.get("controls") or {}).items():
        if isinstance(key, int) or str(key).isdigit():
            cc_num = int(key)
        elif key in CC_NUMBERS:
            cc_num = CC_NUMBERS[key]
        else:
            raise KeyError(
                f"instrument {name!r}: unknown controls key {key!r}; use a MIDI "
                f"CC number or one of {sorted(CC_NUMBERS)}"
            )
        add_cc(inst, cc_num, int(value), 0.0)


def resolve_instruments(ctx: RenderContext, layer: dict[str, Any]) -> list[str]:
    if "instrument" in layer:
        names = [layer["instrument"]]
    elif "instruments" in layer:
        names = list(layer["instruments"])
    elif "group" in layer:
        group_name = layer["group"]
        names = [name for name, group in ctx.groups.items() if group == group_name]
        if not names:
            known_groups = sorted(set(ctx.groups.values()))
            raise KeyError(
                f"layer references unknown or empty instrument group {group_name!r}; "
                f"known groups: {known_groups}"
            )
    else:
        raise KeyError(f"layer needs instrument/instruments/group: {layer}")

    if not names:
        raise ValueError("layer resolved to an empty instrument list")
    unknown = [name for name in names if name not in ctx.instruments]
    if unknown:
        raise KeyError(
            f"layer references unknown instrument(s) {unknown}; "
            f"known instruments: {sorted(ctx.instruments)}"
        )
    return names


def add_note(
    ctx: RenderContext,
    inst_name: str,
    pitch: int | str,
    bar: float,
    beat: float,
    dur_beats: float,
    vel: float,
    *,
    articulation: str = "normal",
    humanize_ms: float = 0.0,
    humanize_velocity_pct: float = 0.0,
    gate: float | None = None,
    pitch_scoop_cents: float = 0.0,
    pitch_bend_curve: list[tuple[float, float]] | None = None,
    pitch_vibrato_cents: float = 0.0,
    pitch_vibrato_rate_hz: float = 5.4,
    pitch_vibrato_delay_beats: float = 0.45,
) -> None:
    """Schedule a single note.

    `humanize_velocity_pct` jitters velocity by N(0, pct) so motoric figures
    don't sound machine-perfect. ±2-4% is a typical ensemble-feel value.

    `pitch_bend_curve` is an optional list of `(beat_offset_in_note, cents)`
    waypoints that get interpolated across the note. Use it for sustained
    guitar bends — `[(0.0, 0), (0.1, 100), (0.5, 100), (0.7, 0)]` rises a
    semitone, holds, then releases.
    """
    if inst_name not in ctx.instruments:
        raise KeyError(f"unknown instrument {inst_name!r}")
    inst = ctx.instruments[inst_name]
    pitch_num = note_to_midi(pitch) if isinstance(pitch, str) else int(pitch)
    pitch_num = fit_midi_pitch(pitch_num)
    start_beat = ctx.bar_to_beat(bar, beat)
    start = ctx.beat_to_time(start_beat)
    if humanize_ms:
        start += float(ctx.rng.normal(0.0, humanize_ms / 1000.0))
    # Clamp before computing the end so negative jitter near t=0 shifts the
    # note instead of lengthening it.
    start = max(0.0, start)
    dur_scale = gate if gate is not None else ARTICULATION_GATE.get(articulation, 0.86)
    end = start + max(0.025, ctx.beat_duration_to_seconds(start_beat, dur_beats * dur_scale))
    if ctx.dynamics_scale is not None:
        vel = vel * float(ctx.dynamics_scale(start_beat))
    if humanize_velocity_pct:
        vel = vel * (1.0 + float(ctx.rng.normal(0.0, humanize_velocity_pct / 100.0)))
    velocity = int(clamp(round(vel), 1, 127))
    inst.notes.append(
        pretty_midi.Note(velocity=velocity, pitch=pitch_num, start=start, end=end)
    )
    ctx.note_events.append(
        {
            "instrument": inst_name,
            "group": ctx.groups.get(inst_name, inst_name),
            "section": ctx.active_section_id,
            "layer": ctx.active_layer_id,
            "layer_kind": ctx.active_layer_kind,
            "pitch": int(pitch_num),
            "note": midi_to_note(pitch_num),
            "velocity": int(velocity),
            "nominal_bar": float(bar),
            "nominal_beat": float(beat),
            "nominal_duration_beats": float(dur_beats),
            "start_time": float(start),
            "end_time": float(end),
            "start_beat": float(ctx.time_to_beat(start)),
            "end_beat": float(ctx.time_to_beat(end)),
        }
    )
    if pitch_bend_curve:
        # Interpolate the curve in time and write as a sequence of pitch bends.
        # Cents are clamped to MIDI's ±2 semitone default range here (200 cents
        # max). For deeper bends, expand `synth.pitch_wheel_sensitivity` upstream.
        note_duration = ctx.beat_duration_to_seconds(start_beat, dur_beats)
        for beat_off, cents in pitch_bend_curve:
            bend_time = start + max(
                0.0, float(beat_off) * (note_duration / max(dur_beats, 1e-6))
            )
            bend_time = min(bend_time, end)
            bend_value = int(clamp(float(cents) / 200.0 * 8192.0, -8192, 8191))
            inst.pitch_bends.append(
                pretty_midi.PitchBend(pitch=bend_value, time=bend_time)
            )
        # Reset to 0 just past the note end so we don't drag bend into the next note.
        inst.pitch_bends.append(pretty_midi.PitchBend(pitch=0, time=end + 0.001))
    else:
        if pitch_scoop_cents:
            bend_value = int(clamp(pitch_scoop_cents / 200.0 * 8192.0, -8192, 8191))
            inst.pitch_bends.append(pretty_midi.PitchBend(pitch=bend_value, time=start))
            inst.pitch_bends.append(
                pretty_midi.PitchBend(pitch=0, time=min(end, start + 0.10))
            )
        if pitch_vibrato_cents:
            # A small delayed pitch vibrato gives MIDI guitar leads more held-note
            # life without requiring the score to spell out pitch-bend curves for
            # every note.  Keep it modest: pitch-bend affects the full MIDI
            # channel, so authors should reserve it for mostly monophonic leads.
            delay_s = ctx.beat_duration_to_seconds(start_beat, float(pitch_vibrato_delay_beats))
            vibrato_start = start + max(0.0, delay_s)
            if end - vibrato_start > 0.12:
                rate = max(0.1, float(pitch_vibrato_rate_hz))
                step = 1.0 / (rate * 8.0)
                t = vibrato_start
                while t < end - 0.01:
                    phase = (t - vibrato_start) * rate * math.tau
                    cents = math.sin(phase) * float(pitch_vibrato_cents)
                    bend_value = int(clamp(cents / 200.0 * 8192.0, -8192, 8191))
                    inst.pitch_bends.append(pretty_midi.PitchBend(pitch=bend_value, time=t))
                    t += step
                inst.pitch_bends.append(pretty_midi.PitchBend(pitch=0, time=end + 0.001))


def add_chord(
    ctx: RenderContext,
    inst_name: str,
    chord: str,
    bar: float,
    beat: float,
    dur_beats: float,
    vel: float,
    *,
    octave: int = 4,
    articulation: str = "pad",
    voicing: str = "open",
    include_slash_bass: bool = True,
    humanize_ms: float = 0.0,
    humanize_velocity_pct: float = 0.0,
    gate: float | None = None,
    constraints: dict[str, Any] | None = None,
) -> None:
    notes = chord_pitches(
        chord,
        octave=octave,
        voicing=voicing,
        include_slash_bass=include_slash_bass,
    )
    if constraints:
        notes = _apply_voicing_constraints(ctx, inst_name, notes, constraints)
    for idx, p in enumerate(notes):
        add_note(
            ctx,
            inst_name,
            p,
            bar,
            beat,
            dur_beats,
            vel - idx * 2,
            articulation=articulation,
            humanize_ms=humanize_ms,
            humanize_velocity_pct=humanize_velocity_pct,
            gate=gate,
        )


def _apply_voicing_constraints(
    ctx: RenderContext,
    inst_name: str,
    notes: list[int],
    constraints: dict[str, Any],
) -> list[int]:
    """Rewrite a chord's voicing per the YAML constraints block.

    All checks are opt-in: nothing is enforced unless the YAML asks for it.
    Two rules currently supported:

    - `voice_leading: minimize_motion` — given the previous chord's voicing
      on this instrument, permute / octave-shift the new notes so the total
      voice motion is minimized. Bass note (lowest) is preserved.
    - `no_clusters: true` — any pair of notes a minor 2nd apart is split
      apart by raising the higher one an octave.
    """
    out = list(notes)
    mode = constraints.get("voice_leading")
    layer_id = getattr(ctx, "active_layer_id", None)
    state_key = f"{layer_id}\0{inst_name}" if layer_id else inst_name
    if mode == "minimize_motion":
        prev = ctx.last_voicing.get(state_key)
        if prev is not None and len(prev) >= len(out):
            # Assign all upper voices together. A register penalty keeps the
            # solution close to the score's authored octave instead of letting
            # a locally cheap octave shift ratchet upward on every progression.
            out = _voice_lead_minimize(prev, out)
    if constraints.get("no_clusters"):
        out = _spread_clusters(out)
    max_pitch = constraints.get("max_pitch")
    min_pitch = constraints.get("min_pitch")
    max_notes = constraints.get("max_notes")
    min_p = 0 if min_pitch is None else int(min_pitch)
    max_p = 127 if max_pitch is None else int(max_pitch)
    if not 0 <= min_p <= 127 or not 0 <= max_p <= 127:
        raise ValueError(
            f"voicing pitch bounds must be within MIDI range 0..127; "
            f"got min_pitch={min_pitch!r}, max_pitch={max_pitch!r}"
        )
    if min_p > max_p:
        raise ValueError(f"voicing min_pitch {min_p} exceeds max_pitch {max_p}")
    bounded: list[int] = []
    for p0 in out:
        original = int(round(float(p0)))
        candidates = [
            original + 12 * octave_shift
            for octave_shift in range(-11, 12)
            if min_p <= original + 12 * octave_shift <= max_p
        ]
        if not candidates:
            raise ValueError(
                f"cannot place pitch {original} (pitch class {original % 12}) "
                f"inside voicing bounds [{min_p}, {max_p}]"
            )
        bounded.append(min(candidates, key=lambda p: (abs(p - original), p)))
    # Final guard: clamp every voice into the valid MIDI range and drop
    # exact duplicates so the constraint stages can't produce out-of-range
    # pitches that would crash the MIDI writer.
    out = [fit_midi_pitch(p) for p in bounded]
    seen: set[int] = set()
    deduped: list[int] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    out = deduped
    if max_notes is not None:
        limit = max(1, int(max_notes))
        out = out[:limit]
    ctx.last_voicing[state_key] = list(out)
    return out


def _voice_lead_minimize(prev: list[int], new: list[int]) -> list[int]:
    """Minimize upper-voice motion without allowing octave-register drift.

    The lowest authored note remains the bass. Upper chord tones are assigned
    globally to prior voices, considering at most one octave of displacement
    in either direction. Octave shifts receive a modest penalty, so repeated
    progressions stay near their authored register instead of accumulating the
    greedy algorithm's one-way octave ratchet.
    """
    if not new:
        return new

    bass = min(new)
    upper_new = list(new)
    upper_new.remove(bass)
    if not upper_new:
        return [bass]

    upper_prev = sorted(prev)[1:]
    voice_count = len(upper_new)
    if len(upper_prev) < voice_count:
        return list(new)

    best_key: tuple[float, int, float, tuple[int, ...]] | None = None
    best_voicing: list[int] | None = None
    octave_shift_penalty = 4.0

    for selected_prev in itertools.combinations(upper_prev, voice_count):
        for ordered_tones in itertools.permutations(upper_new):
            for shifts in itertools.product((-12, 0, 12), repeat=voice_count):
                voiced = [tone + shift for tone, shift in zip(ordered_tones, shifts)]
                if any(pitch < 0 or pitch > 127 for pitch in voiced):
                    continue
                motion = float(
                    sum(abs(pitch - previous) for pitch, previous in zip(voiced, selected_prev))
                )
                octave_count = sum(abs(shift) // 12 for shift in shifts)
                total = motion + octave_shift_penalty * octave_count
                key = (total, octave_count, motion, tuple(sorted(voiced)))
                if best_key is None or key < best_key:
                    best_key = key
                    best_voicing = voiced

    if best_voicing is None:
        return list(new)
    return [bass, *best_voicing]


def _spread_clusters(notes: list[int]) -> list[int]:
    """Move any note that's a minor 2nd from another voice up by an octave
    until no two voices are adjacent semitones — but if shifting up would
    exceed MIDI 120, shift the lower voice DOWN by an octave instead."""
    if len(notes) < 2:
        return notes
    out = sorted(notes)
    changed = True
    iterations = 0
    while changed and iterations < 8:
        changed = False
        iterations += 1
        for i in range(len(out) - 1):
            if out[i + 1] - out[i] == 1:
                if out[i + 1] + 12 <= 120:
                    out[i + 1] += 12
                elif out[i] - 12 >= 12:
                    out[i] -= 12
                else:
                    # Both directions out of range — accept the cluster.
                    continue
                out.sort()
                changed = True
                break
    return out


def add_drum(
    ctx: RenderContext,
    kit: str,
    drum_name: str,
    bar: float,
    beat: float,
    vel: float,
    *,
    dur_beats: float = 0.30,
    humanize_ms: float = 0.0,
) -> None:
    if drum_name not in DRUMS:
        raise ValueError(
            f"unknown drum {drum_name!r} on kit {kit!r}. "
            f"Valid drums: {', '.join(sorted(DRUMS))}"
        )
    pitch = DRUMS[drum_name]
    add_note(
        ctx,
        kit,
        pitch,
        bar,
        beat,
        dur_beats,
        vel,
        articulation="normal",
        humanize_ms=humanize_ms,
        gate=1.0,
    )



def apply_automation(
    ctx: RenderContext, section: dict[str, Any], layer: dict[str, Any]
) -> None:
    for auto in layer.get("automation", []):
        inst_names = (
            resolve_instruments(ctx, auto)
            if any(k in auto for k in ("instrument", "instruments", "group"))
            else resolve_instruments(ctx, layer)
        )
        cc = auto.get("cc", "expression")
        if isinstance(cc, int) or str(cc).isdigit():
            cc_num = int(cc)
        elif cc in CC_NUMBERS:
            cc_num = CC_NUMBERS[cc]
        else:
            # A typo used to silently become CC 11 (expression) — dead config.
            raise KeyError(
                f"unknown automation cc {cc!r}; use a MIDI CC number or one of "
                f"{sorted(CC_NUMBERS)}"
            )
        start_bar = section["start_bar"] + float(auto.get("start_bar", 0.0))
        dur_bars = float(auto.get("bars", section["bars"]))
        start_val = float(auto.get("from", 80))
        end_val = float(auto.get("to", 110))
        curve = auto.get("curve", "linear")
        # Periodic curves use `cycles` across the automation window. `lfo` is a
        # sine sweep; `saw_up` and `saw_down` are deliberately discontinuous
        # ramps for rhythmic timbre/vibrato-depth resets. We sample periodic
        # curves densely enough that SoundFont synths receive smooth ramps
        # between the intentional reset edges.
        if curve in {"lfo", "saw_up", "saw_down"}:
            cycles = float(auto.get("cycles", 4.0))
            default_points_per_cycle = 32 if curve == "lfo" else 16
            points = int(
                auto.get(
                    "points",
                    max(2, int(math.ceil(abs(cycles) * default_points_per_cycle)) + 1),
                )
            )
        else:
            points = int(auto.get("points", 12))
        for inst_name in inst_names:
            inst = ctx.instruments[inst_name]
            for i in range(points):
                a = i / max(1, points - 1)
                if curve == "smooth":
                    a2 = a * a * (3 - 2 * a)
                    val = round(start_val * (1 - a2) + end_val * a2)
                elif curve == "exp":
                    a2 = a * a
                    val = round(start_val * (1 - a2) + end_val * a2)
                elif curve == "lfo":
                    cycles = float(auto.get("cycles", 4.0))
                    center = (start_val + end_val) / 2.0
                    amp = (end_val - start_val) / 2.0
                    val = round(center + amp * math.sin(2.0 * math.pi * cycles * a))
                elif curve in {"saw_up", "saw_down"}:
                    cycles = float(auto.get("cycles", 4.0))
                    phase = (cycles * a) % 1.0
                    if curve == "saw_down":
                        phase = 1.0 - phase
                    val = round(start_val * (1 - phase) + end_val * phase)
                else:  # linear
                    val = round(start_val * (1 - a) + end_val * a)
                add_cc(inst, cc_num, val, ctx.bar_to_time(start_bar + dur_bars * a))


def _layer_human(layer: dict[str, Any], default_ms: float) -> dict[str, float]:
    """Pull humanize parameters from a layer with a per-call default."""
    return {
        "humanize_ms": float(layer.get("humanize_ms", default_ms)),
        "humanize_velocity_pct": float(layer.get("humanize_velocity_pct", 0.0)),
    }


def _layer_constraints(
    spec: dict[str, Any], layer: dict[str, Any]
) -> dict[str, Any] | None:
    """Merge the spec-level and layer-level `constraints` blocks."""
    spec_c = spec.get("constraints") or {}
    layer_c = layer.get("constraints") or {}
    merged = dict(spec_c)
    merged.update(layer_c)
    return merged or None


