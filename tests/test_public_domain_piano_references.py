from __future__ import annotations

from pathlib import Path

from ambition_music_renderer.render.score_core import load_yaml
from ambition_music_renderer.render.score_layers import build_score


SCORES = {
    "reference_maple_leaf_rag.music.yaml": {
        "notes": 2568,
        "min_duration": 160.0,
        "tempo_changes": 4,
    },
    "reference_clair_de_lune.music.yaml": {
        "notes": 1608,
        "min_duration": 250.0,
        "tempo_changes": 54,
    },
    "reference_gymnopedie_no_1.music.yaml": {
        "notes": 455,
        "min_duration": 170.0,
        "tempo_changes": 3,
    },
    "reference_the_entertainer.music.yaml": {
        "notes": 1997,
        "min_duration": 240.0,
        "tempo_changes": 0,
    },
    "reference_chopin_nocturne_op9_no2.music.yaml": {
        "notes": 1246,
        "min_duration": 200.0,
        "tempo_changes": 9,
    },
}


def _score_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "scores" / "examples"


def test_public_domain_piano_references_expand_to_full_polyphonic_scores() -> None:
    for filename, expected in SCORES.items():
        spec = load_yaml(_score_dir() / filename)
        pm, _groups, sections = build_score(spec)

        notes = [note for instrument in pm.instruments for note in instrument.notes]
        assert len(notes) == expected["notes"], filename
        assert pm.get_end_time() >= expected["min_duration"], filename
        assert len((spec.get("tempo") or {}).get("map") or []) == expected["tempo_changes"]

        # These are literal-source reference performances, not reduced melody
        # sketches: the encoded score must contain real simultaneous polyphony.
        starts: dict[int, int] = {}
        for note in notes:
            key = round(note.start * 1000)
            starts[key] = starts.get(key, 0) + 1
        assert max(starts.values()) >= 4, filename

        assert len(sections) == 1
        layer = spec["sections"][0]["layers"][0]
        assert layer["kind"] == "notes"
        assert layer["gate"] == 1.0
        assert spec["meter"]["beats_per_bar"] == 1
