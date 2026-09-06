from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest

from ambition_music_renderer.processing.catalog import (
    canonical_pedalboard_effect_name,
    canonical_processor_name,
    inspector_templates,
    processor_names,
)
from ambition_music_renderer.processing.legacy import legacy_postprocess_chain, legacy_processing_plan
from ambition_music_renderer.processing.mastering import (
    COMPOSITION_MASTER,
    LEGACY_SECTION_POSTPROCESS,
    adaptive_full_mix,
    apply_section_bus_processing,
    master_composition,
    mastering_policy,
)
from ambition_music_renderer.processing.pipeline import apply_processing_plan
from ambition_music_renderer.processing.plans import processing_plan_for_group, processing_plan_for_master
from ambition_music_renderer.render.effects import post_process
from ambition_music_renderer.validation.diagnostics import MusicIRValidationError
from ambition_music_renderer.validation.musicir import validate_musicir_spec


def _audio_fixture():
    sr = 24_000
    rng = np.random.default_rng(42)
    t = np.arange(sr) / sr
    base = (
        0.12 * np.sin(2 * np.pi * 220 * t)
        + 0.03 * np.sin(2 * np.pi * 3500 * t)
        + 0.005 * rng.standard_normal(sr)
    ).astype("float32")
    return sr, np.column_stack([base, np.roll(base, 7)]).astype("float32")


# Frozen against the pre-Phase-5 implementation. These contracts make an
# accidental change to legacy v1/v2 processing audible in tests before a user
# discovers it while regenerating assets.
LEGACY_PCM_SHA256 = {
    "default": "e7f2bd8fe5d2da86754568c653251d8a07bbc3165ef16bef5626a7053a92db92",
    "stem": "f2dca6b255e92ea45c22d613488635a7fe401c1633690a7fd9df1b513a37d446",
    "complex": "3c90833d7dfea18766fc6ecef529625103936c5f18594c2c240b2986af6b91bb",
    "no_room_no_limit": "e132329d5ec54c2209d2a0be12c4b1c3f9189d24f2e7000ea340c117da2e262b",
}


def _legacy_cases():
    return {
        "default": {},
        "stem": {"normalize": False, "target_peak_db": -2.5},
        "complex": {
            "gain_db": -1.5,
            "highpass_hz": 90,
            "transient_tame": 0.22,
            "transient_lowpass_hz": 5500,
            "presence_db": 1.2,
            "presence_low_hz": 1800,
            "presence_high_hz": 3900,
            "high_shelf_db": -0.8,
            "high_shelf_hz": 5000,
            "eq_bands": [{"hz": 700, "db": -1.2, "q": 1.1}],
            "lowpass_hz": 10000,
            "compressor_threshold_db": -20,
            "compressor_ratio": 2.5,
            "compressor_attack_ms": 8,
            "compressor_release_ms": 90,
            "compressor_makeup_db": 0.7,
            "compressor_knee_db": 5,
            "reverb_wet": 0.08,
            "reverb_decay_seconds": 0.7,
            "reverb_damping_hz": 4800,
            "post_reverb_high_shelf_db": -0.5,
            "post_reverb_high_shelf_hz": 5200,
            "stereo_width": 0.06,
            "target_peak_db": -1.2,
            "limiter_drive": 1.04,
            "normalize": True,
        },
        "no_room_no_limit": {
            "reverb_enabled": False,
            "stereo_width": 0.0,
            "limiter_enabled": False,
            "gain_db": 2.0,
        },
    }


@pytest.mark.parametrize("name", sorted(LEGACY_PCM_SHA256))
def test_legacy_postprocess_pcm_contract(name):
    sr, audio = _audio_fixture()
    out = post_process(audio, sr, _legacy_cases()[name])
    assert hashlib.sha256(out.tobytes()).hexdigest() == LEGACY_PCM_SHA256[name]


def test_postprocess_facade_and_processing_plan_are_exactly_equal():
    sr, audio = _audio_fixture()
    settings = _legacy_cases()["complex"]
    via_facade = post_process(audio, sr, settings)
    plan = legacy_processing_plan(settings, stage="test")
    via_plan = apply_processing_plan(audio, sr, plan)
    assert np.array_equal(via_facade, via_plan)


def test_legacy_translation_preserves_operation_order_and_hidden_defaults():
    names = [row["processor"] for row in legacy_postprocess_chain({})]
    assert names == ["reverb", "stereo_width", "limiter"]
    names = [row["processor"] for row in legacy_postprocess_chain({"reverb_enabled": False, "stereo_width": 0, "limiter_enabled": False})]
    assert names == []


def test_processing_catalog_is_the_alias_authority():
    assert canonical_processor_name("pb") == "pedalboard"
    assert canonical_processor_name("guitarix") == "command"
    assert canonical_processor_name("nam_lv2") == "lv2"
    assert canonical_pedalboard_effect_name("drive") == "distortion"
    assert "compressor" in processor_names()
    templates = inspector_templates()
    assert templates["Reverb"]["processor"] == "pedalboard"


def test_canonical_group_and_master_plans_do_not_mix_with_legacy_settings():
    spec = {
        "schema": "ambition.musicir.v3",
        "stem_postprocess": {"gain_db": 99},
        "postprocess": {"gain_db": 99},
        "processing": {
            "stems": {"chain": [{"processor": "gain", "gain_db": -3}]},
            "groups": {"lead": {"chain": [{"processor": "highpass", "cutoff_hz": 90}]}},
            "master": {"chain": [{"processor": "limiter", "target_peak_db": -1, "drive": 1.0, "normalize": False}]},
        },
    }
    group = processing_plan_for_group(spec, "lead")
    assert [op.processor for op in group.operations] == ["gain", "highpass"]
    assert group.operations[0].parameters["gain_db"] == -3
    master = processing_plan_for_master(spec)
    assert [op.processor for op in master.operations] == ["limiter"]


def test_mastering_policy_preserves_legacy_and_defaults_new_v3_to_one_master():
    assert mastering_policy({"schema": "ambition.musicir.v1"}).mode == LEGACY_SECTION_POSTPROCESS
    assert mastering_policy({"schema": "ambition.musicir.v2"}).mode == LEGACY_SECTION_POSTPROCESS
    assert mastering_policy({"schema": "ambition.musicir.v3"}).mode == COMPOSITION_MASTER
    old_global = mastering_policy({"schema": "ambition.musicir.v1", "render": {"adaptive_section_mastering": {"mode": "global_master_slices"}}})
    assert old_global.mode == COMPOSITION_MASTER
    assert old_global.authored_mode == "global_master_slices"


def test_composition_master_sections_are_literal_slices_of_one_master():
    sr, raw = _audio_fixture()
    raw = np.vstack([raw, raw])
    sections = [
        {"id": "a", "start_seconds": 0.0, "end_seconds": 1.0},
        {"id": "b", "start_seconds": 1.0, "end_seconds": 2.0},
    ]
    spec = {
        "schema": "ambition.musicir.v3",
        "processing": {"master": {"chain": [{"processor": "gain", "gain_db": -2.0}]}},
        # A legacy block must not create a second master in the v3 policy.
        "sections": [{"id": "a", "postprocess": {"gain_db": 18.0}}, {"id": "b"}],
    }
    master, _ = master_composition(raw, sr, spec)
    a, detail = adaptive_full_mix(mastered_timeline=master, pre_master_timeline=raw, sample_rate=sr, spec=spec, section=sections[0])
    assert np.array_equal(a, master[:sr])
    assert detail["mode"] == COMPOSITION_MASTER
    assert detail["section_postprocess_ignored"] is True


def test_legacy_section_mastering_matches_historical_merge_semantics():
    sr, raw = _audio_fixture()
    raw = np.vstack([raw, raw])
    spec = {
        "schema": "ambition.musicir.v1",
        "postprocess": {"gain_db": -1.0, "reverb_enabled": False, "stereo_width": 0.0, "limiter_enabled": False},
        "sections": [{"id": "a", "postprocess": {"gain_db": 2.0}}, {"id": "b"}],
    }
    master, _ = master_composition(raw, sr, spec)
    section = {"id": "a", "start_seconds": 0.0, "end_seconds": 1.0}
    got, detail = adaptive_full_mix(mastered_timeline=master, pre_master_timeline=raw, sample_rate=sr, spec=spec, section=section)
    expected = post_process(raw[:sr], sr, {"gain_db": 2.0, "reverb_enabled": False, "stereo_width": 0.0, "limiter_enabled": False, "normalize": True, "target_peak_db": -1.2})
    assert np.array_equal(got, expected)
    assert detail["mode"] == LEGACY_SECTION_POSTPROCESS


def test_canonical_section_processing_occurs_before_master():
    sr = 1000
    raw = np.ones((2000, 2), dtype=np.float32) * 0.1
    sections = [
        {"id": "intro", "start_seconds": 0.0, "end_seconds": 1.0},
        {"id": "loop", "start_seconds": 1.0, "end_seconds": 2.0},
    ]
    spec = {
        "schema": "ambition.musicir.v3",
        "processing": {
            "sections": {"intro": {"chain": [{"processor": "gain", "gain_db": -6.020599913279624}]}},
            "master": {"chain": [{"processor": "gain", "gain_db": 6.020599913279624}]},
        },
    }
    premaster, applied = apply_section_bus_processing(raw, sr, spec, sections)
    assert applied.keys() == {"intro"}
    assert np.allclose(premaster[:sr], 0.05, atol=1e-6)
    assert np.allclose(premaster[sr:], 0.1, atol=1e-6)
    mastered, _ = master_composition(premaster, sr, spec)
    assert np.allclose(mastered[:sr], 0.1, atol=1e-6)
    assert np.allclose(mastered[sr:], 0.2, atol=1e-6)


def _minimal_v3():
    return {
        "schema": "ambition.musicir.v3",
        "id": "processing_validation",
        "timebase": {"ppq": 480},
        "meter": "4/4",
        "tempo": 120,
        "end": {"bar": 2, "beat": 1},
        "instruments": [{"name": "keys", "group": "music", "program": "acoustic_grand_piano"}],
        "parts": [{"id": "part", "instrument": "keys", "voices": [{"id": "voice", "clips": [{"id": "note", "at": {"bar": 1, "beat": 1}, "events": [[0, "1/4", "C4", 90]]}]}]}],
    }


def test_v3_processing_validation_uses_registry_names_and_ranges():
    spec = _minimal_v3()
    spec["processing"] = {
        "master": {
            "chain": [
                {"processor": "compresor", "threshold_db": -20},
                {"processor": "reverb", "wet": 4.0},
            ]
        }
    }
    with pytest.raises(MusicIRValidationError) as info:
        validate_musicir_spec(spec)
    by_code = {d.code: d for d in info.value.diagnostics}
    assert by_code["V3_PROCESSOR_NAME"].hint == "did you mean `compressor`?"
    assert "V3_PROCESSOR_PARAMETER" in by_code


def test_processing_catalog_has_dependency_free_source_reader():
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    reader = repo_root / "dev" / "read_processing_catalog.py"
    result = subprocess.run(
        [sys.executable, "-S", str(reader), "list"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout
    for name in ("compressor", "reverb", "limiter", "pedalboard", "vst3", "lv2", "command"):
        assert name in output
