"""MIDI event construction and automation helpers for MusicIR score expansion."""

from __future__ import annotations

from . import score_core as _core
from . import score_theory as _theory

globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_theory).items() if not k.startswith("__")})

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


def resolve_instruments(ctx: RenderContext, layer: dict[str, Any]) -> list[str]:
    if "instrument" in layer:
        return [layer["instrument"]]
    if "instruments" in layer:
        return list(layer["instruments"])
    if "group" in layer:
        return [name for name, group in ctx.groups.items() if group == layer["group"]]
    raise KeyError(f"layer needs instrument/instruments/group: {layer}")


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
    dur_scale = gate if gate is not None else ARTICULATION_GATE.get(articulation, 0.86)
    end = start + max(0.025, ctx.beat_to_time(dur_beats * dur_scale))
    start = max(0.0, start)
    if end <= start:
        end = start + 0.025
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
            "start_beat": float(start / 60.0 * ctx.bpm),
            "end_beat": float(end / 60.0 * ctx.bpm),
        }
    )
    if pitch_bend_curve:
        # Interpolate the curve in time and write as a sequence of pitch bends.
        # Cents are clamped to MIDI's ±2 semitone default range here (200 cents
        # max). For deeper bends, expand `synth.pitch_wheel_sensitivity` upstream.
        note_duration = ctx.beat_to_time(dur_beats)
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
    elif pitch_scoop_cents:
        bend_value = int(clamp(pitch_scoop_cents / 200.0 * 8192.0, -8192, 8191))
        inst.pitch_bends.append(pretty_midi.PitchBend(pitch=bend_value, time=start))
        inst.pitch_bends.append(
            pretty_midi.PitchBend(pitch=0, time=min(end, start + 0.10))
        )


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
    humanize_ms: float = 0.0,
    humanize_velocity_pct: float = 0.0,
    gate: float | None = None,
    constraints: dict[str, Any] | None = None,
) -> None:
    notes = chord_pitches(chord, octave=octave, voicing=voicing)
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
    if mode == "minimize_motion":
        prev = ctx.last_voicing.get(inst_name)
        if prev is not None and len(prev) >= len(out):
            # Permute new notes to align with prev — for each previous voice,
            # pick the new note (octave-shifted into the closest octave) that
            # minimizes pitch motion. Keep the lowest as bass.
            out = _voice_lead_minimize(prev, out)
    if constraints.get("no_clusters"):
        out = _spread_clusters(out)
    max_pitch = constraints.get("max_pitch")
    min_pitch = constraints.get("min_pitch")
    bounded: list[int] = []
    for p0 in out:
        p = int(round(float(p0)))
        if max_pitch is not None:
            max_p = int(max_pitch)
            while p > max_p:
                p -= 12
        if min_pitch is not None:
            min_p = int(min_pitch)
            while p < min_p:
                p += 12
        bounded.append(p)
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
    ctx.last_voicing[inst_name] = list(out)
    return out


def _voice_lead_minimize(prev: list[int], new: list[int]) -> list[int]:
    """Greedy nearest-voice mapping. Bass voice (lowest of `new`) stays put;
    upper voices are octave-shifted to the closest version of one of the
    remaining new notes."""
    if not new:
        return new
    bass = min(new)
    rest_new = [n for n in new if n != bass] + [n for n in new if n == bass][1:]
    rest_prev = sorted(prev)[1:] if len(prev) > 1 else []
    out = [bass]
    available = list(rest_new)
    for prev_note in rest_prev:
        if not available:
            break
        # Shift each candidate to the nearest octave of prev_note, then pick
        # the candidate with the smallest residual distance.
        best = None
        best_dist = 10**9
        for cand in available:
            shifted = cand
            while shifted < prev_note - 6:
                shifted += 12
            while shifted > prev_note + 6:
                shifted -= 12
            d = abs(shifted - prev_note)
            if d < best_dist:
                best = (cand, shifted)
                best_dist = d
        if best is None:
            break
        chosen_orig, chosen_shifted = best
        out.append(chosen_shifted)
        available.remove(chosen_orig)
    # Append any leftover new notes in their original octave.
    out.extend(available)
    return out


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
        cc_num = CC_NUMBERS.get(
            cc, int(cc) if isinstance(cc, int) or str(cc).isdigit() else 11
        )
        start_bar = section["start_bar"] + float(auto.get("start_bar", 0.0))
        dur_bars = float(auto.get("bars", section["bars"]))
        start_val = float(auto.get("from", 80))
        end_val = float(auto.get("to", 110))
        curve = auto.get("curve", "linear")
        # `lfo` is a periodic sine sweep useful for vibrato (modulation CC) or
        # tremolo (volume CC). `from`/`to` are the troughs/peaks; `cycles` is
        # the number of full sine periods across the automation window. We
        # auto-pick a generous default sample count for sine so the curve is
        # smooth — 32 samples per cycle is plenty for typical vibrato rates.
        if curve == "lfo":
            cycles = float(auto.get("cycles", 4.0))
            points = int(auto.get("points", max(32, int(cycles * 32))))
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


