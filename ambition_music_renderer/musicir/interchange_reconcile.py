"""Reverse DAW interchange: reconcile edited MIDI and lower affected v3 clips.

This module is the reverse half of :mod:`ambition_music_renderer.musicir.interchange`.
MIDI remains transport, the interchange sidecar remains the baseline, and MusicIR
remains the authored source of truth.
"""

from __future__ import annotations

import copy
import json
from bisect import bisect_left, bisect_right
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .graph import normalize_v3_score_graph
from .interchange_conductor import (
    apply_conductor_to_v3,
    reconcile_conductor,
    verify_conductor_against_snapshot,
)
from .model import CompiledScore, compiled_score_fingerprint
from .normalize import MUSICIR_V3_SCHEMA
from ..render.exact_score import ScoreClock


RECONCILIATION_SCHEMA = "ambition.musicir.daw_reconciliation.v1"


class DawRoundtripError(ValueError):
    """Raised when an interchange baseline cannot be reconciled safely."""


def load_interchange_manifest(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf8"))
    if not isinstance(data, dict) or not str(data.get("schema", "")).startswith(
        "ambition.musicir.daw_interchange."
    ):
        raise DawRoundtripError(f"not an Ambition MusicIR interchange sidecar: {path}")
    return data


def _rescale_tick(value: int, *, source_ppq: int, target_ppq: int) -> tuple[int, bool]:
    exact = Fraction(int(value) * int(target_ppq), int(source_ppq))
    rounded = int(round(float(exact)))
    return rounded, exact.denominator == 1


def normalize_snapshot_ppq(snapshot: Mapping[str, Any], *, target_ppq: int) -> dict[str, Any]:
    """Return a snapshot expressed on ``target_ppq`` while recording quantization."""

    source_ppq = int(snapshot.get("ticks_per_beat", 0) or 0)
    if source_ppq <= 0:
        raise DawRoundtripError("edited MIDI has no positive ticks_per_beat")
    out = copy.deepcopy(dict(snapshot))
    quantized = 0

    def scale(row: dict[str, Any], key: str) -> None:
        nonlocal quantized
        row[key], exact = _rescale_tick(
            int(row[key]), source_ppq=source_ppq, target_ppq=int(target_ppq)
        )
        if not exact:
            quantized += 1

    for track in out.get("tracks", []) or []:
        for row in track.get("notes", []) or []:
            scale(row, "start_tick")
            scale(row, "end_tick")
        for row in track.get("controls", []) or []:
            scale(row, "tick")
        for row in track.get("pitch_bends", []) or []:
            scale(row, "tick")
        for row in track.get("program_changes", []) or []:
            scale(row, "tick")
    conductor = out.get("conductor") or {}
    for key in ("tempos", "time_signatures", "markers"):
        for row in conductor.get(key, []) or []:
            scale(row, "tick")
    out["source_ticks_per_beat"] = source_ppq
    out["ticks_per_beat"] = int(target_ppq)
    out["ppq_rescale_quantized_coordinates"] = quantized
    return out


def _track_lookup(snapshot: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot.get("tracks", []) or []:
        by_name.setdefault(str(row.get("name", "")), []).append(row)
    return by_name


def _match_track(
    baseline_track: Mapping[str, Any],
    edited_snapshot: Mapping[str, Any],
    *,
    manifest_index: int,
) -> tuple[dict[str, Any] | None, str]:
    name = str(baseline_track.get("track_id", baseline_track.get("instrument", "")))
    by_name = _track_lookup(edited_snapshot)
    exact = by_name.get(name, [])
    if len(exact) == 1:
        return exact[0], "track_name"
    tracks = list(edited_snapshot.get("tracks", []) or [])
    midi_index = int(baseline_track.get("midi_track_index", manifest_index + 1))
    if 0 <= midi_index < len(tracks):
        candidate = tracks[midi_index]
        if candidate.get("notes") or candidate.get("controls") or candidate.get("pitch_bends"):
            return candidate, "midi_track_index"
    return None, "missing"


def _note_key(row: Mapping[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(row.get("start_tick", 0)),
        int(row.get("end_tick", 0)),
        int(row.get("pitch", -1)),
        int(row.get("velocity", 0)),
    )


def _note_cost(a: Mapping[str, Any], b: Mapping[str, Any], *, ppq: int) -> float:
    start = abs(int(a["start_tick"]) - int(b["start_tick"])) / max(1, ppq)
    da = max(1, int(a["end_tick"]) - int(a["start_tick"]))
    db = max(1, int(b["end_tick"]) - int(b["start_tick"]))
    duration = abs(da - db) / max(1, ppq)
    pitch = abs(int(a["pitch"]) - int(b["pitch"]))
    velocity = abs(int(a["velocity"]) - int(b["velocity"])) / 16.0
    ordinal = abs(int(a.get("ordinal", 0)) - int(b.get("ordinal", 0)))
    return 2.0 * start + 1.25 * duration + 0.7 * pitch + 0.15 * velocity + 0.02 * ordinal


def _classify_note_change(baseline: Mapping[str, Any], edited: Mapping[str, Any]) -> list[str]:
    changes: list[str] = []
    if int(baseline["start_tick"]) != int(edited["start_tick"]):
        changes.append("moved")
    baseline_dur = int(baseline["end_tick"]) - int(baseline["start_tick"])
    edited_dur = int(edited["end_tick"]) - int(edited["start_tick"])
    if baseline_dur != edited_dur:
        changes.append("resized")
    if int(baseline["pitch"]) != int(edited["pitch"]):
        changes.append("repitched")
    if int(baseline["velocity"]) != int(edited["velocity"]):
        changes.append("velocity")
    return changes


def _match_notes(
    baseline_rows: Iterable[Mapping[str, Any]],
    edited_rows: Iterable[Mapping[str, Any]],
    *,
    ppq: int,
) -> dict[str, Any]:
    baseline = [copy.deepcopy(dict(row)) for row in baseline_rows]
    edited = [copy.deepcopy(dict(row)) for row in edited_rows]
    for index, row in enumerate(edited):
        row.setdefault("ordinal", index)

    edited_by_key: dict[tuple[int, int, int, int], list[int]] = {}
    for index, row in enumerate(edited):
        edited_by_key.setdefault(_note_key(row), []).append(index)

    matches: list[dict[str, Any]] = []
    used_baseline: set[int] = set()
    used_edited: set[int] = set()
    for baseline_index, row in enumerate(baseline):
        choices = edited_by_key.get(_note_key(row), [])
        edited_index = next((idx for idx in choices if idx not in used_edited), None)
        if edited_index is None:
            continue
        used_baseline.add(baseline_index)
        used_edited.add(edited_index)
        matches.append(
            {
                "status": "unchanged",
                "event_id": row.get("event_id"),
                "source_ref": copy.deepcopy(row.get("source_ref")),
                "baseline": row,
                "edited": edited[edited_index],
                "changes": [],
                "match_cost": 0.0,
            }
        )

    remaining_edited = sorted(
        ((int(row["start_tick"]), idx) for idx, row in enumerate(edited) if idx not in used_edited)
    )
    edited_starts = [item[0] for item in remaining_edited]
    window = max(ppq * 8, 1)
    candidates: list[tuple[float, int, int]] = []
    for baseline_index, row in enumerate(baseline):
        if baseline_index in used_baseline:
            continue
        start = int(row["start_tick"])
        lo = bisect_left(edited_starts, start - window)
        hi = bisect_right(edited_starts, start + window)
        for _edited_start, edited_index in remaining_edited[lo:hi]:
            if edited_index in used_edited:
                continue
            cost = _note_cost(row, edited[edited_index], ppq=ppq)
            if cost <= 20.0:
                candidates.append((cost, baseline_index, edited_index))

    for cost, baseline_index, edited_index in sorted(candidates):
        if baseline_index in used_baseline or edited_index in used_edited:
            continue
        used_baseline.add(baseline_index)
        used_edited.add(edited_index)
        base = baseline[baseline_index]
        edit = edited[edited_index]
        changes = _classify_note_change(base, edit)
        matches.append(
            {
                "status": "modified" if changes else "unchanged",
                "event_id": base.get("event_id"),
                "source_ref": copy.deepcopy(base.get("source_ref")),
                "baseline": base,
                "edited": edit,
                "changes": changes,
                "match_cost": round(float(cost), 6),
            }
        )

    deleted = [
        {
            "status": "deleted",
            "event_id": baseline[index].get("event_id"),
            "source_ref": copy.deepcopy(baseline[index].get("source_ref")),
            "baseline": baseline[index],
        }
        for index in range(len(baseline))
        if index not in used_baseline
    ]
    added = [
        {"status": "added", "edited": edited[index]}
        for index in range(len(edited))
        if index not in used_edited
    ]
    matches.sort(key=lambda row: (
        int((row.get("edited") or row.get("baseline") or {}).get("start_tick", 0)),
        int((row.get("edited") or row.get("baseline") or {}).get("pitch", -1)),
    ))
    return {"matches": matches, "deleted": deleted, "added": added}


def _match_scalar_events(
    baseline_rows: Iterable[Mapping[str, Any]],
    edited_rows: Iterable[Mapping[str, Any]],
    *,
    identity_keys: tuple[str, ...],
    value_keys: tuple[str, ...],
    ppq: int,
) -> dict[str, Any]:
    baseline = [copy.deepcopy(dict(row)) for row in baseline_rows]
    edited = [copy.deepcopy(dict(row)) for row in edited_rows]
    remaining = set(range(len(edited)))
    matches: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    for base in baseline:
        identity = tuple(base.get(key) for key in identity_keys)
        candidates = [
            idx
            for idx in remaining
            if tuple(edited[idx].get(key) for key in identity_keys) == identity
        ]
        if not candidates:
            deleted.append(
                {
                    "status": "deleted",
                    "baseline": base,
                    "event_id": base.get("event_id"),
                    "source_ref": base.get("source_ref"),
                }
            )
            continue
        idx = min(candidates, key=lambda i: abs(int(edited[i].get("tick", 0)) - int(base.get("tick", 0))))
        remaining.remove(idx)
        edit = edited[idx]
        changes: list[str] = []
        if int(base.get("tick", 0)) != int(edit.get("tick", 0)):
            changes.append("moved")
        for key in value_keys:
            if int(base.get(key, 0)) != int(edit.get(key, 0)):
                changes.append(key)
        matches.append(
            {
                "status": "modified" if changes else "unchanged",
                "event_id": base.get("event_id"),
                "source_ref": copy.deepcopy(base.get("source_ref")),
                "baseline": base,
                "edited": edit,
                "changes": changes,
                "match_cost": round(abs(int(edit.get("tick", 0)) - int(base.get("tick", 0))) / max(1, ppq), 6),
            }
        )
    added = [{"status": "added", "edited": edited[idx]} for idx in sorted(remaining)]
    return {"matches": matches, "deleted": deleted, "added": added}


def _region_rows(manifest: Mapping[str, Any], track: Mapping[str, Any]) -> list[dict[str, Any]]:
    explicit = [
        copy.deepcopy(dict(row))
        for row in manifest.get("source_regions", []) or []
        if str(row.get("instrument")) == str(track.get("instrument"))
    ]
    if explicit:
        return explicit
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event_kind in ("notes", "controls", "pitch_bends"):
        for event in track.get(event_kind, []) or []:
            ref = event.get("source_ref") or {}
            clip_id = ref.get("clip_id")
            if not clip_id:
                continue
            key = (str(ref.get("part_id", "")), str(ref.get("voice_id", "")), str(clip_id))
            start = int(event.get("start_tick", event.get("tick", 0)))
            end = int(event.get("end_tick", start + 1))
            row = grouped.setdefault(
                key,
                {
                    "part_id": key[0],
                    "voice_id": key[1],
                    "clip_id": key[2],
                    "instrument": str(track.get("instrument")),
                    "start_tick": start,
                    "end_tick": max(start + 1, end),
                },
            )
            row["start_tick"] = min(int(row["start_tick"]), start)
            row["end_tick"] = max(int(row["end_tick"]), max(start + 1, end))
    return sorted(grouped.values(), key=lambda row: (row["start_tick"], row["clip_id"]))


def _assign_added_note(note: Mapping[str, Any], regions: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    start = int(note["start_tick"])
    end = int(note["end_tick"])
    overlaps = [
        row
        for row in regions
        if start < int(row["end_tick"]) and end > int(row["start_tick"])
    ]
    if len(overlaps) == 1:
        return copy.deepcopy(dict(overlaps[0]))
    if len(regions) == 1:
        return copy.deepcopy(dict(regions[0]))
    return None


def _assign_added_point(point: Mapping[str, Any], regions: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    tick = int(point["tick"])
    containing = [
        row for row in regions if int(row["start_tick"]) <= tick < int(row["end_tick"])
    ]
    if len(containing) == 1:
        return copy.deepcopy(dict(containing[0]))
    if len(regions) == 1:
        return copy.deepcopy(dict(regions[0]))
    return None


def _summarize_track(track: Mapping[str, Any]) -> dict[str, int]:
    note_changes = track["notes"]
    control_changes = track["controls"]
    bend_changes = track["pitch_bends"]
    return {
        "notes_unchanged": sum(row["status"] == "unchanged" for row in note_changes["matches"]),
        "notes_modified": sum(row["status"] == "modified" for row in note_changes["matches"]),
        "notes_deleted": len(note_changes["deleted"]),
        "notes_added": len(note_changes["added"]),
        "controls_modified": sum(row["status"] == "modified" for row in control_changes["matches"]),
        "controls_deleted": len(control_changes["deleted"]),
        "controls_added": len(control_changes["added"]),
        "pitch_bends_modified": sum(row["status"] == "modified" for row in bend_changes["matches"]),
        "pitch_bends_deleted": len(bend_changes["deleted"]),
        "pitch_bends_added": len(bend_changes["added"]),
    }


def reconcile_edited_midi(
    compiled: CompiledScore,
    manifest: Mapping[str, Any],
    edited_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare edited MIDI to an exported sidecar baseline.

    The report is deliberately independent of source mutation so it can be used
    as the audit surface before any MusicIR write occurs.
    """

    expected = str(manifest.get("compiled_score_fingerprint", ""))
    actual = compiled_score_fingerprint(compiled)
    if expected and expected != actual:
        raise DawRoundtripError(
            "the MusicIR source no longer matches the DAW export baseline: "
            "compiled_score_fingerprint changed; export a fresh DAW bundle before importing"
        )
    expected_graph = manifest.get("authoring_graph_fingerprint")
    if expected_graph and expected_graph != compiled.authoring_graph_fingerprint:
        raise DawRoundtripError(
            "the MusicIR authoring graph no longer matches the DAW export baseline; "
            "export a fresh DAW bundle before importing"
        )
    target_ppq = int((manifest.get("midi") or {}).get("ppq", compiled.pm.resolution))
    edited = normalize_snapshot_ppq(edited_snapshot, target_ppq=target_ppq)

    track_reports: list[dict[str, Any]] = []
    missing_tracks: list[str] = []
    for manifest_index, baseline_track in enumerate(manifest.get("tracks", []) or []):
        edited_track, match_mode = _match_track(
            baseline_track, edited, manifest_index=manifest_index
        )
        if edited_track is None:
            missing_tracks.append(str(baseline_track.get("track_id", baseline_track.get("instrument", ""))))
            edited_track = {"notes": [], "controls": [], "pitch_bends": []}
        notes = _match_notes(
            baseline_track.get("notes", []) or [], edited_track.get("notes", []) or [], ppq=target_ppq
        )
        controls = _match_scalar_events(
            baseline_track.get("controls", []) or [],
            edited_track.get("controls", []) or [],
            identity_keys=("controller",),
            value_keys=("value",),
            ppq=target_ppq,
        )
        bends = _match_scalar_events(
            baseline_track.get("pitch_bends", []) or [],
            edited_track.get("pitch_bends", []) or [],
            identity_keys=(),
            value_keys=("pitch",),
            ppq=target_ppq,
        )
        regions = _region_rows(manifest, baseline_track)
        for added in notes["added"]:
            region = _assign_added_note(added["edited"], regions)
            if region is not None:
                added["source_region"] = region
        for changes in (controls, bends):
            for added in changes["added"]:
                region = _assign_added_point(added["edited"], regions)
                if region is not None:
                    added["source_region"] = region
        row = {
            "track_id": str(baseline_track.get("track_id", baseline_track.get("instrument", ""))),
            "instrument": str(baseline_track.get("instrument", "")),
            "track_match": match_mode,
            "edited_track_name": str(edited_track.get("name", "")),
            "notes": notes,
            "controls": controls,
            "pitch_bends": bends,
        }
        row["summary"] = _summarize_track(row)
        track_reports.append(row)

    unassigned_additions = [
        {"track_id": track["track_id"], "edited": copy.deepcopy(add["edited"])}
        for track in track_reports
        for add in track["notes"]["added"]
        if not add.get("source_region")
    ]
    controller_changes = 0
    transport_controller_changes = 0
    unassigned_controller_edits: list[dict[str, Any]] = []
    for track in track_reports:
        for kind in ("controls", "pitch_bends"):
            changes = track[kind]
            for row in changes["matches"]:
                if row["status"] != "modified":
                    continue
                transport_controller_changes += 1
                if row.get("source_ref"):
                    controller_changes += 1
                elif bool((row.get("baseline") or {}).get("compiled_source")):
                    unassigned_controller_edits.append(
                        {"track_id": track["track_id"], "kind": kind, "change": copy.deepcopy(row)}
                    )
            for row in changes["deleted"]:
                transport_controller_changes += 1
                if row.get("source_ref"):
                    controller_changes += 1
                elif bool((row.get("baseline") or {}).get("compiled_source")):
                    unassigned_controller_edits.append(
                        {"track_id": track["track_id"], "kind": kind, "change": copy.deepcopy(row)}
                    )
            for row in changes["added"]:
                transport_controller_changes += 1
                controller_changes += 1
                if not row.get("source_region"):
                    unassigned_controller_edits.append(
                        {"track_id": track["track_id"], "kind": kind, "change": copy.deepcopy(row)}
                    )
    note_changes = sum(
        track["summary"][key]
        for track in track_reports
        for key in ("notes_modified", "notes_deleted", "notes_added")
    )

    conductor_report = reconcile_conductor(
        compiled,
        manifest,
        edited.get("conductor") or {},
        ppq=target_ppq,
    )
    conductor_changed = bool(conductor_report.get("changed"))
    conductor_blocked = list((conductor_report.get("apply") or {}).get("blocked_by", []) or [])

    return {
        "schema": RECONCILIATION_SCHEMA,
        "score_id": str(manifest.get("score_id", compiled.normalized_spec.get("id", ""))),
        "baseline_schema": str(manifest.get("schema", "")),
        "baseline_compiled_score_fingerprint": actual,
        "edited_midi": {
            "source_ppq": int(edited.get("source_ticks_per_beat", target_ppq)),
            "normalized_ppq": target_ppq,
            "ppq_rescale_quantized_coordinates": int(edited.get("ppq_rescale_quantized_coordinates", 0)),
        },
        "tracks": track_reports,
        "summary": {
            "note_changes": note_changes,
            "controller_changes": controller_changes,
            "transport_controller_changes": transport_controller_changes,
            "missing_tracks": missing_tracks,
            "unassigned_added_notes": len(unassigned_additions),
            "unassigned_controller_edits": len(unassigned_controller_edits),
            "conductor_changed": conductor_changed,
            "tempo_event_changes": int((conductor_report.get("summary") or {}).get("tempo_event_changes", 0)),
            "meter_event_changes": int((conductor_report.get("summary") or {}).get("meter_event_changes", 0)),
            "form_marker_changes": int((conductor_report.get("summary") or {}).get("marker_changes", 0)),
        },
        "conductor": conductor_report,
        "unassigned_added_notes": unassigned_additions,
        "unassigned_controller_edits": unassigned_controller_edits,
        "apply": {
            "supported": (
                compiled.canonical_schema == MUSICIR_V3_SCHEMA
                and not missing_tracks
                and not unassigned_additions
                and not unassigned_controller_edits
                and not conductor_blocked
            ),
            "strategy": "lower_affected_v3_clips_and_reconcile_conductor",
            "blocked_by": list(
                dict.fromkeys(
                    [
                        reason
                        for condition, reason in (
                            (compiled.canonical_schema != MUSICIR_V3_SCHEMA, "source_is_not_musicir_v3"),
                            (bool(missing_tracks), "missing_midi_tracks"),
                            (bool(unassigned_additions), "ambiguous_added_note_source_region"),
                            (bool(unassigned_controller_edits), "controller_edit_has_no_unique_v3_clip_source"),
                        )
                        if condition
                    ]
                    + conductor_blocked
                )
            ),
        },
    }


def _find_source_clip(spec: Mapping[str, Any], source_ref: Mapping[str, Any]) -> dict[str, Any]:
    part_id = str(source_ref.get("part_id", ""))
    voice_id = str(source_ref.get("voice_id", ""))
    clip_id = str(source_ref.get("clip_id", ""))
    for part in spec.get("parts", []) or []:
        if str(part.get("id")) != part_id:
            continue
        for voice in part.get("voices", []) or []:
            if str(voice.get("id")) != voice_id:
                continue
            for clip in voice.get("clips", []) or []:
                if str(clip.get("id")) == clip_id:
                    return clip
    raise DawRoundtripError(
        f"cannot locate source clip {part_id}/{voice_id}/{clip_id} in current MusicIR"
    )


def _clip_key(source_ref: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(source_ref.get("part_id", "")),
        str(source_ref.get("voice_id", "")),
        str(source_ref.get("clip_id", "")),
    )



def lower_reconciled_clips(
    source_spec: Mapping[str, Any],
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a supported reconciliation by literalizing only affected v3 clips."""

    if not bool((report.get("apply") or {}).get("supported")):
        blocked = ", ".join((report.get("apply") or {}).get("blocked_by", []) or [])
        raise DawRoundtripError(f"reconciliation is not safely applicable: {blocked or 'unknown reason'}")
    spec = copy.deepcopy(dict(source_spec))
    if str(spec.get("schema")) != MUSICIR_V3_SCHEMA:
        raise DawRoundtripError("automatic DAW apply currently requires MusicIR v3")

    graph = normalize_v3_score_graph(spec)
    clock = ScoreClock(graph.timing_score())
    affected: set[tuple[str, str, str]] = set()
    final_by_clip: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    automation_by_clip: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    for track in report.get("tracks", []) or []:
        for match in track["notes"]["matches"]:
            ref = match.get("source_ref") or {}
            if not ref.get("clip_id"):
                continue
            key = _clip_key(ref)
            final_by_clip.setdefault(key, []).append(copy.deepcopy(match["edited"]))
            if match["status"] == "modified":
                affected.add(key)
        for deleted in track["notes"]["deleted"]:
            ref = deleted.get("source_ref") or {}
            if ref.get("clip_id"):
                affected.add(_clip_key(ref))
        for added in track["notes"]["added"]:
            region = added.get("source_region") or {}
            if not region.get("clip_id"):
                continue
            key = (
                str(region.get("part_id", "")),
                str(region.get("voice_id", "")),
                str(region.get("clip_id", "")),
            )
            final_by_clip.setdefault(key, []).append(copy.deepcopy(added["edited"]))
            affected.add(key)
        for kind in ("controls", "pitch_bends"):
            for match in track[kind]["matches"]:
                ref = match.get("source_ref") or {}
                if not ref.get("clip_id"):
                    continue
                key = _clip_key(ref)
                point = copy.deepcopy(match["edited"])
                point["kind"] = "cc" if kind == "controls" else "pitch_bend"
                automation_by_clip.setdefault(key, []).append(point)
                if match["status"] == "modified":
                    affected.add(key)
            for deleted in track[kind]["deleted"]:
                ref = deleted.get("source_ref") or {}
                if ref.get("clip_id"):
                    affected.add(_clip_key(ref))
            for added in track[kind]["added"]:
                region = added.get("source_region") or {}
                if not region.get("clip_id"):
                    continue
                key = (
                    str(region.get("part_id", "")),
                    str(region.get("voice_id", "")),
                    str(region.get("clip_id", "")),
                )
                point = copy.deepcopy(added["edited"])
                point["kind"] = "cc" if kind == "controls" else "pitch_bend"
                automation_by_clip.setdefault(key, []).append(point)
                affected.add(key)

    lowering_rows: list[dict[str, Any]] = []
    for key in sorted(affected):
        ref = {"part_id": key[0], "voice_id": key[1], "clip_id": key[2]}
        clip = _find_source_clip(spec, ref)
        original_kind = "generate" if "generate" in clip else "material" if "use" in clip else "events"
        original_start = int(clock.position_to_tick(clip.get("at", {"tick": 0})))
        notes = sorted(
            final_by_clip.get(key, []),
            key=lambda row: (int(row["start_tick"]), int(row["pitch"]), int(row["end_tick"])),
        )
        automation = sorted(
            automation_by_clip.get(key, []),
            key=lambda row: (int(row["tick"]), str(row.get("kind", ""))),
        )
        coordinates = [original_start]
        coordinates.extend(int(row["start_tick"]) for row in notes)
        coordinates.extend(int(row["tick"]) for row in automation)
        origin = min(coordinates) if coordinates else original_start
        if origin != original_start:
            clip["at"] = {"tick": origin}

        events: list[dict[str, Any]] = []
        for index, note in enumerate(notes):
            start = int(note["start_tick"])
            end = max(start + 1, int(note["end_tick"]))
            events.append(
                {
                    "id": f"daw_{index:04d}",
                    "at": start - origin,
                    "dur": end - start,
                    "pitch": int(note["pitch"]),
                    "velocity": int(note["velocity"]),
                    "gate": 1.0,
                }
            )

        preserved = {
            key_name: copy.deepcopy(clip[key_name])
            for key_name in ("id", "at", "instrument", "technique", "articulation")
            if key_name in clip
        }
        clip.clear()
        clip.update(preserved)
        clip["events"] = events
        if automation:
            points: list[dict[str, Any]] = []
            for index, point in enumerate(automation):
                row: dict[str, Any] = {"id": f"daw_automation_{index:04d}", "at": int(point["tick"]) - origin}
                if point["kind"] == "cc":
                    row["cc"] = int(point["controller"])
                    row["value"] = int(point["value"])
                else:
                    row["pitch_bend"] = int(point["pitch"])
                points.append(row)
            clip["automation"] = points
        lowering_rows.append(
            {
                "part_id": key[0],
                "voice_id": key[1],
                "clip_id": key[2],
                "from": original_kind,
                "to": "events",
                "notes": len(events),
                "automation_points": len(automation),
                "origin_tick": origin,
            }
        )

    # Apply conductor edits after clip lowering.  Clip/event coordinates above are
    # interpreted in the baseline clock; changing meter first could change the
    # meaning of bar-addressed source positions before they are literalized.
    spec, conductor_apply = apply_conductor_to_v3(spec, report.get("conductor") or {})

    return spec, {
        "strategy": "lower_affected_v3_clips_and_reconcile_conductor",
        "clips_lowered": lowering_rows,
        "conductor": conductor_apply,
    }


def write_musicir_yaml(spec: Mapping[str, Any], path: str | Path) -> Path:
    """Write a reconciled score atomically after the caller has verified compilation."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(dict(spec), sort_keys=False, allow_unicode=True, width=110)
    temporary = path.with_name(f".{path.name}.daw-roundtrip.tmp")
    temporary.write_text(text, encoding="utf8")
    temporary.replace(path)
    return path


def verify_compiled_matches_edited_midi(
    compiled: CompiledScore,
    manifest: Mapping[str, Any],
    edited_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify that an applied MusicIR source recompiles to the edited MIDI notes."""

    from .interchange import build_interchange_manifest

    target_ppq = int((manifest.get("midi") or {}).get("ppq", compiled.pm.resolution))
    edited = normalize_snapshot_ppq(edited_snapshot, target_ppq=target_ppq)
    compiled_manifest = build_interchange_manifest(compiled, midi_filename="verification.mid")
    mismatches: list[dict[str, Any]] = []
    for index, expected_track in enumerate(manifest.get("tracks", []) or []):
        edited_track, _match_mode = _match_track(expected_track, edited, manifest_index=index)
        if edited_track is None:
            mismatches.append({"track_id": expected_track.get("track_id"), "reason": "edited_track_missing"})
            continue
        actual_track = next(
            (
                row
                for row in compiled_manifest.get("tracks", []) or []
                if str(row.get("track_id")) == str(expected_track.get("track_id"))
            ),
            None,
        )
        if actual_track is None:
            mismatches.append({"track_id": expected_track.get("track_id"), "reason": "compiled_track_missing"})
            continue
        expected_notes = sorted(
            (
                int(row["start_tick"]),
                int(row["end_tick"]),
                int(row["pitch"]),
                int(row["velocity"]),
            )
            for row in edited_track.get("notes", []) or []
        )
        actual_notes = sorted(
            (
                int(row["start_tick"]),
                int(row["end_tick"]),
                int(row["pitch"]),
                int(row["velocity"]),
            )
            for row in actual_track.get("notes", []) or []
        )
        if expected_notes != actual_notes:
            mismatches.append(
                {
                    "track_id": expected_track.get("track_id"),
                    "reason": "note_mismatch",
                    "edited_note_count": len(expected_notes),
                    "compiled_note_count": len(actual_notes),
                    "edited_only": [list(row) for row in sorted(set(expected_notes) - set(actual_notes))[:32]],
                    "compiled_only": [list(row) for row in sorted(set(actual_notes) - set(expected_notes))[:32]],
                }
            )
    conductor_verification = verify_conductor_against_snapshot(
        compiled,
        edited.get("conductor") or {},
        ppq=target_ppq,
    )
    mismatches.extend(copy.deepcopy(conductor_verification.get("mismatches", []) or []))
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "conductor": conductor_verification,
    }
