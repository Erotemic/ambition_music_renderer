from pathlib import Path

import numpy as np
import pytest

from ambition_music_renderer.audit.sfz_smoke import (
    SmokeCandidate,
    _estimate_pitch,
    inspect_sfz,
    run_sfz_smoke,
)


def test_inspect_sfz_follows_program_root_includes_and_samples(tmp_path: Path):
    program = tmp_path / "Programs" / "kit.sfz"
    include = tmp_path / "Programs" / "Data" / "map.txt"
    sample = tmp_path / "Programs" / "Samples" / "kick.wav"
    include.parent.mkdir(parents=True)
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"sample")
    include.write_text("<region> key=36 sample=../Samples/kick.wav\nset_cc7=100\n")
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_text('#include "Data/map.txt"\n')

    report = inspect_sfz(program)
    assert report["files_read"] == 2
    assert report["missing_samples"] == []
    assert report["startup_cc"] == {"7": 100}


def test_sfz_smoke_reports_unresolved_without_rendering(tmp_path: Path):
    candidate = SmokeCandidate("missing", path="does-not-exist.sfz", probes=(60,))
    report = run_sfz_smoke(roots=[tmp_path], candidates=[candidate])
    assert report["candidate_count"] == 1
    assert report["ok_count"] == 0
    assert report["rows"][0]["status"] == "UNRESOLVED"


def test_pitch_estimator_returns_a_reasonable_fundamental():
    sample_rate = 24000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    audio = (0.5 * np.sin(2 * np.pi * 220 * time))[:, None]
    midi, cents = _estimate_pitch(audio, sample_rate, 57)
    assert midi is not None and cents is not None
    assert abs(midi - 57) < 0.15
    assert abs(cents) < 15


def test_pitch_diagnostic_anchors_harmonic_rich_signal_to_expected_note():
    from ambition_music_renderer.audit.sfz_smoke import _pitch_diagnostic

    sample_rate = 24000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    # The second harmonic is intentionally louder than the fundamental, which
    # is the failure mode that made the former free-running estimator lie about
    # guitar and bass pitch.
    audio = (
        0.10 * np.sin(2 * np.pi * 220 * time)
        + 0.80 * np.sin(2 * np.pi * 440 * time)
        + 0.50 * np.sin(2 * np.pi * 660 * time)
    )[:, None]
    result = _pitch_diagnostic(audio, sample_rate, 57)
    assert abs(result["pitch_error_cents"]) < 15
    assert result["pitch_status"] == "reliable"
    assert result["pitch_confidence"] > 0


def test_sfz_smoke_skips_out_of_range_without_failing_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ambition_music_renderer.audit import sfz_smoke

    sfz = tmp_path / "kit.sfz"
    sfz.write_text("<region> lokey=36 hikey=46 sample=hit.wav\n")

    def fake_render(pm, **_kwargs):
        return np.ones((4000, 2), dtype=np.float32) * 0.1

    monkeypatch.setattr(sfz_smoke, "render_sfizz", fake_render)
    candidate = SmokeCandidate("kit", path="kit.sfz", probes=(42, 49), pitch_probe=False)
    report = run_sfz_smoke(roots=[tmp_path], candidates=[candidate], sample_rate=1000)
    row = report["rows"][0]
    assert row["status"] == "ok"
    assert row["probes"][1]["status"] == "OUT_OF_RANGE"
    assert row["probes"][1]["skipped"] is True
    assert report["ok_count"] == 1
