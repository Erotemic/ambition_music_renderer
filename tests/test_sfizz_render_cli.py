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


class _FakeProc:
    """Just enough of a `Popen` for the backend: a return code and a pid."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.pid = 4242


def _patch_sfizz_calls(monkeypatch, calls, outcome):
    """Record every sfizz argv and answer it with `outcome(cmd, index)`.

    ⛔⛔ THE BACKEND CALLS `Popen`, NOT `run`, and patching `run` is why these
    tests recorded ZERO calls and had been red invisibly. `_render_sfizz_cli`
    grew a heartbeat + timeout wrapper — *"a hung sfizz_render must not run
    forever"* — so it opens the process itself and reads it through
    `communicate_with_heartbeat`. Both halves have to be faked: `Popen` sees the
    ARGV (which is what these tests are about) and the heartbeat returns the
    streams.
    """

    def fake_popen(cmd, **_kwargs):
        calls.append(list(cmd))
        code, stderr = outcome(list(cmd), len(calls))
        if code == 0:
            wav = Path(cmd[cmd.index("--wav") + 1])
            # ⚠ A FULL SECOND, not 64 frames. The backend grew a truncation
            # guard, so a token buffer is now rejected as a short render before
            # any argv assertion below is reached.
            sf.write(wav, np.zeros((48_000, 2), dtype=np.float32), 48000)
        fake_popen.pending = ("", stderr)
        return _FakeProc(code)

    def fake_heartbeat(proc, **_kwargs):
        return fake_popen.pending

    fake_popen.pending = ("", "")
    monkeypatch.setattr(sfizz_backend.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sfizz_backend, "communicate_with_heartbeat", fake_heartbeat)


def _always_succeeds(_cmd, _index):
    return 0, ""


def test_sfizz_cli_uses_documented_samplerate_and_safe_blocksize(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    sfz = tmp_path / "instrument.sfz"
    sfz.write_text("<region> sample=dummy.wav key=60\n")
    monkeypatch.setattr(sfizz_backend.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(sfizz_backend, "sfz_key_span", lambda path: None)
    _patch_sfizz_calls(monkeypatch, calls, _always_succeeds)

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
    _patch_sfizz_calls(monkeypatch, calls, _always_succeeds)

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

    def first_call_rejects_the_rate(_cmd, index):
        if index == 1:
            return 2, "unknown samplerate option"
        return 0, ""

    _patch_sfizz_calls(monkeypatch, calls, first_call_rejects_the_rate)

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
