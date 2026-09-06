from __future__ import annotations

from ambition_music_renderer.music_stem_inspector import compare_stem_timelines
from ambition_music_renderer.music_timeline import MusicTimeline, TimelineNote


def _note(*, pitch: int, instrument: str, start: float = 0.0, velocity: int = 80) -> TimelineNote:
    return TimelineNote(
        group="lead",
        instrument=instrument,
        section="verse",
        layer="melody",
        layer_kind="motif",
        pitch=pitch,
        note=str(pitch),
        velocity=velocity,
        start_seconds=start,
        end_seconds=start + 0.5,
        start_beat=start * 2,
        end_beat=start * 2 + 1,
    )


def _timeline(*notes: TimelineNote) -> MusicTimeline:
    return MusicTimeline(
        cue_id="cue",
        title="Cue",
        render_hash="hash",
        duration_seconds=2.0,
        notes=notes,
        grid=(),
        sections=(),
    )


def test_instrument_swap_does_not_make_identical_notes_look_rewritten():
    before = _timeline(_note(pitch=60, instrument="old_patch"))
    after = _timeline(_note(pitch=60, instrument="new_patch"))

    report = compare_stem_timelines(before, after, "lead")

    assert len(report.unchanged) == 1
    assert not report.changed
    assert not report.removed
    assert not report.added
    assert report.before_instruments == ("old_patch",)
    assert report.after_instruments == ("new_patch",)
    assert report.has_changes


def test_same_slot_pitch_change_is_classified_as_changed():
    before = _timeline(_note(pitch=60, instrument="lead"))
    after = _timeline(_note(pitch=62, instrument="lead"))

    report = compare_stem_timelines(before, after, "lead")

    assert len(report.changed) == 1
    assert report.changed[0].before.pitch == 60
    assert report.changed[0].after.pitch == 62
    assert not report.removed
    assert not report.added


def test_added_and_removed_slots_stay_distinct():
    before = _timeline(_note(pitch=60, instrument="lead", start=0.0))
    after = _timeline(_note(pitch=64, instrument="lead", start=1.0))

    report = compare_stem_timelines(before, after, "lead")

    assert not report.changed
    assert len(report.removed) == 1
    assert len(report.added) == 1


def test_instrument_definition_lines_reads_group_configuration(tmp_path):
    from types import SimpleNamespace

    from ambition_music_renderer.music_stem_inspector import instrument_definition_lines

    snapshot = tmp_path / "cue.source.music.yaml"
    snapshot.write_text(
        """\nid: cue\ninstruments:\n  - {name: lead_old, group: lead, program: distortion_guitar, volume: 96}\n  - {name: bass_old, group: bass, program: picked_bass}\n""".lstrip(),
        encoding="utf8",
    )
    version = SimpleNamespace(
        score_snapshot_path=snapshot,
        run_dir=tmp_path,
        label="variant",
    )

    lines = instrument_definition_lines(version, None, "lead")

    assert lines[0] == "[render snapshot]"
    assert len(lines) == 2
    assert "lead_old" in lines[1]
    assert "program=distortion_guitar" in lines[1]
    assert "volume=96" in lines[1]
    assert "bass_old" not in lines[1]
