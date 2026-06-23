"""Music theory, harmony, and motif helpers for MusicIR scores."""

from __future__ import annotations

import re
from typing import Any

import pretty_midi

from .score_core import NOTE_CLASS, RenderContext

def note_to_midi(note: str) -> int:
    note = note.strip()
    m = re.fullmatch(r"([A-G](?:#|b)?)(-?\d+)", note)
    if not m:
        raise ValueError(f"bad note name: {note!r}")
    return 12 * (int(m.group(2)) + 1) + NOTE_CLASS[m.group(1)]


def midi_to_note(num: int) -> str:
    return pretty_midi.note_number_to_name(int(num))


def clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def fit_midi_pitch(num: int | float) -> int:
    """Fold an integer pitch into the valid MIDI range by octaves.

    Hard-clamping high generated voicings to 127 creates artificial G9 notes
    that are both musically wrong and extremely obvious in sour-note audits.
    Octave folding preserves pitch class while keeping generated pads playable.
    """
    p = int(round(float(num)))
    while p > 127:
        p -= 12
    while p < 0:
        p += 12
    return int(clamp(p, 0, 127))


def chord_intervals(chord_symbol: str) -> tuple[str, list[int], str | None]:
    raw = chord_symbol.strip()
    if "/" in raw:
        main_candidate, slash_candidate = raw.rsplit("/", 1)
        # Treat C/E and G/B as slash-bass chords, but keep extensions such as
        # D6/9 as part of the chord suffix instead of pretending "9" is a bass note.
        if re.match(r"^[A-G](?:#|b)?$", slash_candidate.strip()):
            main, slash_bass = main_candidate, slash_candidate.strip()
        else:
            main, slash_bass = raw, None
    else:
        main, slash_bass = raw, None
    m = re.match(r"^([A-G](?:#|b)?)(.*)$", main)
    if not m:
        raise ValueError(f"cannot parse chord root from {chord_symbol!r}")
    root = m.group(1)
    suffix = m.group(2).lower()
    if "dim" in suffix or "o" in suffix:
        intervals = [0, 3, 6]
    elif "aug" in suffix or "+" in suffix:
        intervals = [0, 4, 8]
    elif "sus2" in suffix:
        intervals = [0, 2, 7]
    elif "sus4" in suffix or "sus" in suffix:
        intervals = [0, 5, 7]
    elif suffix.startswith("m") and not suffix.startswith("maj"):
        intervals = [0, 3, 7]
    else:
        intervals = [0, 4, 7]
    add9 = "add9" in suffix
    six_nine = "6/9" in suffix or "6add9" in suffix
    major_seventh_quality = "maj7" in suffix or "maj9" in suffix or "Δ" in suffix
    dominant_extension = (
        "7" in suffix
        or "13" in suffix
        or ("9" in suffix and not add9 and not six_nine and "maj9" not in suffix)
    )
    if major_seventh_quality:
        intervals.append(11)
    elif dominant_extension:
        intervals.append(10)
    if "6" in suffix and 9 not in intervals:
        intervals.append(9)
    if "9" in suffix or add9:
        intervals.append(14)
    if "#11" in suffix:
        intervals.append(18)
    elif "11" in suffix:
        intervals.append(17)
    if "b13" in suffix:
        intervals.append(20)
    elif "13" in suffix:
        intervals.append(21)
    if "b9" in suffix:
        intervals.append(13)
    if "#9" in suffix:
        intervals.append(15)
    seen = set()
    intervals = [i for i in intervals if not (i in seen or seen.add(i))]
    return root, intervals, slash_bass


def chord_pitches(
    chord_symbol: str, octave: int = 4, *, voicing: str = "closed"
) -> list[int]:
    root, intervals, slash_bass = chord_intervals(chord_symbol)
    root_midi = note_to_midi(f"{root}{octave}")
    voicing_key = str(voicing).lower().replace("-", "_")
    if voicing_key in {"triad", "plain_triad"}:
        intervals = intervals[:3]
    elif voicing_key in {"root_fifth", "fifth"}:
        intervals = [0, 7]
    elif voicing_key in {"root_fifth_octave", "power", "power_chord"}:
        intervals = [0, 7, 12]
    elif voicing_key in {"guitar_shell", "rhythm_shell"}:
        # Guitar rhythm beds usually sound more realistic when long ringing
        # chords use a stable root/fifth shell plus one chord-quality note, not
        # every extension from the lead-sheet symbol.  This avoids add9/sus/6
        # tones smearing into the next bar while the reverb supplies sustain.
        third = intervals[1] if len(intervals) > 1 and intervals[1] in {3, 4, 5} else None
        intervals = [0, 7] + ([third + 12] if third is not None else [12])
    notes = [root_midi + i for i in intervals]
    if voicing_key in {"open", "spread"} and len(notes) >= 4:
        notes = [notes[0] - 12, notes[2], notes[1] + 12, notes[3]] + [
            n + 12 for n in notes[4:]
        ]
    elif voicing_key == "wide" and len(notes) >= 3:
        notes = [notes[0] - 12, notes[2], notes[1] + 12] + [n + 12 for n in notes[3:]]
    elif voicing_key == "drop2" and len(notes) >= 4:
        notes = notes[:]
        notes[-2] -= 12
        notes.sort()
    elif voicing_key == "guitar_shell" and len(notes) >= 3:
        notes = [notes[0] - 12, notes[1], notes[2]]
    if slash_bass and voicing_key not in {"root_fifth", "fifth", "root_fifth_octave", "power", "power_chord", "guitar_shell", "rhythm_shell"}:
        bass_root = re.match(r"^([A-G](?:#|b)?)", slash_bass.strip())
        if bass_root:
            notes.insert(0, note_to_midi(f"{bass_root.group(1)}{octave - 1}"))
    return notes


def section_starts(sections: list[dict[str, Any]]) -> dict[str, int]:
    starts: dict[str, int] = {}
    cursor = 0
    for sec in sections:
        starts[sec["id"]] = cursor
        sec["start_bar"] = cursor
        cursor += int(sec["bars"])
    return starts



def chord_for_bar(section: dict[str, Any], local_bar: int) -> str:
    harmony = section.get("harmony") or ["C"]
    return harmony[local_bar % len(harmony)]


def root_for_chord(chord: str, octave: int = 2) -> int:
    root, _intervals, slash = chord_intervals(chord)
    bass = slash or root
    bass = re.match(r"^([A-G](?:#|b)?)", bass).group(1)  # type: ignore[union-attr]
    return note_to_midi(f"{bass}{octave}")


def transform_motif(
    notes: list[int], transform: str | dict[str, Any] | None, pivot: int | None = None
) -> list[int]:
    out = list(notes)
    if not transform:
        return out
    if isinstance(transform, dict):
        kind = transform.get("kind")
    else:
        kind = transform
    if kind == "retrograde":
        out = list(reversed(out))
    elif kind == "invert":
        p = pivot if pivot is not None else out[0]
        out = [p - (n - p) for n in out]
    elif kind == "transpose":
        shift = int(transform.get("semitones", 0)) if isinstance(transform, dict) else 0
        out = [n + shift for n in out]
    elif kind == "up_octave":
        out = [n + 12 for n in out]
    elif kind == "down_octave":
        out = [n - 12 for n in out]
    return out


def motif_notes(
    ctx: RenderContext,
    motif_id: str,
    root: str | int | None = None,
    transform: Any = None,
    transpose: int = 0,
) -> tuple[list[int], list[float], list[float]]:
    motif = ctx.motifs[motif_id]
    if "notes" in motif:
        notes = [
            note_to_midi(n) if isinstance(n, str) else int(n) for n in motif["notes"]
        ]
        if root is not None and isinstance(root, str):
            base = note_to_midi(root)
            motif_base = note_to_midi(motif.get("root", "C4"))
            notes = [base + (n - motif_base) for n in notes]
    else:
        base = note_to_midi(root if isinstance(root, str) else motif.get("root", "C4"))
        notes = [base + int(x) for x in motif.get("intervals", [0])]
    notes = [n + transpose for n in notes]
    if transform:
        if isinstance(transform, list):
            for tr in transform:
                notes = transform_motif(notes, tr)
        else:
            notes = transform_motif(notes, transform)
    rhythm = [float(x) for x in motif.get("rhythm", [1.0] * len(notes))]
    velocities = [float(x) for x in motif.get("velocities", [1.0] * len(notes))]
    return notes, rhythm, velocities


