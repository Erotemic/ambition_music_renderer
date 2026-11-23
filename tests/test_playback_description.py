from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
import soundfile as sf

from ambition_music_renderer import cli
from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.model import compiled_score_fingerprint
from ambition_music_renderer.musicir.playback import (
    published_playback_description, rendered_playback_description, score_playback_description,
)
from ambition_music_renderer.render.playback_layers import (
    playback_layer_plan, runtime_product_path, write_playback_layers,
)
from ambition_music_renderer.validation.musicir import validate_musicir_spec
from ambition_music_renderer.validation.diagnostics import MusicIRValidationError


def procedural(sections, *, playback=None, tempo=None):
    return {
        "schema": "ambition.musicir.v1", "id": "clock_fixture", "seed": 11,
        "tempo": tempo or {"bpm": 240}, "meter": {"beats_per_bar": 4},
        "instruments": [{"name": "keys", "group": "music", "program": "acoustic_grand_piano"}],
        "sections": sections, "playback": playback or {"full": True},
    }


def exact():
    return {
        "schema": "ambition.musicir.v3", "id": "exact_clock_fixture",
        "timebase": {"ppq": 100},
        "meter": [{"bar": 1, "signature": "4/4"}, {"bar": 2, "signature": "3/4"}],
        "tempo": [{"at": {"bar": 1}, "bpm": 120},
                  {"at": {"bar": 2}, "bpm": 60, "hold_seconds": 1.25}],
        "end": {"bar": 4},
        "form": [{"id": "main", "from": {"bar": 1}, "to": {"bar": 4},
                  "valid_exit_local_bars": [1, 2, 3]}],
        "instruments": [], "parts": [], "playback": {"full": True},
    }


def test_procedural_lead_in_uses_the_last_compiled_beat_not_the_average():
    compiled = compile_score(procedural([
        {"id": "lead", "bars": 2, "layers": []},
        {"id": "body", "bars": 1, "layers": []},
    ], tempo={"bpm": 120, "map": [{"bar": 1, "bpm": 60}]}, playback={
        "full": True, "sections": [{"id": "loop", "form": ["body"], "loop": True, "lead_in": "lead"}],
    }))
    section = score_playback_description(compiled)["sections"][0]
    assert section["lead_in_start_seconds"] == pytest.approx(5.0, abs=1e-6)
    assert section["lead_in_start_seconds"] == compiled.clock.time_at_beat(7)
    assert section["material"]["lead_in"] == "folded"
    assert section["material"]["scheduled_pickup"] is False


def test_a_retained_pickup_can_start_at_score_zero():
    spec = procedural([
        {"id": "lead", "bars": 1, "layers": []},
        {"id": "body", "bars": 1, "layers": [{"kind": "notes", "instrument": "keys",
         "humanize_ms": 0, "notes": [[0, -0.01, "C4", 0.25, 80]]}]},
    ], tempo={"bpm": 60}, playback={"full": True, "sections": [
        {"id": "loop", "form": ["body"], "loop": True, "lead_in": "lead"},
    ]})
    spec["meter"]["beats_per_bar"] = 1
    section = score_playback_description(compile_score(spec))["sections"][0]
    assert section["lead_in_start_seconds"] == 0.0
    assert section["material"]["unretained_pickup_attacks"] == 0


def test_variable_meter_tempo_holds_and_exit_roles_use_the_exact_compiler_clock():
    spec = exact()
    validate_musicir_spec(spec, strict_schema=True)
    compiled = compile_score(spec)
    description = score_playback_description(compiled, sample_rate=8000)
    section = description["sections"][0]
    assert section["clock"] == {"kind": "boundaries", "bar_seconds": [0.0, 2.0, 6.25, 9.25]}
    assert section["musical_end_seconds"] == 9.25
    assert [(marker["role"], marker["seconds"]) for marker in section["markers"]] == [
        ("entry", 0.0), ("exit", 2.0), ("exit", 6.25), ("exit", 9.25),
    ]
    assert section["frame_plan"]["bar_frames"] == [0, 16000, 50000, 74000]
    assert description["evidence"] == "score_plan"
    assert "products" not in section


def test_global_cut_rounding_is_not_local_duration_rounding():
    spec = exact()
    spec.update(meter="4/4", tempo=60, end={"tick": 16}, form=[
        {"id": "offset", "from": {"tick": 4}, "to": {"tick": 16}},
    ])
    compiled = compile_score(spec)
    section = score_playback_description(compiled, sample_rate=10)["sections"][0]
    assert round(section["musical_end_seconds"] * 10) == 1
    assert section["frame_plan"]["score_origin_frame"] == 0
    assert section["frame_plan"]["musical_end_frame"] == 2


@pytest.mark.parametrize("exits", [[0], [True], [1.0], [4], "1"])
def test_invalid_exit_offsets_fail_before_rendering(exits):
    spec = exact()
    spec["form"][0]["valid_exit_local_bars"] = exits
    with pytest.raises(ValueError, match="bar|list"):
        score_playback_description(compile_score(spec))


def test_exact_event_ownership_can_cross_a_performed_boundary_without_changing_notes():
    spec = exact()
    spec.update(meter="4/4", tempo=60, end={"bar": 3}, form=[
        {"id": "a", "from": {"bar": 1}, "to": {"bar": 2}},
        {"id": "b", "from": {"bar": 2}, "to": {"bar": 3}},
    ], instruments=[{"name": "keys", "group": "music", "program": "acoustic_grand_piano"}],
       parts=[{"id": "keys", "instrument": "keys", "voices": [{"id": "voice", "clips": [
           {"id": "all", "at": {"bar": 1}, "events": [{"at": "399/400", "dur": "1/4", "pitch": "C4", "velocity": 80}]},
       ]}]}])
    event = spec["parts"][0]["voices"][0]["clips"][0]["events"][0]
    original = compile_score(spec)
    event["form_region"] = "a"
    assert compiled_score_fingerprint(compile_score(spec)) == compiled_score_fingerprint(original)
    event["form_region"] = "b"
    owned = compile_score(spec)
    assert [(note.start, note.end, note.pitch, note.velocity) for note in owned.pm.instruments[0].notes] == [
        (note.start, note.end, note.pitch, note.velocity) for note in original.pm.instruments[0].notes
    ]
    assert owned.note_events[0]["section"] == "b"
    assert compiled_score_fingerprint(owned) != compiled_score_fingerprint(original)
    assert score_playback_description(owned)["sections"][1]["material"]["unretained_pickup_attacks"] == 1
    event["form_region"] = "missing"
    with pytest.raises(ValueError, match="unknown form region"):
        compile_score(spec)
    with pytest.raises(MusicIRValidationError) as failure:
        validate_musicir_spec(spec)
    assert failure.value.diagnostics[0].path == ("parts", 0, "voices", 0, "clips", 0, "events", 0, "form_region")


def test_note_free_ring_validation_uses_compiled_event_ownership():
    spec = procedural([
        {"id": "lead", "bars": 1, "layers": []},
        {"id": "body", "bars": 1, "layers": [{"kind": "notes", "instrument": "keys",
         "humanize_ms": 0, "notes": [[0, -0.04, "C4", 0.5, 80]]}]},
    ], playback={"full": True, "sections": [
        {"id": "loop", "form": ["body"], "loop": True, "lead_in": "lead"},
    ]})
    compiled = compile_score(spec)
    plan = playback_layer_plan(compiled)
    assert compiled.note_events[0]["start_time"] < plan["sections"][0]["start_seconds"]
    assert compiled.note_events[0]["section"] == "body"
    spec["sections"][0]["layers"] = [{"kind": "notes", "instrument": "keys",
        "humanize_ms": 0, "notes": [[0, 0, "C4", 0.5, 80]]}]
    with pytest.raises(ValueError, match="lead_in.*owns note attacks"):
        playback_layer_plan(compile_score(spec))


@pytest.mark.parametrize("outgoing_loops", [False, True])
@pytest.mark.parametrize("frontend", ["v1", "v3"])
@pytest.mark.parametrize("incoming_retains_pickup", [False, True])
def test_a_shared_ring_keeps_its_file_span_without_the_next_programs_pickup(outgoing_loops, frontend, incoming_retains_pickup, tmp_path):
    spec = exact()
    spec.update(meter="4/4", tempo=60, end={"bar": 4}, form=[
        {"id": "a", "from": {"bar": 1}, "to": {"bar": 2}},
        {"id": "ring", "from": {"bar": 2}, "to": {"bar": 3}},
        {"id": "b", "from": {"bar": 3}, "to": {"bar": 4}},
    ], instruments=[{"name": "keys", "group": "music", "program": "acoustic_grand_piano"}],
       parts=[{"id": "keys", "instrument": "keys", "voices": [{"id": "voice", "clips": [
           {"id": "all", "at": {"bar": 1}, "events": [{"at": "799/400", "dur": "1/4", "pitch": "C4", "velocity": 80, "form_region": "b"}]},
       ]}]}], playback={"full": True, "layers": {"bed": ["music"]}, "sections": [
           {"id": "outgoing", "form": ["a"], "loop": outgoing_loops, "tail": "ring"},
           {"id": "incoming", "form": ["b"], "loop": True, "lead_in": "ring"},
       ]})
    if not incoming_retains_pickup:
        spec["playback"]["sections"][1].pop("lead_in")
        spec["playback"]["sections"][1]["loop"] = False
    if frontend == "v1":
        spec = procedural([
            {"id": "a", "bars": 1, "layers": []},
            {"id": "ring", "bars": 1, "layers": []},
            {"id": "b", "bars": 1, "layers": [{"kind": "notes", "instrument": "keys",
             "humanize_ms": 0, "notes": [[0, -0.01, "C4", 1.0, 80]]}]},
        ], tempo={"bpm": 60}, playback=spec["playback"])
    compiled = compile_score(spec)
    plan = playback_layer_plan(compiled)
    timeline = np.zeros((12000, 2), dtype=np.float32)
    timeline[7990:8090] = 1.0
    written = {}
    def write(audio, path):
        written[(path.parent.name, path.stem.rsplit(".", 1)[-1])] = audio
    write_playback_layers(plan, {"music": timeline}, 1000, tmp_path, "shared", write,
                          pre_master=timeline, master=lambda audio: audio)
    for layer in ("bed", "full"):
        assert len(written[("outgoing", layer)]) == (4000 if outgoing_loops else 8000)
        assert not written[("outgoing", layer)].any()
        if incoming_retains_pickup:
            assert written[("incoming", layer)][-10:].all()
        else:
            assert not written[("incoming", layer)][-10:].any()
    section = score_playback_description(compiled, sample_rate=1000)["sections"][0]
    assert section["material"]["tail_excludes_pickup"] is True
    assert section["frame_plan"]["tail_source_frames"] == 4000
    assert section["frame_plan"]["tail_source_audio_frames"] == 3990


def encoded(tmp_path):
    compiled = compile_score(procedural([
        {"id": "body", "bars": 2, "layers": []},
        {"id": "ring", "bars": 1, "layers": []},
    ], playback={"full": True, "layers": {"bed": ["music"]},
                 "sections": [{"id": "entry", "form": ["body"], "tail": "ring"}]}))
    plan = playback_layer_plan(compiled)
    timeline = np.zeros((24000, 2), dtype=np.float32)
    def write(audio, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, audio, 8000, format="OGG", subtype="VORBIS")
    files = {"playback": write_playback_layers(plan, {"music": timeline}, 8000, tmp_path,
              "fixture_hash", write, pre_master=timeline, master=lambda audio: audio)}
    description = rendered_playback_description(
        compiled, root=tmp_path, files=files, sample_rate=8000, render_fingerprint="render_identity",
        runtime_stem_gain_mode="shared", runtime_gain_db=-6.0,
        adaptive_mastering_mode="legacy_section_postprocess",
    )
    return compiled, files, description


def test_encoded_frames_tail_gain_basis_and_published_identity(tmp_path):
    _, _, description = encoded(tmp_path)
    section = description["sections"][0]
    assert section["frame_plan"]["musical_end_frame"] == 16000
    assert section["material"]["tail"] == "appended"
    assert {product["frames"] for product in section["products"]} == {24000}
    products = {product["layer"]: product for product in section["products"]}
    assert products["bed"]["gain_basis"] == "grouped_pre_master"
    assert products["bed"]["applied_runtime_gain_db"] == -6.0
    assert products["full"]["gain_basis"] == "mastered_full"
    assert products["full"]["applied_runtime_gain_db"] == 0.0
    assert products["full"]["mastering"] == "composition_master"
    published = tmp_path / "published"
    for product in section["products"]:
        dest = published / runtime_product_path("playback", section["id"], product["layer"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp_path / product["path"], dest)
    result = published_playback_description(description, published)
    assert result["render_fingerprint"] == "render_identity"
    assert result["evidence"] == "published_products"
    assert result["sections"][0]["products"][0]["sha256"] == section["products"][0]["sha256"]
    (published / runtime_product_path("playback", "entry", "bed")).write_bytes(b"other media")
    with pytest.raises(ValueError, match="differs from its render"):
        published_playback_description(description, published)


def test_mismatched_encoded_frames_and_missing_layers_fail_at_export(tmp_path):
    compiled, files, _ = encoded(tmp_path)
    files["playback"]["entry"].pop("bed")
    with pytest.raises(ValueError, match="missing"):
        rendered_playback_description(compiled, root=tmp_path, files=files, sample_rate=8000,
            render_fingerprint="id", runtime_stem_gain_mode="native", runtime_gain_db=0,
            adaptive_mastering_mode="composition_master")
    _, files, _ = encoded(tmp_path)
    sf.write(tmp_path / files["playback"]["entry"]["bed"], np.zeros((32, 2)), 8000, format="OGG", subtype="VORBIS")
    with pytest.raises(ValueError, match="expected 24000 frames"):
        rendered_playback_description(compiled, root=tmp_path, files=files, sample_rate=8000,
            render_fingerprint="id", runtime_stem_gain_mode="native", runtime_gain_db=0,
            adaptive_mastering_mode="composition_master")


def test_publisher_installs_the_rebased_playback_facts_with_the_media(tmp_path, monkeypatch):
    generated = tmp_path / "generated"
    _, files, description = encoded(generated)
    manifest = generated / "fixture.adaptive_manifest.json"
    manifest.write_text(json.dumps({"files": files, "music_playback": description}))
    monkeypatch.setattr(cli, "find_latest_manifest", lambda *_: manifest)
    monkeypatch.setattr(cli, "find_full_mix", lambda *_: generated / files["playback"]["entry"]["full"])
    monkeypatch.setattr(cli, "is_adaptive_cue", lambda *_: False)
    assert cli.publish_cue("fixture", generated, tmp_path / "runtime")
    runtime = tmp_path / "runtime" / "fixture"
    result = json.loads((runtime / "fixture.adaptive_manifest.json").read_text())["music_playback"]
    assert result["evidence"] == "published_products"
    for product in result["sections"][0]["products"]:
        assert (runtime / product["path"]).is_file()


def test_inspection_command_uses_the_compiled_plan(tmp_path, capsys):
    import yaml
    source = tmp_path / "fixture.music.yaml"
    source.write_text(yaml.safe_dump(exact()))
    assert cli.main(["cue", "playback", str(source), "--json", "--sample-rate", "8000"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["evidence"] == "score_plan"
    assert report["sections"][0]["frame_plan"]["musical_end_frame"] == 74000
