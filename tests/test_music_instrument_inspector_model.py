from __future__ import annotations

from pathlib import Path

import yaml

from ambition_music_renderer.music_instrument_inspector_model import (
    LibraryEntry,
    apply_library_entry,
    build_probe_request,
    default_instrument_document,
    load_score_instrument,
    parse_yaml_mapping,
    render_probe,
    write_export_document,
)


def test_library_selection_updates_only_backend_choice():
    base = default_instrument_document()
    sfz = apply_library_entry(base, LibraryEntry("sfz_alias", "guitar.emily", "guitar.emily", "guitar.emily"))
    assert sfz["instrument_backend"] == {"kind": "sfz", "library_ref": "guitar.emily"}
    gm = apply_library_entry(sfz, LibraryEntry("gm", "distortion_guitar", "Distortion guitar", "distortion_guitar"))
    assert gm["program"] == "distortion_guitar"
    assert "instrument_backend" not in gm


def test_load_score_instrument_also_loads_group_processing(tmp_path: Path):
    path = tmp_path / "cue.music.yaml"
    path.write_text(yaml.safe_dump({
        "instruments": [{"name": "lead", "group": "lead", "program": "clean_guitar", "volume": 90}],
        "group_postprocess": {"lead": {"gain_db": 3.0, "effect_chain": [{"kind": "pedalboard", "effects": [{"effect": "distortion", "drive_db": 12}]}]}},
    }), encoding="utf8")
    inst, processing = load_score_instrument(path, "lead")
    assert inst["program"] == "clean_guitar"
    assert processing["gain_db"] == 3.0
    assert processing["effect_chain"][0]["kind"] == "pedalboard"


def test_export_is_yaml_snippet_not_score_mutation(tmp_path: Path):
    out = write_export_document(
        tmp_path / "patch.yaml",
        instrument={"name": "lead", "group": "lead", "program": "clean_guitar"},
        processing={"gain_db": 2.0},
    )
    data = yaml.safe_load(out.read_text())
    assert data["instrument"]["name"] == "lead"
    assert data["group_postprocess"]["lead"]["gain_db"] == 2.0


def test_probe_request_clamps_and_parses_yaml():
    inst = parse_yaml_mapping("name: x\ngroup: x\nprogram: violin\n", label="instrument")
    req = build_probe_request(instrument=inst, processing={}, probe="C4", velocity=999, duration_seconds=0)
    assert req["velocity"] == 127
    assert req["duration_seconds"] == 0.05


def test_fallback_probe_renders_audio(tmp_path: Path):
    req = build_probe_request(
        instrument={"name": "lead", "group": "lead", "program": "violin", "volume": 100, "expression": 100},
        processing={"reverb_enabled": False, "limiter_enabled": False, "stereo_width": 0.0},
        probe="C4",
        velocity=100,
        duration_seconds=0.2,
        backend="fallback",
        sample_rate=12000,
    )
    result = render_probe(req, output_root=tmp_path)
    assert result.dry_audio.is_file()
    assert result.processed_audio.is_file()
    assert result.report["dry"]["peak"] > 0


def test_effect_template_appends_without_replacing_existing_processing():
    from ambition_music_renderer.music_instrument_inspector_model import append_effect_template
    got = append_effect_template({"gain_db": 2.0}, "Distortion")
    assert got["gain_db"] == 2.0
    assert got["effect_chain"][0]["kind"] == "pedalboard"
    assert got["effect_chain"][0]["effects"][0]["effect"] == "distortion"


def test_drum_probe_uses_renderer_crash_mapping():
    from ambition_music_renderer.music_instrument_inspector_model import _make_probe_pm
    req = build_probe_request(
        instrument={"name": "kit", "group": "drums", "is_drum": True},
        processing={},
        probe="crash",
        velocity=108,
        duration_seconds=0.4,
        backend="fallback",
    )
    pm, _groups, _group = _make_probe_pm(req)
    assert pm.instruments[0].notes[0].pitch == 49


def test_gm_library_entries_are_grouped_by_family():
    from ambition_music_renderer.music_instrument_inspector_model import gm_library_entries
    rows = {row.value: row for row in gm_library_entries()}
    assert rows["acoustic_grand_piano"].group_path == ("Piano",)
    assert rows["distortion_guitar"].group_path == ("Guitar",)
    assert rows["trumpet"].group_path == ("Brass",)


def test_alias_entries_are_grouped_by_namespace():
    from ambition_music_renderer.music_instrument_inspector_model import alias_library_entries
    rows = {row.value: row for row in alias_library_entries()}
    assert rows["guitar.emily"].group_path == ("Guitar",)
    assert rows["orchestra.horns_sustain"].group_path == ("Orchestra",)


def test_major_scale_probe_is_phrase_not_single_note():
    from ambition_music_renderer.music_instrument_inspector_model import _make_probe_pm
    req = build_probe_request(
        instrument={"name": "lead", "group": "lead", "program": "violin"},
        processing={},
        probe="C4",
        probe_template="major_scale",
        velocity=100,
        duration_seconds=0.4,
        backend="fallback",
    )
    pm, _groups, _group = _make_probe_pm(req)
    pitches = [note.pitch for note in pm.instruments[0].notes]
    assert len(pitches) > 16
    assert pitches[:8] == [60, 62, 64, 65, 67, 69, 71, 72]
    assert max(note.end for note in pm.instruments[0].notes) > 4.0


def test_drum_groove_starts_with_crash_and_contains_backbeat():
    from ambition_music_renderer.music_instrument_inspector_model import _make_probe_pm
    req = build_probe_request(
        instrument={"name": "kit", "group": "drums", "is_drum": True},
        processing={},
        probe="crash",
        probe_template="rock_groove",
        velocity=100,
        backend="fallback",
    )
    pm, _groups, _group = _make_probe_pm(req)
    notes = pm.instruments[0].notes
    assert any(note.pitch == 49 and abs(note.start - 0.2) < 1e-9 for note in notes)
    assert sum(note.pitch == 38 for note in notes) == 4
    assert sum(note.pitch == 42 for note in notes) == 16
    assert sum(note.pitch == 36 for note in notes) >= 4


def test_probe_hash_changes_with_phrase_template():
    from ambition_music_renderer.music_instrument_inspector_model import probe_request_hash
    common = dict(
        instrument={"name": "lead", "group": "lead", "program": "violin"},
        processing={},
        probe="C4",
        backend="fallback",
    )
    major = build_probe_request(**common, probe_template="major_scale")
    minor = build_probe_request(**common, probe_template="minor_scale")
    assert probe_request_hash(major) != probe_request_hash(minor)


def test_drum_alias_switches_default_document_to_drum_probe_semantics():
    inst = apply_library_entry(
        default_instrument_document(),
        LibraryEntry("sfz_alias", "drums.big_rusty", "Big Rusty", "drums.big_rusty"),
    )
    assert inst["is_drum"] is True
    melodic = apply_library_entry(inst, LibraryEntry("gm", "violin", "Violin", "violin"))
    assert "is_drum" not in melodic


def test_sfz_preflight_diagnoses_required_controller_gate(tmp_path: Path):
    from ambition_music_renderer.music_instrument_inspector_model import (
        apply_probe_control_suggestions,
        format_probe_diagnostics,
        sfz_probe_preflight,
    )

    sample = tmp_path / "electric" / "c4.wav"
    sample.parent.mkdir()
    sample.touch()
    sfz = tmp_path / "electric_four.sfz"
    sfz.write_text(
        "<group> lokey=60 hikey=72 lovel=1 hivel=127 locc107=76 hicc107=100\n"
        "<region> sample=electric/c4.wav\n",
        encoding="utf8",
    )
    inst = {
        "name": "electric_four",
        "group": "audition",
        "program": "clean_guitar",
        "instrument_backend": {"kind": "sfz", "sfz": str(sfz)},
    }
    req = build_probe_request(
        instrument=inst, processing={}, probe="C4", probe_template="major_scale", velocity=108
    )
    diag = sfz_probe_preflight(req)
    assert diag["status"] == "blocked"
    assert diag["suggested_controls"] == {"107": 88}
    assert diag["candidate_samples_found"] == 1
    assert "CC107 is 0" in format_probe_diagnostics(diag)

    fixed = apply_probe_control_suggestions(inst, diag)
    assert fixed["controls"][107] == 88
    fixed_req = build_probe_request(
        instrument=fixed, processing={}, probe="C4", probe_template="major_scale", velocity=108
    )
    fixed_diag = sfz_probe_preflight(fixed_req)
    assert fixed_diag["status"] == "ok"
    assert fixed_diag["matched_event_count"] == fixed_diag["probe_event_count"]


def test_probe_pm_emits_suggested_controller_before_notes(tmp_path: Path):
    from ambition_music_renderer.music_instrument_inspector_model import _make_probe_pm
    inst = {
        "name": "electric_four",
        "group": "audition",
        "program": "clean_guitar",
        "controls": {107: 88},
    }
    req = build_probe_request(instrument=inst, processing={}, probe="C4", probe_template="single_note")
    pm, _groups, _group = _make_probe_pm(req)
    ccs = {(cc.number, cc.value, cc.time) for cc in pm.instruments[0].control_changes}
    assert (107, 88, 0.0) in ccs
