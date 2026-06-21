from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from ambition_music_renderer.cli import build_parser
from ambition_music_renderer.cue_bundle import (
    copy_manifest_referenced_files,
    make_zip,
    manifest_audio_entries,
    should_include_in_report_zip,
    summarize_mix_diagnostics,
    prepare_manifest_analysis_root,
    write_manifest_audio_level_report,
    write_spectral_fingerprint,
    write_stem_amplitude_report,
    write_adaptive_section_report,
    write_adaptive_composition_mastering_report,
    write_state_mix_report,
    write_stem_export_report,
)
from ambition_music_renderer.arrangement_audit import audit_spec as audit_arrangement_spec
from ambition_music_renderer.arrangement_audit import write_reports as write_arrangement_reports
from ambition_music_renderer.dissonance_audit import audit_spec, write_reports as write_dissonance_reports
from ambition_music_renderer.render_group_worker import build_parser as build_worker_parser
from ambition_music_renderer.render_isolated import build_parser as build_isolated_parser
from ambition_music_renderer.reference_audio_audit import analyze_audio as analyze_reference_audio, write_reports as write_reference_audio_reports
from ambition_music_renderer.sour_note_audit import audit_spec as audit_sour_note_spec
from ambition_music_renderer.sour_note_audit import write_reports as write_sour_note_reports
from ambition_music_renderer.shrill_note_audit import audit_spec as audit_shrill_note_spec
from ambition_music_renderer.shrill_note_audit import write_reports as write_shrill_note_reports
from ambition_music_renderer.musicir_renderer import chord_intervals, timeline_markers_from_spec


def test_backend_defaults_prefer_pretty_midi():
    assert build_isolated_parser().parse_args(["cue.music.yaml"]).backend == "pretty-midi"
    assert build_worker_parser().parse_args(
        ["cue.music.yaml", "--outdir", "out", "--group", "keys"]
    ).backend == "pretty-midi"
    assert build_parser().parse_args(["render", "lofi_study_loop"]).backend == "pretty-midi"
    assert build_parser().parse_args(["cue", "bundle", "lofi_study_loop"]).backend == "pretty-midi"
    adaptive_args = build_parser().parse_args(["render-publish", "first_goblin_tune_v2", "--full-mix-only"])
    assert adaptive_args.full_mix_only is True
    shared_args = build_isolated_parser().parse_args([
        "cue.music.yaml",
        "--runtime-stem-gain-mode",
        "shared",
        "--runtime-stem-max-gain-db",
        "18",
    ])
    assert shared_args.runtime_stem_gain_mode == "shared"
    assert shared_args.runtime_stem_max_gain_db == 18.0


def test_bundle_parser_exposes_publish_and_zip_flags():
    args = build_parser().parse_args(
        [
            "cue",
            "bundle",
            "for_emmy_forever_ago",
            "--publish",
            "--zip",
            "--jobs",
            "2",
            "--runtime-stem-gain-mode",
            "shared",
            "--runtime-stem-max-gain-db",
            "18",
            "--zip-report",
            "--plot-format",
            "jpg",
        ]
    )
    assert args.command == "cue"
    assert args.cue_action == "bundle"
    assert args.cue == "for_emmy_forever_ago"
    assert args.publish is True
    assert args.zip_bundle is True
    assert args.jobs == 2
    assert args.runtime_stem_gain_mode == "shared"
    assert args.runtime_stem_max_gain_db == 18.0
    assert args.zip_report_bundle is True
    assert args.plot_format == "jpg"


def test_stem_export_report_compares_scratch_adaptive_and_preview_audio():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = 48_000
        t = np.arange(sr // 10, dtype="float32") / sr
        tone = 0.1 * np.sin(2 * np.pi * 440.0 * t)
        stereo = np.stack([tone, tone], axis=1).astype("float32")

        scratch = root / "scratch_stems"
        scratch.mkdir()
        np.save(scratch / "testcue_deadbeef.keys.npy", stereo)

        adaptive = root / "adaptive" / "loop"
        adaptive.mkdir(parents=True)
        sf.write(adaptive / "testcue_deadbeef.loop.keys.wav", stereo, sr)
        sf.write(adaptive / "testcue_deadbeef.loop.full.wav", stereo, sr)

        preview = root / "preview"
        preview.mkdir()
        sf.write(preview / "testcue_deadbeef.full_soundtrack_preview.wav", stereo, sr)

        manifest = {
            "id": "testcue",
            "sample_rate": sr,
            "files": {
                "adaptive": {
                    "loop": {
                        "keys": "adaptive/loop/testcue_deadbeef.loop.keys.wav",
                        "full": "adaptive/loop/testcue_deadbeef.loop.full.wav",
                    }
                },
                "preview": {
                    "full_soundtrack": "preview/testcue_deadbeef.full_soundtrack_preview.wav"
                },
            },
        }

        report_path = write_stem_export_report(root, manifest, root / "reports")
        text = report_path.read_text()
        assert "scratch_npy" in text
        assert "adaptive_audio" in text
        assert "preview_audio" in text
        assert "keys" in text
        data = json.loads((root / "reports" / "stem_export_report.json").read_text())
        assert data["cue_id"] == "testcue"
        assert len(data["rows"]) == 4


def test_make_zip_contains_bundle_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundle = root / "mycue_hash_bundle"
        (bundle / "reports").mkdir(parents=True)
        (bundle / "reports" / "report.txt").write_text("ok", encoding="utf8")
        zip_path = make_zip(bundle, root / "mycue_hash_bundle.zip")
        assert zip_path.exists()
        import zipfile

        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        assert "mycue_hash_bundle/reports/report.txt" in names


def test_report_zip_excludes_large_binary_artifacts():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundle = root / "mycue_hash_bundle"
        (bundle / "reports").mkdir(parents=True)
        (bundle / "adaptive" / "loop").mkdir(parents=True)
        (bundle / "plots").mkdir(parents=True)
        (bundle / "reports" / "report.txt").write_text("ok", encoding="utf8")
        (bundle / "source.music.yaml").write_text("id: mycue", encoding="utf8")
        (bundle / "plots" / "stem.spectrogram.jpg").write_bytes(b"jpeg")
        (bundle / "adaptive" / "loop" / "mycue.loop.full.ogg").write_bytes(b"ogg")
        (bundle / "scratch_stems").mkdir()
        (bundle / "scratch_stems" / "mycue.keys.npy").write_bytes(b"npy")

        assert should_include_in_report_zip(bundle / "reports" / "report.txt")
        assert should_include_in_report_zip(bundle / "plots" / "stem.spectrogram.jpg")
        assert not should_include_in_report_zip(bundle / "adaptive" / "loop" / "mycue.loop.full.ogg")
        assert not should_include_in_report_zip(bundle / "scratch_stems" / "mycue.keys.npy")

        zip_path = make_zip(bundle, root / "mycue_hash_bundle_report.zip", report_only=True)
        import zipfile

        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        assert "mycue_hash_bundle/reports/report.txt" in names
        assert "mycue_hash_bundle/plots/stem.spectrogram.jpg" in names
        assert "mycue_hash_bundle/adaptive/loop/mycue.loop.full.ogg" not in names
        assert "mycue_hash_bundle/scratch_stems/mycue.keys.npy" not in names


def test_manifest_audio_entries_and_bundle_copy_are_manifest_scoped():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        current = root / "preview" / "cue_hash.full_soundtrack_preview.ogg"
        stale = root / "preview" / "cue_old.full_soundtrack_preview.ogg"
        adaptive = root / "adaptive" / "loop" / "cue_hash.loop.full.ogg"
        current.parent.mkdir(parents=True)
        adaptive.parent.mkdir(parents=True)
        current.write_bytes(b"current")
        stale.write_bytes(b"stale")
        adaptive.write_bytes(b"adaptive")
        (current.with_name(current.name + ".metadata.json")).write_text("{}", encoding="utf8")
        manifest = {
            "files": {
                "preview": {"full_soundtrack": "preview/cue_hash.full_soundtrack_preview.ogg"},
                "adaptive": {"loop": {"full": "adaptive/loop/cue_hash.loop.full.ogg"}},
            }
        }
        entries = manifest_audio_entries(manifest)
        assert {e["path"] for e in entries} == {
            "preview/cue_hash.full_soundtrack_preview.ogg",
            "adaptive/loop/cue_hash.loop.full.ogg",
        }
        bundle = root / "bundle"
        copied = copy_manifest_referenced_files(root, manifest, bundle)
        assert sorted(copied) == [
            "adaptive/loop/cue_hash.loop.full.ogg",
            "preview/cue_hash.full_soundtrack_preview.ogg",
            "preview/cue_hash.full_soundtrack_preview.ogg.metadata.json",
        ]
        assert (bundle / "preview" / current.name).exists()
        assert (bundle / "preview" / (current.name + ".metadata.json")).exists()
        assert not (bundle / "preview" / stale.name).exists()


def test_manifest_audio_level_report_ignores_stale_audio():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = 48_000
        t = np.arange(sr // 20, dtype="float32") / sr
        tone = 0.05 * np.sin(2 * np.pi * 220.0 * t)
        stereo = np.stack([tone, tone], axis=1).astype("float32")
        preview = root / "preview"
        preview.mkdir()
        sf.write(preview / "cue_hash.full_soundtrack_preview.wav", stereo, sr)
        sf.write(preview / "cue_old.full_soundtrack_preview.wav", stereo, sr)
        manifest = {
            "files": {
                "preview": {"full_soundtrack": "preview/cue_hash.full_soundtrack_preview.wav"},
                "adaptive": {},
            }
        }
        report = write_manifest_audio_level_report(root, manifest, root / "reports")
        text = report.read_text()
        assert "cue_hash.full_soundtrack_preview.wav" in text
        assert "cue_old.full_soundtrack_preview.wav" not in text


def test_mix_diagnostics_surfaces_renderer_warnings():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        manifest = {
            "id": "cue",
            "hash": "abc123",
            "runtime_stem_gain_mode": "native",
            "diagnostics": {
                "raw_full": {"rms_dbfs": -75.0, "peak_dbfs": -55.0},
                "mastered_full": {"rms_dbfs": -24.0, "peak_dbfs": -8.0},
                "master_rms_lift_db": 51.0,
                "runtime_gain_db": 0.0,
                "runtime_gain_reason": "native",
                "native_stems": {"keys": {"rms_dbfs": -75.0, "peak_dbfs": -55.0}},
                "runtime_stems": {"keys": {"rms_dbfs": -75.0, "peak_dbfs": -55.0}},
                "warnings": ["native runtime stems are very quiet"],
            },
        }
        report, warnings = summarize_mix_diagnostics(manifest, root / "reports")
        text = report.read_text()
        assert "master_rms_lift_db" in text
        assert "native runtime stems are very quiet" in text
        assert warnings == ["native runtime stems are very quiet"]



def test_analysis_root_copies_only_current_hash_scratch_stems():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = 48_000
        audio = np.zeros((128, 2), dtype="float32")
        scratch = root / "scratch_stems"
        scratch.mkdir()
        np.save(scratch / "cue_current.keys.npy", audio)
        np.save(scratch / "cue_old.keys.npy", audio)
        preview = root / "preview"
        preview.mkdir()
        sf.write(preview / "cue_current.full_soundtrack_preview.wav", audio, sr)
        sf.write(preview / "cue_old.full_soundtrack_preview.wav", audio, sr)
        manifest = {
            "id": "cue",
            "hash": "current",
            "files": {
                "preview": {"full_soundtrack": "preview/cue_current.full_soundtrack_preview.wav"},
                "adaptive": {},
            },
        }
        analysis = prepare_manifest_analysis_root(root, manifest, root / "analysis")
        assert (analysis / "scratch_stems" / "cue_current.keys.npy").exists()
        assert not (analysis / "scratch_stems" / "cue_old.keys.npy").exists()
        assert (analysis / "preview" / "cue_current.full_soundtrack_preview.wav").exists()
        assert not (analysis / "preview" / "cue_old.full_soundtrack_preview.wav").exists()



def test_spectral_fingerprint_is_llm_friendly_json_and_tsv():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = 48_000
        duration = 0.25
        t = np.arange(int(sr * duration), dtype="float32") / sr
        low = 0.1 * np.sin(2 * np.pi * 120.0 * t)
        high = 0.1 * np.sin(2 * np.pi * 4200.0 * t)
        scratch = root / "scratch_stems"
        scratch.mkdir()
        np.save(scratch / "cue_hash.low_keys.npy", np.stack([low, low], axis=1).astype("float32"))
        np.save(scratch / "cue_hash.pluck.npy", np.stack([high, high], axis=1).astype("float32"))
        manifest = {
            "id": "cue",
            "hash": "hash",
            "sample_rate": sr,
            "sections": [{"end_seconds": duration}],
        }
        report = write_spectral_fingerprint(root, manifest, root / "reports", bucket_seconds=0.25)
        payload = json.loads(report.read_text())
        assert payload["schema"] == "ambition.music_spectral_fingerprint.v1"
        assert payload["mean_band_fraction_by_group"]["low"]["low_keys"] > 0.9
        assert payload["mean_band_fraction_by_group"]["vhigh"]["pluck"] > 0.9
        assert (root / "reports" / "spectral_fingerprint.tsv").exists()
        assert (root / "reports" / "spectral_fingerprint_summary.txt").exists()


def test_state_mix_report_flags_similar_states():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        spec = {
            "id": "cue",
            "instruments": [
                {"name": "piano", "group": "keys"},
                {"name": "bass", "group": "bass"},
            ],
            "state_map": {
                "default": {"section": "loop", "stems": {"keys": 0.8, "bass": 0.6}},
                "quiet": {"section": "loop", "stems": {"keys": 0.7, "bass": 0.5}},
            },
        }
        manifest = {"diagnostics": {"runtime_previews": {}}}
        report = write_state_mix_report(spec, manifest, root / "reports")
        payload = json.loads(report.read_text())
        assert payload["schema"] == "ambition.music_state_mix_report.v1"
        text = (root / "reports" / "state_mix_report_summary.txt").read_text()
        assert "state distances from default" in text
        assert "warning: state maps are close together" in text


def test_dissonance_audit_identifies_close_layer_clash():
    spec = {
        "schema": "ambition.musicir.v1",
        "id": "clash_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "a", "group": "keys", "program": "acoustic_grand_piano"},
            {"name": "b", "group": "lead", "program": "acoustic_grand_piano"},
        ],
        "layer_templates": {
            "a_note": {
                "kind": "motif",
                "instrument": "a",
                "motif": "a_motif",
                "root": "C4",
                "starts": [[0, 0.0]],
                "repeats": 1,
                "velocity": 90,
            },
            "b_note": {
                "kind": "motif",
                "instrument": "b",
                "motif": "b_motif",
                "root": "C#4",
                "starts": [[0, 0.0]],
                "repeats": 1,
                "velocity": 90,
            },
        },
        "motifs": [
            {"id": "a_motif", "root": "C4", "intervals": [0], "rhythm": [1.0], "velocities": [1.0]},
            {"id": "b_motif", "root": "C#4", "intervals": [0], "rhythm": [1.0], "velocities": [1.0]},
        ],
        "sections": [
            {"id": "loop", "bars": 1, "harmony": ["C"], "layers": ["a_note", "b_note"]}
        ],
    }
    payload = audit_spec(spec)
    assert payload["hotspots"]
    top = payload["hotspots"][0]
    assert top["worst_pairs"][0]["interval_class"] == 1
    assert top["worst_pairs"][0]["layers"] == ["a_note", "b_note"]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        paths = write_dissonance_reports(payload, root / "reports", plots_dir=root / "plots", plot_format="jpg")
        assert Path(paths["summary"]).exists()
        assert Path(paths["markdown"]).exists()
        assert "minor second" in Path(paths["summary"]).read_text()
        assert "Top Hotspots" in Path(paths["markdown"]).read_text()
        if "timeline_plot" in paths:
            assert Path(paths["timeline_plot"]).exists()
        if "layer_pair_plot" in paths:
            assert Path(paths["layer_pair_plot"]).exists()


def test_arrangement_audit_reports_group_prominence_and_bass_collisions():
    spec = {
        "schema": "ambition.musicir.v1",
        "id": "arrangement_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "bass", "group": "low_keys", "program": "acoustic_grand_piano"},
            {"name": "horn", "group": "horns", "program": "french_horn"},
            {"name": "lead", "group": "keys", "program": "acoustic_grand_piano"},
        ],
        "state_map": {
            "default": {"section": "loop", "stems": {"low_keys": 0.4, "horns": 0.7, "keys": 0.7}}
        },
        "layer_templates": {
            "bass_note": {
                "kind": "motif",
                "instrument": "bass",
                "motif": "bass_motif",
                "root": "C2",
                "starts": [[0, 0.0]],
                "velocity": 80,
            },
            "horn_note": {
                "kind": "motif",
                "instrument": "horn",
                "motif": "horn_motif",
                "root": "G3",
                "starts": [[0, 0.0]],
                "velocity": 80,
            },
            "lead_note": {
                "kind": "motif",
                "instrument": "lead",
                "motif": "lead_motif",
                "root": "C5",
                "starts": [[0, 0.0]],
                "velocity": 80,
            },
        },
        "motifs": [
            {"id": "bass_motif", "root": "C2", "intervals": [0], "rhythm": [2.0], "velocities": [1.0]},
            {"id": "horn_motif", "root": "G3", "intervals": [0], "rhythm": [2.0], "velocities": [1.0]},
            {"id": "lead_motif", "root": "C5", "intervals": [1], "rhythm": [2.0], "velocities": [1.0]},
        ],
        "sections": [{"id": "loop", "bars": 1, "harmony": ["C"], "layers": ["bass_note", "horn_note", "lead_note"]}],
    }
    payload = audit_arrangement_spec(spec)
    assert payload["schema"] == "ambition.music_arrangement_audit.v1"
    assert any(row["group"] == "horns" for row in payload["groups"])
    assert payload["bass_collision_candidates"]
    with tempfile.TemporaryDirectory() as td:
        paths = write_arrangement_reports(payload, Path(td))
        assert Path(paths["summary"]).exists()
        assert Path(paths["markdown"]).exists()
        assert "Default-state group presence" in Path(paths["markdown"]).read_text()



def test_sour_note_audit_points_to_motif_root_sources():
    spec = {
        "schema": "ambition.musicir.v1",
        "id": "sour_note_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "piano", "group": "keys", "program": "acoustic_grand_piano"},
        ],
        "state_map": {"default": {"section": "loop", "stems": {"keys": 1.0}}},
        "motifs": [
            {"id": "bad_turn", "root": "C4", "intervals": [0], "rhythm": [1.5], "velocities": [1.0]},
        ],
        "layer_templates": {
            "bad_motif": {
                "kind": "motif",
                "instrument": "piano",
                "motif": "bad_turn",
                "roots": ["F#4"],
                "starts": [[0, 0.0]],
                "repeats": 1,
                "velocity": 90,
            },
        },
        "sections": [{"id": "loop", "bars": 1, "harmony": ["C"], "layers": ["bad_motif"]}],
    }
    payload = audit_sour_note_spec(spec, min_score=0.1)
    assert payload["schema"] == "ambition.music_sour_note_audit.v1"
    assert payload["candidates"]
    top = payload["candidates"][0]
    assert top["note"] == "F#4"
    assert "layer_templates.bad_motif.roots[0]" in top["source_hint"]
    assert "motifs.bad_turn.intervals[0]" in top["source_hint"]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        paths = write_sour_note_reports(payload, root / "reports", plots_dir=root / "plots", plot_format="jpg")
        assert Path(paths["summary"]).exists()
        assert Path(paths["markdown"]).exists()
        assert "Top Candidates" in Path(paths["markdown"]).read_text()



def test_stem_amplitude_report_shows_default_weighted_balance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = 48_000
        t = np.arange(sr // 4, dtype="float32") / sr
        loud = 0.10 * np.sin(2 * np.pi * 220.0 * t)
        soft = 0.025 * np.sin(2 * np.pi * 440.0 * t)
        adaptive = root / "adaptive" / "loop"
        adaptive.mkdir(parents=True)
        sf.write(adaptive / "cue_hash.loop.keys.wav", np.stack([loud, loud], axis=1), sr)
        sf.write(adaptive / "cue_hash.loop.horns.wav", np.stack([soft, soft], axis=1), sr)
        manifest = {
            "id": "cue",
            "hash": "hash",
            "sample_rate": sr,
            "files": {
                "adaptive": {
                    "loop": {
                        "keys": "adaptive/loop/cue_hash.loop.keys.wav",
                        "horns": "adaptive/loop/cue_hash.loop.horns.wav",
                    }
                },
                "preview": {},
            },
        }
        spec = {
            "id": "cue",
            "state_map": {"default": {"section": "loop", "stems": {"keys": 0.5, "horns": 1.0}}},
        }
        report = write_stem_amplitude_report(root, spec, manifest, root / "reports", plots_dir=root / "plots", plot_format="jpg")
        payload = json.loads(report.read_text())
        assert payload["schema"] == "ambition.music_stem_amplitude.v1"
        by_group = {row["group"]: row for row in payload["groups"]}
        assert "keys" in by_group and "horns" in by_group
        assert by_group["keys"]["weighted_default_rms_dbfs"] > by_group["horns"]["weighted_default_rms_dbfs"]
        assert (root / "reports" / "stem_amplitude_summary.txt").exists()
        assert (root / "reports" / "stem_amplitude_envelope.tsv").exists()
        if (root / "plots" / "stem_amplitude_balance.jpg").exists():
            assert (root / "plots" / "stem_amplitude_timeline.jpg").exists()



def test_adaptive_section_report_draws_per_section_noise_views():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = 48_000
        t = np.arange(sr // 2, dtype="float32") / sr
        low = 0.12 * np.sin(2 * np.pi * 110.0 * t)
        hissy = 0.04 * np.sin(2 * np.pi * 7000.0 * t)
        stereo_low = np.stack([low, low], axis=1).astype("float32")
        stereo_hissy = np.stack([hissy, hissy], axis=1).astype("float32")
        for section, audio in [("intro", stereo_hissy), ("wave1", stereo_low)]:
            d = root / "adaptive" / section
            d.mkdir(parents=True)
            sf.write(d / f"cue_hash.{section}.full.wav", audio, sr)
            sf.write(d / f"cue_hash.{section}.strings.wav", audio, sr)
        manifest = {
            "id": "cue",
            "hash": "hash",
            "sample_rate": sr,
            "sections": [
                {"id": "intro", "start_seconds": 0.0, "end_seconds": 0.5, "duration_seconds": 0.5},
                {"id": "wave1", "start_seconds": 0.5, "end_seconds": 1.0, "duration_seconds": 0.5},
            ],
            "files": {
                "adaptive": {
                    "intro": {"full": "adaptive/intro/cue_hash.intro.full.wav", "strings": "adaptive/intro/cue_hash.intro.strings.wav"},
                    "wave1": {"full": "adaptive/wave1/cue_hash.wave1.full.wav", "strings": "adaptive/wave1/cue_hash.wave1.strings.wav"},
                },
                "preview": {},
            },
        }
        spec = {"id": "cue", "state_map": {"intro": {"section": "intro"}, "wave1": {"preferred_section": "wave1", "stems": {"strings": 1.0}}}}
        report = write_adaptive_section_report(root, spec, manifest, root / "reports", plots_dir=root / "plots", plot_format="jpg")
        payload = json.loads(report.read_text())
        assert payload["schema"] == "ambition.adaptive_section_audit.v1"
        by_section = {row["section"]: row for row in payload["rows"] if row["kind"] == "full"}
        assert by_section["intro"]["high_band_ratio"] > by_section["wave1"]["high_band_ratio"]
        assert (root / "reports" / "adaptive_section_audit_summary.txt").exists()
        assert (root / "reports" / "adaptive_section_audit.tsv").exists()
        if (root / "plots" / "adaptive_section_full_levels.jpg").exists():
            assert (root / "plots" / "adaptive_section_full_highband.jpg").exists()
            assert (root / "plots" / "adaptive_section_stack_intro.jpg").exists()


def test_publish_cue_copies_adaptive_full_sections_to_stable_runtime_paths():
    from ambition_music_renderer.cli import publish_cue

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        outdir = root / "generated" / "cue"
        preview = outdir / "preview"
        intro = outdir / "adaptive" / "intro"
        wave1 = outdir / "adaptive" / "wave1"
        preview.mkdir(parents=True)
        intro.mkdir(parents=True)
        wave1.mkdir(parents=True)
        (preview / "cue_hash.full_soundtrack_preview.ogg").write_bytes(b"full")
        (intro / "cue_hash.intro.full.ogg").write_bytes(b"intro")
        (wave1 / "cue_hash.wave1.full.ogg").write_bytes(b"wave1")
        (outdir / "cue_hash.adaptive_manifest.json").write_text(
            json.dumps(
                {
                    "id": "cue",
                    "hash": "hash",
                    "files": {
                        "preview": {
                            "full_soundtrack": "preview/cue_hash.full_soundtrack_preview.ogg"
                        },
                        "adaptive": {
                            "intro": {"full": "adaptive/intro/cue_hash.intro.full.ogg"},
                            "wave1": {"full": "adaptive/wave1/cue_hash.wave1.full.ogg"},
                        },
                    },
                }
            ),
            encoding="utf8",
        )
        dest = root / "assets" / "audio" / "music" / "generated"

        assert publish_cue("cue", outdir, dest)
        assert (dest / "cue" / "full.ogg").read_bytes() == b"full"
        assert (dest / "cue" / "adaptive" / "intro" / "intro.full.ogg").read_bytes() == b"intro"
        assert (dest / "cue" / "adaptive" / "wave1" / "wave1.full.ogg").read_bytes() == b"wave1"
        assert (dest / "cue" / "cue.adaptive_manifest.json").exists()


def test_publish_adaptive_cue_fails_without_section_fulls():
    from ambition_music_renderer.cli import publish_cue

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        outdir = root / "generated" / "first_goblin_tune_v2"
        preview = outdir / "preview"
        preview.mkdir(parents=True)
        (preview / "first_goblin_tune_v2_hash.full_soundtrack_preview.ogg").write_bytes(b"full")
        (outdir / "first_goblin_tune_v2_hash.adaptive_manifest.json").write_text(
            json.dumps(
                {
                    "id": "first_goblin_tune_v2",
                    "hash": "hash",
                    "files": {
                        "preview": {
                            "full_soundtrack": "preview/first_goblin_tune_v2_hash.full_soundtrack_preview.ogg"
                        },
                        "adaptive": {},
                    },
                }
            ),
            encoding="utf8",
        )
        dest = root / "assets" / "audio" / "music" / "generated"

        assert not publish_cue("first_goblin_tune_v2", outdir, dest)
        assert not (dest / "first_goblin_tune_v2" / "full.ogg").exists()
        assert not (dest / "first_goblin_tune_v2" / "adaptive").exists()


def test_top_level_adaptive_render_defaults_to_full_mix_sections():
    from ambition_music_renderer.cli import render_mode_for_cue

    args = build_parser().parse_args(["render", "first_goblin_tune_v2"])
    assert render_mode_for_cue("first_goblin_tune_v2", args) == (False, True)

    args = build_parser().parse_args(["render", "first_goblin_tune_v2", "--no-simple-mix"])
    assert render_mode_for_cue("first_goblin_tune_v2", args) == (False, False)

    args = build_parser().parse_args(["render", "lofi_study_loop"])
    assert render_mode_for_cue("lofi_study_loop", args) == (True, False)


def test_reference_audio_audit_reports_surface_features():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = 48_000
        t = np.arange(sr // 2, dtype="float32") / sr
        audio = 0.1 * np.sin(2 * np.pi * 440.0 * t)
        wav = root / "reference.wav"
        sf.write(wav, np.stack([audio, audio], axis=1), sr)
        payload = analyze_reference_audio(wav, frame_seconds=0.1)
        assert payload["schema"] == "ambition.reference_audio_audit.v1"
        assert payload["duration_s"] > 0.49
        assert payload["overall"]["spectral_centroid_mean_hz"] > 100
        paths = write_reference_audio_reports(payload, root / "reports")
        assert Path(paths["summary"]).exists()
        assert Path(paths["envelope"]).exists()


def test_adaptive_composition_mastering_report_prefers_global_slices():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = 48_000
        t = np.arange(sr // 2, dtype="float32") / sr
        quiet_hiss = 0.01 * np.sin(2 * np.pi * 9000.0 * t)
        loud_low = 0.12 * np.sin(2 * np.pi * 110.0 * t)
        for section, audio in [("intro", quiet_hiss), ("wave1", loud_low)]:
            d = root / "adaptive" / section
            d.mkdir(parents=True)
            sf.write(d / f"cue_hash.{section}.full.wav", np.stack([audio, audio], axis=1), sr)
        manifest = {
            "id": "cue",
            "hash": "hash",
            "sample_rate": sr,
            "sections": [
                {"id": "intro", "start_seconds": 0.0, "end_seconds": 0.5, "duration_seconds": 0.5},
                {"id": "wave1", "start_seconds": 0.5, "end_seconds": 1.0, "duration_seconds": 0.5},
            ],
            "files": {
                "adaptive": {
                    "intro": {"full": "adaptive/intro/cue_hash.intro.full.wav"},
                    "wave1": {"full": "adaptive/wave1/cue_hash.wave1.full.wav"},
                },
                "preview": {},
            },
        }
        spec = {
            "id": "cue",
            "render": {"adaptive_section_mastering": {"mode": "global_master_slices"}},
            "sections": [
                {"id": "intro", "kind": "intro", "intensity": 0.35, "density": 0.1},
                {"id": "wave1", "kind": "loop_component", "intensity": 0.6, "density": 0.4},
            ],
        }
        report = write_adaptive_composition_mastering_report(root, spec, manifest, root / "reports", plots_dir=root / "plots", plot_format="jpg")
        payload = json.loads(report.read_text())
        assert payload["schema"] == "ambition.adaptive_composition_mastering.v1"
        assert payload["mastering"]["mode"] == "global_master_slices"
        text = (root / "reports" / "adaptive_composition_mastering_summary.txt").read_text()
        assert "mastering mode: global_master_slices" in text
        assert (root / "reports" / "adaptive_composition_mastering.tsv").exists()
        if (root / "plots" / "adaptive_composition_mastering_levels.jpg").exists():
            assert (root / "plots" / "adaptive_composition_noise_floor.jpg").exists()


def test_shrill_note_audit_flags_whistle_register_sources():
    spec = {
        "schema": "ambition.musicir.v1",
        "id": "shrill_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "guitar", "group": "guitars", "program": "distortion_guitar"},
            {"name": "kit", "group": "drums", "is_drum": True},
        ],
        "state_map": {"default": {"section": "loop", "stems": {"guitars": 1.0}}},
        "motifs": [
            {"id": "bad_whistle", "root": "C4", "intervals": [0], "rhythm": [1.0], "velocities": [1.0]},
        ],
        "layer_templates": {
            "bad_guitar": {
                "kind": "motif",
                "instrument": "guitar",
                "motif": "bad_whistle",
                "root": "C9",
                "starts": [[0, 0.0]],
                "velocity": 100,
            },
            "kit_noise": {
                "kind": "drums",
                "instrument": "kit",
                "events": [{"drum": "crash", "beat": 0.0, "velocity": 120}],
            },
        },
        "sections": [{"id": "loop", "bars": 1, "harmony": ["C"], "layers": ["bad_guitar", "kit_noise"]}],
    }
    payload = audit_shrill_note_spec(spec, min_frequency_hz=4000.0)
    assert payload["schema"] == "ambition.music_shrill_note_audit.v1"
    assert payload["candidates"]
    top = payload["candidates"][0]
    assert top["note"] == "C9"
    assert top["group"] == "guitars"
    assert top["severity"] in {"whistle_8k_plus", "extreme_10k_plus"}
    assert "layer_templates.bad_guitar.root=C9" in top["source_hint"]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        paths = write_shrill_note_reports(payload, root / "reports", plots_dir=root / "plots", plot_format="jpg")
        assert Path(paths["summary"]).exists()
        assert Path(paths["markdown"]).exists()
        assert "Top Candidates" in Path(paths["markdown"]).read_text()


def test_bundle_many_parser_accepts_parallel_flags():
    args = build_parser().parse_args([
        "bundle-many",
        "lofi_study_loop",
        "tech_bros_disruption",
        "--workers",
        "3",
        "--render-jobs",
        "1",
        "--force",
        "--zip-report",
    ])
    assert args.command == "bundle-many"
    assert args.workers == 3
    assert args.render_jobs == 1
    assert args.cues == ["lofi_study_loop", "tech_bros_disruption"]


def test_chord_intervals_does_not_treat_d6_over_9_as_slash_bass():
    root, intervals, slash = chord_intervals("D6/9")
    assert root == "D"
    assert slash is None
    assert 9 in intervals
    assert 14 in intervals


def test_timeline_markers_include_explicit_form_markers():
    spec = {
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "render": {"metadata_markers": [{"id": "bloom", "label": "Bloom", "bar": 9}]},
    }
    sections = [{"id": "loop", "label": "Loop", "kind": "loop_component", "start_seconds": 0.0}]
    markers = timeline_markers_from_spec(spec, sections)
    assert [m["id"] for m in markers] == ["loop", "bloom"]
    assert markers[1]["start_seconds"] == 16.0
