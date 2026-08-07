from pathlib import Path

import yaml

from ambition_music_renderer.audit import dissonance_audit, sour_note_audit
from ambition_music_renderer.render.score_layers import build_score


SCORE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scores"
    / "active"
    / "super_smash_siblings_grand_symphony.music.yaml"
)


def _spec():
    return yaml.safe_load(SCORE_PATH.read_text())


def test_grand_symphony_stays_exhilarated_for_a_two_minute_sampled_orchestra():
    spec = _spec()

    assert spec["schema"] == "ambition.musicir.v1"
    assert spec["id"] == "super_smash_siblings_grand_symphony"
    assert spec["title"] == "The Distance Starts Losing - Grand Symphony"
    assert spec["tempo"]["bpm"] == 152
    assert spec["playback"]["loop"] is False
    assert sum(section["bars"] for section in spec["sections"]) == 76
    assert min(section["intensity"] for section in spec["sections"]) >= 0.95
    assert all(section["loopable"] is False for section in spec["sections"])

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
    assert instruments["harp"]["instrument_backend"]["library_ref"] == "folk.harp"

    pm, _, _ = build_score(spec)
    rendered = {inst.name: inst for inst in pm.instruments}
    assert required <= rendered.keys()
    assert 119.0 < pm.get_end_time() < 121.0
    assert sum(len(inst.notes) for inst in pm.instruments) > 6500

    # The register-stable voice-leading work from the earlier renderer pass must
    # continue to hold under a denser, faster score.
    assert max(note.pitch for note in rendered["horns_sus"].notes) <= 84
    assert max(note.pitch for note in rendered["trumpets_sus"].notes) <= 90
    assert min(note.pitch for note in rendered["violins_i_stacc"].notes) >= 55
    assert min(note.pitch for note in rendered["harp"].notes) >= 48
    assert max(note.pitch for note in rendered["harp"].notes) <= 96


def test_grand_symphony_melody_learns_in_real_time_instead_of_repeating_square_phrases():
    spec = _spec()
    motifs = {motif["id"]: motif for motif in spec["motifs"]}

    seed = motifs["distance_seed_a"]
    assert seed["intervals"][:6] == [0, 7, 10, 14, 15, 12]
    assert max(seed["intervals"]) - min(seed["intervals"]) >= 19
    assert len(set(seed["rhythm"])) >= 8
    assert len(set(seed["durations"])) >= 10
    assert seed["durations"] != seed["rhythm"]
    assert {0.25, 0.5, 0.75, 1.25, 1.75} <= set(seed["rhythm"])

    pressure = motifs["pressure_ladder_b"]
    assert max(pressure["intervals"]) >= 19
    assert 11 in pressure["intervals"]
    assert len(set(pressure["rhythm"])) >= 7

    hands = next(section for section in spec["sections"] if section["id"] == "hands_know_first")
    compressed = [
        layer["rhythm_scale"]
        for layer in hands["layers"]
        if isinstance(layer, dict) and layer.get("kind") == "motif" and "rhythm_scale" in layer
    ]
    assert compressed == [0.84, 0.74, 0.68]

    rules = next(section for section in spec["sections"] if section["id"] == "rules_under_stress")
    assert rules["harmony"][0].startswith("Gm")
    assert rules["harmony"][4].startswith("Abm")
    assert rules["harmony"][8].startswith("Am")


def test_grand_symphony_reveals_a_larger_ceiling_without_a_quiet_preclimax_or_major_victory_flip():
    spec = _spec()
    hands = next(section for section in spec["sections"] if section["id"] == "hands_know_first")
    summit = next(section for section in spec["sections"] if section["id"] == "the_distance_starts_losing")
    coda = next(section for section in spec["sections"] if section["id"] == "no_more_ceiling")

    assert hands["intensity"] > 1.0
    assert summit["intensity"] > hands["intensity"]
    assert coda["intensity"] > summit["intensity"]

    # The penultimate passage remains fast and loud but intentionally withholds
    # low sustained brass and harp; the summit adds those colors on its first bar.
    assert "trombone_chorale" not in hands["layers"]
    assert "tuba_sync_foundation" not in hands["layers"]
    assert "harp_sparks" not in hands["layers"]
    assert "trombone_chorale" in summit["layers"]
    assert "tuba_pedal_foundation" in summit["layers"]
    assert "harp_sparks" in summit["layers"]
    assert "cymbal_every_two" in summit["layers"]

    # Power comes from mastering dangerous harmony, not the stock minor-to-major
    # heroic transformation. The final sonority keeps the Dorian/minor bite.
    assert coda["harmony"][-1] == "Dm6/9"
    assert "D" not in coda["harmony"]
    assert summit["harmony"][-1] == "Dm6/9"

    sour = sour_note_audit.audit_spec(spec)
    dissonance = dissonance_audit.audit_spec(spec)
    assert sour["candidate_count"] < 60
    assert max(row["score"] for row in sour["candidates"]) < 1.5
    assert sour["ignored_unpitched_note_count"] > 500
    assert dissonance["ignored_unpitched_note_count"] > 500
    # Deliberately altered dominants and pedal-tone seconds remain, but the
    # stacked accidental semitone mud from the exploratory draft is gone.
    assert dissonance["hotspots"][0]["score"] < 4.0


def test_grand_symphony_preserves_listener_anchors_while_tension_stays_authored():
    spec = _spec()
    sections = {section["id"]: section for section in spec["sections"]}
    motifs = {motif["id"]: motif for motif in spec["motifs"]}
    seconds_per_bar = 4.0 * 60.0 / spec["tempo"]["bpm"]

    correction = sections["first_correction"]
    # The full-brass Em hit lands at ~0:18.95. Preserve the listener-approved
    # gear shift exactly while the surrounding melody becomes more tonal.
    correction_start_bar = sections["already_moving"]["bars"]
    assert abs((correction_start_bar + 4) * seconds_per_bar - 18.947368) < 0.01
    assert correction["harmony"][4] == "Em9add11"
    correction_hits = next(
        layer for layer in correction["layers"]
        if isinstance(layer, dict)
        and layer.get("kind") == "chord_hits"
        and "trombones_stacc" in layer.get("instruments", [])
    )
    assert [4, 0] in correction_hits["hits"]

    summit = sections["the_distance_starts_losing"]
    bars_before_summit = sum(
        section["bars"] for section in spec["sections"]
        if section["id"] not in {"the_distance_starts_losing", "no_more_ceiling"}
    )
    # The second summit bar begins at exactly 1:30. Preserve the luminous
    # Eb-major/Lydian upper structure over D and the melody that made it work.
    assert abs((bars_before_summit + 1) * seconds_per_bar - 90.0) < 0.01
    assert summit["harmony"][:2] == ["Dm9add11", "Ebmaj9#11add13/D"]
    assert motifs["mastery_line_a"]["intervals"] == [
        0, 7, 10, 5, 15, 12, 19, 17, 24, 22, 17, 26, 24, 19, 14, 17, 11, 11
    ]

    # The recurring hooks now get their bite from functional leading tones,
    # suspensions, and register rather than arbitrary chromatic targets.
    assert motifs["distance_seed_a"]["intervals"] == [
        0, 7, 10, 14, 15, 12, 17, 11, 12, 19, 16, 14, 19, 17, 12
    ]
    assert motifs["distance_seed_b"]["intervals"][9:13] == [11, 14, 17, 19]
    assert motifs["distance_seed_c"]["durations"][-1] == 0.75
    assert motifs["pressure_ladder_a"]["intervals"][8:15] == [11, 14, 17, 19, 14, 11, 17]
    assert motifs["pressure_ladder_b"]["intervals"][6] == 10
    assert sections["rules_under_stress"]["harmony"][4] == "Abm7add9add11"

    dissonance = dissonance_audit.audit_spec(spec)
    # The exceptional 1:30 ceiling break is now the top of the tension hierarchy:
    # other dissonance is allowed, but no random collision should eclipse it.
    assert dissonance["hotspots"][0]["bar"] == 58
    assert 3.0 < dissonance["hotspots"][0]["score"] < 4.0
