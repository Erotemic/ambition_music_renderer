from types import SimpleNamespace


def test_minimize_motion_stays_near_the_authored_register():
    from ambition_music_renderer.render.score_events import _voice_lead_minimize

    # The old greedy mapping chose E6 for the last C-major voice and then kept
    # ratcheting upward each time the progression repeated.
    assert sorted(_voice_lead_minimize([76, 79, 83], [72, 76, 79])) == [72, 76, 79]


def test_voice_leading_state_is_scoped_to_the_active_layer():
    from ambition_music_renderer.render.score_events import _apply_voicing_constraints

    ctx = SimpleNamespace(last_voicing={}, active_layer_id="high_pad")
    first = _apply_voicing_constraints(
        ctx, "strings", [72, 76, 79], {"voice_leading": "minimize_motion"}
    )
    ctx.active_layer_id = "low_hits"
    second = _apply_voicing_constraints(
        ctx, "strings", [48, 52, 55], {"voice_leading": "minimize_motion"}
    )

    assert first == [72, 76, 79]
    assert second == [48, 52, 55]
    assert len(ctx.last_voicing) == 2
