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


def test_sfz_smoke_marks_pitch_uncertainty_separately_from_renderability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ambition_music_renderer.audit import sfz_smoke

    sfz = tmp_path / "bass.sfz"
    sfz.write_text("<region> lokey=36 hikey=36 sample=note.wav\n")

    monkeypatch.setattr(
        sfz_smoke,
        "render_sfizz",
        lambda *_args, **_kwargs: np.ones((4000, 2), dtype=np.float32) * 0.1,
    )
    monkeypatch.setattr(
        sfz_smoke,
        "_pitch_diagnostic",
        lambda *_args, **_kwargs: {
            "estimated_midi": 24.0,
            "pitch_error_cents": -1200.0,
            "pitch_confidence": 0.9,
            "pitch_unreliable": True,
            "pitch_status": "unreliable",
        },
    )
    candidate = SmokeCandidate("bass", path="bass.sfz", probes=(36,))
    report = run_sfz_smoke(roots=[tmp_path], candidates=[candidate], sample_rate=1000)
    row = report["rows"][0]
    assert row["status"] == "ok"
    assert row["render_status"] == "ok"
    assert row["validation_status"] == "PITCH_UNRELIABLE"
    assert report["ok_count"] == 1
    assert report["validated_count"] == 0


def test_resolve_candidate_forwards_alias_preferences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ambition_music_renderer.audit import sfz_smoke

    expected = tmp_path / "chosen.sfz"
    expected.write_text("")
    observed = {}

    def fake_resolve(*, library_ref, prefer, roots):
        observed.update(library_ref=library_ref, prefer=tuple(prefer), roots=list(roots))
        return expected

    monkeypatch.setattr(sfz_smoke, "resolve_sfz_reference", fake_resolve)
    candidate = SmokeCandidate(
        "alias", library_ref="guitar.test", prefer=("chords", "wide"), probes=(60,)
    )
    assert sfz_smoke._resolve_candidate(candidate, [tmp_path]) == expected
    assert observed["library_ref"] == "guitar.test"
    assert observed["prefer"] == ("chords", "wide")


def test_dedicated_guitar_programs_do_not_claim_keyswitch_probes():
    from ambition_music_renderer.audit.sfz_smoke import CANDIDATES

    by_name = {candidate.name: candidate for candidate in CANDIDATES}
    assert by_name["blackgreen_twang"].keyswitch_probes == ()
    assert by_name["blackgreen_staccato"].keyswitch_probes == ()
    assert by_name["shiny_electric"].probes == (37, 52, 64, 76)
