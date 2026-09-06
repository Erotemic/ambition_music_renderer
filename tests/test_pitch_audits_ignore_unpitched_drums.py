from __future__ import annotations

from ambition_music_renderer.audit import dissonance_audit, sour_note_audit


def _spec_with_sustained_drum_trigger() -> dict:
    return {
        "id": "ignore_trigger_keys",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4},
        "instruments": [
            {"name": "keys", "group": "harmony", "program": "acoustic_grand_piano"},
            {"name": "snare_patch", "group": "percussion", "is_drum": True},
        ],
        "layer_templates": {
            "held_tonic": {
                "kind": "notes",
                "instrument": "keys",
                "notes": [[0, 0.0, "C4", 4.0, 80]],
            },
            "sample_trigger": {
                "kind": "notes",
                "instrument": "snare_patch",
                "notes": [[0, 0.0, "C#4", 4.0, 100]],
            },
        },
        "sections": [
            {
                "id": "s",
                "kind": "loop_component",
                "bars": 1,
                "intensity": 1.0,
                "harmony": ["C"],
                "layers": ["held_tonic", "sample_trigger"],
            }
        ],
        "state_map": {"default": {"section": "s", "stems": {}}},
    }


def test_dissonance_audit_ignores_unpitched_trigger_keys():
    payload = dissonance_audit.audit_spec(_spec_with_sustained_drum_trigger())
    assert payload["ignored_unpitched_note_count"] == 1
    assert payload["note_count"] == 1
    assert payload["hotspots"] == []


def test_sour_note_report_and_pianoroll_ignore_unpitched_trigger_keys():
    spec = _spec_with_sustained_drum_trigger()
    payload = sour_note_audit.audit_spec(spec)
    assert payload["ignored_unpitched_note_count"] == 1
    assert payload["note_count"] == 1
    assert payload["candidates"] == []

    plot_data = sour_note_audit.pianoroll_data(spec)
    assert plot_data is not None
    assert {row["pitch"] for row in plot_data["notes"]} == {60}
