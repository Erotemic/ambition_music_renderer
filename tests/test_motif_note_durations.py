from ambition_music_renderer.render.score_layers import build_score


def test_motif_durations_are_independent_from_inter_onset_rhythm():
    spec = {
        "schema": "ambition.musicir.v1",
        "id": "motif_duration_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "lead", "group": "lead", "program": "acoustic_grand_piano"},
        ],
        "motifs": [
            {
                "id": "breathing_phrase",
                "root": "C4",
                "intervals": [0, 4, 7],
                "rhythm": [1.5, 0.5, 2.0],
                "durations": [0.25, 0.4, 1.75],
                "velocities": [1.0, 1.0, 1.0],
            }
        ],
        "sections": [
            {
                "id": "phrase",
                "bars": 1,
                "harmony": ["C"],
                "layers": [
                    {
                        "kind": "motif",
                        "instrument": "lead",
                        "motif": "breathing_phrase",
                        "root": "C4",
                        "starts": [[0, 0.0]],
                        "velocity": 90,
                        "gate": 1.0,
                        "humanize_ms": 0,
                    }
                ],
            }
        ],
    }

    pm, _, _ = build_score(spec)
    events = list(pm._ambition_note_events)
    assert [round(ev["start_beat"], 3) for ev in events] == [0.0, 1.5, 2.0]
    assert [round(ev["end_beat"] - ev["start_beat"], 3) for ev in events] == [0.25, 0.4, 1.75]


def test_motif_without_durations_keeps_legacy_duration_behavior():
    spec = {
        "schema": "ambition.musicir.v1",
        "id": "motif_duration_legacy_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "lead", "group": "lead", "program": "acoustic_grand_piano"},
        ],
        "motifs": [
            {
                "id": "legacy_phrase",
                "root": "C4",
                "intervals": [0, 4],
                "rhythm": [0.75, 1.25],
                "velocities": [1.0, 1.0],
            }
        ],
        "sections": [
            {
                "id": "phrase",
                "bars": 1,
                "harmony": ["C"],
                "layers": [
                    {
                        "kind": "motif",
                        "instrument": "lead",
                        "motif": "legacy_phrase",
                        "root": "C4",
                        "starts": [[0, 0.0]],
                        "velocity": 90,
                        "gate": 1.0,
                        "humanize_ms": 0,
                    }
                ],
            }
        ],
    }

    pm, _, _ = build_score(spec)
    events = list(pm._ambition_note_events)
    assert [round(ev["start_beat"], 3) for ev in events] == [0.0, 0.75]
    assert [round(ev["end_beat"] - ev["start_beat"], 3) for ev in events] == [0.75, 1.25]
