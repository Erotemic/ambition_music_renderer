from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pretty_midi
import soundfile as sf

from ambition_music_renderer.backends import sfizz_backend


def _minimal_pm() -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120, resolution=960)
    inst = pretty_midi.Instrument(program=0, name="piano")
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=0.25))
    pm.instruments.append(inst)
    return pm


def _fake_successful_run(calls: list[list[str]]):
    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        wav = Path(cmd[cmd.index("--wav") + 1])
        sf.write(wav, np.zeros((64, 2), dtype=np.float32), 48000)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_run


def test_sfizz_cli_uses_documented_samplerate_and_safe_blocksize(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    sfz = tmp_path / "instrument.sfz"
    sfz.write_text("<region> sample=dummy.wav key=60\n")
    monkeypatch.setattr(sfizz_backend.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(sfizz_backend, "sfz_key_span", lambda path: None)
    monkeypatch.setattr(sfizz_backend.subprocess, "run", _fake_successful_run(calls))

    sfizz_backend._render_sfizz_cli(
        _minimal_pm(),
        sfz=sfz,
        sample_rate=48000,
        tempdir=tmp_path,
        output_name="probe",
        minimum_duration=0.0,
        settings={},
    )

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[cmd.index("--samplerate") + 1] == "48000"
    assert cmd[cmd.index("--blocksize") + 1] == "1024"
    assert "--sample-rate" not in cmd


def test_sfizz_cli_blocksize_is_configurable(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    sfz = tmp_path / "instrument.sfz"
    sfz.write_text("<region> sample=dummy.wav key=60\n")
    monkeypatch.setattr(sfizz_backend.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(sfizz_backend, "sfz_key_span", lambda path: None)
    monkeypatch.setattr(sfizz_backend.subprocess, "run", _fake_successful_run(calls))

    sfizz_backend._render_sfizz_cli(
        _minimal_pm(),
        sfz=sfz,
        sample_rate=48000,
        tempdir=tmp_path,
        output_name="probe",
        minimum_duration=0.0,
        settings={"block_size": 512},
    )

    cmd = calls[0]
    assert cmd[cmd.index("--blocksize") + 1] == "512"


def test_sfizz_cli_rate_probe_falls_back_without_dropping_blocksize(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    sfz = tmp_path / "instrument.sfz"
    sfz.write_text("<region> sample=dummy.wav key=60\n")
    monkeypatch.setattr(sfizz_backend.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(sfizz_backend, "sfz_key_span", lambda path: None)

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="unknown samplerate option")
        wav = Path(cmd[cmd.index("--wav") + 1])
        sf.write(wav, np.zeros((64, 2), dtype=np.float32), 48000)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(sfizz_backend.subprocess, "run", fake_run)

    sfizz_backend._render_sfizz_cli(
        _minimal_pm(),
        sfz=sfz,
        sample_rate=48000,
        tempdir=tmp_path,
        output_name="probe",
        minimum_duration=0.0,
        settings={},
    )

    assert len(calls) == 2
    first, second = calls
    assert "--samplerate" in first
    assert first[first.index("--blocksize") + 1] == "1024"
    assert "--samplerate" not in second
    assert second[second.index("--blocksize") + 1] == "1024"
