"""Small guitar-performance compiler helpers.

This is intentionally not a full tablature solver.  It provides deterministic
MusicIR-side semantics that remain useful whether the audio comes from GM,
FluidSynth, SFZ, VST3, or an external amp chain:

* assign simultaneous chord notes to plausible unique strings;
* turn block chords into ordered down/up strums;
* generate simple power-chord chugs with separate-take offsets; and
* add tiny lead-note scoops based on string/fret movement.
"""

from __future__ import annotations

import dataclasses as dc
from typing import Any, Iterable

STANDARD_TUNING = (40, 45, 50, 55, 59, 64)  # E2 A2 D3 G3 B3 E4, low to high.
DROP_D_TUNING = (38, 45, 50, 55, 59, 64)

TUNINGS = {
    "standard": STANDARD_TUNING,
    "eadgbe": STANDARD_TUNING,
    "drop_d": DROP_D_TUNING,
    "dadgbe": DROP_D_TUNING,
}


@dc.dataclass(frozen=True)
class StringFret:
    string_index: int  # 0 = lowest pitched string
    fret: int
    pitch: int
    source_pitch: int


def tuning_from_spec(spec: str | Iterable[int] | None) -> tuple[int, ...]:
    if spec is None:
        return STANDARD_TUNING
    if isinstance(spec, str):
        key = spec.lower().replace("-", "_").strip()
        if key in TUNINGS:
            return tuple(TUNINGS[key])
        raise ValueError(f"unknown guitar tuning {spec!r}; use standard/drop_d or a MIDI list")
    vals = tuple(int(x) for x in spec)
    if len(vals) != 6:
        raise ValueError("guitar tuning must have exactly 6 MIDI string pitches")
    return vals


def positions_for_pitch(
    pitch: int,
    *,
    tuning: tuple[int, ...] = STANDARD_TUNING,
    max_fret: int = 19,
    octave_shifts: Iterable[int] = (-12, 0, 12),
) -> list[StringFret]:
    out: list[StringFret] = []
    seen: set[tuple[int, int, int]] = set()
    for source_shift in octave_shifts:
        p = int(pitch) + int(source_shift)
        for string_index, open_pitch in enumerate(tuning):
            fret = p - int(open_pitch)
            if 0 <= fret <= int(max_fret):
                key = (string_index, fret, p)
                if key not in seen:
                    out.append(StringFret(string_index=string_index, fret=fret, pitch=p, source_pitch=int(pitch)))
                    seen.add(key)
    out.sort(key=lambda sf: (sf.fret == 0, -sf.string_index, sf.fret), reverse=True)
    return out


def _span(frets: list[int]) -> int:
    fretted = [f for f in frets if f > 0]
    if not fretted:
        return 0
    return max(fretted) - min(fretted)


def _candidate_score(
    combo: list[StringFret],
    *,
    max_span: int,
    prefer_open: bool,
    previous: list[StringFret] | None,
) -> float:
    frets = [sf.fret for sf in combo]
    strings = [sf.string_index for sf in combo]
    span = _span(frets)
    score = span * 10.0
    if span > max_span:
        score += (span - max_span) * 100.0
    score += sum(max(0, f - 7) for f in frets) * 1.5
    score += sum(frets) * 0.12
    if prefer_open:
        score -= sum(1 for f in frets if f == 0) * 2.0
    # Prefer chord shapes whose sorted strings are compact but not all on one
    # narrow high cluster.
    if strings:
        score += (max(strings) - min(strings)) * 0.25
    if previous:
        prev_by_src = {sf.source_pitch: sf for sf in previous}
        motion = 0.0
        for sf in combo:
            old = prev_by_src.get(sf.source_pitch)
            if old is not None:
                motion += abs(old.fret - sf.fret) + abs(old.string_index - sf.string_index) * 0.5
        score += motion * 0.8
    return float(score)


def allocate_chord(
    pitches: Iterable[int],
    *,
    tuning: tuple[int, ...] = STANDARD_TUNING,
    max_fret: int = 17,
    max_span: int = 5,
    max_notes: int = 6,
    prefer_open: bool = True,
    previous: list[StringFret] | None = None,
) -> list[StringFret]:
    """Assign chord pitches to playable unique strings.

    The search is small by construction: keep at most max_notes notes, try each
    pitch in nearby octaves, and prune duplicate strings.  If a fully unique
    solution is unavailable, fall back to a simple low-to-high voicing.
    """
    base = [int(p) for p in pitches]
    # Remove duplicates by pitch class/octave while preserving order.
    deduped: list[int] = []
    seen: set[int] = set()
    for p in base:
        if p not in seen:
            deduped.append(p)
            seen.add(p)
    notes = deduped[: int(max_notes)]
    if not notes:
        return []
    choices = [positions_for_pitch(p, tuning=tuning, max_fret=max_fret)[:8] for p in notes]
    if any(not c for c in choices):
        # Fold impossible notes by octaves into the instrument range.
        folded: list[int] = []
        for p in notes:
            q = int(p)
            while q < min(tuning):
                q += 12
            while q > max(tuning) + max_fret:
                q -= 12
            folded.append(q)
        choices = [positions_for_pitch(p, tuning=tuning, max_fret=max_fret)[:8] for p in folded]
    best: list[StringFret] | None = None
    best_score = float("inf")

    def rec(idx: int, used_strings: set[int], acc: list[StringFret]) -> None:
        nonlocal best, best_score
        if idx == len(choices):
            score = _candidate_score(acc, max_span=max_span, prefer_open=prefer_open, previous=previous)
            if score < best_score:
                best = list(acc)
                best_score = score
            return
        for sf in choices[idx]:
            if sf.string_index in used_strings:
                continue
            used_strings.add(sf.string_index)
            acc.append(sf)
            rec(idx + 1, used_strings, acc)
            acc.pop()
            used_strings.remove(sf.string_index)

    rec(0, set(), [])
    if best is not None:
        return sorted(best, key=lambda sf: sf.string_index)
    fallback: list[StringFret] = []
    used: set[int] = set()
    for choice in choices:
        avail = [sf for sf in choice if sf.string_index not in used]
        if not avail:
            continue
        sf = min(avail, key=lambda x: (x.fret, -x.string_index))
        fallback.append(sf)
        used.add(sf.string_index)
    return sorted(fallback, key=lambda sf: sf.string_index)


def strum_plan(
    pitches: Iterable[int],
    *,
    bpm: float,
    direction: str = "down",
    spread_ms: float = 35.0,
    velocity: float = 88.0,
    velocity_slope: float = -2.0,
    tuning: tuple[int, ...] = STANDARD_TUNING,
    max_fret: int = 17,
    max_span: int = 5,
    max_notes: int = 6,
    prefer_open: bool = True,
    previous: list[StringFret] | None = None,
) -> tuple[list[dict[str, float]], list[StringFret]]:
    assignment = allocate_chord(
        pitches,
        tuning=tuning,
        max_fret=max_fret,
        max_span=max_span,
        max_notes=max_notes,
        prefer_open=prefer_open,
        previous=previous,
    )
    ordered = sorted(assignment, key=lambda sf: sf.string_index)
    if direction.lower().startswith("up"):
        ordered = list(reversed(ordered))
    beat_per_second = float(bpm) / 60.0
    if len(ordered) <= 1:
        offsets = [0.0]
    else:
        offsets = [i * (float(spread_ms) / 1000.0) * beat_per_second / (len(ordered) - 1) for i in range(len(ordered))]
    events: list[dict[str, float]] = []
    for idx, (sf, off) in enumerate(zip(ordered, offsets)):
        events.append(
            {
                "pitch": float(sf.pitch),
                "beat_offset": float(off),
                "velocity": float(velocity + velocity_slope * idx),
                "string": float(sf.string_index),
                "fret": float(sf.fret),
            }
        )
    return events, assignment


def power_chord_pitches(root: int, *, shape: str = "fifth_octave") -> list[int]:
    if shape in {"root", "single"}:
        return [int(root)]
    if shape in {"fifth", "power2"}:
        return [int(root), int(root) + 7]
    if shape in {"octave", "root_octave"}:
        return [int(root), int(root) + 12]
    return [int(root), int(root) + 7, int(root) + 12]


def take_specs(layer: dict[str, Any], default_instruments: list[str]) -> list[dict[str, Any]]:
    raw = layer.get("takes")
    if raw:
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, str):
                out.append({"instrument": item})
            else:
                out.append(dict(item))
        return out
    return [{"instrument": name} for name in default_instruments]
