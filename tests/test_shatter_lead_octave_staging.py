"""The lead hook sits low, while the eight-bar shred solo returns to high register."""

from pathlib import Path

import pretty_midi
import yaml

from ambition_music_renderer.musicir.compile import compile_score


SCORE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scores"
    / "active"
    / "shatter_the_iron_sky.music.yaml"
)
SOLO_CLIP = "lead_guitar_breaking_the_columns"


def load_score():
    return yaml.safe_load(SCORE_PATH.read_text(encoding="utf-8"))


def test_shatter_lead_registers_are_intentionally_staged():
    score = load_score()
    part = next(p for p in score["parts"] if p["instrument"] == "lead_guitar")
    clips = part["voices"][0]["clips"]
    assert len(clips) == len(score["form"])
    assert clips[0]["id"] == "lead_guitar_intro"
    assert clips[-1]["id"] == "lead_guitar_outro"
    assert len(clips) == 15
    assert any(c["id"] == SOLO_CLIP for c in clips)

    for clip in clips:
        pitches = [pretty_midi.note_name_to_number(row[2]) for row in clip["events"]]
        assert pitches, clip["id"]
        # FreePats FSBS Distorted #1 covers MIDI pitches 35 through 86.
        assert all(35 <= pitch <= 86 for pitch in pitches), clip["id"]
        if clip["id"] == SOLO_CLIP:
            assert min(pitches) >= 64, "shred solo must retain its original octave"
            assert max(pitches) >= 79, "shred solo must reach its high register"
        else:
            assert max(pitches) <= 63, f"normal melody should stay below E4: {clip['id']}"

    # Check the actual low -> high -> low sequence, not only the individual ranges.
    names = [c["id"] for c in clips]
    i = names.index(SOLO_CLIP)
    assert names[i - 1] == "lead_guitar_cathedral_of_ash"
    assert names[i + 1] == "lead_guitar_iron_crown_ascent"


def test_shatter_octave_staging_compiles_on_exact_musicir_grid():
    score = load_score()
    compiled = compile_score(score, strict_schema=True)
    assert len(compiled.instrument_specs) == len(score["instruments"]) == 12
    assert len(compiled.note_events) > 5000
    assert len(compiled.sections) == len(score["form"])
