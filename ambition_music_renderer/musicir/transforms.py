"""Common clip transforms shared by exact and generated MusicIR v3 material."""
from __future__ import annotations

import dataclasses as dc
from typing import Any, Mapping


@dc.dataclass(frozen=True)
class ClipTransform:
    """Source-independent transformations applied after material expansion.

    These fields intentionally live at the clip level so an exact event list,
    reusable material, and procedural generator all respond to the same knobs.
    Generator-specific fields with similar names remain inside ``generate`` and
    execute before these common transforms.
    """

    transpose: int = 0
    octave: int = 0
    velocity_scale: float = 1.0
    velocity_offset: int = 0
    gate: float = 1.0
    time_scale: float = 1.0

    @property
    def semitones(self) -> int:
        return int(self.transpose) + 12 * int(self.octave)

    def transform_tick_offset(self, ticks: int) -> int:
        return int(round(int(ticks) * self.time_scale))

    def transform_duration_ticks(self, ticks: int) -> int:
        return max(1, int(round(int(ticks) * self.time_scale)))

    def transform_velocity(self, velocity: int | float) -> int:
        value = round(float(velocity) * self.velocity_scale + self.velocity_offset)
        return max(1, min(127, int(value)))

    def transform_pitch(self, pitch: int) -> int:
        return max(0, min(127, int(pitch) + self.semitones))

    def transform_sounding_duration_ticks(self, ticks: int) -> int:
        scaled = self.transform_duration_ticks(ticks)
        return max(1, int(round(scaled * self.gate)))

    def as_dict(self) -> dict[str, Any]:
        return dc.asdict(self)


def clip_transform(clip: Mapping[str, Any]) -> ClipTransform:
    transform = ClipTransform(
        transpose=int(clip.get("transpose", 0)),
        octave=int(clip.get("octave", 0)),
        velocity_scale=float(clip.get("velocity_scale", 1.0)),
        velocity_offset=int(clip.get("velocity_offset", 0)),
        gate=float(clip.get("gate", 1.0)),
        time_scale=float(clip.get("time_scale", 1.0)),
    )
    if transform.velocity_scale < 0:
        raise ValueError("MusicIR v3 clip velocity_scale must be >= 0")
    if transform.gate <= 0:
        raise ValueError("MusicIR v3 clip gate must be > 0")
    if transform.time_scale <= 0:
        raise ValueError("MusicIR v3 clip time_scale must be > 0")
    return transform
