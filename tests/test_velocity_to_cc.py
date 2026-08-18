from __future__ import annotations

from ambition_music_renderer.render.score_core import velocity_to_cc_value
from ambition_music_renderer.render.score_layers import build_score


def test_velocity_to_cc_linear_mapping():
    spec = {
        "velocity_to_cc": {
            "cc": "modulation",
            "input_min": 20,
            "input_max": 110,
            "output_min": 70,
            "output_max": 120,
        }
    }
    assert velocity_to_cc_value(spec, 20) == (1, 70)
    assert velocity_to_cc_value(spec, 65) == (1, 95)
    assert velocity_to_cc_value(spec, 110) == (1, 120)
    assert velocity_to_cc_value(spec, 1) == (1, 70)
    assert velocity_to_cc_value(spec, 127) == (1, 120)


def test_exact_score_emits_dynamic_cc_at_note_on():
    spec = {
        "schema": "ambition.musicir.v2",
        "id": "velocity_cc_exact",
        "title": "velocity cc exact",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {
                "name": "lead",
                "group": "woodwinds",
                "program": "flute",
                "velocity_to_cc": {
                    "cc": "modulation",
                    "input_min": 20,
                    "input_max": 110,
                    "output_min": 70,
                    "output_max": 120,
                },
            }
        ],
        "score": {
            "timebase": {"ppq": 960},
            "meter": [{"bar": 1, "signature": "4/4"}],
            "tempo": [{"tick": 0, "bpm": 120}],
            "form": [{"id": "all", "from": {"tick": 0}, "to": {"tick": 1920}}],
            "end_tick": 1920,
        },
        "parts": [
            {
                "id": "lead",
                "instrument": "lead",
                "voices": [{"id": "score", "events": [[960, 480, 72, 65, "normal"]]}],
            }
        ],
        "state_map": {"default": {"section": "all", "stems": {}}},
    }
    pm, _groups, _meta = build_score(spec)
    lead = pm.instruments[0]
    note = lead.notes[0]
    cc1 = [cc for cc in lead.control_changes if cc.number == 1]
    assert [(round(cc.time, 6), cc.value) for cc in cc1] == [(round(note.start, 6), 95)]
