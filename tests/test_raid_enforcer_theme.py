from pathlib import Path

import yaml

from ambition_music_renderer.cli import find_score, radio_cues


def test_raid_enforcer_theme_is_active_radio_cue():
    score_path = find_score("raid_enforcer_theme")
    assert score_path is not None
    assert score_path.name == "raid_enforcer_theme.music.yaml"
    assert "raid_enforcer_theme" in radio_cues()

    spec = yaml.safe_load(Path(score_path).read_text())
    assert spec["schema"] == "ambition.musicir.v1"
    assert spec["id"] == "raid_enforcer_theme"
    assert spec["render"]["backend"] == "fallback"
    assert spec["sections"][0]["id"] == "enforcer_loop"
    assert "hook_brass" in spec["sections"][0]["layers"]

def test_tech_bro_banger_cues_are_active_radio_cues():
    expected = {
        "pivot_protocol",
        "minimum_viable_apocalypse",
        "terms_and_conditions",
        "burn_rate_bossa",
        "shareholder_ritual",
    }
    radio = set(radio_cues())
    missing = expected - radio
    assert not missing, f"missing radio cue registrations: {sorted(missing)}"
    for cue in expected:
        score_path = find_score(cue)
        assert score_path is not None
        assert score_path.name == f"{cue}.music.yaml"
