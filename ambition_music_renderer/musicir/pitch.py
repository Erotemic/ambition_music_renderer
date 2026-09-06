"""Explicit pitch semantics for MusicIR v3 exact events.

Compact integers/note names remain legal.  Mapping forms make intent explicit
when a pitch depends on harmony, scale position, percussion identity, or a
physical string/fret coordinate.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..render.score_theory import chord_intervals, note_to_midi, root_for_chord

SCALE_INTERVALS: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "ionian": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "natural_minor": (0, 2, 3, 5, 7, 8, 10),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "melodic_minor": (0, 2, 3, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "major_pentatonic": (0, 2, 4, 7, 9),
    "minor_pentatonic": (0, 3, 5, 7, 10),
}

GM_DRUM_NOTES: dict[str, int] = {
    "kick": 36,
    "bass_drum": 36,
    "side_stick": 37,
    "snare": 38,
    "clap": 39,
    "electric_snare": 40,
    "low_floor_tom": 41,
    "closed_hat": 42,
    "closed_hihat": 42,
    "high_floor_tom": 43,
    "pedal_hat": 44,
    "low_tom": 45,
    "open_hat": 46,
    "open_hihat": 46,
    "low_mid_tom": 47,
    "high_mid_tom": 48,
    "crash": 49,
    "high_tom": 50,
    "ride": 51,
    "china": 52,
    "ride_bell": 53,
    "tambourine": 54,
    "splash": 55,
    "cowbell": 56,
    "crash_2": 57,
    "vibraslap": 58,
    "ride_2": 59,
}

PITCH_KINDS = (
    "note",
    "midi",
    "relative",
    "harmony_root",
    "chord_tone",
    "scale_degree",
    "drum",
    "guitar_fret",
)


def _fit(pitch: int) -> int:
    if not 0 <= int(pitch) <= 127:
        raise ValueError(f"MusicIR v3 pitch {pitch} is outside MIDI range 0..127")
    return int(pitch)


def _root_note(value: str, octave: int) -> int:
    text = str(value).strip()
    if text and text[-1].isdigit() or (len(text) >= 2 and text[-2] == "-" and text[-1].isdigit()):
        return note_to_midi(text)
    return note_to_midi(f"{text}{int(octave)}")


def _degree_pitch(root: int, intervals: tuple[int, ...] | list[int], degree: int) -> int:
    if degree == 0:
        raise ValueError("MusicIR v3 degrees are one-based; degree 0 is invalid")
    if degree < 0:
        # -1 means the scale/chord tone immediately below degree 1.
        zero = degree
    else:
        zero = degree - 1
    size = len(intervals)
    octave_shift, index = divmod(zero, size)
    return int(root + int(intervals[index]) + 12 * octave_shift)


def resolve_pitch(
    value: Any,
    *,
    graph: Any,
    clock: Any,
    tick: int,
) -> int:
    """Resolve one compact or explicit pitch expression to a MIDI note."""

    if isinstance(value, bool):
        raise TypeError("boolean is not a MusicIR pitch")
    if isinstance(value, int):
        return _fit(value)
    if isinstance(value, str):
        return _fit(note_to_midi(value))
    if not isinstance(value, Mapping):
        raise TypeError(f"unsupported MusicIR v3 pitch expression {value!r}")

    kind = str(value.get("kind", "")).strip()
    if not kind:
        # Friendly explicit shorthands while keeping one normalized semantic set.
        for candidate in PITCH_KINDS:
            if candidate in value:
                kind = candidate
                payload = value[candidate]
                if isinstance(payload, Mapping):
                    merged = dict(payload)
                    merged["kind"] = candidate
                    value = merged
                elif candidate == "note":
                    value = {"kind": "note", "name": payload}
                elif candidate == "midi":
                    value = {"kind": "midi", "value": payload}
                elif candidate == "drum":
                    value = {"kind": "drum", "name": payload}
                break
    if kind not in PITCH_KINDS:
        raise ValueError(
            f"unknown MusicIR v3 pitch kind {kind!r}; expected one of {list(PITCH_KINDS)}"
        )

    if kind == "note":
        return _fit(note_to_midi(str(value.get("name", value.get("value")))))
    if kind == "midi":
        return _fit(int(value.get("value", value.get("note"))))
    if kind == "relative":
        root = value.get("root")
        if root is None:
            raise ValueError("MusicIR v3 relative pitch needs `root`")
        root_pitch = resolve_pitch(root, graph=graph, clock=clock, tick=tick)
        return _fit(root_pitch + int(value.get("semitones", value.get("offset", 0))))

    if kind == "drum":
        name = str(value.get("name", value.get("value", ""))).lower().replace("-", "_").replace(" ", "_")
        if name not in GM_DRUM_NOTES:
            raise ValueError(
                f"unknown MusicIR v3 drum name {name!r}; expected one of {sorted(GM_DRUM_NOTES)}"
            )
        return GM_DRUM_NOTES[name]

    if kind == "guitar_fret":
        open_pitch = value.get("string", value.get("open"))
        if open_pitch is None:
            raise ValueError("MusicIR v3 guitar_fret pitch needs `string`/`open`, e.g. E2")
        fret = int(value.get("fret", 0))
        if fret < 0:
            raise ValueError("MusicIR v3 guitar fret must be >= 0")
        base = resolve_pitch(open_pitch, graph=graph, clock=clock, tick=tick)
        return _fit(base + fret)

    if kind == "harmony_root":
        chord = graph.chord_at_tick(clock, int(tick))
        octave = int(value.get("octave", 3))
        if bool(value.get("use_slash_bass", False)):
            base = root_for_chord(chord, octave=octave)
        else:
            root, _intervals, _slash = chord_intervals(chord)
            base = note_to_midi(f"{root}{octave}")
        return _fit(base + int(value.get("offset", 0)))

    if kind == "chord_tone":
        chord = graph.chord_at_tick(clock, int(tick))
        root_name, intervals, _slash = chord_intervals(chord)
        octave = int(value.get("octave", 4))
        root = note_to_midi(f"{root_name}{octave}")
        degree = int(value.get("degree", 1))
        return _fit(_degree_pitch(root, intervals, degree) + int(value.get("offset", 0)))

    if kind == "scale_degree":
        mode = str(value.get("mode", "major")).lower().replace("-", "_")
        if mode not in SCALE_INTERVALS:
            raise ValueError(
                f"unknown MusicIR v3 scale mode {mode!r}; expected one of {sorted(SCALE_INTERVALS)}"
            )
        tonic = value.get("tonic", value.get("key"))
        if tonic is None and getattr(graph, "key_context", None):
            tonic = graph.key_context.get("tonic")
            if "mode" not in value and graph.key_context.get("mode"):
                mode = str(graph.key_context["mode"]).lower().replace("-", "_")
                if mode not in SCALE_INTERVALS:
                    raise ValueError(
                        f"unknown MusicIR v3 score key mode {mode!r}; expected one of {sorted(SCALE_INTERVALS)}"
                    )
        if tonic is None:
            # With no score key, fall back to the active harmony root while
            # still using scale intervals rather than chord tones.
            chord = graph.chord_at_tick(clock, int(tick))
            tonic, _intervals, _slash = chord_intervals(chord)
        root = _root_note(str(tonic), int(value.get("octave", 4)))
        degree = int(value.get("degree", 1))
        return _fit(_degree_pitch(root, SCALE_INTERVALS[mode], degree) + int(value.get("offset", 0)))

    raise AssertionError(kind)


def pitch_syntax_reference() -> dict[str, Any]:
    """Return compact machine-readable examples for agent introspection."""

    return {
        "compact": [60, "C4"],
        "explicit": {
            "note": {"kind": "note", "name": "C#5"},
            "midi": {"kind": "midi", "value": 73},
            "relative": {"kind": "relative", "root": "E4", "semitones": 7},
            "harmony_root": {"kind": "harmony_root", "octave": 3},
            "chord_tone": {"kind": "chord_tone", "degree": 3, "octave": 4},
            "scale_degree": {"kind": "scale_degree", "tonic": "E", "mode": "minor", "degree": 6, "octave": 4},
            "drum": {"kind": "drum", "name": "snare"},
            "guitar_fret": {"kind": "guitar_fret", "string": "A2", "fret": 7},
        },
        "scale_modes": sorted(SCALE_INTERVALS),
        "gm_drum_names": dict(sorted(GM_DRUM_NOTES.items())),
    }
