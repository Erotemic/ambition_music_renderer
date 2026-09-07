"""Generic score/audio boundary diagnostics; no named-song snapshots."""
import numpy as np
import pytest

from ambition_music_renderer.audit.loop_review import audio_loop_report, score_loop_report
from ambition_music_renderer.musicir.compile import compile_score


def score():
    return {
        "schema": "ambition.musicir.v3", "id": "boundary_fixture", "tempo": 120,
        "meter": "4/4", "timebase": {"ppq": 960}, "end": {"bar": 4, "beat": 1},
        "form": [
            {"id": "pre", "from": {"bar": 1}, "to": {"bar": 2}},
            {"id": "loop", "from": {"bar": 2}, "to": {"bar": 4}, "loopable": True},
        ],
        "instruments": [{"name": "piano", "program": "acoustic_grand_piano"}],
        "materials": {"cell": {"events": [[0, "1/4", "C4", 84]]}},
        "parts": [{"id": "p", "instrument": "piano", "voices": [{"id": "v", "clips": [
            {"id": "pre", "at": {"bar": 1}, "use": "cell"},
            {"id": "body", "at": {"bar": 2}, "events": [[0, "1/4", "G4", 88]]},
            {"id": "tail", "at": {"bar": 3}, "use": "cell"},
        ]}]}],
    }


def test_matching_preroll_is_compared_by_music_not_source_ids():
    result = score_loop_report(compile_score(score()))
    assert result["loops"][0]["pre_roll_matches_ending"]
    assert result["loops"][0]["pre_roll_seconds"] == 2
    assert result["loops"][0]["period_seconds"] == 4
    assert result["same_pitch_overlaps"] == 0


def test_different_velocity_invalidates_reference():
    spec = score()
    spec["parts"][0]["voices"][0]["clips"][-1]["velocity_scale"] = .7
    assert not score_loop_report(compile_score(spec))["loops"][0]["pre_roll_matches_ending"]


def test_controller_state_and_overlapping_notes_are_observed():
    import pretty_midi
    compiled = compile_score(score())
    inst = compiled.pm.instruments[0]
    inst.control_changes.append(pretty_midi.ControlChange(64, 127, 5))
    inst.notes.append(pretty_midi.Note(80, 60, .25, 1))
    result = score_loop_report(compiled)
    assert result["same_pitch_overlaps"] == 1
    assert not result["loops"][0]["boundary_controller_state_equal"]
    assert not result["loops"][0]["pre_roll_matches_ending"]


def test_no_preroll_does_not_claim_a_match():
    spec = score()
    spec["form"] = [{"id": "loop", "from": {"bar": 1}, "to": {"bar": 4}, "loopable": True}]
    assert score_loop_report(compile_score(spec))["loops"][0]["pre_roll_matches_ending"] is None


def test_audio_audition_is_exact_tail_plus_head_and_measures_period():
    x = np.linspace(-.2, .3, 400, dtype=np.float32)[:, None]
    result, audition = audio_loop_report(x, 100, period_seconds=4, context_seconds=1)
    np.testing.assert_array_equal(audition, np.concatenate([x[-100:], x[:100]]))
    assert result["duration_matches_score"]
    assert result["audition_join_seconds"] == 1
    assert result["hard_join_step_dbfs"] == pytest.approx(20 * np.log10(.5))
    wrong, _ = audio_loop_report(x, 100, period_seconds=5)
    assert not wrong["duration_matches_score"]


@pytest.mark.parametrize("value", [np.array([]), np.array([0.]), np.array([0., np.nan]), np.zeros((3, 3))])
def test_audio_rejects_invalid_data(value):
    with pytest.raises(ValueError):
        audio_loop_report(value, 48000, period_seconds=1)


def test_zero_context_is_rejected_and_silence_is_finite():
    with pytest.raises(ValueError):
        audio_loop_report(np.zeros(10), 10, period_seconds=1, context_seconds=0)
    report, _ = audio_loop_report(np.zeros(10), 10, period_seconds=1)
    assert np.isfinite(report["hard_join_step_dbfs"])
    assert report["sample_peak_dbfs"] == -240
