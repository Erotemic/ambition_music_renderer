from pathlib import Path

import yaml

from ambition_music_renderer.audit import dissonance_audit, sour_note_audit
from ambition_music_renderer.render.score_layers import build_score


SCORE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scores"
    / "active"
    / "super_smash_siblings_character_select.music.yaml"
)


def test_character_select_is_a_fast_looping_sampled_orchestral_cue():
    spec = yaml.safe_load(SCORE_PATH.read_text())

    assert spec["schema"] == "ambition.musicir.v1"
    assert spec["id"] == "super_smash_siblings_character_select"
    assert spec["tempo"]["bpm"] == 174
    assert spec["sections"][0]["bars"] == 48
    assert spec["sections"][0]["loopable"] is True
    assert spec["sections"][0]["valid_exit_local_bars"] == [8, 16, 24, 32, 40, 48]

    instruments = {item["name"]: item for item in spec["instruments"]}
    required = {
        "horns_sus", "trumpets_sus", "trombones_sus", "tuba_sus",
        "horns_stacc", "trumpets_stacc", "trombones_stacc",
        "violins_i", "violins_ii", "violins_i_stacc", "violins_ii_stacc",
        "violas", "celli", "celli_stacc", "double_basses",
        "flutes", "oboes", "clarinets", "timpani",
        "concert_bass_drum", "orchestral_snare", "orchestral_cymbal",
    }
    assert required <= instruments.keys()
    assert all(instruments[name]["instrument_backend"]["kind"] == "sfz" for name in required)

    pm, _, _ = build_score(spec)
    rendered = {inst.name: inst for inst in pm.instruments}
    assert required <= rendered.keys()
    assert 65.5 < pm.get_end_time() < 67.5
    assert sum(len(inst.notes) for inst in pm.instruments) > 4200

    # The fast textures must remain within practical sampled-section registers.
    for name in ("violins_i_stacc", "violins_ii_stacc"):
        assert min(note.pitch for note in rendered[name].notes) >= 55
    assert min(note.pitch for note in rendered["horns_stacc"].notes) >= 40
    assert max(note.pitch for note in rendered["horns_stacc"].notes) <= 84


def test_character_select_preserves_sampled_percussion_and_clean_harmony_audits():
    spec = yaml.safe_load(SCORE_PATH.read_text())
    instruments = {item["name"]: item for item in spec["instruments"]}

    assert instruments["concert_bass_drum"]["instrument_backend"]["note_remap"] == {"concert_bass_drum": "C4"}
    assert instruments["orchestral_snare"]["instrument_backend"]["note_remap"] == {"snare": "C4"}
    assert instruments["orchestral_cymbal"]["instrument_backend"]["note_remap"] == {"crash": "C4"}

    sour = sour_note_audit.audit_spec(spec)
    dissonance = dissonance_audit.audit_spec(spec)
    assert sour["candidate_count"] == 0
    assert sour["ignored_unpitched_note_count"] > 300
    assert dissonance["ignored_unpitched_note_count"] > 300
    assert dissonance["hotspots"][0]["score"] < 2.5
