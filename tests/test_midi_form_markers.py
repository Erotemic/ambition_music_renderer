from pathlib import Path

import mido
import pretty_midi

from ambition_music_renderer.render.export import write_marked_midi


def test_write_marked_midi_preserves_form_markers(tmp_path: Path) -> None:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0, resolution=960)
    inst = pretty_midi.Instrument(program=0, name="piano")
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=4.0))
    pm.instruments.append(inst)

    path = tmp_path / "preview.mid"
    write_marked_midi(
        pm,
        path,
        [
            {"id": "opening", "label": "Opening", "start_seconds": 0.0},
            {"id": "development", "label": "Development", "start_seconds": 2.0},
        ],
    )

    midi = mido.MidiFile(path)
    markers = []
    absolute_tick = 0
    for message in midi.tracks[0]:
        absolute_tick += message.time
        if message.type == "marker":
            markers.append((message.text, absolute_tick))

    assert [text for text, _tick in markers] == ["Opening", "Development"]
    assert markers[0][1] == 0
    assert markers[1][1] == 3840
