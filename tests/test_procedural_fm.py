from __future__ import annotations

from pathlib import Path

import numpy as np
import pretty_midi

from ambition_music_renderer.render.group import render_group_audio
from ambition_music_renderer.render.synth import render_procedural_fm


def _one_note_pm() -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=80, name="lead")
    inst.notes.append(pretty_midi.Note(velocity=100, pitch=69, start=0.0, end=0.5))
    pm.instruments.append(inst)
    return pm


def _spec(index: float) -> dict:
    return {
        "kind": "procedural_fm",
        "carrier": {"waveform": "square", "harmonics": 11},
        "fm": {"waveform": "sine", "ratio": 0.25, "index": index},
        "envelope": {"attack_ms": 2, "decay_ms": 20, "sustain": 0.9, "release_ms": 20},
        "saturation_drive": 1.1,
        "output_gain_db": -6,
    }


def test_procedural_fm_is_audible_and_fm_changes_waveform():
    pm = _one_note_pm()
    plain = render_procedural_fm(pm, _spec(0.0), 24_000, 0.6)
    modulated = render_procedural_fm(pm, _spec(0.18), 24_000, 0.6)
    assert plain.shape == modulated.shape
    assert float(np.max(np.abs(modulated))) > 1e-3
    assert float(np.mean(np.abs(modulated - plain))) > 1e-3


def test_group_routes_procedural_fm_without_soundfont(tmp_path: Path):
    pm = _one_note_pm()
    pm._ambition_instrument_specs = {  # type: ignore[attr-defined]
        "lead": {"instrument_backend": _spec(0.14)}
    }
    audio = render_group_audio(
        pm,
        {"lead": "melody"},
        "melody",
        "pretty-midi",
        "",
        24_000,
        tmp_path,
        0.6,
        120.0,
        render_cfg={},
    )
    assert audio.ndim == 2 and audio.shape[1] == 2
    assert float(np.max(np.abs(audio))) > 1e-3
