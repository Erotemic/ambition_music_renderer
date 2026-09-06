"""Evidence-oriented composition diagnostics over canonical ``CompiledScore`` data.

The report intentionally avoids assigning a single quality score.  It exposes
measurements that are useful to a human or composition agent when deciding what
to revise, and consumes only the canonical compilation result plus checked-in
instrument authoring knowledge.
"""
from __future__ import annotations

from collections import defaultdict
import math
import statistics
from typing import Any, Iterable, Mapping

from ..instrument_authoring import instrument_family_profiles
from ..instrument_catalog import instrument_catalog
from ..musicir.model import CompiledScore


def _safe_mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return float(sum(rows) / len(rows)) if rows else None


def _safe_median(values: Iterable[float]) -> float | None:
    rows = list(values)
    return float(statistics.median(rows)) if rows else None


def _event_duration(event: Mapping[str, Any]) -> float:
    return max(0.0, float(event.get("end_time", 0.0)) - float(event.get("start_time", 0.0)))


def _instrument_catalog_ref(spec: Mapping[str, Any]) -> str | None:
    backend = spec.get("instrument_backend") or spec.get("backend") or {}
    if isinstance(backend, str):
        return None
    if not isinstance(backend, Mapping):
        return None
    ref = backend.get("library_ref") or backend.get("library")
    return str(ref) if ref else None


def _recommended_range(spec: Mapping[str, Any]) -> tuple[int, int] | None:
    ref = _instrument_catalog_ref(spec)
    if not ref:
        return None
    entry = instrument_catalog().get(ref)
    if entry is None:
        return None
    profile = instrument_family_profiles().get(entry.family) or {}
    value = profile.get("recommended_midi_range")
    if isinstance(value, list) and len(value) == 2:
        return int(value[0]), int(value[1])
    return None


def _group_report(compiled: CompiledScore, group: str, events: list[Mapping[str, Any]]) -> dict[str, Any]:
    instruments = sorted({str(e.get("instrument")) for e in events})
    pitches = [int(e["pitch"]) for e in events if e.get("pitch") is not None]
    velocities = [int(e["velocity"]) for e in events if e.get("velocity") is not None]
    starts = [float(e.get("start_time", 0.0)) for e in events]
    ends = [float(e.get("end_time", 0.0)) for e in events]
    span = max(ends, default=0.0) - min(starts, default=0.0)
    range_issues: list[dict[str, Any]] = []
    for name in instruments:
        spec = compiled.instrument_specs.get(name) or {}
        recommended = _recommended_range(spec)
        if recommended is None:
            continue
        inst_pitches = [int(e["pitch"]) for e in events if str(e.get("instrument")) == name and e.get("pitch") is not None]
        if not inst_pitches:
            continue
        low, high = recommended
        below = sum(p < low for p in inst_pitches)
        above = sum(p > high for p in inst_pitches)
        if below or above:
            range_issues.append({
                "instrument": name,
                "library_ref": _instrument_catalog_ref(spec),
                "recommended_midi_range": [low, high],
                "observed_midi_range": [min(inst_pitches), max(inst_pitches)],
                "notes_below": below,
                "notes_above": above,
            })
    return {
        "group": group,
        "instruments": instruments,
        "note_count": len(events),
        "active_span_s": float(max(0.0, span)),
        "notes_per_active_second": float(len(events) / span) if span > 0 else 0.0,
        "pitch_range": [min(pitches), max(pitches)] if pitches else None,
        "median_pitch": _safe_median(pitches),
        "mean_velocity": _safe_mean(velocities),
        "mean_note_duration_s": _safe_mean(_event_duration(e) for e in events),
        "recommended_range_observations": range_issues,
    }


def _section_report(section: Mapping[str, Any], events: list[Mapping[str, Any]]) -> dict[str, Any]:
    start = float(section.get("start_seconds", 0.0) or 0.0)
    end = float(section.get("end_seconds", start) or start)
    duration = max(0.0, end - start)
    pitches = [int(e["pitch"]) for e in events if e.get("pitch") is not None]
    velocities = [int(e["velocity"]) for e in events if e.get("velocity") is not None]
    by_group: dict[str, int] = defaultdict(int)
    for event in events:
        by_group[str(event.get("group") or "ungrouped")] += 1
    return {
        "id": str(section.get("id")),
        "start_s": start,
        "end_s": end,
        "duration_s": duration,
        "note_count": len(events),
        "notes_per_second": float(len(events) / duration) if duration > 0 else 0.0,
        "mean_velocity": _safe_mean(velocities),
        "pitch_range": [min(pitches), max(pitches)] if pitches else None,
        "notes_by_group": dict(sorted(by_group.items())),
    }


def _bar_signatures(compiled: CompiledScore) -> list[tuple[int, tuple[tuple[Any, ...], ...]]]:
    """Return bar-local note signatures when nominal bar metadata is available."""
    rows: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for event in compiled.note_events:
        if event.get("nominal_bar") is None:
            continue
        bar = int(event["nominal_bar"])
        beat = round(float(event.get("nominal_beat", 0.0)), 6)
        duration = round(float(event.get("end_beat", 0.0)) - float(event.get("start_beat", 0.0)), 6)
        rows[bar].append((
            str(event.get("group") or ""), beat, duration,
            int(event.get("pitch", -1)), int(event.get("velocity", -1)),
        ))
    return [(bar, tuple(sorted(values))) for bar, values in sorted(rows.items())]


def composition_quality_report(compiled: CompiledScore) -> dict[str, Any]:
    """Return deterministic measurements useful for composition review."""
    events = [e for e in compiled.note_events if e.get("event_type", "note") == "note"]
    duration = float(compiled.duration_seconds)
    by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        by_group[str(event.get("group") or compiled.groups.get(str(event.get("instrument")), "ungrouped"))].append(event)

    groups = [_group_report(compiled, name, rows) for name, rows in sorted(by_group.items())]
    sections = []
    for section in compiled.sections:
        start = float(section.get("start_seconds", 0.0) or 0.0)
        end = float(section.get("end_seconds", start) or start)
        selected = [e for e in events if start <= float(e.get("start_time", 0.0)) < end]
        sections.append(_section_report(section, selected))

    # Register overlap is evidence of potential masking, not an error.  Report
    # only pairs with enough notes to make the statistic meaningful.
    overlaps: list[dict[str, Any]] = []
    for index, left in enumerate(groups):
        if left["note_count"] < 8 or not left["pitch_range"]:
            continue
        for right in groups[index + 1:]:
            if right["note_count"] < 8 or not right["pitch_range"]:
                continue
            lo = max(left["pitch_range"][0], right["pitch_range"][0])
            hi = min(left["pitch_range"][1], right["pitch_range"][1])
            if lo <= hi:
                union_lo = min(left["pitch_range"][0], right["pitch_range"][0])
                union_hi = max(left["pitch_range"][1], right["pitch_range"][1])
                union = max(1, union_hi - union_lo + 1)
                overlap = hi - lo + 1
                overlaps.append({
                    "groups": [left["group"], right["group"]],
                    "overlap_midi_range": [lo, hi],
                    "range_overlap_fraction": float(overlap / union),
                })

    signatures = _bar_signatures(compiled)
    repeated_runs: list[dict[str, Any]] = []
    run_start = None
    run_sig = None
    run_end = None
    for bar, sig in signatures:
        if sig and sig == run_sig and run_end is not None and bar == run_end + 1:
            run_end = bar
        else:
            if run_start is not None and run_end is not None and run_end - run_start + 1 >= 3:
                repeated_runs.append({"start_bar_zero_based": run_start, "end_bar_zero_based": run_end, "count": run_end - run_start + 1})
            run_start = bar
            run_end = bar
            run_sig = sig
    if run_start is not None and run_end is not None and run_end - run_start + 1 >= 3:
        repeated_runs.append({"start_bar_zero_based": run_start, "end_bar_zero_based": run_end, "count": run_end - run_start + 1})

    velocities = [int(e["velocity"]) for e in events if e.get("velocity") is not None]
    return {
        "schema": "ambition.composition_quality_report.v1",
        "source_schema": compiled.source_schema,
        "canonical_schema": compiled.canonical_schema,
        "duration_s": duration,
        "note_count": len(events),
        "notes_per_second": float(len(events) / duration) if duration > 0 else 0.0,
        "velocity": {
            "min": min(velocities) if velocities else None,
            "max": max(velocities) if velocities else None,
            "mean": _safe_mean(velocities),
            "distinct": len(set(velocities)),
        },
        "groups": groups,
        "sections": sections,
        "register_overlap": overlaps,
        "identical_bar_runs": repeated_runs,
    }
