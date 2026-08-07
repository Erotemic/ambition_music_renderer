from pathlib import Path

import yaml

from ambition_music_renderer.audit import dissonance_audit, sour_note_audit
from ambition_music_renderer.render.score_layers import build_score


SCORE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scores"
    / "active"
    / "super_smash_siblings_theme.music.yaml"
)


def test_super_smash_siblings_theme_expands_as_full_sampled_orchestra():
    spec = yaml.safe_load(SCORE_PATH.read_text())

    assert spec["schema"] == "ambition.musicir.v1"
    assert spec["id"] == "super_smash_siblings_theme"
    assert spec["tempo"]["bpm"] == 152
    assert spec["sections"][0]["bars"] == 64
    assert spec["sections"][0]["loopable"] is True

    instruments = {item["name"]: item for item in spec["instruments"]}
    required = {
        "horns_sus",
        "trumpets_sus",
        "trombones_sus",
        "tuba_sus",
        "violins_i",
        "violins_ii",
        "violins_i_stacc",
        "violins_ii_stacc",
        "violas",
        "celli",
        "celli_stacc",
        "double_basses",
        "flutes",
        "oboes",
        "clarinets",
        "timpani",
        "concert_bass_drum",
        "orchestral_snare",
        "orchestral_cymbal",
    }
    assert required <= instruments.keys()
    assert all(instruments[name]["instrument_backend"]["kind"] == "sfz" for name in required)

    pm, _, _ = build_score(spec)
    rendered = {inst.name: inst for inst in pm.instruments}
    assert required <= rendered.keys()
    assert 100.0 < pm.get_end_time() < 102.0
    assert sum(len(inst.notes) for inst in pm.instruments) > 3500

    # Upper-section chord textures should not inherit inversion bass notes.
    for name in ("violins_i", "violins_ii", "violins_i_stacc", "violins_ii_stacc"):
        assert min(note.pitch for note in rendered[name].notes) >= 55
    for name in ("horns_sus", "trombones_sus"):
        assert min(note.pitch for note in rendered[name].notes) >= 40


def test_super_smash_siblings_sampled_percussion_keeps_gm_fallback_semantics():
    spec = yaml.safe_load(SCORE_PATH.read_text())
    instruments = {item["name"]: item for item in spec["instruments"]}

    expected = {
        "concert_bass_drum": {"concert_bass_drum": "C4"},
        "orchestral_snare": {"snare": "C4"},
        "orchestral_cymbal": {"crash": "C4"},
    }
    for name, remap in expected.items():
        backend = instruments[name]["instrument_backend"]
        assert backend["note_remap"] == remap
        assert backend["fallback_backend"] == "pretty-midi"


def test_super_smash_siblings_polish_pass_opens_space_and_resolves_hotspots():
    spec = yaml.safe_load(SCORE_PATH.read_text())

    assert spec["group_postprocess"]["strings"]["gain_db"] == 1.5
    assert spec["group_postprocess"]["woodwinds"]["gain_db"] == 6.2
    assert spec["group_postprocess"]["percussion"]["gain_db"] == 0.2
    assert spec["state_map"]["default"]["stems"]["woodwinds"] == 0.90

    layers = spec["layer_templates"]
    assert layers["violins_i_sweep"]["dynamics"][0]["start_bar"] == 24
    assert layers["violins_i_sweep"]["dynamics"][0]["to"] == 0.72
    assert layers["bridge_winds"]["dynamics"][0]["to"] == 1.08
    assert layers["low_answer_dm"]["motif"] == "sibling_answer"
    assert layers["low_answer_gm"]["motif"] == "sibling_answer_gm"
    assert layers["transition_brass_hits"]["voicing"] == "triad"
    assert layers["climax_rise"]["instrument_octave_offsets"]["horns_sus"] == -1

    sour = sour_note_audit.audit_spec(spec)
    dissonance = dissonance_audit.audit_spec(spec)
    assert sour["candidate_count"] == 0
    assert sour["ignored_unpitched_note_count"] > 500
    assert dissonance["ignored_unpitched_note_count"] > 500
    assert dissonance["hotspots"][0]["score"] < 2.0
