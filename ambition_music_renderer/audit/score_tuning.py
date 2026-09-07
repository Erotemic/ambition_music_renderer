"""Score-level orchestration for instrument tuning audits.

This module turns one compiled MusicIR score into a bounded set of dry tuning
measurements.  It audits only pitched instruments that actually sound in the
cue, collapses duplicate realizations, and measures the pitches/representative
velocities the score really uses.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import copy
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any, Callable, Mapping

import pretty_midi
import yaml

from .._paths import agent_root
from ..instrument_resolution import backend_spec_from_instrument, resolve_instrument_backend
from ..musicir.midi import initial_control_values
from ..musicir.model import CompiledScore, compiled_score_fingerprint
from .instrument_tuning import TUNING_REPORT_SCHEMA, summarize_tuning_rows


SCORE_TUNING_REPORT_SCHEMA = "ambition.score_tuning_audit.v2"


def _canonical_json_hash(payload: Mapping[str, Any], *, length: int = 20) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf8")).hexdigest()[:length]


def _realization_identity(
    instrument: Mapping[str, Any], *, base_dir: Path
) -> tuple[str, dict[str, Any]]:
    """Return a machine-local dry-realization identity for tuning purposes."""

    backend = backend_spec_from_instrument(instrument)
    if backend:
        plan = resolve_instrument_backend(backend, base_dir=base_dir)
        backend_identity: dict[str, Any] = {
            "kind": plan.kind,
            "resolved_sfz": str(plan.resolved_sfz) if plan.resolved_sfz else None,
            "requested": None if plan.resolved_sfz else plan.requested,
            "fallback_backend": plan.fallback_backend,
            "settings": dict(plan.sfizz_settings),
        }
    else:
        backend_identity = {"kind": "gm"}

    payload = {
        "program": instrument.get("program"),
        "is_drum": bool(instrument.get("is_drum", False)),
        "backend": backend_identity,
        # Preserve the complete startup controller state.  Sampled instruments
        # may use CCs for articulation/layer selection, so two otherwise equal
        # patches with different startup controls are distinct realizations.
        "initial_controls": initial_control_values(instrument),
    }
    return _canonical_json_hash(payload), payload


def _select_used_pitches(
    pitch_counts: Mapping[int, int], *, max_notes: int
) -> list[int]:
    """Bound a score-used pitch set while retaining useful octave anchors."""

    notes = sorted(int(note) for note in pitch_counts)
    if not notes:
        return []
    limit = max(3, int(max_notes))
    if len(notes) <= limit:
        return notes

    must = {notes[0], notes[-1]}
    c_anchors = [note for note in notes if note % 12 == 0 and note not in must]
    slots = max(0, limit - len(must))
    if len(c_anchors) <= slots:
        must.update(c_anchors)
    elif slots > 0:
        # Preserve octave coverage even when an extremely small max-notes cap
        # cannot retain every C used by a very broad instrument.
        if slots == 1:
            must.add(c_anchors[len(c_anchors) // 2])
        else:
            positions = [
                round(index * (len(c_anchors) - 1) / (slots - 1))
                for index in range(slots)
            ]
            must.update(c_anchors[pos] for pos in positions)

    remaining = [note for note in notes if note not in must]
    remaining.sort(key=lambda note: (-int(pitch_counts[note]), note))
    must.update(remaining[: max(0, limit - len(must))])
    return sorted(must)


def build_score_tuning_plan(
    compiled: CompiledScore,
    *,
    score_path: Path,
    max_notes: int = 61,
) -> dict[str, Any]:
    """Describe the unique pitched realizations actually used by a score."""

    base_dir = Path(score_path).resolve().parent
    events_by_instrument: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in compiled.note_events:
        if str(event.get("event_type", "note")) != "note":
            continue
        name = str(event.get("instrument") or "")
        if name:
            events_by_instrument[name].append(event)

    targets_by_key: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for name in sorted(events_by_instrument):
        spec = dict(compiled.instrument_specs.get(name) or {})
        events = events_by_instrument[name]
        if bool(spec.get("is_drum", False)):
            skipped.append(
                {
                    "instrument": name,
                    "group": str(compiled.groups.get(name, name)),
                    "reason": "drums_unpitched",
                    "note_events": len(events),
                }
            )
            continue

        pitch_counts = Counter(int(event["pitch"]) for event in events)
        velocities: dict[int, list[int]] = defaultdict(list)
        for event in events:
            velocities[int(event["pitch"])].append(int(event.get("velocity", 100)))

        realization_id, realization = _realization_identity(spec, base_dir=base_dir)
        target = targets_by_key.setdefault(
            realization_id,
            {
                "realization_id": realization_id,
                "realization": realization,
                "representative_instrument": name,
                "instrument": spec,
                "instrument_names": [],
                "groups": [],
                "note_events": 0,
                "pitch_counts": Counter(),
                "pitch_velocities": defaultdict(list),
                "per_instrument": [],
            },
        )
        target["instrument_names"].append(name)
        target["groups"].append(str(compiled.groups.get(name, name)))
        target["note_events"] += len(events)
        target["pitch_counts"].update(pitch_counts)
        for pitch, values in velocities.items():
            target["pitch_velocities"][pitch].extend(values)
        target["per_instrument"].append(
            {
                "name": name,
                "group": str(compiled.groups.get(name, name)),
                "note_events": len(events),
                "used_pitches": sorted(pitch_counts),
            }
        )

    targets: list[dict[str, Any]] = []
    for realization_id, raw in sorted(
        targets_by_key.items(), key=lambda item: str(item[1]["representative_instrument"])
    ):
        pitch_counts = Counter(raw.pop("pitch_counts"))
        velocity_lists = raw.pop("pitch_velocities")
        used_pitches = sorted(pitch_counts)
        audit_pitches = _select_used_pitches(pitch_counts, max_notes=max_notes)
        note_velocities = {
            str(pitch): int(round(median(velocity_lists[pitch])))
            for pitch in audit_pitches
            if velocity_lists[pitch]
        }
        raw["instrument_names"] = sorted(set(raw["instrument_names"]))
        raw["groups"] = sorted(set(raw["groups"]))
        raw["used_pitches"] = used_pitches
        raw["used_pitch_names"] = [pretty_midi.note_number_to_name(pitch) for pitch in used_pitches]
        raw["audit_pitches"] = audit_pitches
        raw["audit_pitch_names"] = [pretty_midi.note_number_to_name(pitch) for pitch in audit_pitches]
        raw["note_velocities"] = note_velocities
        raw["distinct_used_pitches"] = len(used_pitches)
        raw["audited_pitches"] = len(audit_pitches)
        targets.append(raw)

    return {
        "schema": "ambition.score_tuning_plan.v1",
        "score_path": str(Path(score_path).resolve()),
        "score_id": str(compiled.normalized_spec.get("id") or Path(score_path).stem),
        "compiled_score_fingerprint": compiled_score_fingerprint(compiled),
        "pitched_instruments": sum(len(row["instrument_names"]) for row in targets),
        "unique_realizations": len(targets),
        "targets": targets,
        "skipped": skipped,
    }


def score_tuning_report_hash(plan: Mapping[str, Any], options: Mapping[str, Any]) -> str:
    payload = {
        "schema": SCORE_TUNING_REPORT_SCHEMA,
        "instrument_audit_schema": TUNING_REPORT_SCHEMA,
        "plan": plan,
        "options": dict(options),
        # The representative instrument documents contain mappings that are
        # already deterministic after MusicIR compilation.
    }
    return _canonical_json_hash(payload)


def propose_tuning_correction(
    audit: Mapping[str, Any],
    *,
    report_hash: str,
    realization_id: str,
    max_abs_cents: float = 50.0,
) -> dict[str, Any] | None:
    """Build a conservative correction profile from dual-estimator consensus."""

    validated = [
        row for row in (audit.get("notes") or [])
        if row.get("validation_status") == "agree" and row.get("validated_cents") is not None
    ]
    if len(validated) < 3:
        return None
    normalized_rows = [
        {"midi": int(row["midi"]), "status": "ok", "cents": float(row["validated_cents"])}
        for row in validated
    ]
    summary = summarize_tuning_rows(normalized_rows)
    max_measured = max(abs(float(row["validated_cents"])) for row in validated)
    if max_measured > float(max_abs_cents):
        return None
    if max_measured < 3.0:
        return None
    source = {
        "kind": "score_tuning_audit_consensus",
        "report_hash": str(report_hash),
        "realization_id": str(realization_id),
        "validated_notes": len(validated),
        "estimators": ["normalized_autocorrelation", "harmonic_spectral_peaks"],
    }
    classification = str(summary.get("classification") or "")
    global_correction = summary.get("suggested_global_correction_cents")
    if classification == "global_offset" and global_correction is not None:
        return {
            "mode": "global",
            "cents": round(float(global_correction), 3),
            "max_abs_cents": float(max_abs_cents),
            "source": source,
        }
    if max_measured < 6.0:
        return None
    points = {
        pretty_midi.note_number_to_name(int(row["midi"])): round(-float(row["validated_cents"]), 3)
        for row in sorted(validated, key=lambda item: int(item["midi"]))
    }
    return {
        "mode": "curve",
        "interpolation": "linear",
        "max_abs_cents": float(max_abs_cents),
        "points": points,
        "source": source,
    }


def score_correction_snippet(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a score-authoring snippet; it never mutates the score automatically."""

    instruments: dict[str, Any] = {}
    for row in report.get("realizations") or []:
        proposal = row.get("proposed_tuning_correction")
        if not proposal:
            continue
        for name in row.get("instrument_names") or []:
            instruments[str(name)] = {"tuning_correction": copy.deepcopy(proposal)}
    return {
        "schema": "ambition.score_tuning_corrections.v1",
        "score_id": report.get("score_id"),
        "source_report": report.get("report_json"),
        "instruments": instruments,
    }


def format_score_tuning_report(report: Mapping[str, Any]) -> str:
    """Return a compact human-readable score tuning report."""

    summary = dict(report.get("summary") or {})
    lines = [
        f"Score tuning audit: {report.get('score_id', '?')}",
        "Dry instrument pitch against A4=440 Hz / 12-TET; score processing is excluded.",
        (
            f"Pitched instruments: {summary.get('pitched_instruments', 0)} · "
            f"unique realizations: {summary.get('unique_realizations', 0)} · "
            f"drums skipped: {summary.get('skipped', 0)} · "
            f"failures: {summary.get('failures', 0)}"
        ),
        "",
        "instrument(s)                         used/audited   class                     median    p95    max",
    ]
    for row in report.get("realizations") or []:
        names = ",".join(
            row.get("instrument_names")
            or [row.get("representative_instrument", "?")]
        )
        result = dict(row.get("audit") or {})
        audit_summary = dict(result.get("summary") or {})
        if row.get("status") == "error":
            used = int(row.get("distinct_used_pitches", 0))
            audited = int(row.get("audited_pitches", 0))
            lines.append(
                f"{names[:36]:36s} {used:3d}/{audited:3d}       "
                f"ERROR  {row.get('error', '')}"
            )
            continue
        classification = str(audit_summary.get("classification", "unknown"))
        med = audit_summary.get("median_cents")
        p95 = audit_summary.get("p95_abs_cents")
        max_abs = audit_summary.get("max_abs_cents")
        med_text = f"{float(med):+7.2f}" if med is not None else "    n/a"
        p95_text = f"{float(p95):6.2f}" if p95 is not None else "   n/a"
        max_text = f"{float(max_abs):6.2f}" if max_abs is not None else "   n/a"
        lines.append(
            f"{names[:36]:36s} {row.get('distinct_used_pitches', 0):3d}/{row.get('audited_pitches', 0):3d}       "
            f"{classification[:24]:24s} {med_text} {p95_text} {max_text}"
        )

    proposals = [
        row for row in report.get("realizations") or []
        if row.get("proposed_tuning_correction")
    ]
    if proposals:
        lines.extend(["", "Correction proposals (dual-estimator consensus; not applied automatically):"] )
        for row in proposals:
            names = ",".join(row.get("instrument_names") or [])
            proposal = dict(row.get("proposed_tuning_correction") or {})
            if proposal.get("mode") == "global":
                detail = f"global {float(proposal.get('cents', 0.0)):+.2f} cents"
            else:
                detail = f"curve with {len(proposal.get('points') or {})} measured points"
            lines.append(f"  {names}: {detail}")

    issues: list[str] = []
    for row in report.get("realizations") or []:
        if row.get("status") != "ok":
            continue
        names = ",".join(row.get("instrument_names") or [])
        for note in (row.get("audit") or {}).get("notes") or []:
            cents = note.get("cents")
            status = str(note.get("status") or "")
            if cents is None:
                if status in {"silent", "unreliable", "unstable"}:
                    issues.append(f"  {names}: {note.get('note', '?')} {status}")
                continue
            if abs(float(cents)) >= 6.0 or status != "ok":
                issues.append(
                    f"  {names}: {note.get('note', '?')} @ vel {note.get('velocity', '?')} "
                    f"{float(cents):+.2f} cents ({status})"
                )
    if issues:
        lines.extend(["", "Used-note findings (>=6 cents or non-ok):", *issues])

    skipped = report.get("skipped") or []
    if skipped:
        lines.extend(["", "Skipped:"])
        for row in skipped:
            lines.append(f"  {row.get('instrument')}: {row.get('reason')}")

    lines.extend(
        [
            "",
            f"JSON: {report.get('report_json', '-')}",
            f"Text: {report.get('report_text', '-')}",
            f"Corrections: {report.get('corrections_yaml', '-')}",
        ]
    )
    return "\n".join(lines)


def render_score_tuning_audit(
    score_path: Path,
    *,
    backend: str = "auto",
    sample_rate: int = 48000,
    max_notes: int = 61,
    output_dir: Path | None = None,
    force: bool = False,
    progress: Callable[[int, int, str, str], None] | None = None,
) -> dict[str, Any]:
    """Audit every pitched realization actually used by ``score_path``."""

    from ..music_instrument_inspector_model import (
        build_tuning_audit_request,
        render_tuning_audit,
    )
    from ..musicir.compile import compile_score
    from ..render.score_core import load_yaml

    score_path = Path(score_path).expanduser().resolve()
    compiled = compile_score(load_yaml(score_path))
    plan = build_score_tuning_plan(compiled, score_path=score_path, max_notes=max_notes)
    options = {
        "backend": str(backend),
        "sample_rate": int(sample_rate),
        "max_notes": int(max_notes),
    }
    report_hash = score_tuning_report_hash(plan, options)
    if output_dir is None:
        root = agent_root() / "tuning_audits" / str(plan["score_id"]) / report_hash
    else:
        root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    report_json = root / "report.json"
    report_text = root / "report.txt"
    corrections_yaml = root / "corrections.yaml"

    if not force and report_json.is_file() and report_text.is_file() and corrections_yaml.is_file():
        cached = json.loads(report_json.read_text(encoding="utf8"))
        return cached

    rows: list[dict[str, Any]] = []
    targets = list(plan.get("targets") or [])
    for index, target in enumerate(targets, start=1):
        label = ",".join(
            target.get("instrument_names")
            or [target.get("representative_instrument", "?")]
        )
        if progress is not None:
            progress(index, len(targets), label, "running")
        row = {key: value for key, value in target.items() if key != "instrument"}
        try:
            request = build_tuning_audit_request(
                instrument=dict(target["instrument"]),
                backend=str(backend),
                sample_rate=int(sample_rate),
                max_notes=int(max_notes),
                notes=list(target.get("audit_pitches") or []),
                note_velocities=dict(target.get("note_velocities") or {}),
                base_dir=score_path.parent,
            )
            result = render_tuning_audit(request, force=force)
            row["status"] = "ok"
            row["request_hash"] = result.request_hash
            row["audit_report_path"] = str(result.report_path)
            row["dry_audio"] = str(result.dry_audio)
            row["audit"] = result.report
            row["proposed_tuning_correction"] = propose_tuning_correction(
                result.report,
                report_hash=report_hash,
                realization_id=str(target.get("realization_id", "")),
            )
        except (KeyError, ValueError, RuntimeError, OSError) as ex:
            row["status"] = "error"
            row["error"] = str(ex)
        rows.append(row)
        if progress is not None:
            progress(index, len(targets), label, row["status"])

    failures = sum(1 for row in rows if row.get("status") == "error")
    classifications = Counter(
        str((row.get("audit") or {}).get("summary", {}).get("classification", "unknown"))
        for row in rows
        if row.get("status") == "ok"
    )
    report: dict[str, Any] = {
        "schema": SCORE_TUNING_REPORT_SCHEMA,
        "score_id": plan["score_id"],
        "score_path": plan["score_path"],
        "compiled_score_fingerprint": plan["compiled_score_fingerprint"],
        "report_hash": report_hash,
        "reference": {
            "a4_hz": 440.0,
            "temperament": "12-TET",
            "stage": "dry_pre_processing",
            "note_selection": "score_used_pitches",
            "velocity_selection": "median_score_velocity_per_pitch",
        },
        "options": options,
        "summary": {
            "pitched_instruments": int(plan["pitched_instruments"]),
            "unique_realizations": int(plan["unique_realizations"]),
            "skipped": len(plan.get("skipped") or []),
            "failures": failures,
            "classifications": dict(sorted(classifications.items())),
        },
        "realizations": rows,
        "skipped": plan.get("skipped") or [],
        "report_json": str(report_json),
        "report_text": str(report_text),
        "corrections_yaml": str(corrections_yaml),
    }
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf8")
    report_text.write_text(format_score_tuning_report(report) + "\n", encoding="utf8")
    corrections_yaml.write_text(
        yaml.safe_dump(score_correction_snippet(report), sort_keys=False, allow_unicode=True, width=110),
        encoding="utf8",
    )
    return report
