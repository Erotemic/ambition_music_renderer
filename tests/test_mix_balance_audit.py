"""Tests for the static mix-balance / lead-audibility audit.

The audit reconstructs the product (instrument volume x group gain x state_map
stem weight) that decides whether a lead instrument can actually be heard, and
flags a lead whose group is allocated far less mix budget than the bed — the
mistake that produced a piano-led cue where the piano was inaudible.
"""
from __future__ import annotations

from ambition_music_renderer.audit import mix_balance_audit as mb


def _base_spec(**overrides):
    spec = {
        "id": "t",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "piano", "group": "keys", "program": "acoustic_grand_piano", "volume": 110},
            {"name": "gtr", "group": "guitars", "program": "clean_guitar", "volume": 100},
            {"name": "drums", "group": "perc", "is_drum": True, "volume": 110},
        ],
        "layer_templates": {
            "melody": {"kind": "guitar_lead", "instrument": "piano", "motif": "m", "root": "C4"},
            "comp": {"kind": "pad_chords", "instrument": "gtr", "every_bars": 1,
                     "octave": 3, "duration_beats": 3.5},
            "beat": {"kind": "drums", "instrument": "drums",
                     "events": [{"drum": "kick", "beats": [0.0, 2.0], "velocity": 90}]},
        },
        "motifs": [{"id": "m", "root": "C4", "intervals": [0, 2, 4, 5],
                    "rhythm": [1, 1, 1, 1], "velocities": [0.9, 0.9, 0.9, 0.9]}],
        "sections": [{
            "id": "verse", "kind": "loop_component", "bars": 2, "intensity": 1.0,
            "harmony": ["C", "G"],
            "layers": [
                {"template": "melody", "starts": [[0, 0.0]]},
                "comp", "beat",
            ],
        }],
        "state_map": {"wave_1": {"preferred_section": "verse", "stems": overrides.get(
            "stems", {"keys": 1.0, "guitars": 1.0, "perc": 1.0})}},
    }
    return spec


def test_lead_with_healthy_budget_is_not_flagged():
    payload = mb.audit_spec(_base_spec())
    assert payload["sections"], "expected at least one section"
    assert payload["warnings"] == [], f"unexpected warnings: {payload['warnings']}"


def test_buried_lead_is_flagged_when_its_group_is_downweighted():
    # The piano (keys) carries the melody but its stem weight is crushed.
    payload = mb.audit_spec(_base_spec(stems={"keys": 0.05, "guitars": 1.0, "perc": 1.0}))
    assert any("buried lead" in w and "keys" in w for w in payload["warnings"]), payload["warnings"]
    # the keys row should report a large negative budget and be marked buried
    verse = payload["sections"][0]
    keys = next(r for r in verse["groups"] if r["group"] == "keys")
    assert keys["buried_lead"] is True
    assert keys["budget_db"] < -10.0


def test_group_gain_compensates_state_weight():
    # A low stem weight offset by a big group gain is NOT buried.
    spec = _base_spec(stems={"keys": 0.1, "guitars": 1.0, "perc": 1.0})
    spec["group_postprocess"] = {"keys": {"gain_db": 20.0}}  # +20 dB ~ x10 -> budget ~1.0
    payload = mb.audit_spec(spec)
    assert payload["warnings"] == [], f"gain should rescue budget: {payload['warnings']}"
