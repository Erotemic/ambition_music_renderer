from __future__ import annotations


def _spec(*, clip_to_bar: bool) -> dict:
    return {
        "id": "arpeggio_bar_clip_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "guitar", "program": "steel_guitar", "group": "guitar"}
        ],
        "sections": [
            {
                "id": "main",
                "bars": 1,
                "harmony": ["Dadd9"],
                "layers": [
                    {
                        "kind": "arpeggio",
                        "instrument": "guitar",
                        "octave": 3,
                        "pattern": [0, 2, 1, 2],
                        "step": 0.5,
                        "duration_beats": 0.94,
                        "articulation": "tenuto",
                        "clip_to_bar": clip_to_bar,
                        "bar_end_margin_beats": 0.04,
                        "humanize_ms": 0.0,
                        "humanize_velocity_pct": 0.0,
                    }
                ],
            }
        ],
    }


def test_arpeggio_clip_to_bar_preserves_inner_sustain_but_stops_at_harmony_edge():
    from ambition_music_renderer.render.score_layers import build_score

    pm, _groups, _sections = build_score(_spec(clip_to_bar=True))
    events = list(pm._ambition_note_events)  # type: ignore[attr-defined]
    assert events
    assert max(float(event["end_beat"]) for event in events) <= 3.961
    # Early notes retain the authored long duration; only the tail is shortened.
    assert float(events[0]["nominal_duration_beats"]) == 0.94
    assert float(events[-1]["nominal_duration_beats"]) < 0.94


def test_arpeggio_without_clip_can_ring_across_bar_edge():
    from ambition_music_renderer.render.score_layers import build_score

    pm, _groups, _sections = build_score(_spec(clip_to_bar=False))
    events = list(pm._ambition_note_events)  # type: ignore[attr-defined]
    assert max(float(event["end_beat"]) for event in events) > 4.0
