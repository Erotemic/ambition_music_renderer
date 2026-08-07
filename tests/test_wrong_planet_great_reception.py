from pathlib import Path

import yaml

from ambition_music_renderer.audit import dissonance_audit, sour_note_audit
from ambition_music_renderer.render.score_layers import build_score


SCORE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scores"
    / "active"
    / "wrong_planet_great_reception.music.yaml"
)


def _normalized_signature(notes, start_bar):
    return [
        (
            round(float(row["bar"]) - start_bar, 3),
            round(float(row["beat"]), 3),
            row["note"],
            round(float(row["dur"]), 3),
        )
        for row in notes
        if start_bar <= float(row["bar"]) < start_bar + 4
    ]


def _normalized_full_notes(notes, start_bar):
    rows = []
    for row in notes:
        bar = float(row["bar"])
        if not (start_bar <= bar < start_bar + 4):
            continue
        clone = dict(row)
        clone["bar"] = round(bar - start_bar, 3)
        rows.append(clone)
    return rows


def test_wrong_planet_is_a_balanced_looping_synth_pop_transmission():
    spec = yaml.safe_load(SCORE_PATH.read_text())

    assert spec["schema"] == "ambition.musicir.v1"
    assert spec["id"] == "wrong_planet_great_reception"
    assert spec["title"] == "Wrong Planet, Great Reception"
    assert spec["tempo"]["bpm"] == 128
    assert [section["id"] for section in spec["sections"][:7]] == [
        "bubbles_before_language",
        "first_contact",
        "signal_lift",
        "great_reception",
        "wrong_planet_bridge",
        "great_reception_louder",
        "still_transmitting",
    ]
    assert [section["bars"] for section in spec["sections"][:7]] == [8, 8, 8, 12, 8, 12, 8]
    assert sum(section["bars"] for section in spec["sections"]) == 68
    assert spec["playback"]["loop"] is True
    assert spec["render"]["soundfont"].endswith("GeneralUser-GS.sf2")

    mix = spec["group_postprocess"]
    assert mix["lead"]["gain_db"] == -1.5
    assert mix["lead"]["compressor_ratio"] == 2.6
    assert mix["percussion"]["gain_db"] == -1.0
    assert mix["bass"]["gain_db"] == -0.1
    assert mix["whimsy"]["gain_db"] == 5.0
    assert mix["keys"]["gain_db"] == 2.4
    assert mix["pads"]["gain_db"] == 0.6

    section_gains = {section["id"]: section["mix_gain_db"] for section in spec["sections"]}
    assert section_gains == {
        "bubbles_before_language": 9.0,
        "first_contact": 1.0,
        "signal_lift": 0.0,
        "great_reception": -1.75,
        "wrong_planet_bridge": 0.75,
        "great_reception_louder": -2.0,
        "still_transmitting": -1.5,
        "loop_handoff": 8.5,
    }
    assert spec["render"]["section_mix_transition_beats"] == 2.0

    intro = spec["sections"][0]
    assert intro["intensity"] == 1.0
    intro_drums = next(
        layer for layer in intro["layers"]
        if isinstance(layer, dict) and layer.get("template") == "drums_intro"
    )
    assert intro_drums["dynamics"][0]["from"] == 0.50

    instruments = {row["name"]: row for row in spec["instruments"]}
    assert instruments["signal_lead"]["program"] == "lead_saw"
    assert instruments["signal_lead"]["modulation"] >= 10
    assert instruments["bubble_goblin"]["program"] == "fx_goblins"
    assert instruments["bubble_chiff"]["program"] == "lead_chiff"
    assert instruments["kit"]["is_drum"] is True

    pm, _, _ = build_score(spec)
    rendered = {inst.name: inst for inst in pm.instruments}
    assert 127.0 < pm.get_end_time() < 128.0
    assert sum(len(inst.notes) for inst in pm.instruments) == 4194
    assert sum(len(inst.pitch_bends) for inst in pm.instruments) == 1046
    assert len(rendered["signal_lead"].pitch_bends) > 250
    assert len(rendered["bubble_goblin"].pitch_bends) > 250


def test_loop_handoff_is_the_existing_intro_second_half_not_new_arrangement_material():
    spec = yaml.safe_load(SCORE_PATH.read_text())
    intro = spec["sections"][0]
    handoff = spec["sections"][-1]

    assert handoff["id"] == "loop_handoff"
    assert handoff["bars"] == 4
    assert handoff["harmony"] == intro["harmony"][4:8]
    assert handoff["layers"][:2] == intro["layers"][:2] == ["glow_pad", "bubble_arp"]

    for instrument in ("bubble_goblin", "crystal", "signal_lead"):
        intro_layer = next(
            layer for layer in intro["layers"]
            if isinstance(layer, dict) and layer.get("instrument") == instrument
        )
        tail_layer = next(
            layer for layer in handoff["layers"]
            if isinstance(layer, dict) and layer.get("instrument") == instrument
        )
        assert _normalized_full_notes(intro_layer["notes"], 4) == tail_layer["notes"]

    handoff_drums = next(
        layer for layer in handoff["layers"]
        if isinstance(layer, dict) and layer.get("template") == "drums_intro"
    )
    assert handoff_drums["dynamics"][0]["from"] == 0.90
    assert handoff_drums["dynamics"][0]["to"] == 0.50


def test_hook_repeats_exactly_enough_to_be_an_earworm_and_uses_high_vibrato():
    spec = yaml.safe_load(SCORE_PATH.read_text())
    chorus = next(section for section in spec["sections"] if section["id"] == "great_reception")
    lead_layer = next(
        layer for layer in chorus["layers"]
        if isinstance(layer, dict) and layer.get("instrument") == "signal_lead"
    )
    notes = lead_layer["notes"]

    first = _normalized_signature(notes, 0)
    second = _normalized_signature(notes, 4)
    third = _normalized_signature(notes, 8)
    assert first == second == third
    assert len(first) >= 24

    long_vibrato = [
        row for row in notes
        if float(row.get("dur", 0)) >= 0.65 and float(row.get("vibrato_cents", 0)) >= 30
    ]
    assert len(long_vibrato) >= 9
    assert all(float(row.get("vibrato_rate_hz", 0)) >= 7.0 for row in long_vibrato)

    intro = next(section for section in spec["sections"] if section["id"] == "bubbles_before_language")
    gurgle = next(
        layer for layer in intro["layers"]
        if isinstance(layer, dict) and layer.get("instrument") == "bubble_goblin"
    )
    assert len(gurgle["notes"]) >= 50
    assert all(row.get("bend") for row in gurgle["notes"])


def test_whimsy_stays_harmonically_controlled():
    spec = yaml.safe_load(SCORE_PATH.read_text())
    sour = sour_note_audit.audit_spec(spec)
    dissonance = dissonance_audit.audit_spec(spec)

    assert sour["candidate_count"] < 50
    assert max(row["score"] for row in sour["candidates"]) < 0.9
    assert dissonance["hotspots"][0]["score"] < 4.5
