"""Regression tests for the first renderer correctness audit overlay."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def _minimal_spec(layer: dict) -> dict:
    return {
        "id": "audit_test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {
                "name": "keys",
                "program": "acoustic_grand_piano",
                "group": "keys",
            }
        ],
        "sections": [
            {
                "id": "main",
                "bars": 4,
                "harmony": ["C", "Dm", "Em", "F"],
                "layers": [layer],
            }
        ],
    }


def test_pad_chords_preserves_fractional_every_bars():
    from ambition_music_renderer.render.score_layers import build_score

    pm, _groups, _sections = build_score(
        _minimal_spec(
            {
                "kind": "pad_chords",
                "instrument": "keys",
                "every_bars": 1.5,
                "duration_beats": 0.5,
            }
        )
    )
    starts = sorted(
        {
            event["nominal_bar"]
            for event in pm._ambition_note_events  # type: ignore[attr-defined]
        }
    )
    assert starts == [0.0, 1.5, 3.0]


def test_unknown_instrument_group_fails_instead_of_rendering_silence():
    from ambition_music_renderer.render.score_layers import build_score

    with pytest.raises(KeyError, match="unknown or empty instrument group 'keyz'"):
        build_score(_minimal_spec({"kind": "pad_chords", "group": "keyz"}))


def test_nonpositive_ostinato_rhythm_fails_instead_of_looping_forever():
    from ambition_music_renderer.render.score_layers import build_score

    with pytest.raises(ValueError, match="rhythm durations must be finite and > 0"):
        build_score(
            _minimal_spec(
                {
                    "kind": "ostinato",
                    "instrument": "keys",
                    "intervals": [0],
                    "rhythm": [0.0],
                }
            )
        )


def test_voicing_constraints_never_escape_requested_bounds():
    from ambition_music_renderer.render.score_events import _apply_voicing_constraints

    ctx = SimpleNamespace(last_voicing={})
    assert _apply_voicing_constraints(
        ctx, "keys", [48, 64, 84], {"min_pitch": 60, "max_pitch": 72}
    ) == [60, 64, 72]
    with pytest.raises(ValueError, match="cannot place pitch 64"):
        _apply_voicing_constraints(
            ctx, "keys", [64], {"min_pitch": 60, "max_pitch": 60}
        )


def test_reverb_cutoff_maps_to_one_pole_state_coefficient(monkeypatch):
    from ambition_music_renderer.render import effects

    observed: list[float] = []

    def fake_comb(signal_in, delay, feedback, damping):
        observed.append(float(damping))
        return np.zeros_like(signal_in)

    monkeypatch.setattr(effects, "_comb_filter", fake_comb)
    monkeypatch.setattr(
        effects, "_allpass_filter", lambda signal_in, delay, feedback=0.5: signal_in
    )
    audio = np.zeros((64, 2), dtype=np.float32)

    effects.simple_reverb(audio, 48_000, wet=1.0, damping_hz=1_000.0)
    low_cutoff_coefficient = observed[0]
    observed.clear()
    effects.simple_reverb(audio, 48_000, wet=1.0, damping_hz=10_000.0)
    high_cutoff_coefficient = observed[0]

    assert low_cutoff_coefficient > high_cutoff_coefficient


def test_ogg_timestamp_rounding_carries_into_next_minute():
    from ambition_music_renderer.render.export import format_ogg_timestamp

    assert format_ogg_timestamp(59.9996) == "00:01:00.000"
    assert format_ogg_timestamp(3_599.9996) == "01:00:00.000"


def test_ffmpeg_audio_export_writes_metadata_sidecar(tmp_path: Path, monkeypatch):
    from ambition_music_renderer.render import export

    monkeypatch.setattr(export.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"OggS")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(export.subprocess, "run", fake_run)
    ogg_path = tmp_path / "cue.ogg"
    metadata = {"CUE_ID": "cue", "TITLE": "Cue"}
    export.write_ogg_from_audio(
        np.zeros((32, 2), dtype=np.float32),
        48_000,
        ogg_path,
        metadata=metadata,
    )

    sidecar = ogg_path.with_name("cue.ogg.metadata.json")
    assert sidecar.exists()
    assert '"CUE_ID": "cue"' in sidecar.read_text()
