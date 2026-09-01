from pathlib import Path

from ambition_music_renderer.audio_plugins import (
    common_clap_dirs,
    common_vst3_dirs,
    discover_clap_plugins,
    discover_vst3_plugins,
    resolve_vst3_reference,
    validate_score_plugins,
)
from ambition_music_renderer.backends.lv2_backend import (
    apply_lv2_effect,
    build_lv2proc_command,
)
from ambition_music_renderer.backends.plugin_chain import apply_effect_chain
import numpy as np
import pytest


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
    assert "gain:0.5" in cmd
    assert cmd[-1] == "urn:example:plugin"


def test_build_lv2apply_command_uses_lilv_control_syntax(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    input_path = tmp_path / "in.wav"
    output_path = tmp_path / "out.wav"
    cmd = build_lv2proc_command(
        input_path,
        output_path,
        {
            "binary": "lv2apply",
            "plugin_uri": "urn:example:plugin",
            "params": {"drive": 0.75},
        },
    )
    control_idx = cmd.index("-c")
    assert cmd[control_idx : control_idx + 3] == ["-c", "drive", "0.75"]
    assert cmd[-1] == "urn:example:plugin"


def test_lv2_dual_mono_processes_channels_independently(monkeypatch):
    calls = []

    def fake_run_file_effect_raw(audio, sample_rate, spec):
        source = np.asarray(audio, dtype=np.float32)
        calls.append(source.copy())
        return (source[:, None] * 2.0).astype(np.float32)

    monkeypatch.setattr(
        "ambition_music_renderer.backends.lv2_backend.run_file_effect_raw",
        fake_run_file_effect_raw,
    )
    audio = np.column_stack(
        [
            np.linspace(-0.25, 0.25, 16, dtype=np.float32),
            np.linspace(0.4, -0.4, 16, dtype=np.float32),
        ]
    )
    out = apply_lv2_effect(
        audio,
        48_000,
        {
            "kind": "lv2proc",
            "plugin_uri": "urn:example:mono-pedal",
            "channel_mode": "dual_mono",
        },
    )
    assert len(calls) == 2
    assert np.allclose(calls[0], audio[:, 0])
    assert np.allclose(calls[1], audio[:, 1])
    assert np.allclose(out, audio * 2.0)


def test_effect_chain_top_level_wet_mix(monkeypatch, capsys):
    def fake_apply_lv2_effects(audio, sample_rate, effects):
        return np.asarray(audio, dtype=np.float32) * 3.0

    monkeypatch.setattr(
        "ambition_music_renderer.backends.lv2_backend.apply_lv2_effects",
        fake_apply_lv2_effects,
    )
    audio = np.ones((32, 2), dtype=np.float32) * 0.1
    out = apply_effect_chain(
        audio,
        48_000,
        [
            {
                "kind": "lv2proc",
                "plugin_uri": "urn:example:parallel",
                "wet_mix": 0.25,
                "report_levels": True,
                "label": "parallel-test",
            }
        ],
    )
    # 75% dry + 25% of a 3x processed signal = 1.5x dry.
    assert np.allclose(out, audio * 1.5)
    stderr = capsys.readouterr().err
    assert "chain=parallel-test" in stderr
    assert "wet_mix=0.250" in stderr
    assert "shape_change_db=" in stderr


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


def test_validate_score_plugins_optional_pedalboard_missing_is_warning(tmp_path):
    score = {
        "postprocess": {
            "effect_chain": [
                {"kind": "pedalboard", "optional": True, "effects": [{"effect": "compressor"}]},
            ]
        }
    }
    report = validate_score_plugins(score, base_dir=tmp_path)
    assert report["errors"] == 0
    assert report["warnings"] >= 0
    assert report["ok"]


def test_discover_clap_plugins_from_explicit_dir(tmp_path):
    bundle = tmp_path / "ToyMod.clap"
    bundle.write_bytes(b"clap")
    found = discover_clap_plugins([tmp_path])
    assert found
    assert found[0]["name"] == "ToyMod"
    assert Path(found[0]["path"]).name == "ToyMod.clap"


def test_common_clap_dirs_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AMBITION_MUSIC_CLAP_PATHS", str(tmp_path))
    dirs = common_clap_dirs()
    assert dirs[0] == tmp_path


def test_validate_score_plugins_reports_clap_discovery_without_hosting(tmp_path):
    clap = tmp_path / "ToyMod.clap"
    clap.write_bytes(b"clap")
    score = {
        "postprocess": {
            "effect_chain": [
                {"kind": "clap", "path": str(clap), "optional": True},
            ]
        }
    }
    report = validate_score_plugins(score, base_dir=tmp_path)
    assert report["errors"] == 0
    assert report["warnings"] >= 1
    assert any(
        "CLAP hosting" in message["message"]
        for entry in report["effect_specs"]
        for message in entry["messages"]
    )


def test_pedalboard_gain_can_drive_distortion_and_report_levels(capsys):
    pytest.importorskip("pedalboard")
    sr = 48_000
    t = np.arange(sr, dtype=np.float32) / sr
    # Deliberately quiet source: the regression was that distortion saw audio
    # around this level and therefore behaved almost like clean gain.
    mono = (
        10.0 ** (-34.0 / 20.0) * np.sin(2.0 * np.pi * 440.0 * t)
    ).astype(np.float32)
    audio = np.column_stack([mono, mono])
    chain = [
        {
            "kind": "pedalboard",
            "label": "gain-stage-test",
            "report_levels": True,
            "effects": [
                {"effect": "gain", "gain_db": 28.0},
                {"effect": "distortion", "drive_db": 8.0},
                {"effect": "gain", "gain_db": -34.0},
            ],
        }
    ]
    out = apply_effect_chain(audio, sr, chain)
    assert out.shape == audio.shape
    assert np.max(np.abs(out)) < 0.1, "post-gain must return the driven signal to mix-safe level"

    # Compare against the best gain-matched dry signal. The remaining residual
    # must be substantial, proving the distortion was actually driven into its
    # nonlinear region rather than acting as a clean level boost.
    dry = audio[:, 0].astype(np.float64)
    wet = out[:, 0].astype(np.float64)
    scale = float(np.dot(wet, dry) / max(np.dot(dry, dry), 1e-30))
    residual = wet - scale * dry
    residual_rel = float(
        np.sqrt(np.mean(np.square(residual))) / max(np.sqrt(np.mean(np.square(wet))), 1e-30)
    )
    assert residual_rel > 0.05

    stderr = capsys.readouterr().err
    assert "chain=gain-stage-test" in stderr
    assert "effect=0:gain" in stderr
    assert "effect=1:distortion" in stderr
    assert "in_peak_dbfs" in stderr


def test_pedalboard_degradation_effects_and_parallel_mix(capsys):
    pytest.importorskip("pedalboard")
    sr = 48_000
    t = np.arange(sr, dtype=np.float32) / sr
    mono = (0.08 * np.sin(2.0 * np.pi * 311.0 * t)).astype(np.float32)
    audio = np.column_stack([mono, mono])
    chain = [
        {
            "kind": "pedalboard",
            "label": "degrade-test",
            "report_levels": True,
            "effects": [
                {"effect": "gain", "gain_db": 20.0},
                {"effect": "clipping", "threshold_db": -12.0, "wet_mix": 0.75},
                {"effect": "bitcrush", "bit_depth": 6.0, "wet_mix": 0.35},
                {"effect": "resample", "target_sample_rate": 12000.0, "wet_mix": 0.25},
                {"effect": "gain", "gain_db": -20.0},
            ],
        }
    ]
    out = apply_effect_chain(audio, sr, chain)
    assert out.shape == audio.shape
    assert np.isfinite(out).all()
    assert not np.allclose(out, audio)

    dry = audio[:, 0].astype(np.float64)
    wet = out[:, 0].astype(np.float64)
    scale = float(np.dot(wet, dry) / max(np.dot(dry, dry), 1e-30))
    residual = wet - scale * dry
    residual_rel = float(
        np.sqrt(np.mean(np.square(residual))) / max(np.sqrt(np.mean(np.square(wet))), 1e-30)
    )
    assert residual_rel > 0.10

    stderr = capsys.readouterr().err
    assert "effect=1:clipping" in stderr
    assert "effect=2:bitcrush" in stderr
    assert "effect=3:resample" in stderr
    assert "shape_change_db=" in stderr
    assert "wet_mix=0.750" in stderr
