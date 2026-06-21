from pathlib import Path

from ambition_music_renderer.audio_plugins import (
    common_vst3_dirs,
    discover_vst3_plugins,
    resolve_vst3_reference,
    validate_score_plugins,
)
from ambition_music_renderer.backends.lv2_backend import build_lv2proc_command
from ambition_music_renderer.backends.plugin_chain import apply_effect_chain
import numpy as np


def test_discover_vst3_plugins_from_explicit_dir(tmp_path):
    bundle = tmp_path / "ToyAmp.vst3"
    bundle.mkdir()
    found = discover_vst3_plugins([tmp_path])
    assert found
    assert found[0]["name"] == "ToyAmp"
    assert Path(found[0]["path"]).name == "ToyAmp.vst3"


def test_resolve_vst3_relative_path(tmp_path):
    bundle = tmp_path / "LocalAmp.vst3"
    bundle.mkdir()
    resolved = resolve_vst3_reference("LocalAmp.vst3", base_dir=tmp_path)
    assert resolved == bundle.resolve()


def test_common_vst3_dirs_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AMBITION_MUSIC_VST3_PATHS", str(tmp_path))
    dirs = common_vst3_dirs()
    assert dirs[0] == tmp_path


def test_validate_score_plugins_reports_missing_vst(tmp_path):
    score = {
        "postprocess": {
            "effect_chain": [
                {"kind": "vst3", "path": "missing.vst3"},
            ]
        }
    }
    report = validate_score_plugins(score, base_dir=tmp_path)
    assert report["effect_spec_count"] == 1
    assert report["errors"] >= 1
    assert not report["ok"]


def test_validate_score_plugins_accepts_existing_command(tmp_path):
    score = {
        "group_postprocess": {
            "guitars": {
                "effect_chain": [
                    {"kind": "command", "command": ["python", "-c", "pass"]},
                ]
            }
        }
    }
    report = validate_score_plugins(score, base_dir=tmp_path)
    assert report["effect_spec_count"] == 1
    assert report["errors"] == 0


def test_build_lv2proc_command_requires_uri(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    input_path = tmp_path / "in.wav"
    output_path = tmp_path / "out.wav"
    cmd = build_lv2proc_command(
        input_path,
        output_path,
        {"plugin_uri": "urn:example:plugin", "params": {"gain": 0.5}},
    )
    assert cmd[:4] == ["lv2proc", "-i", str(input_path), "-o"]
    assert "gain=0.5" in cmd
    assert cmd[-1] == "urn:example:plugin"


def test_empty_effect_chain_is_identity():
    audio = np.zeros((16, 2), dtype=np.float32)
    out = apply_effect_chain(audio, 48000, [])
    assert out.shape == audio.shape
    assert np.allclose(out, audio)


def test_validate_score_plugins_sees_nested_pedalboard_vst(tmp_path):
    score = {
        "postprocess": {
            "effect_chain": [
                {
                    "kind": "pedalboard",
                    "effects": [
                        {"effect": "vst3", "path": "missing.vst3"},
                    ],
                }
            ]
        }
    }
    report = validate_score_plugins(score, base_dir=tmp_path)
    assert report["effect_spec_count"] == 2
    assert report["errors"] >= 1
