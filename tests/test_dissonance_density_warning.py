"""Density warnings distinguish virtuosic single instruments from layering."""

from __future__ import annotations

from ambition_music_renderer.audit.dissonance_audit import _dense_hotspot_spans_multiple_parts


def _hotspot(instruments: list[str], groups: list[str]) -> dict:
    return {
        "active_note_count": len(instruments),
        "active_notes": [
            {"pitch": 48 + idx, "instrument": instrument, "group": group}
            for idx, (instrument, group) in enumerate(zip(instruments, groups))
        ],
    }


def test_dense_single_instrument_is_not_arrangement_layering_warning():
    hotspot = _hotspot(["concert_grand"] * 10, ["piano"] * 10)
    assert not _dense_hotspot_spans_multiple_parts(hotspot)


def test_dense_multiple_instruments_is_arrangement_layering_warning():
    hotspot = _hotspot(
        ["violin_1"] * 4 + ["violin_2"] * 4,
        ["strings"] * 8,
    )
    assert _dense_hotspot_spans_multiple_parts(hotspot)
