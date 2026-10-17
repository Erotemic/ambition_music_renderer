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


def test_instrument_mix_gain_is_applied_after_synthesis(tmp_path: Path):
    base_pm = _one_note_pm()
    base_pm._ambition_instrument_specs = {  # type: ignore[attr-defined]
        "lead": {"instrument_backend": _spec(0.14), "mix_gain_db": 0.0}
    }
    trimmed_pm = _one_note_pm()
    trimmed_pm._ambition_instrument_specs = {  # type: ignore[attr-defined]
        "lead": {"instrument_backend": _spec(0.14), "mix_gain_db": -6.0}
    }
    base = render_group_audio(
        base_pm,
        {"lead": "melody"},
        "melody",
        "pretty-midi",
        "",
        24_000,
        tmp_path / "base",
        0.6,
        120.0,
        render_cfg={},
    )
    trimmed = render_group_audio(
        trimmed_pm,
        {"lead": "melody"},
        "melody",
        "pretty-midi",
        "",
        24_000,
        tmp_path / "trimmed",
        0.6,
        120.0,
        render_cfg={},
    )
    ratio = float(np.max(np.abs(trimmed))) / float(np.max(np.abs(base)))
    assert np.isclose(ratio, 10.0 ** (-6.0 / 20.0), rtol=1e-4)


def _sine_spec(**motion) -> dict:
    spec = {
        "kind": "procedural_fm",
        "carrier": {"waveform": "sine", "harmonics": 1},
        "fm": {"waveform": "sine", "ratio": 1.0, "index": 0.0},
        "envelope": {"attack_ms": 1, "decay_ms": 1, "sustain": 1.0, "release_ms": 1},
        "output_gain_db": -6,
    }
    spec.update(motion)
    return spec


def _hz(audio: np.ndarray, sr: int, t0: float, t1: float) -> float:
    """The mean frequency over a span, by zero crossings."""
    x = audio[int(t0 * sr) : int(t1 * sr), 0]
    crossings = np.count_nonzero(np.diff(np.signbit(x)))
    return crossings / 2.0 / (t1 - t0)


def _two_notes(gap: float = 0.0) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=80, name="lead")
    inst.notes.append(pretty_midi.Note(velocity=100, pitch=57, start=0.0, end=0.5))  # A3, 220 Hz
    inst.notes.append(pretty_midi.Note(velocity=100, pitch=69, start=0.5 + gap, end=1.5 + gap))  # A4, 440 Hz
    pm.instruments.append(inst)
    return pm


def test_a_voice_with_no_pitch_motion_keeps_its_pitch():
    sr = 24_000
    audio = render_procedural_fm(_two_notes(), _sine_spec(), sr, 1.6)
    assert abs(_hz(audio, sr, 0.55, 0.65) - 440.0) < 15.0


def test_a_glide_slides_from_the_note_before_and_settles():
    sr = 24_000
    glided = render_procedural_fm(_two_notes(), _sine_spec(glide_ms=400), sr, 1.6)
    assert _hz(glided, sr, 0.52, 0.6) < 380.0, "early in the glide it is still near the note before"
    assert abs(_hz(glided, sr, 1.1, 1.4) - 440.0) < 10.0, "it settles on its own note"
    apart = render_procedural_fm(_two_notes(gap=0.5), _sine_spec(glide_ms=400), sr, 2.1)
    assert abs(_hz(apart, sr, 1.02, 1.1) - 440.0) < 20.0, "a note after a rest does not glide"


def test_vibrato_wobbles_the_pitch_about_the_note():
    sr = 24_000
    pm = _one_note_pm()
    pm.instruments[0].notes[0].end = 2.0
    plain = render_procedural_fm(pm, _sine_spec(), sr, 2.1)
    wobbly = render_procedural_fm(pm, _sine_spec(vibrato={"rate_hz": 5.0, "depth_cents": 60.0, "rise_ms": 10}), sr, 2.1)
    spans = [_hz(wobbly, sr, a, a + 0.05) for a in np.arange(0.5, 1.5, 0.05)]
    # 60 cents at 440 Hz is about +-15 Hz; a 50 ms window counts in 10 Hz steps.
    assert max(spans) - min(spans) >= 15.0, spans
    assert abs(np.mean(spans) - 440.0) < 10.0
    assert abs(_hz(plain, sr, 0.5, 1.5) - 440.0) < 3.0


def test_a_voice_follows_its_pitch_bends_only_when_asked():
    sr = 24_000
    pm = _one_note_pm()
    pm.instruments[0].notes[0].end = 1.0
    # Up a whole range (12 semitones) from 0.5 s.
    pm.instruments[0].pitch_bends.append(pretty_midi.PitchBend(pitch=8191, time=0.5))
    followed = render_procedural_fm(pm, _sine_spec(follow_pitch_bend=True, pitch_bend_range_semitones=12), sr, 1.1)
    assert abs(_hz(followed, sr, 0.6, 0.9) - 880.0) < 20.0
    ignored = render_procedural_fm(pm, _sine_spec(), sr, 1.1)
    assert abs(_hz(ignored, sr, 0.6, 0.9) - 440.0) < 10.0
