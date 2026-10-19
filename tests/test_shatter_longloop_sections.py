"""Arrangement and runtime export contracts for Shatter's long-form level cue."""

from fractions import Fraction
from pathlib import Path

import yaml

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.render.playback_layers import playback_layer_plan

SCORE = Path(__file__).resolve().parents[1] / "scores/active/shatter_the_iron_sky.music.yaml"
BARS_PER_COMBAT_LOOP = 104
TEMPO_BPM = 168


def _score():
    return yaml.safe_load(SCORE.read_text(encoding="utf8"))


def test_shatter_form_and_runtime_loop_duration():
    score = _score()
    assert score["tempo"] == TEMPO_BPM
    assert score["end"] == {"bar": 121, "beat": 1}
    starts = [(x["from"]["bar"], x["to"]["bar"]) for x in score["form"]]
    assert starts == [(n, n + 8) for n in range(1, 121, 8)]
    playback = score["playback"]["sections"]
    assert [x["id"] for x in playback] == ["intro", "combat", "outro"]
    assert [bool(x["loop"]) for x in playback] == [False, True, False]
    assert playback[0]["form"] == ["intro"]
    assert playback[1]["form"] == [x["id"] for x in score["form"][1:-1]]
    assert playback[2]["form"] == ["outro"]
    assert 140 <= BARS_PER_COMBAT_LOOP * 4 * 60 / TEMPO_BPM <= 160
    assert len(score["harmony"]["progression"]) == 120
    assert [score["harmony"]["progression"][i] for i in (110, 111, 112)] == [
        "B7(b9)", "B7(b9)", "Em"
    ]


def test_shatter_compiles_and_playback_section_spans():
    score = _score()
    compiled = compile_score(score, strict_schema=True)
    assert len(compiled.pm.instruments) == 12
    assert len(compiled.sections) == len(score["form"]) == 15
    plan = playback_layer_plan(score, compiled.sections, [i["group"] for i in score["instruments"]])
    assert plan is not None
    sections = plan["sections"]
    assert [s["id"] for s in sections] == ["intro", "combat", "outro"]
    assert all(sections[i]["end_seconds"] == sections[i+1]["start_seconds"] for i in (0, 1))
    durations = [s["end_seconds"] - s["start_seconds"] for s in sections]
    assert abs(durations[0] - 8 * 4 * 60 / TEMPO_BPM) < 0.001
    assert abs(durations[1] - BARS_PER_COMBAT_LOOP * 4 * 60 / TEMPO_BPM) < 0.001
    assert abs(durations[2] - durations[0]) < 0.001
    assert len(compiled.note_events) > 7500
    assert not any(n["event_type"] == "pitch_bend" for n in compiled.note_events)


def test_intro_turnaround_matches_combat_loop_for_every_instrument():
    score = _score()
    for part in score["parts"]:
        clips = part["voices"][0]["clips"]
        assert len(clips) == len(score["form"])
        assert clips[0]["id"].endswith("_intro")
        assert clips[-2]["id"].endswith("_iron_sky_falls")
        tail = lambda clip: [row for row in clip["events"] if Fraction(str(row[0])) >= 6]
        assert tail(clips[0]) == tail(clips[-2]), part["instrument"]


def test_no_clip_note_extends_past_its_8_bar_section():
    score = _score()
    ppq = score["timebase"]["ppq"]
    for part in score["parts"]:
        for clip in part["voices"][0]["clips"]:
            for at, duration, note, velocity in clip["events"]:
                tick = Fraction(str(at)) * (4 * ppq)
                assert tick.denominator == 1, (clip["id"], at)
                dt = int(duration["ticks"])
                assert 0 < dt and tick + dt <= 8 * 4 * ppq, (clip["id"], at, dt)
                assert 1 <= int(velocity) <= 127


def test_shred_remains_high_and_all_new_melodies_remain_low():
    from pretty_midi import note_name_to_number

    score = _score()
    part = next(p for p in score["parts"] if p["instrument"] == "lead_guitar")
    for clip in part["voices"][0]["clips"]:
        pitches = [note_name_to_number(x[2]) for x in clip["events"]]
        assert pitches
        assert min(pitches) >= 35 and max(pitches) <= 86
        if clip["id"].endswith("breaking_the_columns"):
            assert min(pitches) >= 64 and max(pitches) >= 79
        else:
            assert max(pitches) <= 63


def test_every_pitched_note_stays_inside_resolved_sample_ranges():
    """Ranges measured from the source 3133eece render's resolution report."""
    from pretty_midi import note_name_to_number

    ranges = {
        "rhythm_left": (33, 91), "rhythm_right": (33, 91),
        "bass": (28, 75), "kick_drive": (24, 96),
        "kit_core": (24, 96), "lead_guitar": (35, 86),
        "brass_charges": (40, 77), "choir_male": (43, 66),
        "choir_female": (67, 84), "counter_guitar": (40, 86),
        "growly_counterbass": (33, 84), "timpani": (36, 96),
    }
    for part in _score()["parts"]:
        lo, hi = ranges[part["instrument"]]
        for clip in part["voices"][0]["clips"]:
            for row in clip["events"]:
                notes = row[2] if isinstance(row[2], list) else [row[2]]
                for note in notes:
                    pitch = note if isinstance(note, int) else note_name_to_number(note)
                    assert lo <= pitch <= hi, (part["instrument"], clip["id"], note)
