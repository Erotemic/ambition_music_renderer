from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.inspect import (
    authoring_graph_report,
    expand_compiled_score,
    trace_compiled_event,
)
from ambition_music_renderer.musicir.model import compiled_score_fingerprint
from ambition_music_renderer.validation.diagnostics import MusicIRValidationError
from ambition_music_renderer.validation.musicir import validate_musicir_file, validate_musicir_spec


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "scores/examples/musicir_v3_authoring.music.yaml"


def _minimal_score():
    return {
        "schema": "ambition.musicir.v3",
        "id": "diagnostic_score",
        "timebase": {"ppq": 480},
        "meter": "4/4",
        "tempo": 120,
        "harmony": ["C"],
        "end": {"bar": 2, "beat": 1},
        "instruments": [
            {
                "name": "keys",
                "group": "music",
                "program": "acoustic_grand_piano",
            }
        ],
        "materials": {
            "hook": {
                "events": [
                    {"id": "n1", "at": 0, "dur": "1/4", "pitch": "C4", "velocity": 90}
                ]
            }
        },
        "parts": [
            {
                "id": "part",
                "instrument": "keys",
                "voices": [
                    {
                        "id": "voice",
                        "clips": [
                            {
                                "id": "hook_clip",
                                "at": {"bar": 1, "beat": 1},
                                "use": "hook",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_v3_validation_reports_precise_unknown_generator_field(tmp_path: Path):
    text = """\
schema: ambition.musicir.v3
id: typo_score
timebase: {ppq: 480}
meter: 4/4
tempo: 120
harmony: [C]
end: {bar: 2, beat: 1}
instruments:
  - {name: keys, group: music, program: acoustic_grand_piano}
parts:
  - id: part
    instrument: keys
    voices:
      - id: voice
        clips:
          - id: arp
            at: {bar: 1, beat: 1}
            duration: {bars: 1}
            generate:
              kind: harmony.arpeggio
              patern: [0, 2, 1, 2]
              step: 0.5
"""
    path = tmp_path / "typo.music.yaml"
    path.write_text(text)
    with pytest.raises(MusicIRValidationError) as info:
        validate_musicir_file(path)
    matches = [d for d in info.value.diagnostics if d.code == "V3_GENERATOR_FIELD"]
    assert len(matches) == 1
    diag = matches[0]
    assert diag.path_text == "parts[0].voices[0].clips[0].generate.patern"
    assert diag.location is not None
    assert diag.location.line == 21
    assert diag.hint == "did you mean `pattern`?"
    rendered = info.value.format()
    assert "typo.music.yaml:21" in rendered
    assert "did you mean `pattern`?" in rendered


def test_v3_validation_points_at_bad_material_and_pitch_semantics(tmp_path: Path):
    spec = _minimal_score()
    clip = spec["parts"][0]["voices"][0]["clips"][0]
    clip["use"] = "hok"
    event = spec["materials"]["hook"]["events"][0]
    event["pitch"] = {"kind": "scale_degree", "mode": "minro", "degree": 2, "tonic": "C"}
    path = tmp_path / "bad.music.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    with pytest.raises(MusicIRValidationError) as info:
        validate_musicir_file(path)
    by_code = {d.code: d for d in info.value.diagnostics}
    assert by_code["V3_CLIP_MATERIAL"].hint == "did you mean `hook`?"
    assert by_code["V3_SCALE_MODE"].hint == "did you mean `minor`?"
    assert by_code["V3_CLIP_MATERIAL"].location is not None
    assert by_code["V3_SCALE_MODE"].location is not None


def test_v3_validation_catches_source_identity_and_controller_contracts(tmp_path: Path):
    spec = _minimal_score()
    clips = spec["parts"][0]["voices"][0]["clips"]
    clips.append(copy.deepcopy(clips[0]))
    clips[1]["automation"] = [
        {"id": "bend", "at": 0, "pitch_bend": 99999},
        {"id": "bend", "at": "1/4", "cc": "expresion", "value": 140},
    ]
    path = tmp_path / "identity.music.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    with pytest.raises(MusicIRValidationError) as info:
        validate_musicir_file(path)
    codes = [d.code for d in info.value.diagnostics]
    assert "V3_CLIP_DUPLICATE_ID" in codes
    assert "V3_AUTOMATION_DUPLICATE_ID" in codes
    assert "V3_PITCH_BEND" in codes
    assert "V3_CC_NAME" in codes
    assert "V3_CC_VALUE" in codes
    cc_name = next(d for d in info.value.diagnostics if d.code == "V3_CC_NAME")
    assert cc_name.hint == "did you mean `expression`?"


def test_v3_validation_wraps_semantic_compile_error_with_source_context():
    spec = _minimal_score()
    clip = spec["parts"][0]["voices"][0]["clips"][0]
    clip.pop("use")
    clip["duration"] = {"bars": 1}
    clip["generate"] = {
        "kind": "harmony.arpeggio",
        "pattern": [0, 1],
        "step": 0.5,
        "duration_beats": 0.4,
        "octave": 4,
        "velocity": 80,
        "humanize_ms": 0,
    }
    # Start off a bar boundary: this is a semantic restriction of the current
    # v1 generator bridge and belongs to canonical compilation, not static shape
    # validation.
    clip["at"] = {"bar": 1, "beat": 2}
    with pytest.raises(MusicIRValidationError) as info:
        validate_musicir_spec(spec)
    assert len(info.value.diagnostics) == 1
    diag = info.value.diagnostics[0]
    assert diag.code == "V3_COMPILE"
    assert "bar boundary" in diag.message


def test_expand_report_connects_generator_source_harmony_events_and_realization():
    spec = yaml.safe_load(EXAMPLE.read_text())
    compiled = compile_score(spec)
    before = compiled_score_fingerprint(compiled)
    report = expand_compiled_score(compiled, clip_id="harmony_motion", base_dir=EXAMPLE.parent)
    after = compiled_score_fingerprint(compiled)
    assert before == after
    assert report["counts"] == {"clips": 1, "notes": 24, "controls": 1}
    source = report["source_clips"][0]
    assert source["generator_kind"] == "harmony.arpeggio"
    assert source["path"] == "parts[0].voices[0].clips[1]"
    assert {row["harmony"] for row in report["expanded_notes"]} == {"F", "C", "G"}
    assert report["expanded_controls"][0]["source_ref"]["source_event_id"] == "arp_expression"
    assert set(report["instrument_resolution"]) == {"keys"}
    assert report["instrument_resolution"]["keys"]["authored_instrument"]["name"] == "keys"


def test_trace_event_recovers_material_and_generator_derivation():
    spec = yaml.safe_load(EXAMPLE.read_text())
    compiled = compile_score(spec)
    material_event = next(e for e in compiled.note_events if e.get("source_ref", {}).get("material_id") == "answer")
    material_trace = trace_compiled_event(compiled, material_event["event_id"], base_dir=EXAMPLE.parent)
    assert material_trace["source_clip"]["material_id"] == "answer"
    assert material_trace["source_ref"]["source_event_id"] == "a1"
    assert material_trace["source_event"]["id"] == "a1"
    assert material_trace["harmony"] == "Am"

    generated_event = next(e for e in compiled.note_events if e.get("source_ref", {}).get("generator_kind") == "harmony.arpeggio")
    generated_trace = trace_compiled_event(compiled, generated_event["event_id"], base_dir=EXAMPLE.parent)
    assert generated_trace["source_clip"]["generator_kind"] == "harmony.arpeggio"
    assert generated_trace["generator_output_index"] == 0
    assert generated_trace["harmony"] == "F"
    assert generated_trace["instrument_resolution"]["authored_instrument"]["name"] == "keys"


def test_graph_report_preserves_composition_structure_without_expanding_it():
    compiled = compile_score(yaml.safe_load(EXAMPLE.read_text()))
    report = authoring_graph_report(compiled)
    assert report["kind"] == "graph"
    assert report["counts"] == {"nodes": 8, "edges": 8, "materials": 1, "clips": 3}
    clip_nodes = [node for node in report["nodes"] if node["kind"] == "clip"]
    assert {node["label"] for node in clip_nodes} == {
        "opening_answer",
        "harmony_motion",
        "final_accent",
    }
    assert any(edge["kind"] == "uses" and edge["to"] == "material:answer" for edge in report["edges"])
    assert any(edge["kind"] == "generates" and edge["to"] == "generator:harmony.arpeggio" for edge in report["edges"])


def test_graph_report_explains_legacy_score_without_breaking_it():
    spec = {
        "schema": "ambition.musicir.v2",
        "id": "legacy_exact",
        "instruments": [{"name": "keys", "program": "acoustic_grand_piano"}],
        "score": {
            "timebase": {"ppq": 480},
            "meter": [{"bar": 1, "signature": "4/4"}],
            "tempo": [{"tick": 0, "bpm": 120}],
            "end_tick": 480,
        },
        "parts": [
            {
                "id": "keys_part",
                "instrument": "keys",
                "voices": [{"id": "voice", "events": [{"tick": 0, "dur_ticks": 480, "pitch": 60, "velocity": 80}]}],
            }
        ],
    }
    compiled = compile_score(spec)
    report = authoring_graph_report(compiled)
    assert report["canonical_schema"] == "ambition.musicir.v2"
    assert "remain renderable" in report["message"]


def test_validation_and_expansion_share_checked_in_instrument_identity(tmp_path: Path):
    spec = _minimal_score()
    inst = spec["instruments"][0]
    inst["instrument_backend"] = {"kind": "sfz", "library_ref": "guitar.emliy"}
    path = tmp_path / "bad-instrument.music.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    with pytest.raises(MusicIRValidationError) as info:
        validate_musicir_file(path)
    diag = next(d for d in info.value.diagnostics if d.code == "V3_INSTRUMENT_LIBRARY_REF")
    assert diag.hint == "did you mean `guitar.emily`?"

    inst["instrument_backend"]["library_ref"] = "guitar.emily"
    compiled = compile_score(spec)
    report = expand_compiled_score(compiled, base_dir=tmp_path)
    plan = report["instrument_resolution"]["keys"]
    assert plan["library_ref"] == "guitar.emily"
    assert plan["expected_catalog_instrument"] is True
    assert plan["catalog"]["ref"] == "guitar.emily"
