from __future__ import annotations

import pretty_midi
import pytest

from ambition_music_renderer.render.backend_notes import (
    apply_backend_note_remap,
    backend_note_remap,
)


def _drum_pm(*pitches: int) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0, is_drum=True, name="orchestra_percussion")
    for idx, pitch in enumerate(pitches):
        inst.notes.append(
            pretty_midi.Note(
                velocity=100,
                pitch=pitch,
                start=idx * 0.25,
                end=idx * 0.25 + 0.1,
            )
        )
    pm.instruments.append(inst)
    return pm


def test_backend_note_remap_normalizes_drum_roles_and_note_names():
    assert backend_note_remap(
        {"note_remap": {"concert_bass_drum": "C4", "snare": "C#4", "crash": 62}}
    ) == {35: 60, 38: 61, 49: 62}


def test_backend_note_remap_accepts_drum_roles_and_note_names():
    pm = _drum_pm(35, 38, 49)
    changed = apply_backend_note_remap(
        pm,
        {"note_remap": {"concert_bass_drum": "C4", "snare": "C#4", "crash": 62}},
    )
    assert changed == 3
    assert [note.pitch for note in pm.instruments[0].notes] == [60, 61, 62]


def test_backend_note_remap_leaves_unmapped_notes_alone():
    pm = _drum_pm(35, 38)
    changed = apply_backend_note_remap(pm, {"midi_note_map": {"snare": "C4"}})
    assert changed == 1
    assert [note.pitch for note in pm.instruments[0].notes] == [35, 60]


def test_backend_note_remap_rejects_invalid_notes():
    pm = _drum_pm(38)
    with pytest.raises(ValueError, match="invalid backend note"):
        apply_backend_note_remap(pm, {"note_remap": {"snare": "not-a-note"}})
