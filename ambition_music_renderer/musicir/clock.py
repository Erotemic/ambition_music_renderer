"""Project compiler clocks in quarter-note beats and zero-based bars."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..render.exact_score import ExactTempoMap, ScoreClock
    from ..render.score_core import TempoMap


class CompiledClock(Protocol):
    """Queries use the clock that compiled the score's events."""

    def time_at_beat(self, beat: float) -> float: ...
    def beat_at_bar(self, bar: int) -> float: ...
    def bar_at_beat(self, beat: float) -> int: ...
    def constant_grid(self, start: float, end: float) -> tuple[float, float] | None: ...
    def as_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProceduralClock:
    tempo: TempoMap
    beats_per_bar: float

    def time_at_beat(self, beat: float) -> float:
        return self.tempo.beat_to_time(beat)

    def beat_at_bar(self, bar: int) -> float:
        return bar * self.beats_per_bar

    def bar_at_beat(self, beat: float) -> int:
        return math.floor(beat / self.beats_per_bar)

    def constant_grid(self, start: float, end: float) -> tuple[float, float] | None:
        values = [self.tempo.bpm_at(start), self.tempo.bpm_at(end)]
        values.extend(bpm for beat, bpm in self.tempo.knots if start < beat < end)
        if all(math.isclose(value, values[0], rel_tol=1e-12) for value in values):
            return values[0], self.beats_per_bar
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "procedural",
            "beats_per_bar": self.beats_per_bar,
            "tempo_knots": [list(knot) for knot in self.tempo.knots],
        }


@dataclass(frozen=True)
class ExactClock:
    meter: ScoreClock
    tempo: ExactTempoMap

    def time_at_beat(self, beat: float) -> float:
        return self.tempo.tick_to_time(round(beat * self.meter.ppq))

    def beat_at_bar(self, bar: int) -> float:
        return self.meter.bar_start_tick(bar + 1) / self.meter.ppq

    def bar_at_beat(self, beat: float) -> int:
        return int(self.meter.tick_to_position(round(beat * self.meter.ppq))["bar"]) - 1

    def constant_grid(self, start: float, end: float) -> tuple[float, float] | None:
        first, last = round(start * self.meter.ppq), round(end * self.meter.ppq)
        if any(first <= tick < last for tick, _ in self.tempo.holds):
            return None
        values = [self.tempo.bpm_at_tick(first)]
        for segment in self.tempo.segments:
            if segment.start_tick < last and (segment.end_tick is None or segment.end_tick > first):
                values.extend((
                    self.tempo.bpm_at_tick(max(first, segment.start_tick)),
                    self.tempo.bpm_at_tick(min(last - 1, segment.end_tick or last)),
                ))
        change = self.meter.meter_at_bar(self.bar_at_beat(start) + 1)
        width = change.ticks_per_bar
        if any(first < item.start_tick < last and item.ticks_per_bar != width
               for item in self.meter.meter_changes):
            return None
        if all(math.isclose(value, values[0], rel_tol=1e-12) for value in values):
            return values[0], width / self.meter.ppq
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "exact",
            "ppq": self.meter.ppq,
            "meter_changes": [asdict(item) for item in self.meter.meter_changes],
            "tempo_segments": [asdict(item) for item in self.tempo.segments],
            "holds": [{"tick": tick, "seconds": seconds} for tick, seconds in self.tempo.holds],
        }
