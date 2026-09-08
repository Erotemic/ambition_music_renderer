from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from ambition_music_renderer.audit.composition_quality import composition_quality_report
from ambition_music_renderer.audit.render_compare import compare_audio_arrays
from ambition_music_renderer.instrument_authoring import (
    build_instrument_authoring_index,
    canonical_audition_score,
)
from ambition_music_renderer.instrument_catalog import instrument_catalog
from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.validation.v3 import diagnose_v3_spec

ROOT = Path(__file__).resolve().parents[1]


def _score(*, clips, key=None, harmony=None, instrument=None):
    spec = {
        "schema": "ambition.musicir.v3",
        "id": "v3_completion_test",
        "seed": 19,
        "timebase": {"ppq": 480},
        "meter": "4/4",
        "tempo": 120,
        "end": {"bar": 5, "beat": 1},
        "harmony": harmony or ["Em", "C", "G", "D"],
        "instruments": [instrument or {
            "name": "keys", "group": "music", "program": "acoustic_grand_piano"
        }],
        "parts": [{
            "id": "part", "instrument": "keys",
            "voices": [{"id": "voice", "clips": clips}],
        }],
    }
    if key is not None:
        spec["key"] = key
    return spec


def _notes(compiled):
    return sorted(
        (
            int(round(compiled.pm.time_to_tick(n.start))),
            int(round(compiled.pm.time_to_tick(n.end))),
            int(n.pitch),
            int(n.velocity),
        )
        for inst in compiled.pm.instruments
        for n in inst.notes
    )


def test_explicit_technique_changes_gate_but_absence_preserves_literal_duration():
    plain = compile_score(_score(clips=[{
        "id": "plain", "at": {"bar": 1, "beat": 1},
        "events": [[0, "1/4", "C4", 90]],
    }]))
    short = compile_score(_score(clips=[{
        "id": "short", "at": {"bar": 1, "beat": 1}, "technique": "staccato",
        "events": [[0, "1/4", "C4", 90]],
    }]))
    assert _notes(plain)[0][:3] == (0, 480, 60)
    assert _notes(short)[0][:3] == (0, 192, 60)


def test_score_key_supplies_scale_degree_context():
    compiled = compile_score(_score(
        key="E minor",
        clips=[{
            "id": "degree", "at": {"bar": 1, "beat": 1},
            "events": [{
                "at": 0, "dur": "1/4",
                "pitch": {"kind": "scale_degree", "degree": 3, "octave": 4},
                "velocity": 90,
            }],
        }],
    ))
    assert _notes(compiled)[0][2] == 67  # G4, third degree of E natural minor


def test_score_key_scale_degree_does_not_require_harmony():
    spec = _score(
        key="D dorian",
        clips=[{
            "id": "degree", "at": {"bar": 1, "beat": 1},
            "events": [{
                "at": 0, "dur": "1/4",
                "pitch": {"kind": "scale_degree", "degree": 6, "octave": 4},
                "velocity": 90,
            }],
        }],
    )
    spec.pop("harmony")
    compiled = compile_score(spec)
    assert _notes(compiled)[0][2] == 71  # B4, sixth degree of D dorian


def test_automation_curve_expands_deterministically_with_provenance():
    spec = _score(clips=[{
        "id": "curve", "at": {"bar": 1, "beat": 1},
        "events": [[0, "1/2", "C4", 80]],
        "automation": [{
            "id": "swell", "cc": "expression",
            "points": [[0, 64], ["1/2", 112]],
            "interpolation": "linear", "resolution": "1/8",
        }],
    }])
    first = compile_score(spec)
    second = compile_score(copy.deepcopy(spec))
    controls = [row for row in first.controller_events if row.get("event_type") == "control_change"]
    assert [row["value"] for row in controls] == [64, 76, 88, 100, 112]
    assert all((row.get("source_ref") or {}).get("source_kind") == "automation_curve" for row in controls)
    assert first.controller_events == second.controller_events


def test_generator_variation_controls_are_opt_in_and_audible_in_compiled_events():
    base_generate = {
        "kind": "harmony.arpeggio", "pattern": [0, 1, 2, 1],
        "step": 0.5, "duration_beats": 0.45, "octave": 4, "velocity": 80,
    }
    plain = compile_score(_score(clips=[{
        "id": "arp", "at": {"bar": 1, "beat": 1}, "duration": {"bars": 1},
        "generate": base_generate,
    }]))
    varied_spec = copy.deepcopy(base_generate)
    varied_spec.update({"velocity_pattern": [1.0, 0.5], "octave_pattern": [0, 1]})
    varied = compile_score(_score(clips=[{
        "id": "arp", "at": {"bar": 1, "beat": 1}, "duration": {"bars": 1},
        "generate": varied_spec,
    }]))
    plain_notes = _notes(plain)
    varied_notes = _notes(varied)
    assert len(plain_notes) == len(varied_notes)
    assert [n[3] for n in varied_notes[:4]] != [n[3] for n in plain_notes[:4]]
    assert max(n[2] for n in varied_notes) > max(n[2] for n in plain_notes)


def test_drum_fill_and_bar_dynamics_are_available_without_changing_default_pattern():
    drum = {"name": "keys", "group": "drums", "is_drum": True}
    base = {
        "kind": "drums.pattern",
        "events": [
            {"drum": "kick", "beats": [0, 2], "velocity": 80},
            {"drum": "snare", "beats": [1, 3], "velocity": 90},
        ],
    }
    plain = compile_score(_score(instrument=drum, clips=[{
        "id": "drums", "at": {"bar": 1, "beat": 1}, "duration": {"bars": 4}, "generate": base,
    }]))
    advanced = copy.deepcopy(base)
    advanced.update({
        "bar_velocity_pattern": [0.8, 1.0, 0.9, 1.1],
        "fill_every_bars": 4,
        "fill_mode": "overlay",
        "fill_events": [{"drum": "closed_hat", "beats": [3.0, 3.25, 3.5, 3.75], "velocity": 74}],
    })
    varied = compile_score(_score(instrument=drum, clips=[{
        "id": "drums", "at": {"bar": 1, "beat": 1}, "duration": {"bars": 4}, "generate": advanced,
    }]))
    assert len(_notes(varied)) == len(_notes(plain)) + 4
    assert len({n[3] for n in _notes(varied)}) > len({n[3] for n in _notes(plain)})


def test_generator_catalog_rejects_bad_typed_array_items():
    spec = _score(clips=[{
        "id": "bad", "at": {"bar": 1, "beat": 1}, "duration": {"bars": 1},
        "generate": {"kind": "harmony.arpeggio", "velocity_pattern": [1.0, -0.5]},
    }])
    diagnostics = diagnose_v3_spec(spec)
    assert any(d.code == "V3_GENERATOR_VALUE" and "velocity_pattern" in d.path_text for d in diagnostics)


def test_instrument_authoring_index_is_exactly_regenerable_and_auditions_compile():
    checked = json.loads((ROOT / "ambition_music_renderer/data/instrument_authoring_index.json").read_text())
    assert build_instrument_authoring_index() == checked
    for ref in sorted(instrument_catalog()):
        compiled = compile_score(canonical_audition_score(ref))
        assert sum(len(inst.notes) for inst in compiled.pm.instruments) > 0, ref


def test_source_only_authoring_register_check_runs_with_python_S():
    proc = subprocess.run(
        [sys.executable, "-S", str(ROOT / "dev/check_source_only_authoring.py")],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    # The register's count is compared with the checked-in catalog, not a
    # literal: the catalog may grow (73 -> 74 with `japan.shamisen`) and the
    # claim under test is "the source-only register agrees with the authority",
    # which stays falsifiable — a register that skipped or double-counted an
    # instrument would still disagree with the catalog.
    expected_instruments = len(instrument_catalog())
    assert expected_instruments > 0
    assert f"{expected_instruments} instruments" in proc.stdout, proc.stdout
    assert "16 generators" in proc.stdout

    index_check = subprocess.run(
        [sys.executable, str(ROOT / "dev/update_instrument_authoring_index.py"), "--check"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert index_check.returncode == 0, index_check.stderr
    assert "instrument authoring index is current" in index_check.stdout


def test_composition_quality_report_exposes_evidence_not_scalar_score():
    compiled = compile_score(_score(clips=[{
        "id": "phrase", "at": {"bar": 1, "beat": 1},
        "events": [
            [0, "1/4", "C4", 70], ["1/4", "1/4", "E4", 80],
            ["1/2", "1/4", "G4", 90], ["3/4", "1/4", "C5", 100],
        ],
        "repeat": {"count": 4, "every": {"bars": 1}},
    }]))
    report = composition_quality_report(compiled)
    assert report["schema"] == "ambition.composition_quality_report.v1"
    assert "score" not in report
    assert report["note_count"] == 16
    assert report["velocity"]["distinct"] == 4
    assert report["groups"][0]["group"] == "music"
    assert report["identical_bar_runs"]


def test_audio_compare_reports_signal_and_spectral_deltas():
    sr = 48000
    t = np.arange(sr, dtype=np.float64) / sr
    before = np.column_stack([0.2 * np.sin(2 * np.pi * 220 * t)] * 2)
    after = np.column_stack([
        0.3 * np.sin(2 * np.pi * 440 * t),
        0.25 * np.sin(2 * np.pi * 440 * t + 0.2),
    ])
    report = compare_audio_arrays(before, after, sr)
    assert report["delta"]["rms_db"] > 0
    assert report["delta"]["spectral_centroid_hz"] > 100
    assert report["after"]["stereo"]["side_to_mid_rms_ratio"] > report["before"]["stereo"]["side_to_mid_rms_ratio"]
    assert report["delta"]["aligned_waveform_correlation"] < 0.2


def test_legacy_regeneration_corpus_compiles(tmp_path):
    report_fpath = tmp_path / "legacy_regeneration.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "dev/check_legacy_regeneration.py"),
            "--json-out",
            str(report_fpath),
        ],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(report_fpath.read_text(encoding="utf8"))
    assert report["score_count"] > 0
    assert report["failed"] == 0
    assert report["passed"] == report["score_count"]
    assert (
        f"legacy regeneration OK: {report['passed']} scores compiled "
        f"across {report['rounds']} round(s)"
    ) in proc.stdout


def test_sequence_material_composes_event_materials_with_transforms_and_provenance():
    spec = _score(clips=[{
        "id": "phrase_clip", "at": {"bar": 1, "beat": 1}, "use": "phrase",
    }])
    spec["materials"] = {
        "riff": {
            "kind": "events",
            "events": [{"id": "hit", "at": 0, "dur": "1/4", "pitch": "C4", "velocity": 80}],
        },
        "phrase": {
            "kind": "sequence",
            "items": [
                {"id": "a", "use": "riff", "at": 0},
                {"id": "b", "use": "riff", "at": "1/4", "transpose": 7, "velocity_scale": 0.5},
            ],
        },
    }
    compiled = compile_score(spec)
    assert _notes(compiled) == [(0, 480, 60, 80), (480, 960, 67, 40)]
    assert compiled.note_events[0]["source_ref"]["material_chain"] == ("phrase", "riff") or compiled.note_events[0]["source_ref"]["material_chain"] == ["phrase", "riff"]
    assert compiled.note_events[1]["source_ref"]["source_event_id"].startswith("b.r000.")


def test_form_energy_is_shared_section_intent_for_generators():
    clip = {
        "id": "arp", "at": {"bar": 1, "beat": 1}, "duration": {"bars": 1},
        "generate": {"kind": "harmony.arpeggio", "velocity": 100, "humanize_ms": 0},
    }
    plain_spec = _score(clips=[clip])
    low_spec = copy.deepcopy(plain_spec)
    low_spec["form"] = [{
        "id": "low", "from": {"bar": 1, "beat": 1}, "to": {"bar": 2, "beat": 1},
        "energy": 0.5,
    }]
    plain = _notes(compile_score(plain_spec))
    low = _notes(compile_score(low_spec))
    assert len(plain) == len(low)
    assert max(n[3] for n in low) < max(n[3] for n in plain)
    assert max(n[3] for n in low) in {49, 50, 51}


def test_v3_starter_and_showcase_scores_compile_deterministically(tmp_path):
    paths = [
        ROOT / "ambition_music_renderer/data/musicir_v3_new.music.yaml",
        *sorted((ROOT / "scores/examples").glob("musicir_v3_*showcase.music.yaml")),
    ]
    for path in paths:
        spec = yaml.safe_load(path.read_text())
        first = compile_score(copy.deepcopy(spec))
        second = compile_score(copy.deepcopy(spec))
        from ambition_music_renderer.musicir.model import compiled_score_fingerprint
        assert compiled_score_fingerprint(first) == compiled_score_fingerprint(second), path.name
        assert first.note_events == second.note_events, path.name

    output = tmp_path / "fresh.music.yaml"
    proc = subprocess.run(
        [sys.executable, "-S", str(ROOT / "dev/new_musicir_v3.py"), "Fresh: Agent Cue", str(output)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    fresh = yaml.safe_load(output.read_text())
    assert fresh["schema"] == "ambition.musicir.v3"
    assert fresh["id"] == "fresh_agent_cue"
    assert fresh["title"] == "Fresh: Agent Cue"
    compile_score(fresh)
