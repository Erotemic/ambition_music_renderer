"""Regression checks for Shatter the Iron Sky's adaptive-song handoffs.

These checks use the native MusicIR source, not compressed audio. Gapless sample
scheduling and master headroom still require a full SFZ render on the workstation.
"""

from fractions import Fraction
from pathlib import Path

import yaml

from ambition_music_renderer.musicir.compile import compile_score


SCORE = Path(__file__).resolve().parents[1] / 'scores/active/shatter_the_iron_sky.music.yaml'


def _score():
    return yaml.safe_load(SCORE.read_text())


def _clip(part, section):
    return next(c for c in part['voices'][0]['clips'] if c['id'].endswith(section))


def _intro_bar_counts(score):
    counts = [0] * 8
    for part in score['parts']:
        for ev in part['voices'][0]['clips'][0]['events']:
            t = Fraction(ev[0])
            if 0 <= t < 8:
                counts[int(t)] += 1
    return counts


def test_intro_keeps_the_band_present_from_bar_one():
    score = _score()
    assert all(c >= 25 for c in _intro_bar_counts(score)[:4])
    parts = {p['instrument']: p for p in score['parts']}
    for name in ('rhythm_left', 'rhythm_right', 'bass', 'kick_drive', 'kit_core', 'lead_guitar'):
        assert any(Fraction(e[0]) < 1 for e in parts[name]['voices'][0]['clips'][0]['events']), name
    kit = parts['kit_core']['voices'][0]['clips'][0]['events']
    for bar in range(4):
        assert sum(int(Fraction(e[0])) == bar and e[2] == 38 for e in kit) >= 2
        assert sum(int(Fraction(e[0])) == bar and e[2] == 42 for e in kit) >= 8


def test_intro_turnaround_equals_end_of_combat_for_every_instrument():
    score = _score()
    assert score['playback']['sections'][1]['loop'] is True
    assert score['form'][13]['id'] == 'iron_sky_falls'
    for part in score['parts']:
        intro = part['voices'][0]['clips'][0]['events']
        last_combat = part['voices'][0]['clips'][13]['events']
        # Both clips are locally indexed: offsets 6..8 are the final two bars.
        a = [e for e in intro if 6 <= Fraction(e[0]) < 8]
        b = [e for e in last_combat if 6 <= Fraction(e[0]) < 8]
        assert a == b, part['instrument']


def test_shred_choir_no_longer_sustains_across_following_chords():
    score = _score()
    for part in score['parts']:
        if part['instrument'] not in ('choir_male', 'choir_female'):
            continue
        events = part['voices'][0]['clips'][9]['events']
        assert len(events) == 8
        for ev in events:
            offset = Fraction(ev[0])
            end = offset + Fraction(ev[1]['ticks'], 4 * score['timebase']['ppq'])
            assert end < int(offset) + 1, (part['instrument'], ev)


def test_native_score_compiles_without_warnings():
    score = _score()
    compiled = compile_score(score)
    compiled.assert_internal_consistency()
    assert compiled.normalization_warnings == ()
    assert len(compiled.sections) == 15
    assert len(compiled.note_events) > 8000
    assert abs(compiled.duration_seconds - 171.42857142857142) < 0.001
