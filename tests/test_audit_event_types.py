from ambition_music_renderer.audit._score_common import harmonic_events, musical_note_events


def test_control_events_are_not_musical_notes():
    events = [
        {"event_type": "keyswitch", "instrument": "gtr", "pitch": 33},
        {"event_type": "note", "instrument": "gtr", "pitch": 60},
        {"instrument": "legacy", "pitch": 61},
    ]
    assert [event["pitch"] for event in musical_note_events(events)] == [60, 61]


def test_harmonic_events_exclude_controls_without_counting_them_as_drums():
    spec = {"instruments": [{"name": "gtr"}, {"name": "kit", "is_drum": True}]}
    events = [
        {"event_type": "keyswitch", "instrument": "gtr", "pitch": 33},
        {"event_type": "note", "instrument": "gtr", "pitch": 60},
        {"event_type": "note", "instrument": "kit", "pitch": 38},
    ]
    kept, ignored_unpitched = harmonic_events(spec, events)
    assert [event["pitch"] for event in kept] == [60]
    assert ignored_unpitched == 1


def test_lead_collision_ignores_control_events():
    from ambition_music_renderer.audit.lead_collision import audit_events
    spec = {"id": "control_filter", "instruments": [{"name": "lead_a"}, {"name": "lead_b"}]}
    events = [
        {
            "event_type": "keyswitch", "instrument": "lead_a", "layer_kind": "notes",
            "layer": "a", "pitch": 61, "velocity": 127,
            "start_time": 0.0, "end_time": 1.0, "start_beat": 0.0, "end_beat": 2.0,
        },
        {
            "event_type": "note", "instrument": "lead_b", "layer_kind": "notes",
            "layer": "b", "pitch": 60, "note": "C4", "velocity": 100,
            "start_time": 0.0, "end_time": 1.0, "start_beat": 0.0, "end_beat": 2.0,
        },
    ]
    report = audit_events(events, spec, beats_per_bar=4)
    assert report["collision_count"] == 0
