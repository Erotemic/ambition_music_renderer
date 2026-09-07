from __future__ import annotations

from pathlib import Path

import pretty_midi

from ambition_music_renderer.audit.score_tuning import (
    _select_used_pitches,
    build_score_tuning_plan,
    format_score_tuning_report,
)
from ambition_music_renderer.musicir.model import CompiledScore


def _compiled_fixture() -> CompiledScore:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    for name, program, is_drum in [
        ("piano_a", 0, False),
        ("piano_b", 0, False),
        ("drums", 0, True),
    ]:
        pm.instruments.append(
            pretty_midi.Instrument(program=program, is_drum=is_drum, name=name)
        )
    specs = {
        "piano_a": {"name": "piano_a", "group": "keys", "program": "acoustic_grand_piano"},
        "piano_b": {"name": "piano_b", "group": "keys2", "program": "acoustic_grand_piano"},
        "drums": {"name": "drums", "group": "drums", "is_drum": True},
    }
    events = [
        {"instrument": "piano_a", "event_type": "note", "pitch": 60, "velocity": 80},
        {"instrument": "piano_a", "event_type": "note", "pitch": 60, "velocity": 100},
        {"instrument": "piano_b", "event_type": "note", "pitch": 64, "velocity": 110},
        {"instrument": "drums", "event_type": "note", "pitch": 36, "velocity": 120},
    ]
    return CompiledScore(
        source_schema="ambition.music.v3",
        canonical_schema="ambition.music.v3",
        normalized_spec={"id": "tiny"},
        pm=pm,
        groups={"piano_a": "keys", "piano_b": "keys2", "drums": "drums"},
        sections=[],
        instrument_specs=specs,
        note_events=events,
    )


def test_score_tuning_plan_collapses_equal_realizations_and_skips_drums(tmp_path: Path):
    compiled = _compiled_fixture()
    score = tmp_path / "tiny.music.yaml"
    score.write_text("schema: ambition.music.v3\nid: tiny\n", encoding="utf8")
    plan = build_score_tuning_plan(compiled, score_path=score)
    assert plan["pitched_instruments"] == 2
    assert plan["unique_realizations"] == 1
    assert plan["skipped"] == [
        {"instrument": "drums", "group": "drums", "reason": "drums_unpitched", "note_events": 1}
    ]
    target = plan["targets"][0]
    assert target["instrument_names"] == ["piano_a", "piano_b"]
    assert target["used_pitches"] == [60, 64]
    assert target["audit_pitches"] == [60, 64]
    assert target["note_velocities"] == {"60": 90, "64": 110}


def test_score_used_pitch_selection_is_bounded_and_keeps_used_c_octaves():
    counts = {note: 1 for note in range(21, 109)}
    counts[71] = 50
    got = _select_used_pitches(counts, max_notes=20)
    assert len(got) <= 20
    assert 21 in got and 108 in got and 71 in got
    assert all(note in got for note in range(24, 109, 12))

    tiny = _select_used_pitches(counts, max_notes=3)
    assert len(tiny) == 3
    assert tiny[0] == 21 and tiny[-1] == 108


def test_score_tuning_text_report_surfaces_used_note_outliers():
    report = {
        "score_id": "demo",
        "summary": {"pitched_instruments": 1, "unique_realizations": 1, "skipped": 0, "failures": 0},
        "realizations": [
            {
                "status": "ok",
                "instrument_names": ["harpsichord"],
                "distinct_used_pitches": 3,
                "audited_pitches": 3,
                "audit": {
                    "summary": {
                        "classification": "local_outliers_or_mixed",
                        "median_cents": 0.5,
                        "p95_abs_cents": 8.0,
                        "max_abs_cents": 9.0,
                    },
                    "notes": [
                        {"note": "C5", "velocity": 96, "cents": 9.0, "status": "ok"},
                    ],
                },
            }
        ],
        "skipped": [],
        "report_json": "/tmp/report.json",
        "report_text": "/tmp/report.txt",
    }
    text = format_score_tuning_report(report)
    assert "harpsichord" in text
    assert "C5 @ vel 96 +9.00 cents" in text


def test_score_tuning_proposal_requires_dual_estimator_consensus():
    from ambition_music_renderer.audit.score_tuning import propose_tuning_correction

    audit = {
        "notes": [
            {"midi": 48, "validation_status": "agree", "validated_cents": 18.0},
            {"midi": 52, "validation_status": "agree", "validated_cents": 14.0},
            {"midi": 55, "validation_status": "agree", "validated_cents": 11.0},
        ]
    }
    proposal = propose_tuning_correction(
        audit, report_hash="abc", realization_id="realization"
    )
    assert proposal is not None
    assert proposal["mode"] == "curve"
    assert proposal["points"]["C3"] == -18.0
    assert proposal["source"]["estimators"] == [
        "normalized_autocorrelation",
        "harmonic_spectral_peaks",
    ]

    audit["notes"][1]["validation_status"] = "disagree"
    assert propose_tuning_correction(
        audit, report_hash="abc", realization_id="realization"
    ) is None


def test_score_correction_snippet_maps_shared_realization_to_each_instrument():
    from ambition_music_renderer.audit.score_tuning import score_correction_snippet

    proposal = {
        "mode": "global",
        "cents": -7.0,
        "max_abs_cents": 50.0,
        "source": {"kind": "score_tuning_audit_consensus"},
    }
    report = {
        "score_id": "demo",
        "report_json": "/tmp/demo/report.json",
        "realizations": [
            {
                "instrument_names": ["left", "right"],
                "proposed_tuning_correction": proposal,
            }
        ],
    }
    snippet = score_correction_snippet(report)
    assert snippet["schema"] == "ambition.score_tuning_corrections.v1"
    assert snippet["instruments"]["left"]["tuning_correction"] == proposal
    assert snippet["instruments"]["right"]["tuning_correction"] == proposal
