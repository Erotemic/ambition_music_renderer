"""Spectral masking diagnostics flag support energy over a foreground tone."""

from __future__ import annotations

import numpy as np
import pretty_midi

from ambition_music_renderer.audit.spectral_masking_audit import analyze_spectral_masking


def _tone(freq: float, amp: float, sr: int, seconds: float) -> np.ndarray:
    t = np.arange(int(sr * seconds), dtype=np.float64) / sr
    mono = (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def test_foreground_masking_is_reported_for_same_band_support():
    sr = 8000
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    lead = pretty_midi.Instrument(program=68, name="oboe")
    lead.notes.append(pretty_midi.Note(velocity=70, pitch=81, start=0.0, end=2.0))
    support = pretty_midi.Instrument(program=41, name="viola")
    support.notes.append(pretty_midi.Note(velocity=70, pitch=81, start=0.0, end=2.0))
    pm.instruments = [lead, support]
    spec = {
        "instruments": [
            {"name": "oboe", "mix_role": "foreground"},
            {"name": "viola", "mix_role": "support"},
        ]
    }
    payload = analyze_spectral_masking(
        {
            "woodwinds": _tone(880.0, 0.10, sr, 2.0),
            "strings": _tone(880.0, 0.35, sr, 2.0),
        },
        pm,
        {"oboe": "woodwinds", "viola": "strings"},
        spec,
        sr,
        window_s=0.4,
        hop_s=0.2,
    )
    assert payload["warning_count"] > 0
    assert any(
        row["lead_group"] == "woodwinds"
        and row["support_group"] == "strings"
        and row["band"] == "mid"
        for row in payload["warnings"]
    )


def test_high_foreground_does_not_report_irrelevant_bass_masking():
    sr = 8000
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    lead = pretty_midi.Instrument(program=68, name="oboe")
    lead.notes.append(pretty_midi.Note(velocity=70, pitch=81, start=0.0, end=2.0))
    support = pretty_midi.Instrument(program=41, name="viola")
    support.notes.append(pretty_midi.Note(velocity=70, pitch=45, start=0.0, end=2.0))
    pm.instruments = [lead, support]
    spec = {
        "instruments": [
            {"name": "oboe", "mix_role": "foreground"},
            {"name": "viola", "mix_role": "support"},
        ]
    }
    woodwind = _tone(880.0, 0.10, sr, 2.0)
    strings = _tone(100.0, 0.60, sr, 2.0) + _tone(880.0, 0.20, sr, 2.0)
    payload = analyze_spectral_masking(
        {"woodwinds": woodwind, "strings": strings},
        pm,
        {"oboe": "woodwinds", "viola": "strings"},
        spec,
        sr,
        window_s=0.4,
        hop_s=0.2,
    )
    assert payload["band_relevance"] == "active lead-pitch low-order harmonics"
    assert not any(row["band"] == "bass" for row in payload["warnings"])
    assert any(row["band"] == "mid" for row in payload["warnings"])


def test_register_aware_manifest_summary_has_no_prepass_count():
    from ambition_music_renderer.render.isolated import (
        _spectral_masking_manifest_summary,
    )

    summary = _spectral_masking_manifest_summary(
        {
            "pre_protection_warning_count": None,
            "post_protection_warning_count": 7,
        }
    )
    assert summary == {
        "pre_protection_warning_count": None,
        "post_protection_warning_count": 7,
    }


def test_bus_protection_manifest_summary_keeps_both_counts():
    from ambition_music_renderer.render.isolated import (
        _spectral_masking_manifest_summary,
    )

    summary = _spectral_masking_manifest_summary(
        {
            "pre_protection_warning_count": 11,
            "post_protection_warning_count": 3,
        }
    )
    assert summary == {
        "pre_protection_warning_count": 11,
        "post_protection_warning_count": 3,
    }


def test_nearly_silent_active_foreground_is_classified_as_underdriven():
    sr = 8000
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    lead = pretty_midi.Instrument(program=68, name="oboe")
    lead.notes.append(pretty_midi.Note(velocity=70, pitch=81, start=0.0, end=2.0))
    support = pretty_midi.Instrument(program=41, name="viola")
    support.notes.append(pretty_midi.Note(velocity=70, pitch=81, start=0.0, end=2.0))
    pm.instruments = [lead, support]
    spec = {
        "instruments": [
            {"name": "oboe", "mix_role": "foreground"},
            {"name": "viola", "mix_role": "support"},
        ]
    }
    payload = analyze_spectral_masking(
        {
            "woodwinds": _tone(880.0, 0.00001, sr, 2.0),
            "strings": _tone(880.0, 0.30, sr, 2.0),
        },
        pm,
        {"oboe": "woodwinds", "viola": "strings"},
        spec,
        sr,
        window_s=0.4,
        hop_s=0.2,
    )
    assert payload["underdriven_foreground_count"] > 0
    assert payload["warning_count"] == 0
    assert payload["underdriven_foreground"][0]["lead_group"] == "woodwinds"
