from __future__ import annotations

from pathlib import Path

import numpy as np
import pretty_midi

from ambition_music_renderer.instrument_resolution import (
    normalize_tuning_correction,
    resolve_instrument_backend,
)


def test_soundfont_resolution_and_tuning_api_coexist(tmp_path: Path):
    sf2 = tmp_path / "shamisen.sf2"
    sf2.write_bytes(b"soundfont")
    plan = resolve_instrument_backend(
        {"kind": "soundfont", "soundfont": str(sf2), "renderer": "fluidsynth-cli"},
        base_dir=tmp_path,
    )
    assert plan.wants_soundfont is True
    assert plan.resolved_soundfont == sf2.resolve()
    assert normalize_tuning_correction(-7.0)["cents"] == -7.0


def test_group_routes_tuned_instrument_through_its_soundfont(monkeypatch, tmp_path: Path):
    import ambition_music_renderer.render.group as group_mod

    sf2 = tmp_path / "shamisen.sf2"
    sf2.write_bytes(b"soundfont")
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=106, name="shamisen")
    inst.notes.append(pretty_midi.Note(velocity=96, pitch=64, start=0.0, end=0.25))
    pm.instruments.append(inst)
    calls = []

    def fake_render(pm_arg, backend, soundfont, sample_rate, midi_path, dry_wav_path, minimum_duration):
        calls.append((backend, soundfont, [(pb.time, pb.pitch) for pb in pm_arg.instruments[0].pitch_bends]))
        return np.ones((100, 2), dtype=np.float32) * 0.01

    monkeypatch.setattr(group_mod, "render_synth_audio", fake_render)
    audio = group_mod.render_group_audio(
        pm, {"shamisen": "lead"}, "lead", "fallback", "", 12000, tmp_path, 0.25, 120.0,
        base_dir=tmp_path,
        instrument_specs={"shamisen": {
            "name": "shamisen", "group": "lead", "program": 106,
            "tuning_correction": -7.0,
            "instrument_backend": {
                "kind": "soundfont", "soundfont": str(sf2), "renderer": "fluidsynth-cli"
            },
        }},
    )
    assert len(audio) == 100
    assert len(calls) == 1
    assert calls[0][0] == "fluidsynth-cli"
    assert calls[0][1] == str(sf2.resolve())
    assert any(value != 0 for _time, value in calls[0][2])
