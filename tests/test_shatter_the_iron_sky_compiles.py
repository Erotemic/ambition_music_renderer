"""Prevent non-tick-exact timing in the actively authored Shatter score."""

from pathlib import Path

import yaml

from ambition_music_renderer.musicir.compile import compile_score


def test_active_shatter_score_compiles_with_exact_timing():
    score_path = (
        Path(__file__).resolve().parents[1]
        / "scores"
        / "active"
        / "shatter_the_iron_sky.music.yaml"
    )
    spec = yaml.safe_load(score_path.read_text(encoding="utf8"))
    compiled = compile_score(spec, strict_schema=True)
    assert compiled.note_events
    assert compiled.canonical_schema == "ambition.musicir.v3"
