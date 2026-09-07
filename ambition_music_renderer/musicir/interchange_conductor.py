"""Conductor reconciliation for MusicIR <-> DAW MIDI round trips.

The MIDI conductor track is a transport representation, not the authored timing
model.  Step tempo and meter edits can map back directly.  Tempo ramps require
semantic reconstruction because Standard MIDI Files contain only sampled
``set_tempo`` events.  MusicIR holds remain source/sidecar-authoritative because
SMF has no native hold event.
"""

from __future__ import annotations

import copy
import math
from fractions import Fraction
from typing import Any, Iterable, Mapping

import mido

from .model import CompiledScore
from .normalize import MUSICIR_V2_SCHEMA, MUSICIR_V3_SCHEMA
from ..render.exact_score import ExactTempoMap, ScoreClock


CONDUCTOR_RECONCILIATION_SCHEMA = "ambition.musicir.daw_conductor_reconciliation.v1"
_RAMP_FIT_BPM_TOLERANCE = 0.05
_RAMP_MAX_SAMPLE_GAP_BEATS = 1.0
_CLOCK_VERIFY_TOLERANCE_SECONDS = 0.02


def _timing_score(compiled: CompiledScore) -> dict[str, Any] | None:
    if compiled.canonical_schema == MUSICIR_V2_SCHEMA:
        return copy.deepcopy(compiled.normalized_spec.get("score") or {})
    if compiled.canonical_schema == MUSICIR_V3_SCHEMA and compiled.authoring_graph:
        graph = compiled.authoring_graph
        score: dict[str, Any] = {
            "timebase": {"ppq": int(graph.get("ppq", compiled.pm.resolution))},
            "meter": copy.deepcopy(graph.get("meter") or []),
            "tempo": copy.deepcopy(graph.get("tempo") or []),
            "form": copy.deepcopy(graph.get("form") or []),
        }
        if graph.get("end") is not None:
            score["end"] = copy.deepcopy(graph["end"])
        return score
    return None


def _event_value_tuple(row: Mapping[str, Any], value_keys: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in value_keys)


def _match_events(
    baseline_rows: Iterable[Mapping[str, Any]],
    edited_rows: Iterable[Mapping[str, Any]],
    *,
    value_keys: tuple[str, ...],
    prefer_text_identity: bool = False,
) -> dict[str, Any]:
    """Build an auditable event-level diff without using it as apply authority."""

    baseline = [copy.deepcopy(dict(row)) for row in baseline_rows]
    edited = [copy.deepcopy(dict(row)) for row in edited_rows]
    remaining_base = set(range(len(baseline)))
    remaining_edit = set(range(len(edited)))
    matches: list[dict[str, Any]] = []

    # Exact events first.  This keeps large sampled ramps readable: only changed
    # samples appear as modifications/deletions/additions.
    edited_exact: dict[tuple[Any, ...], list[int]] = {}
    for idx, row in enumerate(edited):
        key = (int(row.get("tick", 0)),) + _event_value_tuple(row, value_keys)
        edited_exact.setdefault(key, []).append(idx)
    for bi, row in enumerate(baseline):
        key = (int(row.get("tick", 0)),) + _event_value_tuple(row, value_keys)
        ei = next((idx for idx in edited_exact.get(key, []) if idx in remaining_edit), None)
        if ei is None:
            continue
        remaining_base.remove(bi)
        remaining_edit.remove(ei)
        matches.append(
            {
                "status": "unchanged",
                "baseline": row,
                "edited": edited[ei],
                "changes": [],
            }
        )

    # Prefer marker text identity before nearest-coordinate fallback.
    if prefer_text_identity:
        for bi in sorted(tuple(remaining_base)):
            base = baseline[bi]
            candidates = [
                ei
                for ei in remaining_edit
                if str(edited[ei].get("text", "")) == str(base.get("text", ""))
            ]
            if not candidates:
                continue
            ei = min(candidates, key=lambda idx: abs(int(edited[idx].get("tick", 0)) - int(base.get("tick", 0))))
            remaining_base.remove(bi)
            remaining_edit.remove(ei)
            edit = edited[ei]
            changes = []
            if int(base.get("tick", 0)) != int(edit.get("tick", 0)):
                changes.append("moved")
            matches.append(
                {
                    "status": "modified" if changes else "unchanged",
                    "baseline": base,
                    "edited": edit,
                    "changes": changes,
                }
            )

    # Greedy nearest-coordinate pairing gives changed values a stable identity
    # while leaving cardinality changes explicit.
    candidates: list[tuple[int, int, int]] = []
    for bi in remaining_base:
        for ei in remaining_edit:
            candidates.append(
                (
                    abs(int(edited[ei].get("tick", 0)) - int(baseline[bi].get("tick", 0))),
                    bi,
                    ei,
                )
            )
    for _distance, bi, ei in sorted(candidates):
        if bi not in remaining_base or ei not in remaining_edit:
            continue
        remaining_base.remove(bi)
        remaining_edit.remove(ei)
        base = baseline[bi]
        edit = edited[ei]
        changes: list[str] = []
        if int(base.get("tick", 0)) != int(edit.get("tick", 0)):
            changes.append("moved")
        for key in value_keys:
            if base.get(key) != edit.get(key):
                changes.append(key)
        matches.append(
            {
                "status": "modified" if changes else "unchanged",
                "baseline": base,
                "edited": edit,
                "changes": changes,
            }
        )

    deleted = [{"status": "deleted", "baseline": baseline[idx]} for idx in sorted(remaining_base)]
    added = [{"status": "added", "edited": edited[idx]} for idx in sorted(remaining_edit)]
    matches.sort(
        key=lambda row: (
            int((row.get("edited") or row.get("baseline") or {}).get("tick", 0)),
            tuple(str((row.get("edited") or row.get("baseline") or {}).get(key, "")) for key in value_keys),
        )
    )
    return {"matches": matches, "deleted": deleted, "added": added}


def _change_count(diff: Mapping[str, Any]) -> int:
    return (
        sum(row.get("status") == "modified" for row in diff.get("matches", []) or [])
        + len(diff.get("deleted", []) or [])
        + len(diff.get("added", []) or [])
    )


def _tempo_bpm(row: Mapping[str, Any]) -> float:
    return float(mido.tempo2bpm(int(row["tempo"])))


def _curve_bpm(curve: str, start_bpm: float, end_bpm: float, frac: float) -> float:
    frac = max(0.0, min(1.0, float(frac)))
    if curve in {"linear", "smooth"}:
        return start_bpm + (end_bpm - start_bpm) * frac
    if curve == "exponential":
        if start_bpm <= 0 or end_bpm <= 0:
            return math.inf
        return start_bpm * ((end_bpm / start_bpm) ** frac)
    if curve == "step":
        return start_bpm
    return math.inf


def _fit_ramp(points: list[dict[str, Any]], *, curve: str) -> dict[str, Any]:
    start_tick = int(points[0]["tick"])
    end_tick = int(points[-1]["tick"])
    start_bpm = _tempo_bpm(points[0])
    end_bpm = _tempo_bpm(points[-1])
    if end_tick <= start_tick:
        return {"ok": False, "max_error_bpm": math.inf}
    errors: list[float] = []
    for row in points:
        frac = (int(row["tick"]) - start_tick) / float(end_tick - start_tick)
        predicted = _curve_bpm(curve, start_bpm, end_bpm, frac)
        errors.append(abs(predicted - _tempo_bpm(row)))
    max_error = max(errors, default=0.0)
    return {
        "ok": max_error <= _RAMP_FIT_BPM_TOLERANCE,
        "curve": curve,
        "start_tick": start_tick,
        "end_tick": end_tick,
        "start_bpm": start_bpm,
        "end_bpm": end_bpm,
        "max_error_bpm": max_error,
        "sample_count": len(points),
    }


def _dense_runs(rows: list[dict[str, Any]], *, ppq: int) -> list[list[dict[str, Any]]]:
    if not rows:
        return []
    max_gap = max(1, int(round(ppq * _RAMP_MAX_SAMPLE_GAP_BEATS)))
    runs: list[list[dict[str, Any]]] = []
    current = [rows[0]]
    for row in rows[1:]:
        gap = int(row["tick"]) - int(current[-1]["tick"])
        if 0 < gap <= max_gap:
            current.append(row)
        else:
            runs.append(current)
            current = [row]
    runs.append(current)
    return runs


def _monotone_bpm(points: list[dict[str, Any]]) -> bool:
    values = [_tempo_bpm(row) for row in points]
    if len(values) < 2:
        return False
    diffs = [b - a for a, b in zip(values, values[1:])]
    epsilon = 1e-4
    return all(delta >= -epsilon for delta in diffs) or all(delta <= epsilon for delta in diffs)


def _best_curve_fit(points: list[dict[str, Any]], *, preferred: str | None = None) -> dict[str, Any] | None:
    if len(points) < 3 or not _monotone_bpm(points):
        return None
    start_bpm = _tempo_bpm(points[0])
    end_bpm = _tempo_bpm(points[-1])
    if abs(start_bpm - end_bpm) < 0.05:
        return None
    order: list[str] = []
    if preferred in {"linear", "smooth", "exponential"}:
        order.append(str(preferred))
    for curve in ("linear", "exponential"):
        if curve not in order:
            order.append(curve)
    fits = [_fit_ramp(points, curve=curve) for curve in order]
    good = [fit for fit in fits if fit["ok"]]
    if not good:
        return None
    # Preserve the baseline curve when it still fits.  ``smooth`` and ``linear``
    # currently have the same BPM-coordinate sampling contract, so MIDI cannot
    # distinguish them and source semantics win the tie.
    if preferred and good[0]["curve"] == preferred:
        return good[0]
    return min(good, key=lambda fit: float(fit["max_error_bpm"]))


def _tempo_events_bpm_at_tick(events: list[dict[str, Any]], tick: int) -> float:
    current = 120.0
    tick = int(tick)
    for row in sorted(events, key=lambda item: int(item.get("tick", 0))):
        start = int(row.get("tick", 0))
        if start > tick:
            break
        bpm = row.get("bpm", current)
        if isinstance(bpm, (list, tuple)):
            start_bpm, end_bpm = map(float, bpm)
            end_pos = row.get("to") or row.get("end")
            end_tick = int((end_pos or {}).get("tick", start)) if isinstance(end_pos, Mapping) else start
            if start <= tick <= end_tick and end_tick > start:
                frac = (tick - start) / float(end_tick - start)
                return float(_curve_bpm(str(row.get("curve", "linear")), start_bpm, end_bpm, frac))
            current = end_bpm
        else:
            current = float(bpm)
    return current


def _merge_holds_into_tempo_events(
    events: list[dict[str, Any]],
    holds: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [copy.deepcopy(row) for row in events]
    preserved: list[dict[str, Any]] = []
    for hold in holds:
        tick = int(hold["tick"])
        seconds = float(hold["seconds"])
        candidates = [row for row in rows if int(row.get("tick", 0)) == tick]
        if candidates:
            candidates[-1]["hold_seconds"] = seconds
        else:
            # Holds carry pause semantics, not a frozen baseline BPM.  If the
            # DAW changes surrounding tempo, anchor the hold with the
            # reconstructed tempo in force at that tick so the marker remains a
            # no-op for tempo while preserving the exact pause.
            rows.append(
                {
                    "tick": tick,
                    "bpm": float(_tempo_events_bpm_at_tick(rows, tick)),
                    "hold_seconds": seconds,
                }
            )
        preserved.append({"tick": tick, "seconds": seconds})
    rows.sort(key=lambda row: int(row.get("tick", 0)))
    return rows, preserved


def _tempo_apply_plan(
    compiled: CompiledScore,
    edited_tempos: Iterable[Mapping[str, Any]],
    *,
    ppq: int,
    baseline_tempos: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = sorted((copy.deepcopy(dict(row)) for row in edited_tempos), key=lambda row: int(row["tick"]))
    blocked: list[str] = []
    if not rows:
        return {
            "supported": False,
            "blocked_by": ["tempo_map_has_no_initial_event"],
            "musicir": [],
            "ramps": [],
        }
    if int(rows[0]["tick"]) != 0:
        blocked.append("tempo_map_must_start_at_tick_zero")
    ticks = [int(row["tick"]) for row in rows]
    if len(set(ticks)) != len(ticks):
        blocked.append("multiple_tempo_events_at_same_tick_are_ambiguous")
    if any(int(row.get("tempo", 0)) <= 0 for row in rows):
        blocked.append("tempo_event_must_be_positive")

    timing = _timing_score(compiled)
    if timing is None:
        return {
            "supported": False,
            "blocked_by": blocked + ["source_has_no_exact_conductor_clock"],
            "musicir": [],
            "ramps": [],
        }
    clock = ScoreClock(timing)
    exact_segments = list((compiled.exact_metadata or {}).get("tempo_segments", []) or [])
    holds = list((compiled.exact_metadata or {}).get("holds", []) or [])
    baseline_rows = sorted((copy.deepcopy(dict(row)) for row in baseline_tempos), key=lambda row: int(row["tick"]))

    consumed: set[int] = set()
    reconstructed: list[dict[str, Any]] = []
    ramp_reports: list[dict[str, Any]] = []

    baseline_ramps = [
        seg
        for seg in exact_segments
        if str(seg.get("curve", "step")) != "step"
        and abs(float(seg.get("start_bpm", 0.0)) - float(seg.get("end_bpm", 0.0))) > 1e-9
        and seg.get("end_tick") is not None
    ]
    for seg in baseline_ramps:
        start = int(seg["start_tick"])
        end = int(seg["end_tick"])
        point_indices = [idx for idx, row in enumerate(rows) if start <= int(row["tick"]) <= end]
        points = [rows[idx] for idx in point_indices]
        boundary_ok = bool(points) and int(points[0]["tick"]) == start and int(points[-1]["tick"]) == end
        baseline_samples = [row for row in baseline_rows if start <= int(row["tick"]) <= end]
        if not boundary_ok:
            blocked.append(f"tempo_ramp_boundary_move_needs_manual_resolution:{start}-{end}")
            ramp_reports.append(
                {
                    "baseline_start_tick": start,
                    "baseline_end_tick": end,
                    "status": "blocked",
                    "reason": "boundary_event_missing_or_moved",
                }
            )
            continue
        if len(baseline_samples) > 2 and len(points) < 3:
            blocked.append(f"tempo_ramp_sampling_removed:{start}-{end}")
            ramp_reports.append(
                {
                    "baseline_start_tick": start,
                    "baseline_end_tick": end,
                    "status": "blocked",
                    "reason": "insufficient_ramp_samples",
                    "edited_sample_count": len(points),
                }
            )
            continue
        max_gap = max(
            [int(b["tick"]) - int(a["tick"]) for a, b in zip(points, points[1:])]
            or [0]
        )
        if max_gap > max(1, int(ppq * _RAMP_MAX_SAMPLE_GAP_BEATS)):
            blocked.append(f"tempo_ramp_sampling_too_sparse:{start}-{end}")
            ramp_reports.append(
                {
                    "baseline_start_tick": start,
                    "baseline_end_tick": end,
                    "status": "blocked",
                    "reason": "sampling_gap_too_large",
                    "max_gap_ticks": max_gap,
                }
            )
            continue
        fit = _best_curve_fit(points, preferred=str(seg.get("curve", "linear")))
        if fit is None:
            # A deliberate flattening is representable as a step map; do not
            # force it back into a ramp merely because the baseline was a ramp.
            values = [_tempo_bpm(row) for row in points]
            if values and max(values) - min(values) <= _RAMP_FIT_BPM_TOLERANCE:
                reconstructed.append({"tick": start, "bpm": float(sum(values) / len(values))})
                consumed.update(point_indices)
                ramp_reports.append(
                    {
                        "baseline_start_tick": start,
                        "baseline_end_tick": end,
                        "status": "flattened_to_step",
                        "bpm": float(sum(values) / len(values)),
                        "sample_count": len(points),
                    }
                )
                continue
            blocked.append(f"tempo_ramp_samples_do_not_fit_supported_curve:{start}-{end}")
            ramp_reports.append(
                {
                    "baseline_start_tick": start,
                    "baseline_end_tick": end,
                    "status": "blocked",
                    "reason": "sample_fit_failed",
                    "sample_count": len(points),
                }
            )
            continue
        reconstructed.append(
            {
                "tick": int(fit["start_tick"]),
                "bpm": [float(fit["start_bpm"]), float(fit["end_bpm"])],
                "to": {"tick": int(fit["end_tick"])},
                "curve": str(fit["curve"]),
            }
        )
        consumed.update(point_indices)
        ramp_reports.append(
            {
                "baseline_start_tick": start,
                "baseline_end_tick": end,
                "status": "reconstructed",
                "curve": str(fit["curve"]),
                "start_bpm": float(fit["start_bpm"]),
                "end_bpm": float(fit["end_bpm"]),
                "sample_count": int(fit["sample_count"]),
                "max_error_bpm": round(float(fit["max_error_bpm"]), 9),
            }
        )

    # Dense monotone runs outside baseline ramps can represent a newly drawn DAW
    # tempo ramp.  The threshold is intentionally strict so a few authored step
    # changes never collapse into a curve by accident.
    remaining_index_rows = [(idx, row) for idx, row in enumerate(rows) if idx not in consumed]
    remaining_rows = [row for _idx, row in remaining_index_rows]
    offset = 0
    for run in _dense_runs(remaining_rows, ppq=ppq):
        run_len = len(run)
        run_pairs = remaining_index_rows[offset : offset + run_len]
        offset += run_len
        if run_len < 5:
            continue
        if int(run[-1]["tick"]) - int(run[0]["tick"]) < ppq:
            continue
        fit = _best_curve_fit(run)
        if fit is None:
            continue
        reconstructed.append(
            {
                "tick": int(fit["start_tick"]),
                "bpm": [float(fit["start_bpm"]), float(fit["end_bpm"])],
                "to": {"tick": int(fit["end_tick"])},
                "curve": str(fit["curve"]),
            }
        )
        indices = [idx for idx, _row in run_pairs]
        consumed.update(indices)
        ramp_reports.append(
            {
                "status": "inferred_new_ramp",
                "curve": str(fit["curve"]),
                "start_tick": int(fit["start_tick"]),
                "end_tick": int(fit["end_tick"]),
                "start_bpm": float(fit["start_bpm"]),
                "end_bpm": float(fit["end_bpm"]),
                "sample_count": int(fit["sample_count"]),
                "max_error_bpm": round(float(fit["max_error_bpm"]), 9),
            }
        )

    for idx, row in enumerate(rows):
        if idx in consumed:
            continue
        reconstructed.append({"tick": int(row["tick"]), "bpm": _tempo_bpm(row)})
    reconstructed.sort(key=lambda row: int(row["tick"]))

    # Ensure a reconstructed ramp did not swallow a simultaneous step event.
    start_ticks = [int(row["tick"]) for row in reconstructed]
    if len(start_ticks) != len(set(start_ticks)):
        blocked.append("tempo_reconstruction_has_overlapping_events")

    reconstructed, preserved_holds = _merge_holds_into_tempo_events(
        reconstructed,
        holds,
    )
    return {
        "supported": not blocked,
        "blocked_by": list(dict.fromkeys(blocked)),
        "musicir": reconstructed,
        "ramps": ramp_reports,
        "holds": {
            "policy": "sidecar_authoritative_preserved",
            "preserved": preserved_holds,
        },
    }


def _meter_apply_plan(edited_rows: Iterable[Mapping[str, Any]], *, ppq: int) -> dict[str, Any]:
    rows = sorted((copy.deepcopy(dict(row)) for row in edited_rows), key=lambda row: int(row["tick"]))
    blocked: list[str] = []
    if not rows:
        return {"supported": False, "blocked_by": ["meter_map_has_no_initial_signature"], "musicir": []}
    if int(rows[0]["tick"]) != 0:
        blocked.append("meter_map_must_start_at_tick_zero")
    ticks = [int(row["tick"]) for row in rows]
    if len(ticks) != len(set(ticks)):
        blocked.append("multiple_meter_events_at_same_tick_are_ambiguous")

    musicir: list[dict[str, Any]] = []
    current_bar = 1
    previous_tick = 0
    previous_tpb: int | None = None
    for index, row in enumerate(rows):
        tick = int(row["tick"])
        numerator = int(row["numerator"])
        denominator = int(row["denominator"])
        if numerator <= 0 or denominator <= 0:
            blocked.append(f"invalid_meter_signature_at_tick:{tick}")
            continue
        if index > 0 and previous_tpb is not None:
            delta = tick - previous_tick
            if delta < 0 or delta % previous_tpb != 0:
                blocked.append(f"meter_change_not_on_bar_boundary:{tick}")
            else:
                current_bar += delta // previous_tpb
        tpb = Fraction(numerator * 4 * ppq, denominator)
        if tpb.denominator != 1:
            blocked.append(f"meter_not_exact_at_ppq:{numerator}/{denominator}@{tick}")
            previous_tpb = None
        else:
            previous_tpb = int(tpb)
        musicir.append({"bar": int(current_bar), "signature": f"{numerator}/{denominator}"})
        previous_tick = tick
    return {
        "supported": not blocked,
        "blocked_by": list(dict.fromkeys(blocked)),
        "musicir": musicir,
    }


def _marker_apply_plan(
    compiled: CompiledScore,
    manifest: Mapping[str, Any],
    baseline_markers: Iterable[Mapping[str, Any]],
    edited_markers: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    baseline = sorted((copy.deepcopy(dict(row)) for row in baseline_markers), key=lambda row: int(row["tick"]))
    edited = sorted((copy.deepcopy(dict(row)) for row in edited_markers), key=lambda row: int(row["tick"]))
    sections = list(manifest.get("form", []) or compiled.sections or [])
    blocked: list[str] = []
    if len(edited) != len(baseline):
        blocked.append("form_marker_add_delete_changes_need_manual_topology_resolution")
    if len(sections) != len(baseline):
        blocked.append("form_marker_baseline_does_not_match_compiled_form")
    if len(edited) > 1 and any(int(b["tick"]) <= int(a["tick"]) for a, b in zip(edited, edited[1:])):
        blocked.append("form_markers_must_remain_strictly_ordered")

    rows: list[dict[str, Any]] = []
    for index in range(min(len(sections), len(baseline), len(edited))):
        section = sections[index]
        base = baseline[index]
        edit = edited[index]
        baseline_start = int(section.get("start_tick", base.get("tick", 0)))
        baseline_end = int(section.get("end_tick", baseline_start))
        edited_start = int(edit["tick"])
        if baseline_end > baseline_start and index + 1 >= len(sections) and edited_start >= baseline_end:
            blocked.append(f"form_marker_moves_past_section_end:{section.get('id', index)}")
        rows.append(
            {
                "id": str(section.get("id", f"section_{index}")),
                "baseline_start_tick": baseline_start,
                "baseline_end_tick": baseline_end,
                "edited_start_tick": edited_start,
                "baseline_text": str(base.get("text", section.get("label", section.get("id", "")))),
                "edited_text": str(edit.get("text", "")),
            }
        )
    return {
        "supported": not blocked,
        "blocked_by": list(dict.fromkeys(blocked)),
        "sections": rows,
    }


def reconcile_conductor(
    compiled: CompiledScore,
    manifest: Mapping[str, Any],
    edited_conductor: Mapping[str, Any],
    *,
    ppq: int,
) -> dict[str, Any]:
    """Reconcile DAW conductor events against the exported baseline."""

    baseline = copy.deepcopy((manifest.get("midi") or {}).get("conductor") or {})
    edited = copy.deepcopy(dict(edited_conductor or {}))
    for key in ("tempos", "time_signatures", "markers"):
        baseline.setdefault(key, [])
        edited.setdefault(key, [])

    tempo_diff = _match_events(baseline["tempos"], edited["tempos"], value_keys=("tempo",))
    meter_diff = _match_events(
        baseline["time_signatures"],
        edited["time_signatures"],
        value_keys=("numerator", "denominator"),
    )
    marker_diff = _match_events(
        baseline["markers"],
        edited["markers"],
        value_keys=("text",),
        prefer_text_identity=True,
    )
    tempo_changes = _change_count(tempo_diff)
    meter_changes = _change_count(meter_diff)
    marker_changes = _change_count(marker_diff)
    changed = bool(tempo_changes or meter_changes or marker_changes)

    if changed:
        tempo_plan = _tempo_apply_plan(
            compiled,
            edited["tempos"],
            ppq=ppq,
            baseline_tempos=baseline["tempos"],
        )
        meter_plan = _meter_apply_plan(edited["time_signatures"], ppq=ppq)
        marker_plan = _marker_apply_plan(
            compiled,
            manifest,
            baseline["markers"],
            edited["markers"],
        )
    else:
        tempo_plan = {"supported": True, "blocked_by": [], "musicir": None, "ramps": [], "holds": {"policy": "unchanged"}}
        meter_plan = {"supported": True, "blocked_by": [], "musicir": None}
        marker_plan = {"supported": True, "blocked_by": [], "sections": []}

    blocked = list(
        dict.fromkeys(
            list(tempo_plan.get("blocked_by", []) or [])
            + list(meter_plan.get("blocked_by", []) or [])
            + list(marker_plan.get("blocked_by", []) or [])
        )
    )
    return {
        "schema": CONDUCTOR_RECONCILIATION_SCHEMA,
        "changed": changed,
        "diff": {
            "tempos": tempo_diff,
            "time_signatures": meter_diff,
            "markers": marker_diff,
        },
        "summary": {
            "tempo_event_changes": tempo_changes,
            "meter_event_changes": meter_changes,
            "marker_changes": marker_changes,
        },
        "tempo": tempo_plan,
        "meter": meter_plan,
        "form_markers": marker_plan,
        "baseline_end_tick": int((compiled.exact_metadata or {}).get("end_tick", 0) or 0),
        "apply": {
            "supported": not blocked,
            "blocked_by": blocked,
        },
    }


def apply_conductor_to_v3(
    spec: Mapping[str, Any],
    conductor_report: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a supported semantic conductor reconciliation to a v3 source."""

    out = copy.deepcopy(dict(spec))
    if not conductor_report.get("changed"):
        return out, {"changed": False, "tempo": False, "meter": False, "form_markers": False}
    if not bool((conductor_report.get("apply") or {}).get("supported")):
        blocked = ", ".join((conductor_report.get("apply") or {}).get("blocked_by", []) or [])
        raise ValueError(f"conductor reconciliation is not safely applicable: {blocked}")
    if str(out.get("schema")) != MUSICIR_V3_SCHEMA:
        raise ValueError("automatic conductor apply currently requires MusicIR v3")

    tempo_plan = conductor_report.get("tempo") or {}
    meter_plan = conductor_report.get("meter") or {}
    marker_plan = conductor_report.get("form_markers") or {}
    tempo_changed = int((conductor_report.get("summary") or {}).get("tempo_event_changes", 0)) > 0
    meter_changed = int((conductor_report.get("summary") or {}).get("meter_event_changes", 0)) > 0
    marker_changed = int((conductor_report.get("summary") or {}).get("marker_changes", 0)) > 0

    if tempo_changed:
        out["tempo"] = copy.deepcopy(tempo_plan.get("musicir") or [])
    if meter_changed:
        out["meter"] = copy.deepcopy(meter_plan.get("musicir") or [])
        # Meter changes redefine bar-addressed positions.  Preserve the original
        # exact score end; downstream compilation verification will catch any
        # remaining bar-relative musical content whose tick identity changed.
        end_tick = int(conductor_report.get("baseline_end_tick", 0) or 0)
        if end_tick > 0:
            out["end"] = {"tick": end_tick}

    if marker_changed or meter_changed:
        source_form = list(out.get("form", []) or [])
        section_rows = list(marker_plan.get("sections", []) or [])
        if source_form and len(source_form) == len(section_rows):
            by_id = {str(row.get("id")): row for row in source_form}
            rebuilt: list[dict[str, Any]] = []
            for index, section in enumerate(section_rows):
                section_id = str(section["id"])
                if section_id not in by_id:
                    raise ValueError(f"current MusicIR form has no section {section_id!r}")
                row = copy.deepcopy(by_id[section_id])
                start = int(section["edited_start_tick"])
                if index + 1 < len(section_rows):
                    baseline_end = int(section["baseline_end_tick"])
                    next_base = int(section_rows[index + 1]["baseline_start_tick"])
                    if baseline_end == next_base:
                        end = int(section_rows[index + 1]["edited_start_tick"])
                    else:
                        end = baseline_end
                else:
                    end = int(section["baseline_end_tick"])
                row["from"] = {"tick": start}
                row["to"] = {"tick": end}
                edited_text = str(section.get("edited_text", ""))
                if edited_text and edited_text != section_id:
                    row["label"] = edited_text
                elif row.get("label") is not None and str(row.get("label")) == str(section.get("baseline_text", "")):
                    row.pop("label", None)
                rebuilt.append(row)
            out["form"] = rebuilt
        elif marker_changed:
            raise ValueError("form marker edits require an explicit MusicIR v3 form")

    return out, {
        "changed": True,
        "tempo": tempo_changed,
        "meter": meter_changed,
        "form_markers": marker_changed,
        "tempo_ramps": copy.deepcopy(tempo_plan.get("ramps", []) or []),
        "holds": copy.deepcopy(tempo_plan.get("holds", {}) or {}),
    }


def _midi_time_at_ticks(tempo_rows: list[dict[str, Any]], *, ppq: int, ticks: Iterable[int]) -> dict[int, float]:
    rows = sorted(tempo_rows, key=lambda row: int(row["tick"]))
    if not rows or int(rows[0]["tick"]) != 0:
        return {}
    targets = sorted(set(max(0, int(tick)) for tick in ticks))
    result: dict[int, float] = {}
    event_index = 0
    current_tick = 0
    current_tempo = int(rows[0]["tempo"])
    current_seconds = 0.0
    while event_index + 1 < len(rows) and int(rows[event_index + 1]["tick"]) == 0:
        event_index += 1
        current_tempo = int(rows[event_index]["tempo"])
    for target in targets:
        while event_index + 1 < len(rows) and int(rows[event_index + 1]["tick"]) <= target:
            next_row = rows[event_index + 1]
            next_tick = int(next_row["tick"])
            current_seconds += (next_tick - current_tick) * current_tempo / 1_000_000.0 / ppq
            current_tick = next_tick
            event_index += 1
            current_tempo = int(next_row["tempo"])
        result[target] = current_seconds + (target - current_tick) * current_tempo / 1_000_000.0 / ppq
    return result


def verify_conductor_against_snapshot(
    compiled: CompiledScore,
    edited_conductor: Mapping[str, Any],
    *,
    ppq: int,
) -> dict[str, Any]:
    """Verify reconstructed MusicIR conductor semantics against edited MIDI."""

    from .interchange import build_interchange_manifest

    generated = ((build_interchange_manifest(compiled, midi_filename="verification.mid").get("midi") or {}).get("conductor") or {})
    edited = copy.deepcopy(dict(edited_conductor or {}))
    mismatches: list[dict[str, Any]] = []

    expected_meter = generated.get("time_signatures", []) or []
    edited_meter = edited.get("time_signatures", []) or []
    if expected_meter != edited_meter:
        mismatches.append(
            {
                "reason": "meter_mismatch",
                "compiled": expected_meter,
                "edited": edited_meter,
            }
        )
    expected_markers = generated.get("markers", []) or []
    edited_markers = edited.get("markers", []) or []
    if expected_markers != edited_markers:
        mismatches.append(
            {
                "reason": "form_marker_mismatch",
                "compiled": expected_markers,
                "edited": edited_markers,
            }
        )

    expected_tempos = generated.get("tempos", []) or []
    edited_tempos = edited.get("tempos", []) or []
    exact_segments = list((compiled.exact_metadata or {}).get("tempo_segments", []) or [])
    has_ramp = any(
        str(seg.get("curve", "step")) != "step"
        and abs(float(seg.get("start_bpm", 0.0)) - float(seg.get("end_bpm", 0.0))) > 1e-9
        for seg in exact_segments
    )
    tempo_detail: dict[str, Any]
    if not has_ramp:
        tempo_ok = expected_tempos == edited_tempos
        tempo_detail = {"mode": "exact_step_events", "ok": tempo_ok}
        if not tempo_ok:
            mismatches.append(
                {
                    "reason": "tempo_event_mismatch",
                    "compiled": expected_tempos,
                    "edited": edited_tempos,
                }
            )
    else:
        timing = _timing_score(compiled)
        assert timing is not None
        clock = ScoreClock(timing)
        tempo_map = ExactTempoMap(timing, clock).bind_ppq(clock.ppq)
        point_errors: list[dict[str, Any]] = []
        for row in edited_tempos:
            tick = int(row["tick"])
            expected_micros = int(mido.bpm2tempo(float(tempo_map.bpm_at_tick(tick))))
            delta = abs(expected_micros - int(row["tempo"]))
            if delta > 4:
                point_errors.append(
                    {
                        "tick": tick,
                        "edited_tempo": int(row["tempo"]),
                        "compiled_tempo": expected_micros,
                        "delta_microseconds_per_quarter": delta,
                    }
                )
        end_tick = int((compiled.exact_metadata or {}).get("end_tick", 0) or 0)
        check_ticks = sorted(
            set([end_tick] + [int(row["tick"]) for row in expected_tempos] + [int(row["tick"]) for row in edited_tempos])
        )
        expected_times = _midi_time_at_ticks(expected_tempos, ppq=ppq, ticks=check_ticks)
        edited_times = _midi_time_at_ticks(list(edited_tempos), ppq=ppq, ticks=check_ticks)
        clock_errors = [
            abs(float(expected_times.get(tick, 0.0)) - float(edited_times.get(tick, 0.0)))
            for tick in check_ticks
        ]
        max_clock_error = max(clock_errors, default=0.0)
        tempo_ok = not point_errors and max_clock_error <= _CLOCK_VERIFY_TOLERANCE_SECONDS
        tempo_detail = {
            "mode": "semantic_ramp_and_smf_clock",
            "ok": tempo_ok,
            "point_errors": point_errors[:32],
            "max_smf_clock_error_seconds": max_clock_error,
            "tolerance_seconds": _CLOCK_VERIFY_TOLERANCE_SECONDS,
        }
        if not tempo_ok:
            mismatches.append(
                {
                    "reason": "tempo_ramp_semantic_mismatch",
                    **tempo_detail,
                }
            )

    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "tempo": tempo_detail,
        "holds": {
            "policy": "MusicIR_sidecar_authoritative",
            "compiled": copy.deepcopy((compiled.exact_metadata or {}).get("holds", []) or []),
        },
    }
