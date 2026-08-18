"""Exact-score MusicIR v2 compiler.

MusicIR v1 is optimized for compact procedural game cues.  MusicIR v2 adds a
notation-like, self-contained representation for long-form repertoire and
through-composed music.  V2 score files carry their own musical clock,
parts/voices, tempo/meter maps and literal note events; rendering never needs an
external MIDI/MusicXML source.

The canonical exact coordinate is an integer tick.  Human-authored positions
(`bar`/`beat`/rational offset) compile to ticks through :class:`ScoreClock`.
Imported material can store ticks directly without loss.
"""

from __future__ import annotations

import copy
import dataclasses as dc
from bisect import bisect_right
from fractions import Fraction
import math
from typing import Any, Iterable

import pretty_midi

from .score_core import CC_NUMBERS, GM_PROGRAMS, velocity_to_cc_value
from .score_theory import clamp, fit_midi_pitch, midi_to_note, note_to_midi


EXACT_SCHEMA = "ambition.musicir.v2"


def _fraction(value: Any) -> Fraction:
    """Parse a rational authoring value without introducing float drift."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value, 1)
    if isinstance(value, float):
        # Authoring floats are accepted for convenience but limited to a sane
        # denominator so `0.3333333333` becomes the intended triplet.
        return Fraction(value).limit_denominator(15360)
    text = str(value).strip()
    if not text:
        return Fraction(0, 1)
    return Fraction(text)


def _signature(value: Any) -> tuple[int, int]:
    if isinstance(value, str):
        num, den = value.split("/", 1)
        return int(num), int(den)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    if isinstance(value, dict):
        return int(value["numerator"]), int(value["denominator"])
    raise ValueError(f"invalid meter signature {value!r}")


@dc.dataclass(frozen=True)
class MeterChange:
    bar: int  # 1-based score bar
    numerator: int
    denominator: int
    start_tick: int
    ticks_per_bar: int


class ScoreClock:
    """Map score positions to exact integer ticks under a meter map."""

    def __init__(self, score: dict[str, Any]):
        timebase = score.get("timebase") or {}
        self.ppq = int(timebase.get("ppq", 960))
        if self.ppq <= 0:
            raise ValueError("score.timebase.ppq must be > 0")

        raw_meter = score.get("meter") or [{"bar": 1, "signature": "4/4"}]
        if isinstance(raw_meter, dict):
            if "map" in raw_meter:
                raw_meter = raw_meter.get("map") or []
            else:
                raw_meter = [raw_meter]
        entries = sorted(raw_meter, key=lambda e: int(e.get("bar", 1)))
        if not entries or int(entries[0].get("bar", 1)) != 1:
            raise ValueError("score.meter must start at bar 1")

        changes: list[MeterChange] = []
        tick = 0
        prev_bar = 1
        prev_tpb = None
        for entry in entries:
            bar = int(entry.get("bar", 1))
            if bar < prev_bar:
                raise ValueError("score.meter entries must be ordered by bar")
            if prev_tpb is not None:
                tick += (bar - prev_bar) * prev_tpb
            num, den = _signature(entry.get("signature", entry))
            if num <= 0 or den <= 0:
                raise ValueError(f"invalid meter {num}/{den}")
            raw_tpb = Fraction(num * 4 * self.ppq, den)
            if raw_tpb.denominator != 1:
                raise ValueError(
                    f"ppq={self.ppq} cannot represent {num}/{den} bars exactly"
                )
            tpb = int(raw_tpb)
            changes.append(MeterChange(bar, num, den, tick, tpb))
            prev_bar = bar
            prev_tpb = tpb
        self.meter_changes = tuple(changes)
        self._meter_bars = tuple(ch.bar for ch in changes)

    def meter_at_bar(self, bar: int) -> MeterChange:
        idx = bisect_right(self._meter_bars, int(bar)) - 1
        if idx < 0:
            raise ValueError(f"bar must be >= 1, got {bar}")
        return self.meter_changes[idx]

    def bar_start_tick(self, bar: int) -> int:
        bar = int(bar)
        change = self.meter_at_bar(bar)
        return change.start_tick + (bar - change.bar) * change.ticks_per_bar

    def position_to_tick(self, position: Any) -> int:
        """Convert a v2 position to a canonical tick.

        Supported forms:
          * integer tick
          * ``{tick: 1234}``
          * ``{bar: 12, beat: 2, offset: "1/8"}``

        Bars and beats are 1-based. ``offset`` is a fraction of a whole note;
        e.g. ``1/8`` is one eighth-note after the authored beat.
        """
        if isinstance(position, int):
            return position
        if isinstance(position, dict):
            if "tick" in position:
                return int(position["tick"])
            bar = int(position.get("bar", 1))
            beat = _fraction(position.get("beat", 1))
            offset = _fraction(position.get("offset", 0))
            change = self.meter_at_bar(bar)
            quarter_ticks = self.ppq
            beat_ticks = Fraction(quarter_ticks * 4, change.denominator)
            within = (beat - 1) * beat_ticks + offset * (4 * quarter_ticks)
            if within.denominator != 1:
                raise ValueError(f"position {position!r} is not exact at ppq={self.ppq}")
            return self.bar_start_tick(bar) + int(within)
        raise ValueError(f"invalid score position {position!r}")

    def duration_to_ticks(self, value: Any) -> int:
        """Convert a duration to ticks.

        Integers are already ticks. Strings/fractions are whole-note fractions:
        ``1/4`` = quarter note, ``3/8`` = dotted quarter, ``1/12`` = eighth-note
        triplet at a PPQ divisible by 3.
        """
        if isinstance(value, int):
            return value
        if isinstance(value, dict) and "ticks" in value:
            return int(value["ticks"])
        frac = _fraction(value)
        ticks = frac * (4 * self.ppq)
        if ticks.denominator != 1:
            raise ValueError(f"duration {value!r} is not exact at ppq={self.ppq}")
        return int(ticks)

    def tick_to_position(self, tick: int) -> dict[str, Any]:
        """Best-effort human position for diagnostics."""
        tick = int(tick)
        # Meter changes are bar-addressed; find the latest whose start tick is <= tick.
        starts = [ch.start_tick for ch in self.meter_changes]
        idx = bisect_right(starts, tick) - 1
        change = self.meter_changes[max(0, idx)]
        delta = tick - change.start_tick
        bars = max(0, delta // change.ticks_per_bar)
        bar = change.bar + bars
        rem = delta - bars * change.ticks_per_bar
        beat_ticks = Fraction(self.ppq * 4, change.denominator)
        beat0 = Fraction(rem, 1) / beat_ticks
        whole = int(beat0)
        offset_beats = beat0 - whole
        result: dict[str, Any] = {"bar": bar, "beat": whole + 1}
        if offset_beats:
            whole_frac = offset_beats * Fraction(1, change.denominator)
            result["offset"] = str(whole_frac)
        return result


@dc.dataclass(frozen=True)
class TempoSegment:
    start_tick: int
    end_tick: int | None
    start_bpm: float
    end_bpm: float
    curve: str = "step"


class ExactTempoMap:
    """Tick-based score tempo with exact step changes and linear BPM ramps."""

    def __init__(self, score: dict[str, Any], clock: ScoreClock):
        raw = score.get("tempo") or [{"tick": 0, "bpm": 120.0}]
        if isinstance(raw, dict):
            if "events" in raw:
                base = raw.get("initial") or raw.get("bpm")
                raw = list(raw.get("events") or [])
                if base is not None and not any(self._event_tick(e, clock) == 0 for e in raw):
                    raw.insert(0, {"tick": 0, "bpm": float(base)})
            else:
                raw = [raw]
        if not raw:
            raw = [{"tick": 0, "bpm": 120.0}]

        normalized: list[dict[str, Any]] = []
        for event in raw:
            e = copy.deepcopy(event)
            e["_tick"] = self._event_tick(e, clock)
            normalized.append(e)
        normalized.sort(key=lambda e: int(e["_tick"]))
        if int(normalized[0]["_tick"]) != 0:
            raise ValueError("score.tempo must start at tick 0")

        # Build non-overlapping segments. An event can be either a step change:
        #   {tick: 0, bpm: 72}
        # or a ramp beginning at that point:
        #   {from: {...}, to: {...}, bpm: [72, 120], curve: linear}
        segments: list[TempoSegment] = []
        holds: list[tuple[int, float]] = []
        current_bpm = 120.0
        for i, e in enumerate(normalized):
            tick = int(e["_tick"])
            if "hold_seconds" in e:
                holds.append((tick, float(e["hold_seconds"])))
            bpm_val = e.get("bpm", current_bpm)
            if isinstance(bpm_val, (list, tuple)):
                if len(bpm_val) != 2:
                    raise ValueError("tempo ramp bpm must be [start, end]")
                start_bpm, end_bpm = map(float, bpm_val)
                current_bpm = end_bpm
                to = e.get("to") or e.get("end")
                if to is None:
                    raise ValueError("tempo ramp requires `to` position")
                end_tick = clock.position_to_tick(to)
                if end_tick <= tick:
                    raise ValueError("tempo ramp end must follow its start")
                segments.append(TempoSegment(tick, end_tick, start_bpm, end_bpm, str(e.get("curve", "linear"))))
                # Hold ramp target until next event.
                next_tick = int(normalized[i + 1]["_tick"]) if i + 1 < len(normalized) else None
                if next_tick is not None and next_tick > end_tick:
                    segments.append(TempoSegment(end_tick, next_tick, end_bpm, end_bpm, "step"))
            else:
                bpm = float(bpm_val)
                current_bpm = bpm
                next_tick = int(normalized[i + 1]["_tick"]) if i + 1 < len(normalized) else None
                segments.append(TempoSegment(tick, next_tick, bpm, bpm, "step"))

        # Normalize accidental overlaps from an explicit ramp + subsequent event.
        segments.sort(key=lambda s: s.start_tick)
        cleaned: list[TempoSegment] = []
        for seg in segments:
            if cleaned and cleaned[-1].end_tick is None:
                cleaned[-1] = dc.replace(cleaned[-1], end_tick=seg.start_tick)
            if cleaned and cleaned[-1].end_tick is not None and seg.start_tick < cleaned[-1].end_tick:
                cleaned[-1] = dc.replace(cleaned[-1], end_tick=seg.start_tick)
            if seg.end_tick is None or seg.end_tick > seg.start_tick:
                cleaned.append(seg)
        if not cleaned:
            cleaned = [TempoSegment(0, None, 120.0, 120.0)]
        if cleaned[-1].end_tick is not None:
            cleaned.append(TempoSegment(cleaned[-1].end_tick, None, cleaned[-1].end_bpm, cleaned[-1].end_bpm))
        self.segments = tuple(cleaned)
        self.holds = tuple(sorted(holds))
        self._starts = tuple(s.start_tick for s in self.segments)
        self.ppq = clock.ppq
        self._start_times = self._integrated_start_times()

    @staticmethod
    def _event_tick(event: dict[str, Any], clock: ScoreClock) -> int:
        if "tick" in event:
            return int(event["tick"])
        if "at" in event:
            return clock.position_to_tick(event["at"])
        if "from" in event:
            return clock.position_to_tick(event["from"])
        if "bar" in event:
            return clock.position_to_tick({"bar": event["bar"], "beat": event.get("beat", 1), "offset": event.get("offset", 0)})
        return 0

    @staticmethod
    def _segment_seconds(seg: TempoSegment, tick: int, ppq: int) -> float:
        end = tick
        if end <= seg.start_tick:
            return 0.0
        q = (end - seg.start_tick) / float(ppq)
        if seg.end_tick is None or abs(seg.end_bpm - seg.start_bpm) < 1e-12 or seg.curve == "step":
            return 60.0 * q / seg.start_bpm
        total_q = (seg.end_tick - seg.start_tick) / float(ppq)
        frac = q / total_q
        if seg.curve in {"linear", "smooth"}:
            v0, v1 = seg.start_bpm, seg.end_bpm
            if abs(v1 - v0) < 1e-12:
                return 60.0 * q / v0
            # bpm linear in quarter-note coordinate.
            slope = (v1 - v0) / total_q
            v = v0 + (v1 - v0) * frac
            return 60.0 / slope * math.log(v / v0)
        if seg.curve == "exponential":
            v0, v1 = seg.start_bpm, seg.end_bpm
            if v0 <= 0 or v1 <= 0:
                raise ValueError("exponential tempo ramps require positive bpm")
            k = math.log(v1 / v0) / total_q
            if abs(k) < 1e-12:
                return 60.0 * q / v0
            return 60.0 / (v0 * k) * (1.0 - math.exp(-k * q))
        raise ValueError(f"unsupported tempo curve {seg.curve!r}")

    def _integrated_start_times(self) -> tuple[float, ...]:
        times = [0.0]
        for seg in self.segments[:-1]:
            assert seg.end_tick is not None
            times.append(times[-1] + self._segment_seconds(seg, seg.end_tick, self.ppq))
        return tuple(times)

    def bind_ppq(self, ppq: int) -> "ExactTempoMap":
        # Kept for compatibility with the initial v2 implementation. The map is
        # now bound to the score clock in __init__, so a different PPQ is an
        # authoring error rather than a late mutation.
        ppq = int(ppq)
        if ppq != self.ppq:
            raise ValueError(f"tempo map ppq {self.ppq} does not match requested ppq {ppq}")
        return self

    def tick_to_time(self, tick: int) -> float:
        tick = int(tick)
        idx = max(0, bisect_right(self._starts, tick) - 1)
        seg = self.segments[idx]
        t = self._start_times[idx] + self._segment_seconds(seg, tick, self.ppq)
        # A hold is a discontinuity *after* its score coordinate.  Events that
        # end exactly on the anchor keep their notated end time; events that
        # cross or follow the anchor include the inserted pause.  Applying a
        # hold at ``at <= tick`` incorrectly stretches the preceding interval
        # and shifts an onset located exactly on the anchor.
        t += sum(seconds for at, seconds in self.holds if at < tick)
        return t

    def bpm_at_tick(self, tick: int) -> float:
        idx = max(0, bisect_right(self._starts, int(tick)) - 1)
        seg = self.segments[idx]
        if seg.end_tick is None or seg.end_tick == seg.start_tick or seg.curve == "step":
            return seg.start_bpm
        frac = (int(tick) - seg.start_tick) / (seg.end_tick - seg.start_tick)
        frac = max(0.0, min(1.0, frac))
        if seg.curve in {"linear", "smooth"}:
            return seg.start_bpm + (seg.end_bpm - seg.start_bpm) * frac
        if seg.curve == "exponential":
            return seg.start_bpm * ((seg.end_bpm / seg.start_bpm) ** frac)
        return seg.start_bpm


def _instrument_from_spec(spec: dict[str, Any]) -> pretty_midi.Instrument:
    name = str(spec["name"])
    is_drum = bool(spec.get("is_drum", False))
    if is_drum:
        return pretty_midi.Instrument(program=0, is_drum=True, name=name)
    program_name = spec.get("program", "string_ensemble_1")
    if isinstance(program_name, int):
        program = int(program_name)
    elif program_name in GM_PROGRAMS:
        program = GM_PROGRAMS[program_name]
    else:
        raise ValueError(f"instrument {name!r}: unknown program {program_name!r}")
    return pretty_midi.Instrument(program=program, is_drum=False, name=name)


def _add_initial_cc(inst: pretty_midi.Instrument, spec: dict[str, Any]) -> None:
    init = {7: int(spec.get("volume", 100)), 10: int(spec.get("pan", 64)), 11: int(spec.get("expression", 100))}
    for key, cc_num in CC_NUMBERS.items():
        if key in spec and key not in {"volume", "pan", "expression"}:
            init[cc_num] = int(spec[key])
    for key, value in dict(spec.get("controls") or {}).items():
        if isinstance(key, int) or str(key).isdigit():
            init[int(key)] = int(value)
        elif key in CC_NUMBERS:
            init[CC_NUMBERS[key]] = int(value)
        else:
            raise ValueError(f"instrument {spec['name']!r}: unknown CC key {key!r}")
    for number, value in sorted(init.items()):
        inst.control_changes.append(pretty_midi.ControlChange(number=number, value=int(clamp(value, 0, 127)), time=0.0))


def _event_rows(voice: dict[str, Any], phrases: dict[str, Any], clock: ScoreClock) -> Iterable[dict[str, Any]]:
    """Expand literal events and local phrase instances into event mappings."""
    for raw in voice.get("events", []) or []:
        if isinstance(raw, (list, tuple)):
            if len(raw) < 4:
                raise ValueError(f"compact exact note requires [tick,dur,pitch,velocity], got {raw!r}")
            row = {"tick": int(raw[0]), "dur_ticks": int(raw[1]), "pitch": raw[2], "velocity": raw[3]}
            if len(raw) >= 5:
                row["technique"] = raw[4]
            yield row
        else:
            yield dict(raw)

    for instance in voice.get("sequence", []) or []:
        phrase_id = str(instance["phrase"])
        if phrase_id not in phrases:
            raise KeyError(f"unknown exact-score phrase {phrase_id!r}")
        base = clock.position_to_tick(instance.get("at", instance.get("tick", 0)))
        transpose = int(instance.get("transpose", 0))
        velocity_scale = float(instance.get("velocity_scale", 1.0))
        phrase = phrases[phrase_id]
        for raw in phrase.get("events", []) or []:
            if isinstance(raw, (list, tuple)):
                if len(raw) < 4:
                    raise ValueError(f"compact phrase note requires [tick,dur,pitch,velocity], got {raw!r}")
                row = {"tick": base + int(raw[0]), "dur_ticks": int(raw[1]), "pitch": raw[2], "velocity": int(round(float(raw[3]) * velocity_scale))}
                if len(raw) >= 5:
                    row["technique"] = raw[4]
            else:
                row = dict(raw)
                if "at" in row:
                    rel_pos = row.pop("at")
                else:
                    rel_pos = row.pop("tick", 0)
                rel = clock.position_to_tick(rel_pos)
                row["tick"] = base + rel
                row["velocity"] = int(round(float(row.get("velocity", 80)) * velocity_scale))
            p = row.get("pitch")
            if isinstance(p, int):
                row["pitch"] = p + transpose
            elif isinstance(p, str):
                row["pitch"] = note_to_midi(p) + transpose
            if "pitches" in row:
                row["pitches"] = [(note_to_midi(x) if isinstance(x, str) else int(x)) + transpose for x in row["pitches"]]
            yield row


def _event_tick(row: dict[str, Any], clock: ScoreClock) -> int:
    if "tick" in row:
        return int(row["tick"])
    if "at" in row:
        return clock.position_to_tick(row["at"])
    if "bar" in row:
        return clock.position_to_tick({"bar": row["bar"], "beat": row.get("beat", 1), "offset": row.get("offset", 0)})
    raise ValueError(f"exact note event requires tick/at/bar: {row!r}")


def _duration_ticks(row: dict[str, Any], clock: ScoreClock) -> int:
    if "dur_ticks" in row:
        return int(row["dur_ticks"])
    if "duration_ticks" in row:
        return int(row["duration_ticks"])
    if "dur" in row:
        return clock.duration_to_ticks(row["dur"])
    if "duration" in row:
        return clock.duration_to_ticks(row["duration"])
    raise ValueError(f"exact note event requires dur/dur_ticks: {row!r}")


def _pitch_list(row: dict[str, Any]) -> list[int]:
    if "pitches" in row:
        vals = row["pitches"]
    else:
        vals = [row["pitch"]]
    return [fit_midi_pitch(note_to_midi(v) if isinstance(v, str) else int(v)) for v in vals]


def _form_metadata(spec: dict[str, Any], clock: ScoreClock, tempo: ExactTempoMap, end_tick: int) -> list[dict[str, Any]]:
    score = spec.get("score") or {}
    form = score.get("form") or []
    if not form:
        form = [{"id": "complete_work", "from": {"tick": 0}, "to": {"tick": end_tick}, "kind": "complete_work"}]
    out: list[dict[str, Any]] = []
    for item in form:
        start = clock.position_to_tick(item.get("from", item.get("at", {"tick": 0})))
        if "to" in item:
            stop = clock.position_to_tick(item["to"])
        elif "end_tick" in item:
            stop = int(item["end_tick"])
        elif "bars" in item and isinstance(item["bars"], (list, tuple)):
            b0, b1 = map(int, item["bars"])
            start = clock.bar_start_tick(b0)
            stop = clock.bar_start_tick(b1 + 1)
        else:
            stop = end_tick
        row = {
            "id": str(item["id"]),
            "label": item.get("label", item["id"]),
            "kind": item.get("kind", "section"),
            "start_bar": int(clock.tick_to_position(start)["bar"]) - 1,
            "bars": max(0, int(clock.tick_to_position(max(start, stop - 1))["bar"]) - int(clock.tick_to_position(start)["bar"]) + 1),
            "start_tick": start,
            "end_tick": stop,
            "start_beat": start / clock.ppq,
            "end_beat": stop / clock.ppq,
            "start_seconds": tempo.tick_to_time(start),
            "end_seconds": tempo.tick_to_time(stop),
            "duration_seconds": tempo.tick_to_time(stop) - tempo.tick_to_time(start),
            "loopable": bool(item.get("loopable", False)),
            "valid_exit_local_bars": item.get("valid_exit_local_bars", []),
        }
        # Audio-domain mix intent belongs to the score form, not MIDI velocity.
        # Preserve it in compiled section metadata so every rendering path and
        # audit can apply the same authored hierarchy.
        for key in (
            "mix_gain_db",
            "mix_gain_transition_beats",
            "stem_mix_db",
            "stem_mix_transition_beats",
        ):
            if key in item:
                row[key] = copy.deepcopy(item[key])
        out.append(row)
    return out


def build_exact_score(spec: dict[str, Any]) -> tuple[pretty_midi.PrettyMIDI, dict[str, str], list[dict[str, Any]]]:
    if spec.get("schema") != EXACT_SCHEMA:
        raise ValueError(f"exact-score compiler requires schema {EXACT_SCHEMA!r}")
    score = spec.get("score") or {}
    clock = ScoreClock(score)
    tempo = ExactTempoMap(score, clock).bind_ppq(clock.ppq)
    initial_bpm = tempo.bpm_at_tick(0)
    pm = pretty_midi.PrettyMIDI(initial_tempo=initial_bpm, resolution=clock.ppq)

    instruments: dict[str, pretty_midi.Instrument] = {}
    instrument_specs: dict[str, dict[str, Any]] = {}
    groups: dict[str, str] = {}
    for inst_spec in spec.get("instruments", []) or []:
        inst = _instrument_from_spec(inst_spec)
        _add_initial_cc(inst, inst_spec)
        pm.instruments.append(inst)
        instruments[inst.name] = inst
        instrument_specs[inst.name] = copy.deepcopy(inst_spec)
        groups[inst.name] = str(inst_spec.get("group", inst.name))

    phrases = {str(p["id"]): p for p in score.get("phrases", []) or []}
    note_events: list[dict[str, Any]] = []
    end_tick = 0
    for part in spec.get("parts", []) or []:
        part_id = str(part["id"])
        default_inst = str(part.get("instrument", part_id))
        technique_map = {str(k): str(v) for k, v in dict(part.get("technique_map") or {}).items()}
        if default_inst not in instruments:
            raise KeyError(f"part {part_id!r} references unknown instrument {default_inst!r}")
        part_group = str(part.get("group", groups.get(default_inst, default_inst)))

        # Part-level exact CC/controller events.
        for control in part.get("controls", []) or []:
            tick = _event_tick(control, clock)
            at = tempo.tick_to_time(tick)
            target = str(control.get("instrument", default_inst))
            if target not in instruments:
                raise KeyError(f"part {part_id!r} control references unknown instrument {target!r}")
            number_raw = control.get("cc", control.get("controller"))
            if isinstance(number_raw, str) and not number_raw.isdigit():
                if number_raw not in CC_NUMBERS:
                    raise ValueError(f"unknown controller {number_raw!r}")
                number = CC_NUMBERS[number_raw]
            else:
                number = int(number_raw)
            instruments[target].control_changes.append(pretty_midi.ControlChange(number=number, value=int(clamp(control["value"], 0, 127)), time=at))

        for voice in part.get("voices", []) or []:
            voice_id = str(voice.get("id", "voice"))
            for row in _event_rows(voice, phrases, clock):
                tick = _event_tick(row, clock)
                dur_ticks = _duration_ticks(row, clock)
                if tick < 0 or dur_ticks <= 0:
                    raise ValueError(f"invalid exact note coordinate tick={tick}, duration={dur_ticks}")
                technique = str(row.get("technique", row.get("articulation", "normal")))
                target = str(row.get("instrument", technique_map.get(technique, default_inst)))
                if target not in instruments:
                    raise KeyError(f"part {part_id!r} event references unknown instrument {target!r}")
                velocity = int(clamp(round(float(row.get("velocity", 80))), 1, 127))
                start = tempo.tick_to_time(tick)
                gate = float(row.get("gate", 1.0))
                effective = max(1, int(round(dur_ticks * gate)))
                end = tempo.tick_to_time(tick + effective)
                if end <= start:
                    end = start + 0.001
                velocity_cc = velocity_to_cc_value(instrument_specs[target], velocity)
                if velocity_cc is not None:
                    cc_number, cc_value = velocity_cc
                    instruments[target].control_changes.append(
                        pretty_midi.ControlChange(number=cc_number, value=cc_value, time=start)
                    )
                for pitch in _pitch_list(row):
                    instruments[target].notes.append(pretty_midi.Note(velocity=velocity, pitch=pitch, start=start, end=end))
                    position = clock.tick_to_position(tick)
                    note_events.append({
                        "instrument": target,
                        "group": groups.get(target, part_group),
                        "part": part_id,
                        "voice": voice_id,
                        # The downstream renderer/audit contract predates exact
                        # scores and calls these fields layer/layer_kind. Keep
                        # that canonical event vocabulary at the compiler
                        # boundary instead of teaching every consumer about
                        # v2 parts and voices separately.
                        "layer": voice_id,
                        "layer_kind": "exact_score",
                        "technique": technique,
                        "pitch": pitch,
                        "note": midi_to_note(pitch),
                        "velocity": velocity,
                        "start_tick": tick,
                        "duration_ticks": dur_ticks,
                        "end_tick": tick + dur_ticks,
                        "start_time": start,
                        "end_time": end,
                        # Canonical beat coordinates are quarter-note beats,
                        # independent of meter. Audits use these for overlap
                        # calculations; end_beat follows the *sounding* gate,
                        # matching the v1 score_events contract.
                        "start_beat": tick / clock.ppq,
                        "end_beat": (tick + effective) / clock.ppq,
                        "nominal_bar": int(position["bar"]) - 1,
                        "nominal_beat": float(position["beat"]) - 1.0,
                        "position": position,
                    })
                end_tick = max(end_tick, tick + dur_ticks)

    # Optional explicit score end allows final rests/tails after the last note.
    if "end" in score:
        end_tick = max(end_tick, clock.position_to_tick(score["end"]))
    if "end_tick" in score:
        end_tick = max(end_tick, int(score["end_tick"]))

    meta = _form_metadata(spec, clock, tempo, end_tick)
    form_ranges = [
        (int(item["start_tick"]), int(item["end_tick"]), str(item["id"]))
        for item in meta
    ]
    for event in note_events:
        tick = int(event["start_tick"])
        event["section"] = next(
            (section_id for start_tick, stop_tick, section_id in form_ranges if start_tick <= tick < stop_tick),
            None,
        )

    pm._ambition_note_events = note_events  # type: ignore[attr-defined]
    pm._ambition_instrument_specs = copy.deepcopy(instrument_specs)  # type: ignore[attr-defined]
    pm._ambition_exact_score = {  # type: ignore[attr-defined]
        "ppq": clock.ppq,
        "end_tick": end_tick,
        "meter_changes": [dc.asdict(x) for x in clock.meter_changes],
        "tempo_segments": [dc.asdict(x) for x in tempo.segments],
        "holds": [{"tick": tick, "seconds": seconds} for tick, seconds in tempo.holds],
        "form": copy.deepcopy(score.get("form") or []),
    }
    return pm, groups, meta
