"""SFZ key-span parsing + out-of-range octave folding.

A sampled instrument only covers its real range; an authored sub-bass part below
the lowest sampled string would drop to silence on the sfizz render.  The backend
parses the SFZ's key span and octave-folds out-of-range notes back into it (what a
player does when a note is below the lowest string).
"""
from __future__ import annotations

import pretty_midi

from ambition_music_renderer.backends import sfizz_backend as sb


def test_note_to_midi_parses_numbers_and_names():
    assert sb._note_to_midi("60") == 60
    assert sb._note_to_midi("c4") == 60          # sfizz convention c4 == 60
    assert sb._note_to_midi("a0") == 21
    assert sb._note_to_midi("f#2") == 42


def test_key_span_from_sfz_text(tmp_path):
    sfz = tmp_path / "bass.sfz"
    sfz.write_text(
        "<group> lokey=33 hikey=45 pitch_keycenter=33\n"
        "<region> sample=a.wav key=40\n"
        "<group> lokey=46 hikey=84\n"
        "<region> sample=b.wav\n"
    )
    assert sb.sfz_key_span(str(sfz)) == (33, 84)


def test_fold_lifts_subrange_notes_into_span():
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=33, name="bass")
    # D1(26) and E1(28) are below a (33..84) span; C2(36) is already inside.
    for p in (26, 28, 36):
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=p, start=0.0, end=0.3))
    pm.instruments.append(inst)
    shifted = sb.fold_pm_into_key_span(pm, (33, 84))
    pitches = sorted(n.pitch for n in pm.instruments[0].notes)
    assert shifted == 2
    assert min(pitches) >= 33 and max(pitches) <= 84
    # pitch classes are preserved (folded by whole octaves)
    assert 26 % 12 in {p % 12 for p in pitches}
    assert 28 % 12 in {p % 12 for p in pitches}


def test_fold_skips_narrow_percussion_maps_and_drums():
    pm = pretty_midi.PrettyMIDI()
    drum = pretty_midi.Instrument(program=0, is_drum=True, name="kit")
    drum.notes.append(pretty_midi.Note(velocity=90, pitch=36, start=0.0, end=0.1))
    pm.instruments.append(drum)
    # drums are never folded; a <12-semitone span is also a no-op
    assert sb.fold_pm_into_key_span(pm, (36, 40)) == 0
