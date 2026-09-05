from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ambition_music_renderer.music_audition import version_from_manifest
from ambition_music_renderer.music_timeline import (
    build_timeline,
    live_score_candidate,
    version_timeline_status,
    read_timeline,
    write_render_authoring_artifacts,
    write_timeline,
)


def _fake_score_events():
    return [
        {
            "event_type": "note",
            "group": "lead",
            "instrument": "lead_inst",
            "section": "verse",
            "layer": "melody",
            "layer_kind": "motif",
            "pitch": 64,
            "note": "E4",
            "velocity": 91,
            "start_time": 0.5,
            "end_time": 1.0,
            "start_beat": 1.0,
            "end_beat": 2.0,
        },
        {
            "event_type": "note",
            "group": "bass",
            "instrument": "bass_inst",
            "section": "verse",
            "layer": "pulse",
            "layer_kind": "motif",
            "pitch": 40,
            "note": "E2",
            "velocity": 80,
            "start_time": 0.0,
            "end_time": 0.5,
            "start_beat": 0.0,
            "end_beat": 1.0,
        },
        {
            "event_type": "keyswitch",
            "group": "lead",
            "instrument": "lead_inst",
            "pitch": 24,
            "note": "C1",
            "velocity": 100,
            "start_time": 0.0,
            "end_time": 0.01,
        },
    ]


def test_build_timeline_keeps_semantic_note_data_and_grid():
    spec = {
        "id": "test_cue",
        "title": "Test Cue",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
    }
    pm = SimpleNamespace(_ambition_note_events=_fake_score_events())
    sections = [
        {
            "id": "verse",
            "label": "Verse",
            "start_seconds": 0.0,
            "end_seconds": 2.0,
            "start_beat": 0.0,
            "end_beat": 4.0,
        }
    ]

    timeline = build_timeline(spec, pm, sections, render_hash="abcd")

    assert timeline.cue_id == "test_cue"
    assert timeline.render_hash == "abcd"
    assert timeline.groups == ("bass", "lead")
    assert len(timeline.notes) == 2  # keyswitches are authoring controls, not notes
    assert timeline.notes[0].section == "verse"
    assert timeline.notes[0].layer == "melody"
    assert timeline.grid[0].bar == 1
    assert timeline.grid[0].beat == 1
    assert timeline.grid[0].major is True
    assert timeline.grid[1].time_seconds == 0.5
    assert timeline.sections[0].label == "Verse"


def test_timeline_json_round_trip(tmp_path: Path):
    spec = {
        "id": "test_cue",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
    }
    pm = SimpleNamespace(_ambition_note_events=_fake_score_events())
    sections = [
        {
            "id": "verse",
            "start_seconds": 0,
            "end_seconds": 2,
            "start_beat": 0,
            "end_beat": 4,
        }
    ]
    original = build_timeline(spec, pm, sections, render_hash="abcd")
    path = write_timeline(original, tmp_path / "timeline.json")
    assert read_timeline(path) == original


def test_render_authoring_artifacts_snapshot_source_and_note_timeline(tmp_path: Path):
    score_path = tmp_path / "source.music.yaml"
    score_path.write_text("id: test_cue\ntempo: {bpm: 120}\nmeter: {beats_per_bar: 4}\n", encoding="utf8")
    spec = {
        "id": "test_cue",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
    }
    pm = SimpleNamespace(_ambition_note_events=_fake_score_events())
    sections = [
        {
            "id": "verse",
            "start_seconds": 0,
            "end_seconds": 2,
            "start_beat": 0,
            "end_beat": 4,
        }
    ]
    run_dir = tmp_path / "render"

    artifacts = write_render_authoring_artifacts(
        score_path=score_path,
        spec=spec,
        pm=pm,
        section_meta=sections,
        render_hash="abcd",
        run_dir=run_dir,
    )

    assert artifacts.score_snapshot.read_bytes() == score_path.read_bytes()
    assert read_timeline(artifacts.note_timeline).render_hash == "abcd"
    assert artifacts.manifest_files(run_dir) == {
        "score_snapshot": "authoring/test_cue_abcd.source.music.yaml",
        "note_timeline": "authoring/test_cue_abcd.note_timeline.json",
    }

    manifest = {
        "id": "test_cue",
        "title": "Test Cue",
        "hash": "abcd",
        "sample_rate": 48000,
        "files": {"authoring": artifacts.manifest_files(run_dir)},
        "stems": [],
    }
    manifest_path = run_dir / "test_cue_abcd.adaptive_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    version = version_from_manifest(manifest_path, source_kind="folder")
    assert version is not None
    assert version.timeline_path == artifacts.note_timeline.resolve()
    assert version.score_snapshot_path == artifacts.score_snapshot.resolve()


def test_legacy_scratch_render_can_find_live_score_without_claiming_exactness(tmp_path: Path):
    bank = tmp_path / "agent" / "comparison"
    run_dir = bank / "renders" / "variant_b"
    run_dir.mkdir(parents=True)
    score = bank / "scores" / "variant_b.music.yaml"
    score.parent.mkdir(parents=True)
    score.write_text("id: test_cue\n", encoding="utf8")
    assert live_score_candidate(run_dir, "variant_b") == score.resolve()



def test_version_timeline_status_live_source_signature(tmp_path: Path) -> None:
    """The GUI-facing status helper owns the (run_dir, label) fallback API."""
    run_dir = tmp_path / "agent" / "standing_on_shoulders_ab" / "renders" / "variant_b"
    run_dir.mkdir(parents=True)
    score_dir = run_dir.parent.parent / "scores"
    score_dir.mkdir(parents=True)
    score = score_dir / "variant_b.music.yaml"
    score.write_text("id: variant_b\n", encoding="utf8")

    class Version:
        timeline_path = None
        score_snapshot_path = None
        label = "variant_b"

        def __init__(self, path: Path) -> None:
            self.run_dir = path

    assert version_timeline_status(Version(run_dir)) == "live source"


def test_track_palette_is_stable_and_separates_cue_groups():
    from ambition_music_renderer.music_track_palette import group_hsl, group_palette_hsl

    assert group_hsl("bass") == group_hsl("bass")
    groups = ["bass", "brass", "drums", "giant", "giant_lead", "scholar", "strings"]
    palette = group_palette_hsl(groups)
    assert palette == group_palette_hsl(reversed(groups))
    assert set(palette) == set(groups)
    hues = sorted(color[0] for color in palette.values())
    wrapped_gaps = [
        (hues[(index + 1) % len(hues)] - hue) % 360
        for index, hue in enumerate(hues)
    ]
    assert min(wrapped_gaps) >= 50
