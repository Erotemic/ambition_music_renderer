"""Role-aware foreground protection yields only support-only groups."""

from __future__ import annotations

import numpy as np
import pretty_midi

from ambition_music_renderer.render.foreground_protection import (
    apply_foreground_protection,
    foreground_protection_gain_envelopes,
)


def _score() -> tuple[pretty_midi.PrettyMIDI, dict[str, str], dict]:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    lead = pretty_midi.Instrument(program=68, name="oboe")
    lead.notes.append(pretty_midi.Note(velocity=70, pitch=64, start=1.0, end=2.0))
    support = pretty_midi.Instrument(program=41, name="viola")
    support.notes.append(pretty_midi.Note(velocity=70, pitch=64, start=0.5, end=2.5))
    pm.instruments = [lead, support]
    groups = {"oboe": "woodwinds", "viola": "strings"}
    spec = {
        "render": {
            "foreground_protection": {
                "enabled": True,
                "duck_db_per_priority": -3.0,
                "max_duck_db": -6.0,
                "control_hop_ms": 20,
                "attack_ms": 10,
                "release_ms": 40,
            }
        },
        "instruments": [
            {"name": "oboe", "mix_role": "foreground"},
            {"name": "viola", "mix_role": "support"},
        ],
    }
    return pm, groups, spec


def test_support_group_ducks_under_other_foreground_group():
    pm, groups, spec = _score()
    envelopes, report = foreground_protection_gain_envelopes(
        pm, groups, spec, duration_s=3.0
    )
    assert report["enabled"]
    assert float(np.min(envelopes["strings"])) < -5.0
    assert float(np.min(envelopes["woodwinds"])) > -0.01
    # Outside the oboe phrase the support strings recover.
    assert envelopes["strings"][5] > -0.1


def test_group_with_lower_priority_lead_yields_less_than_support():
    pm, groups, spec = _score()
    violin = pretty_midi.Instrument(program=40, name="violin_lead")
    violin.notes.append(pretty_midi.Note(velocity=70, pitch=76, start=1.2, end=1.8))
    pm.instruments.append(violin)
    groups["violin_lead"] = "strings"
    spec["instruments"].append({"name": "violin_lead", "mix_role": "lead"})
    envelopes, _ = foreground_protection_gain_envelopes(pm, groups, spec, duration_s=3.0)
    idx = int(1.5 / 0.02)
    assert -4.0 < envelopes["strings"][idx] < -2.0


def test_apply_foreground_protection_changes_only_support_bus():
    pm, groups, spec = _score()
    sr = 1000
    stems = {
        "woodwinds": np.ones((3000, 2), dtype=np.float32),
        "strings": np.ones((3000, 2), dtype=np.float32),
    }
    report = apply_foreground_protection(stems, pm, groups, spec, sr)
    assert report["groups"]["strings"]["minimum_gain_db"] < -5.0
    assert np.max(np.abs(stems["woodwinds"] - 1.0)) < 1e-6
    assert float(np.mean(stems["strings"][1200:1800])) < 0.6


def test_instrument_register_protection_ducks_only_colliding_desk():
    from ambition_music_renderer.render.foreground_protection import (
        instrument_register_protection_gain_envelopes,
    )

    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    oboe = pretty_midi.Instrument(program=68, name="oboe")
    oboe.notes.append(pretty_midi.Note(velocity=70, pitch=64, start=1.0, end=2.0))
    viola = pretty_midi.Instrument(program=41, name="viola")
    viola.notes.append(pretty_midi.Note(velocity=70, pitch=64, start=0.5, end=2.5))
    cello = pretty_midi.Instrument(program=42, name="cello")
    cello.notes.append(pretty_midi.Note(velocity=70, pitch=40, start=0.5, end=2.5))
    pm.instruments = [oboe, viola, cello]
    groups = {"oboe": "woodwinds", "viola": "strings", "cello": "strings"}
    spec = {
        "render": {
            "foreground_protection": {
                "enabled": True,
                "mode": "instrument_register",
                "groups": ["strings"],
                "pitch_radius_semitones": 2,
                "duck_db_per_priority": -3.5,
                "max_duck_db": -7.0,
                "control_hop_ms": 20,
                "attack_ms": 10,
                "release_ms": 40,
            }
        },
        "instruments": [
            {"name": "oboe", "mix_role": "foreground"},
            {"name": "viola", "mix_role": "support"},
            {"name": "cello", "mix_role": "support"},
        ],
    }
    envelopes, report = instrument_register_protection_gain_envelopes(
        pm, groups, spec, duration_s=3.0
    )
    idx = int(1.5 / 0.02)
    assert envelopes["viola"][idx] < -6.0
    assert envelopes["cello"][idx] > -0.01
    assert envelopes["oboe"][idx] > -0.01
    assert report["mode"] == "instrument_register"
    assert report["instruments"]["viola"]["ducked_seconds"] > 0.5
    assert report["instruments"]["cello"]["ducked_seconds"] == 0.0


def test_instrument_register_lead_yields_less_than_support():
    from ambition_music_renderer.render.foreground_protection import (
        instrument_register_protection_gain_envelopes,
    )

    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    clarinet = pretty_midi.Instrument(program=71, name="clarinet")
    clarinet.notes.append(pretty_midi.Note(velocity=70, pitch=83, start=1.0, end=2.0))
    violin = pretty_midi.Instrument(program=40, name="violin")
    violin.notes.append(pretty_midi.Note(velocity=70, pitch=83, start=1.0, end=2.0))
    pm.instruments = [clarinet, violin]
    groups = {"clarinet": "woodwinds", "violin": "strings"}
    spec = {
        "render": {
            "foreground_protection": {
                "enabled": True,
                "mode": "instrument_register",
                "groups": ["strings"],
                "pitch_radius_semitones": 2,
                "duck_db_per_priority": -3.5,
                "max_duck_db": -7.0,
                "control_hop_ms": 20,
                "attack_ms": 10,
                "release_ms": 40,
            }
        },
        "instruments": [
            {"name": "clarinet", "mix_role": "foreground"},
            {"name": "violin", "mix_role": "lead"},
        ],
    }
    envelopes, _ = instrument_register_protection_gain_envelopes(
        pm, groups, spec, duration_s=3.0
    )
    idx = int(1.5 / 0.02)
    assert -4.5 < envelopes["violin"][idx] < -3.0
