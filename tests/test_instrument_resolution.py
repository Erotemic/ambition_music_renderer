"""Instrument resolution provenance audit — records what each instrument
actually resolved to (alias -> file, GM program, octave-folds, unmapped drums)."""
from __future__ import annotations

from ambition_music_renderer.audit import instrument_resolution as ir


def _spec(instruments, layers, harmony=("C",)):
    return {
        "id": "t", "tempo": {"bpm": 120}, "meter": {"beats_per_bar": 4},
        "instruments": instruments,
        "layer_templates": {
            "bassline": {"kind": "bassline", "instrument": instruments[0]["name"],
                         "octave": 1, "pattern": [[0, 0.0, 1.0]], "velocity": 70},
        },
        "sections": [{"id": "s", "kind": "loop_component", "bars": 1, "intensity": 1.0,
                      "harmony": list(harmony), "layers": layers}],
        "state_map": {"default": {"section": "s", "stems": {}}},
    }


def test_gm_instrument_reports_soundfont():
    spec = _spec([{"name": "b", "group": "bass", "program": "acoustic_bass"}], ["bassline"])
    spec["render"] = {"soundfont": "/usr/share/sounds/sf2/TimGM6mb.sf2"}
    p = ir.audit_spec(spec)
    row = p["instruments"][0]
    assert row["backend"] == "soundfont"
    assert row["resolved_name"] == "TimGM6mb.sf2"
    assert p["warnings"] == []


def test_unresolved_sfz_warns():
    spec = _spec([{"name": "b", "group": "bass", "program": "acoustic_bass",
                   "instrument_backend": {"kind": "sfz", "library_ref": "no.such.library"}}],
                 ["bassline"])
    p = ir.audit_spec(spec)
    assert any("UNRESOLVED" in r["status"] for r in p["instruments"])
    assert any("did not resolve" in w for w in p["warnings"])


def test_resolution_records_requested_and_resolved_keys():
    spec = _spec([{"name": "b", "group": "bass", "program": "acoustic_bass",
                   "instrument_backend": {"kind": "sfz", "library_ref": "bass.growly"}}],
                 ["bassline"])
    row = ir.audit_spec(spec)["instruments"][0]
    # whether or not the library is installed here, the provenance fields exist
    assert row["requested"] == "bass.growly"
    assert "resolved" in row and "key_span" in row and "notes_out_of_range" in row
