"""Regression tests for deterministic sfizz_render termination."""

from __future__ import annotations

import subprocess
from pathlib import Path

import mido
import numpy as np
import pretty_midi
import soundfile as sf

from ambition_music_renderer.backends import sfizz_backend as sb


def _one_note_pm() -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0, resolution=960)
    inst = pretty_midi.Instrument(program=0, name="piano")
    inst.notes.append(
        pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.25)
    )
    pm.instruments.append(inst)
    return pm


def test_bound_midi_end_of_track_moves_all_tracks_to_requested_time(tmp_path: Path):
    pm = _one_note_pm()
    midi_path = tmp_path / "bounded.mid"
    pm.write(str(midi_path))

    sb._bound_midi_end_of_track(midi_path, pm, end_time_s=1.5)

    mid = mido.MidiFile(str(midi_path))
    expected_tick = int(pm.time_to_tick(1.5))
    assert mid.tracks
    for track in mid.tracks:
        absolute_tick = 0
        eot_ticks = []
        for msg in track:
            absolute_tick += int(msg.time)
            if msg.type == "end_of_track":
                eot_ticks.append(absolute_tick)
        assert eot_ticks == [expected_tick]


def test_sfizz_cli_uses_bounded_eot_by_default(tmp_path: Path, monkeypatch):
    pm = _one_note_pm()
    sfz_path = tmp_path / "piano.sfz"
    sfz_path.write_text("<region> sample=*sine key=60\n")
    calls: list[list[str]] = []

    monkeypatch.setattr(sb.shutil, "which", lambda _binary: "/usr/bin/sfizz_render")

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.args = cmd
            self.returncode = None
            self.pid = 12345
            calls.append(list(cmd))

        def communicate(self, timeout=None):
            wav_path = Path(self.args[self.args.index("--wav") + 1])
            sf.write(wav_path, np.zeros((int(1.6 * 48000), 2), dtype=np.float32), 48000)
            self.returncode = 0
            return "", ""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(sb.subprocess, "Popen", FakePopen)

    audio = sb._render_sfizz_cli(
        pm,
        sfz=sfz_path,
        sample_rate=48000,
        tempdir=tmp_path,
        output_name="bounded",
        minimum_duration=1.0,
        settings={"eot_padding_seconds": 0.5},
    )

    assert calls
    assert "--use-eot" in calls[0]
    assert calls[0][calls[0].index("--blocksize") + 1] == "1024"
    assert len(audio) >= 48000

    midi_path = tmp_path / "bounded.sfizz.mid"
    mid = mido.MidiFile(str(midi_path))
    expected_tick = int(pm.time_to_tick(0.75))
    for track in mid.tracks:
        assert sum(int(msg.time) for msg in track) == expected_tick
        assert track[-1].type == "end_of_track"


def test_sfizz_cli_rejects_truncated_successful_wav(tmp_path: Path, monkeypatch):
    pm = _one_note_pm()
    sfz_path = tmp_path / "piano.sfz"
    sfz_path.write_text("<region> sample=*sine key=60\n")
    monkeypatch.setattr(sb.shutil, "which", lambda _binary: "/usr/bin/sfizz_render")

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.args = cmd
            self.returncode = None
            self.pid = 12346

        def communicate(self, timeout=None):
            wav_path = Path(self.args[self.args.index("--wav") + 1])
            sf.write(wav_path, np.zeros((int(0.1 * 48000), 2), dtype=np.float32), 48000)
            self.returncode = 0
            return "", ""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(sb.subprocess, "Popen", FakePopen)

    try:
        sb._render_sfizz_cli(
            pm,
            sfz=sfz_path,
            sample_rate=48000,
            tempdir=tmp_path,
            output_name="truncated",
            minimum_duration=1.0,
            settings={},
        )
    except RuntimeError as ex:
        assert "truncated WAV" in str(ex)
        assert "content_end=0.250" in str(ex)
    else:
        raise AssertionError("a WAV shorter than the instrument's own MIDI content must be rejected")


def test_sfizz_cli_accepts_sparse_instrument_and_pads_to_mix_duration(tmp_path: Path, monkeypatch):
    pm = _one_note_pm()
    sfz_path = tmp_path / "sparse.sfz"
    sfz_path.write_text("<region> sample=*sine key=60\n")
    monkeypatch.setattr(sb.shutil, "which", lambda _binary: "/usr/bin/sfizz_render")

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.args = cmd
            self.returncode = None
            self.pid = 12347

        def communicate(self, timeout=None):
            wav_path = Path(self.args[self.args.index("--wav") + 1])
            sf.write(wav_path, np.zeros((int(0.30 * 48000), 2), dtype=np.float32), 48000)
            self.returncode = 0
            return "", ""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(sb.subprocess, "Popen", FakePopen)
    audio = sb._render_sfizz_cli(
        pm, sfz=sfz_path, sample_rate=48000, tempdir=tmp_path,
        output_name="sparse", minimum_duration=1.0, settings={},
    )
    assert len(audio) == 48000


def test_sfizz_cli_retries_reported_larger_callback_buffer(tmp_path: Path, monkeypatch):
    pm = _one_note_pm()
    sfz_path = tmp_path / "adaptive.sfz"
    sfz_path.write_text("<region> sample=*sine key=60\n")
    monkeypatch.setattr(sb.shutil, "which", lambda _binary: "/usr/bin/sfizz_render")
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.args = cmd
            self.returncode = None
            self.pid = 12348 + len(calls)
            calls.append(list(cmd))

        def communicate(self, timeout=None):
            wav_path = Path(self.args[self.args.index("--wav") + 1])
            sf.write(wav_path, np.zeros((int(0.30 * 48000), 2), dtype=np.float32), 48000)
            self.returncode = 0
            block = int(self.args[self.args.index("--blocksize") + 1])
            if block == 1024:
                return "", (
                    "[sfizz] Someone asked for a buffer of size 2048; only 1024 available...\n"
                    "[sfizz] Could not get a temporary buffer; exiting callback..."
                )
            return "", ""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(sb.subprocess, "Popen", FakePopen)
    audio = sb._render_sfizz_cli(
        pm, sfz=sfz_path, sample_rate=48000, tempdir=tmp_path,
        output_name="adaptive", minimum_duration=1.0, settings={},
    )
    assert len(audio) == 48000
    assert len(calls) == 2
    assert calls[0][calls[0].index("--blocksize") + 1] == "1024"
    assert calls[1][calls[1].index("--blocksize") + 1] == "2048"
