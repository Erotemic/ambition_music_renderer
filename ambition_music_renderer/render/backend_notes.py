"""Backend-specific MIDI note mapping helpers.

MusicIR parts keep semantic MIDI pitches so General MIDI and score-level audits
remain meaningful. Sampled backends can then remap those authored pitches to a
patch's trigger keys without mutating the shared performance.
"""

from __future__ import annotations

from typing import Any

import pretty_midi

from .score_core import DRUMS


def backend_note_number(value: Any) -> int:
    """Resolve a MIDI endpoint from an integer, note name, or semantic drum role."""

    if isinstance(value, bool):
        raise ValueError(f"boolean is not a valid MIDI note: {value!r}")
    if isinstance(value, (int, float)) and float(value).is_integer():
        note = int(value)
    else:
        token = str(value).strip()
        if token in DRUMS:
            note = DRUMS[token]
        elif token.lstrip("-").isdigit():
            note = int(token)
        else:
            try:
                note = pretty_midi.note_name_to_number(token)
            except ValueError as ex:
                raise ValueError(
                    f"invalid backend note {value!r}; use MIDI 0..127, a note name like C4, "
                    f"or a drum role such as snare"
                ) from ex
    if not 0 <= note <= 127:
        raise ValueError(f"backend MIDI note must be in 0..127; got {note}")
    return note


def backend_note_remap(inst_backend: dict[str, Any]) -> dict[int, int]:
    """Normalize ``note_remap`` / ``midi_note_map`` to integer MIDI pairs."""

    raw = inst_backend.get("note_remap", inst_backend.get("midi_note_map"))
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise TypeError("instrument_backend.note_remap must be a mapping")
    return {backend_note_number(src): backend_note_number(dst) for src, dst in raw.items()}


def remap_backend_pitch(pitch: int, inst_backend: dict[str, Any]) -> int:
    """Return the sampled-backend pitch for one authored MIDI pitch."""

    mapping = backend_note_remap(inst_backend)
    return mapping.get(int(pitch), int(pitch))


def apply_backend_note_remap(pm: pretty_midi.PrettyMIDI, inst_backend: dict[str, Any]) -> int:
    """Apply backend-only remapping to a copied PrettyMIDI performance."""

    mapping = backend_note_remap(inst_backend)
    changed = 0
    for inst in pm.instruments:
        for note in inst.notes:
            replacement = mapping.get(note.pitch)
            if replacement is None or replacement == note.pitch:
                continue
            note.pitch = replacement
            changed += 1
    return changed
