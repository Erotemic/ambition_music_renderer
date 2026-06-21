from ambition_music_renderer import guitar_performance as gp


def test_allocate_chord_uses_unique_strings():
    assignment = gp.allocate_chord([52, 55, 59, 64], max_span=5)
    strings = [item.string_index for item in assignment]
    assert len(strings) == len(set(strings))
    assert all(0 <= item.fret <= 17 for item in assignment)


def test_down_and_up_strums_reverse_order():
    pitches = [52, 55, 59, 64]
    down, _ = gp.strum_plan(pitches, bpm=120, direction="down", spread_ms=40)
    up, _ = gp.strum_plan(pitches, bpm=120, direction="up", spread_ms=40)
    assert [ev["pitch"] for ev in down] == list(reversed([ev["pitch"] for ev in up]))
    assert down[0]["beat_offset"] == 0.0
    assert up[0]["beat_offset"] == 0.0
    assert down[-1]["beat_offset"] > down[0]["beat_offset"]


def test_take_specs_default_to_instruments():
    takes = gp.take_specs({}, ["left", "right"])
    assert [t["instrument"] for t in takes] == ["left", "right"]
