"""Opt-in instrument tuning correction for rendered MIDI performances.

MusicIR keeps authored note numbers semantic. A ``tuning_correction`` attached
at the instrument realization changes only backend synthesis pitch, after score
compilation and before audio processing. This makes measured sample drift
correctable without repitching the score or hiding the correction in effects.

Per-note correction is polyphony-safe. One MIDI pitch-bend stream cannot tune
simultaneous notes by different amounts, so notes are partitioned into a small
set of non-conflicting *tuning lanes*. Each lane is rendered independently and
summed by :mod:`ambition_music_renderer.render.group`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

import pretty_midi

from ..instrument_resolution import (
    normalize_tuning_correction,
    tuning_correction_for_instrument,
)

# The renderer targets the conventional synth/SFZ pitch-bend range of +/-2
# semitones. Tuning correction is intentionally bounded well inside that range.
_PITCH_BEND_RANGE_CENTS = 200.0
_BOUNDARY_EPSILON_S = 1e-5


def correction_cents_for_pitch(profile: Mapping[str, Any] | None, pitch: int) -> float:
    if not profile:
        return 0.0
    if str(profile.get("mode", "global")) == "global":
        return float(profile.get("cents", 0.0))
    points = {int(key): float(value) for key, value in dict(profile.get("points") or {}).items()}
    if not points:
        return 0.0
    p = int(pitch)
    if p in points:
        return points[p]
    keys = sorted(points)
    if p <= keys[0]:
        return points[keys[0]]
    if p >= keys[-1]:
        return points[keys[-1]]
    hi_index = next(index for index, key in enumerate(keys) if key > p)
    lo = keys[hi_index - 1]
    hi = keys[hi_index]
    if str(profile.get("interpolation", "linear")) == "nearest":
        return points[lo] if (p - lo) <= (hi - p) else points[hi]
    alpha = (p - lo) / float(hi - lo)
    return points[lo] + alpha * (points[hi] - points[lo])


def cents_to_pitch_bend(cents: float) -> int:
    value = int(round(float(cents) / _PITCH_BEND_RANGE_CENTS * 8192.0))
    if not -8192 <= value <= 8191:
        raise ValueError(
            f"tuning correction {cents:+.2f} cents exceeds the supported +/-2-semitone pitch-bend range"
        )
    return value


def _bend_at(events: list[pretty_midi.PitchBend], time_s: float) -> int:
    value = 0
    for event in events:
        if float(event.time) <= float(time_s) + 1e-9:
            value = int(event.pitch)
        else:
            break
    return value


@dataclass
class _Lane:
    notes: list[pretty_midi.Note]

    def accepts(self, start: float, end: float, cents: float) -> bool:
        for note in self.notes:
            if float(note.end) <= start + 1e-9 or float(note.start) >= end - 1e-9:
                continue
            other = float(getattr(note, "_ambition_tuning_cents", 0.0))
            if abs(other - cents) > 1e-6:
                return False
        return True


def _assign_tuning_lanes(
    inst: pretty_midi.Instrument,
    profile: Mapping[str, Any],
) -> list[list[pretty_midi.Note]]:
    lanes: list[_Lane] = []
    for source in sorted(inst.notes, key=lambda note: (float(note.start), float(note.end), int(note.pitch))):
        note = copy.deepcopy(source)
        cents = round(correction_cents_for_pitch(profile, int(note.pitch)), 4)
        setattr(note, "_ambition_tuning_cents", cents)
        lane = next(
            (candidate for candidate in lanes if candidate.accepts(float(note.start), float(note.end), cents)),
            None,
        )
        if lane is None:
            lane = _Lane(notes=[])
            lanes.append(lane)
        lane.notes.append(note)
    return [lane.notes for lane in lanes] or [[]]


def _correction_intervals(notes: list[pretty_midi.Note]) -> list[tuple[float, float, float]]:
    if not notes:
        return []
    boundaries = sorted({float(note.start) for note in notes} | {float(note.end) for note in notes})
    intervals: list[tuple[float, float, float]] = []
    for left, right in zip(boundaries, boundaries[1:]):
        if right <= left + 1e-12:
            continue
        active = [
            note for note in notes
            if float(note.start) < right - 1e-12 and float(note.end) > left + 1e-12
        ]
        if not active:
            continue
        values = {round(float(getattr(note, "_ambition_tuning_cents", 0.0)), 4) for note in active}
        if len(values) != 1:
            raise AssertionError(f"tuning lane contains conflicting simultaneous corrections: {sorted(values)}")
        cents = next(iter(values))
        if intervals and abs(intervals[-1][2] - cents) < 1e-6 and abs(intervals[-1][1] - left) < 1e-9:
            intervals[-1] = (intervals[-1][0], right, cents)
        else:
            intervals.append((left, right, cents))
    return intervals


def _correction_at(intervals: list[tuple[float, float, float]], time_s: float) -> float:
    for start, end, cents in intervals:
        if start - 1e-9 <= time_s < end - 1e-9:
            return cents
    return 0.0


def _lane_pitch_bends(
    base_events: list[pretty_midi.PitchBend],
    intervals: list[tuple[float, float, float]],
) -> list[pretty_midi.PitchBend]:
    base = sorted((copy.deepcopy(pb) for pb in base_events), key=lambda pb: float(pb.time))
    values: dict[float, int] = {}
    for pb in base:
        cents = _correction_at(intervals, float(pb.time))
        combined = int(pb.pitch) + cents_to_pitch_bend(cents)
        if not -8192 <= combined <= 8191:
            raise ValueError(
                "authored pitch bend plus tuning correction exceeds MIDI pitch-bend range; "
                "reduce the expressive bend or the calibration offset"
            )
        values[float(pb.time)] = combined

    for index, (start, end, cents) in enumerate(intervals):
        set_time = max(0.0, float(start) - _BOUNDARY_EPSILON_S)
        combined = _bend_at(base, set_time) + cents_to_pitch_bend(cents)
        if not -8192 <= combined <= 8191:
            raise ValueError("authored pitch bend plus tuning correction exceeds MIDI range")
        values[set_time] = combined
        next_start = intervals[index + 1][0] if index + 1 < len(intervals) else None
        if next_start is None or float(next_start) > float(end) + 2 * _BOUNDARY_EPSILON_S:
            reset_time = float(end) + _BOUNDARY_EPSILON_S
            values[reset_time] = _bend_at(base, reset_time)

    out: list[pretty_midi.PitchBend] = []
    previous: int | None = None
    for time_s, value in sorted(values.items()):
        if previous == value:
            continue
        out.append(pretty_midi.PitchBend(pitch=int(value), time=float(time_s)))
        previous = value
    return out


def build_tuning_lane_pms(
    pm: pretty_midi.PrettyMIDI,
    instrument_spec: Mapping[str, Any],
) -> list[pretty_midi.PrettyMIDI]:
    """Return independent pitch-bend-safe render lanes for one instrument PM.

    The caller renders and sums every returned PM. A monophonic part remains
    one pass even for a per-note curve. Chords create only as many passes as are
    needed by simultaneous notes that require different offsets.
    """

    profile = tuning_correction_for_instrument(instrument_spec)
    if profile is None:
        return [pm]
    active = [inst for inst in pm.instruments if inst.notes]
    if len(active) != 1:
        raise ValueError("tuning correction expects a per-instrument PrettyMIDI render copy")
    inst = active[0]
    if inst.is_drum:
        return [pm]
    lane_notes = _assign_tuning_lanes(inst, profile)
    lane_pms: list[pretty_midi.PrettyMIDI] = []
    for lane_index, notes in enumerate(lane_notes):
        lane_pm = copy.deepcopy(pm)
        lane_inst = next(item for item in lane_pm.instruments if item.notes)
        lane_inst.name = inst.name
        lane_inst.notes = []
        for source in notes:
            note = copy.deepcopy(source)
            try:
                delattr(note, "_ambition_tuning_cents")
            except AttributeError:
                pass
            lane_inst.notes.append(note)
        intervals = _correction_intervals(notes)
        lane_inst.pitch_bends = _lane_pitch_bends(inst.pitch_bends, intervals)
        setattr(lane_pm, "_ambition_tuning_lane_index", lane_index)
        setattr(lane_pm, "_ambition_tuning_profile", copy.deepcopy(profile))
        lane_pms.append(lane_pm)
    return lane_pms
