"""MusicIR v3 controller and pitch-bend automation expansion.

Authoring may use isolated points or compact curves. Curves are deterministically
sampled onto the exact score clock before ``CompiledScore`` so rendering, DAW
interchange, fingerprints, and diagnostics all see the same MIDI events.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from .graph import fraction_to_ticks

AUTOMATION_INTERPOLATIONS = ("step", "linear", "smooth")
DEFAULT_CURVE_RESOLUTION = "1/32"


def _point_pair(raw: Any) -> tuple[Any, Any]:
    if isinstance(raw, Mapping):
        if "at" not in raw or "value" not in raw:
            raise ValueError("automation curve point mappings need `at` and `value`")
        return copy.deepcopy(raw["at"]), raw["value"]
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return copy.deepcopy(raw[0]), raw[1]
    raise ValueError("automation curve points need [at, value] or {at: ..., value: ...}")


def _interp(a: float, b: float, alpha: float, kind: str) -> float:
    if kind == "step":
        return a
    if kind == "smooth":
        alpha = alpha * alpha * (3.0 - 2.0 * alpha)
    return a * (1.0 - alpha) + b * alpha


def expand_automation_item(raw: Mapping[str, Any], *, ppq: int) -> list[dict[str, Any]]:
    """Expand one authored automation item to point-form rows.

    Existing point syntax is returned unchanged (apart from a defensive copy).
    Curve syntax uses ``points`` plus optional ``interpolation`` and
    ``resolution``. ``resolution`` is a v3 exact duration such as ``1/32`` or
    ``{ticks: 60}``.
    """

    item = copy.deepcopy(dict(raw))
    if "points" not in item:
        return [item]
    points_raw = item.pop("points")
    if not isinstance(points_raw, list) or len(points_raw) < 2:
        raise ValueError("automation curve `points` must contain at least two points")
    kind = str(item.pop("interpolation", item.pop("curve", "linear"))).strip().lower()
    if kind not in AUTOMATION_INTERPOLATIONS:
        raise ValueError(
            f"automation interpolation {kind!r} must be one of {list(AUTOMATION_INTERPOLATIONS)}"
        )
    resolution_raw = item.pop("resolution", item.pop("step", DEFAULT_CURVE_RESOLUTION))
    resolution = fraction_to_ticks(resolution_raw, ppq=ppq)
    if resolution <= 0:
        raise ValueError("automation curve resolution must be > 0")
    curve_id = str(item.get("id", "automation_curve"))
    base_fields = {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key not in {"at", "value"}
    }
    parsed: list[tuple[int, float]] = []
    for raw_point in points_raw:
        at, value = _point_pair(raw_point)
        tick = fraction_to_ticks(at, ppq=ppq)
        parsed.append((tick, float(value)))
    parsed.sort(key=lambda row: row[0])
    if len({tick for tick, _ in parsed}) != len(parsed):
        raise ValueError("automation curve points must have unique positions")

    samples: dict[int, float] = {}
    for index in range(len(parsed) - 1):
        left_tick, left_value = parsed[index]
        right_tick, right_value = parsed[index + 1]
        if right_tick <= left_tick:
            raise ValueError("automation curve points must increase in time")
        samples[left_tick] = left_value
        if kind != "step":
            tick = left_tick + resolution
            while tick < right_tick:
                alpha = (tick - left_tick) / float(right_tick - left_tick)
                samples[tick] = _interp(left_value, right_value, alpha, kind)
                tick += resolution
    samples[parsed[-1][0]] = parsed[-1][1]

    out: list[dict[str, Any]] = []
    for sample_index, (tick, value) in enumerate(sorted(samples.items())):
        row = copy.deepcopy(base_fields)
        row["id"] = f"{curve_id}.p{sample_index:04d}"
        row["at"] = {"ticks": int(tick)}
        if "cc" in row or "controller" in row:
            row["value"] = int(max(0, min(127, round(value))))
        else:
            key = "pitch_bend" if "pitch_bend" in row else "bend"
            row[key] = int(max(-8192, min(8191, round(value))))
        row["_curve_id"] = curve_id
        row["_curve_interpolation"] = kind
        out.append(row)
    return out


def expand_automation(value: Any, *, ppq: int) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("MusicIR v3 clip automation must be a list")
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise TypeError(f"MusicIR v3 automation[{index}] must be a mapping")
        out.extend(expand_automation_item(raw, ppq=ppq))
    return out
