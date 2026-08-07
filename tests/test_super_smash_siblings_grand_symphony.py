from pathlib import Path

import yaml

from ambition_music_renderer.render.score_layers import build_score


SCORE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scores"
    / "active"
    / "super_smash_siblings_grand_symphony.music.yaml"
)


def _spec():
    return yaml.safe_load(SCORE_PATH.read_text())


def _motif_span(motif):
    if not motif["rhythm"]:
        return 0.0
    return sum(motif["rhythm"][:-1]) + motif["durations"][-1]


def test_grand_symphony_major_rewrite_keeps_the_sampled_orchestra_and_two_minute_form():
    spec = _spec()
    assert spec["schema"] == "ambition.musicir.v1"
    assert spec["id"] == "super_smash_siblings_grand_symphony"
    assert spec["tempo"]["bpm"] == 152
    assert spec["playback"]["loop"] is False
    assert sum(section["bars"] for section in spec["sections"]) == 76

    instruments = {item["name"]: item for item in spec["instruments"]}
    required = {
        "horns_sus", "trumpets_sus", "trombones_sus", "tuba_sus",
        "horns_stacc", "trumpets_stacc", "trombones_stacc",
        "violins_i", "violins_ii", "violins_i_stacc", "violins_ii_stacc",
        "violas", "celli", "celli_stacc", "double_basses",
        "flutes", "oboes", "clarinets", "harp", "timpani",
        "concert_bass_drum", "orchestral_snare", "orchestral_cymbal",
    }
    assert required <= instruments.keys()
    assert all(instruments[name]["instrument_backend"]["kind"] == "sfz" for name in required)

    pm, _, _ = build_score(spec)
    assert 119.0 < pm.get_end_time() < 121.0
    # The previous version exceeded 6,600 notes. The rewrite deliberately leaves
    # foreground space while remaining an active full-orchestra score.
    note_count = sum(len(inst.notes) for inst in pm.instruments)
    assert 2800 < note_count < 4000


def test_foreground_motifs_breathe_instead_of_becoming_constant_fast_flourish():
    spec = _spec()
    motifs = {motif["id"]: motif for motif in spec["motifs"]}

    assert all(min(motif["rhythm"]) >= 0.5 for motif in motifs.values())
    assert all(len(motif["intervals"]) <= 11 for motif in motifs.values())
    assert all(max(motif["durations"]) >= 1.25 for motif in motifs.values())

    # The recognizable opening has long tones and gaps, not a stream of sixteenths.
    opening = motifs["main_call"]
    assert len(opening["intervals"]) == 9
    assert max(opening["durations"]) >= 2.5
    assert sum(1 for d in opening["durations"] if d >= 1.0) >= 4

    summit = motifs["summit_line"]
    assert summit["durations"][0] >= 4.5
    assert min(summit["rhythm"]) >= 0.75

    # Fast sixteenths still exist, but only as the late accompaniment engine.
    sections = {section["id"]: section for section in spec["sections"]}
    sixteenth_users = [
        sid for sid, section in sections.items()
        if "strings_sixteenth_surge" in section["layers"]
    ]
    assert sixteenth_users == ["the_distance_starts_losing", "no_more_ceiling"]


def test_single_018_horn_blast_is_preserved_and_given_foreground_space():
    spec = _spec()
    sections = {section["id"]: section for section in spec["sections"]}
    motifs = {motif["id"]: motif for motif in spec["motifs"]}
    seconds_per_bar = 4.0 * 60.0 / spec["tempo"]["bpm"]

    correction = sections["first_correction"]
    assert abs((sections["already_moving"]["bars"] + 4) * seconds_per_bar - 18.947368) < 0.01
    assert correction["harmony"][4] == "Em9add11"

    hits = next(
        layer for layer in correction["layers"]
        if isinstance(layer, dict)
        and layer.get("kind") == "chord_hits"
        and "trombones_stacc" in layer.get("instruments", [])
    )
    assert [4, 0.0] in hits["hits"]

    # The preceding lead ends before the blast and the next foreground melody
    # waits until bar 7 of the section, so the blast is a landmark rather than
    # one event inside a perpetual run.
    assert 0.25 + _motif_span(motifs["first_push"]) < 16.0
    after = next(
        layer for layer in correction["layers"]
        if isinstance(layer, dict) and layer.get("motif") == "after_blast_line"
    )
    assert after["starts"] == [[6, 0.25]]


def test_harmony_is_tonal_by_default_with_only_two_signature_exceptions():
    spec = _spec()
    sections = {section["id"]: section for section in spec["sections"]}
    all_chords = [chord for section in spec["sections"] for chord in section["harmony"]]

    assert sections["already_moving"]["harmony"] == [
        "Dm9", "Bbmaj7/D", "Gm6/D", "A7sus4", "Dm/F", "C/E", "Gm/D", "A7"
    ]
    assert sections["first_correction"]["harmony"][4:7] == ["Em9add11", "A7/E", "Dm/F"]

    signature = [
        chord for chord in all_chords
        if chord == "Em9add11" or "#11" in chord or "add13" in chord
    ]
    assert signature == ["Em9add11", "Ebmaj9#11add13/D"]
    assert not any("Abm" in chord or "Fm9" in chord for chord in all_chords)


def test_130_ceiling_break_survives_but_the_climax_is_led_by_long_lines():
    spec = _spec()
    sections = {section["id"]: section for section in spec["sections"]}
    summit = sections["the_distance_starts_losing"]
    seconds_per_bar = 4.0 * 60.0 / spec["tempo"]["bpm"]
    bars_before = sum(
        section["bars"] for section in spec["sections"]
        if section["id"] not in {"the_distance_starts_losing", "no_more_ceiling"}
    )
    assert abs((bars_before + 1) * seconds_per_bar - 90.0) < 0.01
    assert summit["harmony"][:2] == ["Dm9", "Ebmaj9#11add13/D"]

    motif_layers = [layer for layer in summit["layers"] if isinstance(layer, dict) and layer.get("kind") == "motif"]
    assert [layer["motif"] for layer in motif_layers] == ["summit_line", "summit_answer"]
    assert "strings_sixteenth_surge" in summit["layers"]
    assert "tuba_stride" in summit["layers"]
    assert "harp_broad" in summit["layers"]
