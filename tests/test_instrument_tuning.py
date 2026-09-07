from __future__ import annotations

import math

import numpy as np

from ambition_music_renderer.audit.instrument_tuning import (
    estimate_known_note_tuning,
    select_tuning_notes,
    summarize_tuning_rows,
)


def test_known_note_tuning_recovers_small_cents_offset():
    sample_rate = 24000
    expected_midi = 72
    expected_hz = 440.0 * 2.0 ** ((expected_midi - 69) / 12.0)
    wanted_cents = 7.5
    actual_hz = expected_hz * 2.0 ** (wanted_cents / 1200.0)
    time = np.arange(int(sample_rate * 0.8), dtype=np.float64) / sample_rate
    envelope = np.exp(-0.8 * time)
    # Strong second harmonic approximates the bright spectra that make generic
    # F0 detectors prone to octave mistakes on sampled keyboards.
    audio = envelope * (
        0.22 * np.sin(2 * math.pi * actual_hz * time)
        + 0.75 * np.sin(2 * math.pi * actual_hz * 2.0 * time)
        + 0.12 * np.sin(2 * math.pi * actual_hz * 3.0 * time)
    )
    got = estimate_known_note_tuning(audio[:, None], sample_rate, expected_midi)
    assert got["status"] == "ok"
    assert abs(got["cents"] - wanted_cents) < 0.8
    assert got["confidence"] > 0.5


def test_tuning_note_selection_keeps_c_octaves_and_anchor():
    got = select_tuning_notes(21, 108, max_notes=20, anchors=[71])
    assert 21 in got and 108 in got and 71 in got
    assert all(note in got for note in range(24, 109, 12))
    assert got == sorted(set(got))


def test_tuning_summary_distinguishes_global_offset_from_range_drift():
    global_rows = [
        {"midi": midi, "status": "ok", "cents": 5.0 + ((midi % 3) - 1) * 0.2}
        for midi in range(48, 73, 4)
    ]
    global_summary = summarize_tuning_rows(global_rows)
    assert global_summary["classification"] == "global_offset"
    assert abs(global_summary["suggested_global_correction_cents"] + 5.0) < 0.5

    drift_rows = [
        {"midi": midi, "status": "ok", "cents": (midi - 60) * 0.8}
        for midi in range(48, 85, 6)
    ]
    drift_summary = summarize_tuning_rows(drift_rows)
    assert drift_summary["classification"] == "range_dependent"
    assert drift_summary["suggested_global_correction_cents"] is None


def test_spectral_estimator_independently_confirms_bright_known_note():
    from ambition_music_renderer.audit.instrument_tuning import (
        combine_tuning_estimators,
        estimate_known_note_tuning_spectral,
    )

    sample_rate = 24000
    expected_midi = 72
    expected_hz = 440.0 * 2.0 ** ((expected_midi - 69) / 12.0)
    wanted_cents = 7.5
    actual_hz = expected_hz * 2.0 ** (wanted_cents / 1200.0)
    time = np.arange(int(sample_rate * 0.8), dtype=np.float64) / sample_rate
    audio = np.exp(-0.8 * time) * (
        0.18 * np.sin(2 * math.pi * actual_hz * time)
        + 0.80 * np.sin(2 * math.pi * actual_hz * 2.0 * time)
        + 0.20 * np.sin(2 * math.pi * actual_hz * 3.0 * time)
    )
    primary = estimate_known_note_tuning(audio[:, None], sample_rate, expected_midi)
    spectral = estimate_known_note_tuning_spectral(audio[:, None], sample_rate, expected_midi)
    assert spectral["status"] == "ok"
    assert abs(spectral["cents"] - wanted_cents) < 0.5
    consensus = combine_tuning_estimators(primary, spectral)
    assert consensus["validation_status"] == "agree"
    assert abs(consensus["validated_cents"] - wanted_cents) < 0.6


def test_tuning_estimator_disagreement_blocks_consensus():
    from ambition_music_renderer.audit.instrument_tuning import combine_tuning_estimators

    got = combine_tuning_estimators(
        {"status": "ok", "cents": 12.0},
        {"status": "ok", "cents": 4.0},
    )
    assert got["validation_status"] == "disagree"
    assert got["validated_cents"] is None
