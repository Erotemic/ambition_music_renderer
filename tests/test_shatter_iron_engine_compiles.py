"""Keep Shatter's new kick bus and lean metal arrangement buildable."""

from fractions import Fraction
from pathlib import Path

import yaml

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.graph import fraction_to_ticks


SCORE = Path(__file__).resolve().parents[1] / 'scores/active/shatter_the_iron_sky.music.yaml'


def _score():
    return yaml.safe_load(SCORE.read_text(encoding='utf8'))


def _part(score, instrument):
    return next(p for p in score['parts'] if p['instrument'] == instrument)


def test_shatter_iron_engine_strict_compiles():
    score = _score()
    compiled = compile_score(score, strict_schema=True)
    assert len(compiled.pm.instruments) == 12
    assert [x['id'] for x in score['playback']['sections']] == ['intro', 'combat', 'outro']
    assert score['tempo'] == 168
    assert score['timebase']['ppq'] == 960
    assert score['form'][-1]['to']['bar'] == 121
    assert all(inst.name for inst in compiled.pm.instruments)


def test_kick_is_independently_mixable_and_on_grid():
    score = _score()
    instruments = {i['name']: i for i in score['instruments']}
    assert instruments['kick_drive']['is_drum']
    assert instruments['kick_drive']['group'] == 'kick_drive'
    assert instruments['kick_drive']['instrument_backend'] == instruments['kit_core']['instrument_backend']
    assert 'kick_drive' in score['playback']['layers']['bed']
    assert 'kick_drive' in score['processing']['groups']

    kicks = [row for clip in _part(score,'kick_drive')['voices'][0]['clips']
             for row in clip['events']]
    core = [row for clip in _part(score,'kit_core')['voices'][0]['clips']
            for row in clip['events']]
    assert len(kicks) >= 800
    assert all(row[2] == 36 for row in kicks)
    assert not any(row[2] in (35,36) for row in core)
    for row in kicks:
        fraction_to_ticks(row[0],ppq=960)
        fraction_to_ticks(row[1],ppq=960)
        assert 1 <= row[3] <= 127


def test_no_inaudible_or_duplicate_stems_and_warmup_is_exact():
    score = _score()
    names = {i['name'] for i in score['instruments']}
    assert not names.intersection({'kit_ornaments','cello_pulse','cyborg_strings','solo_viola'})
    assert names == {p['instrument'] for p in score['parts']}
    groups = {inst['group'] for inst in score['instruments']}
    assert groups == set(score['processing']['groups'])
    assert set(sum(score['playback']['layers'].values(),[])) == groups
    for part in score['parts']:
        clips = part['voices'][0]['clips']
        assert len(clips) == len(score['form'])
        # Intro's final B7(b9) two-bar turnaround must exactly match the
        # combat loop's last two bars before iron_gate's E5 downbeat.
        assert [e for e in clips[0]['events'] if Fraction(str(e[0])) >= 6] == [
            e for e in clips[-2]['events'] if Fraction(str(e[0])) >= 6
        ], part['instrument']


def test_guitar_tones_preserve_dark_minor_interpretation_of_power_chords():
    score = _score()
    progression = score['harmony']['progression']
    for name in ('lead_guitar','counter_guitar'):
        clips = _part(score,name)['voices'][0]['clips']
        for section_index,clip in enumerate(clips):
            for row in clip['events']:
                t=Fraction(str(row[0]))
                chord=progression[clip['at']['bar']-1+int(t)]
                if chord == 'F5':
                    assert row[2] not in ('A4','A#4','D5','G5')
                if chord == 'Bb5':
                    assert row[2] not in ('D4','D5','G5')
                if chord == 'G5':
                    assert row[2] != 'B4'
                if chord == 'C5':
                    assert row[2] not in ('E4','E5')
