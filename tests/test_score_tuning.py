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


def test_score_tuning_text_report_surfaces_validated_used_note_outliers():
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
                        {"note": "C5", "midi": 72, "velocity": 96, "cents": 9.0,
                         "spectral": {"cents": 8.6}, "status": "ok",
                         "validation_status": "agree", "validated_cents": 8.8},
                    ],
                },
                "correction_decision": {"status": "rejected", "reason": "raw_behavior_mixed",
                                        "validated_notes": 1, "audited_notes": 1,
                                        "validation_fraction": 1.0, "span_coverage": 1.0},
            }
        ],
        "skipped": [],
        "report_json": "/tmp/report.json",
        "report_text": "/tmp/report.txt",
        "corrections_yaml": "/tmp/corrections.yaml",
    }
    text = format_score_tuning_report(report)
    assert "harpsichord" in text
    assert "C5 @ vel 96 +8.80 cents (consensus)" in text


def test_score_tuning_proposal_requires_dual_estimator_consensus():
    from ambition_music_renderer.audit.score_tuning import propose_tuning_correction

    audit = {
        "summary": {"classification": "range_dependent"},
        "notes": [
            {"midi": midi, "status": "ok", "cents": 18.0 - (midi - 48) * 0.45,
             "validation_status": "agree", "validated_cents": 18.0 - (midi - 48) * 0.45}
            for midi in range(48, 73, 4)
        ],
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

    for row in audit["notes"][2:]:
        row["validation_status"] = "disagree"
        row["validated_cents"] = None
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


def _audit_with_consensus(raw_class, rows):
    return {
        "summary": {"classification": raw_class},
        "notes": rows,
    }


def test_consensus_policy_rejects_single_estimator_global_bias():
    from ambition_music_renderer.audit.score_tuning import (
        evaluate_tuning_correction_eligibility,
        propose_tuning_correction,
        summarize_tuning_consensus,
    )

    # Mirrors the low_guitar shape: raw estimator is coherently sharp, but only
    # a small upper-register subset agrees with the independent estimator.
    rows = []
    for midi in range(36, 64, 2):
        if midi in {50, 52, 62}:
            rows.append({
                "midi": midi,
                "status": "ok",
                "cents": 7.0,
                "validation_status": "agree",
                "validated_cents": 1.5,
            })
        else:
            rows.append({
                "midi": midi,
                "status": "ok",
                "cents": 7.0,
                "validation_status": "disagree",
                "validated_cents": None,
            })
    audit = _audit_with_consensus("global_offset", rows)
    consensus = summarize_tuning_consensus(audit)
    assert consensus["classification"] == "insufficient_consensus"
    decision = evaluate_tuning_correction_eligibility(audit)
    assert decision["status"] == "rejected"
    assert decision["reason"] == "insufficient_consensus"
    assert propose_tuning_correction(audit, report_hash="x", realization_id="y") is None


def test_consensus_policy_rejects_global_model_for_raw_mixed_behavior():
    from ambition_music_renderer.audit.score_tuning import evaluate_tuning_correction_eligibility

    rows = [
        {"midi": midi, "status": "ok", "cents": 4.0,
         "validation_status": "agree", "validated_cents": 4.0}
        for midi in range(36, 61, 4)
    ]
    audit = _audit_with_consensus("local_outliers_or_mixed", rows)
    decision = evaluate_tuning_correction_eligibility(audit)
    assert decision["status"] == "rejected"
    assert decision["reason"] == "raw_behavior_mixed"


def test_consensus_policy_accepts_well_covered_range_curve():
    from ambition_music_renderer.audit.score_tuning import (
        evaluate_tuning_correction_eligibility,
        propose_tuning_correction,
    )

    rows = []
    for midi in range(40, 68, 2):
        cents = 11.0 - (midi - 40) * 0.45
        rows.append({
            "midi": midi,
            "status": "ok",
            "cents": cents,
            "validation_status": "agree" if midi != 54 else "disagree",
            "validated_cents": None if midi == 54 else cents,
        })
    audit = _audit_with_consensus("range_dependent", rows)
    decision = evaluate_tuning_correction_eligibility(audit)
    assert decision["status"] == "eligible_curve"
    assert decision["span_coverage"] >= 0.9
    proposal = propose_tuning_correction(
        audit, report_hash="abc", realization_id="real", decision=decision
    )
    assert proposal is not None and proposal["mode"] == "curve"
    assert proposal["source"]["policy"] == "conservative_v2"


def test_consensus_policy_blocks_curve_with_large_unvalidated_low_range():
    from ambition_music_renderer.audit.score_tuning import evaluate_tuning_correction_eligibility

    rows = []
    for midi in range(24, 60, 2):
        agree = midi >= 38
        cents = 20.0 - (midi - 24) * 0.4
        rows.append({
            "midi": midi,
            "status": "ok",
            "cents": cents,
            "validation_status": "agree" if agree else "disagree",
            "validated_cents": cents if agree else None,
        })
    audit = _audit_with_consensus("range_dependent", rows)
    decision = evaluate_tuning_correction_eligibility(audit)
    assert decision["status"] == "rejected"
    assert decision["reason"] == "insufficient_range_coverage"
    assert decision["span_coverage"] < 0.65


def test_score_report_separates_validated_offsets_from_estimator_disagreement():
    report = {
        "score_id": "demo",
        "summary": {"pitched_instruments": 1, "unique_realizations": 1, "skipped": 0, "failures": 0},
        "realizations": [{
            "status": "ok",
            "instrument_names": ["guitar"],
            "distinct_used_pitches": 2,
            "audited_pitches": 2,
            "audit": {
                "summary": {"classification": "global_offset", "median_cents": 7.0,
                            "p95_abs_cents": 8.0, "max_abs_cents": 8.0},
                "notes": [
                    {"note": "C2", "midi": 36, "velocity": 100, "status": "ok",
                     "cents": 8.0, "spectral": {"cents": 1.0},
                     "validation_status": "disagree", "validated_cents": None},
                    {"note": "D3", "midi": 50, "velocity": 100, "status": "ok",
                     "cents": 7.0, "spectral": {"cents": 7.4},
                     "validation_status": "agree", "validated_cents": 7.2},
                ],
            },
            "tuning_consensus": {"classification": "insufficient_consensus"},
            "correction_decision": {"status": "rejected", "reason": "insufficient_consensus",
                                    "validated_notes": 1, "audited_notes": 2,
                                    "validation_fraction": 0.5, "span_coverage": 0.0},
        }],
        "skipped": [],
        "report_json": "/tmp/report.json",
        "report_text": "/tmp/report.txt",
        "corrections_yaml": "/tmp/corrections.yaml",
    }
    text = format_score_tuning_report(report)
    assert "Validated used-note findings" in text
    assert "D3 @ vel 100 +7.20 cents (consensus)" in text
    assert "Estimator disagreements (not correction evidence)" in text
    assert "C2 auto +8.00, spectral +1.00 cents" in text
