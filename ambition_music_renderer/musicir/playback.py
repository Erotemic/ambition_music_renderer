"""Prepare playback facts from a compiled score and its encoded products."""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Any

from .model import CompiledScore, compiled_score_fingerprint
from ..score_inventory import score_metadata
from ..render.playback_layers import _frame, playback_layer_plan, runtime_product_path

PLAYBACK_SCHEMA = "ambition.music_playback.v1"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _section_plan(compiled: CompiledScore) -> tuple[str, dict[str, Any]]:
    plan = playback_layer_plan(compiled)
    if plan is not None:
        return "playback", plan
    loops = set((compiled.normalized_spec.get("playback") or {}).get("loop_components") or [])
    return "adaptive", {
        "full": True,
        "layers": {},
        "sections": [{
            "id": str(row["id"]), "form": [str(row["id"])],
            "loop": bool(row.get("loopable")) or row["id"] in loops,
            "lead_in": None, "tail": None,
            "lead_in_start_seconds": None, "tail_end_seconds": None,
            "tail_audio_end_seconds": None,
            "start_seconds": float(row["start_seconds"]), "end_seconds": float(row["end_seconds"]),
            "start_beat": float(row["start_beat"]), "end_beat": float(row["end_beat"]),
        } for row in compiled.sections],
    }


def score_playback_description(compiled: CompiledScore, *, sample_rate: int | None = None) -> dict[str, Any]:
    """Inspect score facts. Frame plans are requested cuts, not measured media."""
    if sample_rate is not None and (type(sample_rate) is not int or sample_rate <= 0):
        raise ValueError("playback sample rate must be a positive integer")
    family, plan = _section_plan(compiled)
    by_id = {str(row["id"]): row for row in compiled.sections}
    if len(by_id) != len(compiled.sections):
        raise ValueError("playback: duplicate form section ids")
    clock = compiled.clock
    sections = []
    for source in plan["sections"]:
        section = copy.deepcopy(source)
        start, end = section["start_beat"], section["end_beat"]
        if not all(math.isfinite(value) for value in (start, end)) or end <= start:
            raise ValueError(f"playback.sections.{section['id']}: musical span must be positive and finite")
        origin = section["start_seconds"]
        first_bar = clock.bar_at_beat(start)
        bar, bars = first_bar, []
        while clock.beat_at_bar(bar) <= end:
            beat = clock.beat_at_bar(bar)
            if beat >= start:
                bars.append((beat, clock.time_at_beat(beat)))
            if clock.beat_at_bar(bar + 1) <= beat:
                raise ValueError("playback clock bars must advance")
            bar += 1
        grid = clock.constant_grid(start, end)
        if grid is None:
            section["clock"] = {"kind": "boundaries", "bar_seconds": [seconds - origin for _, seconds in bars]}
        else:
            bpm, width = grid
            section["clock"] = {"kind": "constant", "bpm": bpm, "beats_per_bar": width,
                                "bar_origin_seconds": clock.time_at_beat(clock.beat_at_bar(first_bar)) - origin}
        markers = [{"id": f"{section['id']}:entry", "role": "entry", "beat": start, "seconds": 0.0}]
        for form_id in section["form"]:
            form = by_id[form_id]
            exits = form.get("valid_exit_local_bars", [])
            if not isinstance(exits, list):
                raise ValueError(f"form.{form_id}.valid_exit_local_bars must be a list")
            form_bar = clock.bar_at_beat(form["start_beat"])
            if exits and not math.isclose(clock.beat_at_bar(form_bar), form["start_beat"], abs_tol=1e-9):
                raise ValueError(f"form.{form_id}: bar exits require a form start on a bar boundary")
            seen = set()
            for local_bar in exits:
                if isinstance(local_bar, bool) or not isinstance(local_bar, int) or local_bar <= 0:
                    raise ValueError(f"form.{form_id}.valid_exit_local_bars needs positive integer bar offsets")
                if local_bar in seen:
                    raise ValueError(f"form.{form_id}: duplicate exit bar {local_bar}")
                seen.add(local_bar)
                beat = clock.beat_at_bar(form_bar + local_bar)
                if beat > form["end_beat"]:
                    raise ValueError(f"form.{form_id}: exit bar {local_bar} is outside the form section")
                markers.append({"id": f"{form_id}:exit:{local_bar}", "role": "exit", "beat": beat,
                                "seconds": clock.time_at_beat(beat) - origin})
        section["markers"] = sorted(markers, key=lambda marker: (marker["beat"], marker["id"]))
        section["musical_end_seconds"] = section["end_seconds"] - origin
        section["file_duration_seconds"] = (section["end_seconds"] if section["loop"] else
                                            section["tail_end_seconds"] or section["end_seconds"]) - origin
        retained_entry = section["lead_in_start_seconds"] if section["lead_in_start_seconds"] is not None else origin
        section["material"] = {
            "tail": "folded" if section["loop"] and section["tail"] else "appended" if section["tail"] else "none",
            "lead_in": "folded" if section["lead_in"] else "none",
            "independent_tail": False, "scheduled_pickup": False,
            "tail_excludes_pickup": section["tail_audio_end_seconds"] != section["tail_end_seconds"],
            "unretained_pickup_attacks": sum(1 for event in compiled.note_events
                if event.get("event_type", "note") == "note" and event.get("section") in section["form"]
                and float(event["start_time"]) < retained_entry),
        }
        section["product_roles"] = {
            **{layer: "grouped_pre_master" for layer in plan["layers"]},
            **({"full": "mastered_full"} if plan["full"] else {}),
        }
        if sample_rate is not None:
            first = _frame(origin, sample_rate)
            body = _frame(section["end_seconds"], sample_rate) - first
            if body <= 0:
                raise ValueError(f"playback.sections.{section['id']}: musical body has no frames at {sample_rate} Hz")
            audible_end = first + body if section["loop"] else _frame(section["tail_end_seconds"] or section["end_seconds"], sample_rate)
            section["frame_plan"] = {
                "sample_rate": sample_rate, "score_origin_frame": first,
                "musical_end_frame": body, "file_frames": audible_end - first,
                "loop_frames": body if section["loop"] else None,
                "tail_source_frames": 0 if section["tail_end_seconds"] is None else
                    _frame(section["tail_end_seconds"], sample_rate) - first - body,
                "tail_source_audio_frames": 0 if section["tail_audio_end_seconds"] is None else
                    _frame(section["tail_audio_end_seconds"], sample_rate) - first - body,
                "lead_in_source_frames": 0 if section["lead_in_start_seconds"] is None else
                    first - _frame(section["lead_in_start_seconds"], sample_rate),
                "bar_frames": [_frame(seconds, sample_rate) - first for _, seconds in bars],
                "markers": [{"id": marker["id"], "role": marker["role"],
                             "frame": _frame(clock.time_at_beat(marker["beat"]), sample_rate) - first}
                            for marker in section["markers"]],
            }
        sections.append(section)
    return {
        "schema": PLAYBACK_SCHEMA, "evidence": "score_plan",
        **score_metadata(compiled.normalized_spec),
        "compiled_score_fingerprint": compiled_score_fingerprint(compiled),
        "score_clock": clock.as_dict(), "product_family": family,
        "layer_groups": copy.deepcopy(plan["layers"]), "sections": sections,
    }


def rendered_playback_description(
    compiled: CompiledScore, *, root: Path, files: dict[str, Any], sample_rate: int,
    render_fingerprint: str, runtime_stem_gain_mode: str, runtime_gain_db: float,
    adaptive_mastering_mode: str,
) -> dict[str, Any]:
    """Bind playback facts to the files produced by this render."""
    import soundfile as sf

    result = score_playback_description(compiled, sample_rate=sample_rate)
    result["evidence"] = "encoded_products"
    result["render_fingerprint"] = render_fingerprint
    exported = files.get(result["product_family"]) or {}
    for section in result["sections"]:
        section["products"] = []
        for layer, role in section["product_roles"].items():
            path = (exported.get(section["id"]) or {}).get(layer)
            if path is None:
                if exported:
                    raise ValueError(f"playback product missing: {section['id']}.{layer}")
                continue
            source = root / path
            info = sf.info(source)
            expected = section["frame_plan"]["file_frames"]
            if info.samplerate != sample_rate or info.frames != expected:
                raise ValueError(f"playback product {path}: expected {expected} frames at {sample_rate} Hz; got {info.frames} at {info.samplerate} Hz")
            section["products"].append({
                "layer": layer, "path": str(path), "sha256": _file_sha256(source),
                "frames": info.frames, "sample_rate": info.samplerate,
                "channels": info.channels, "format": info.format, "subtype": info.subtype,
                "frame_observer": "libsndfile",
                "gain_basis": role,
                "runtime_stem_gain_mode": runtime_stem_gain_mode if role == "grouped_pre_master" else None,
                "applied_runtime_gain_db": runtime_gain_db if role == "grouped_pre_master" and runtime_stem_gain_mode == "shared" else 0.0,
                "mastering": ("composition_master" if result["product_family"] == "playback" else adaptive_mastering_mode) if role == "mastered_full" else None,
            })
        section["available"] = bool(section["products"])
    return result


def published_playback_description(description: dict[str, Any], root: Path) -> dict[str, Any]:
    """Keep the render identity when files move to runtime paths."""
    if description.get("schema") != PLAYBACK_SCHEMA or description.get("evidence") != "encoded_products":
        raise ValueError("publication needs encoded playback products")
    result = copy.deepcopy(description)
    for section in result["sections"]:
        for product in section["products"]:
            relative = runtime_product_path(result["product_family"], section["id"], product["layer"])
            if _file_sha256(root / relative) != product["sha256"]:
                raise ValueError(f"published playback product differs from its render: {relative}")
            product["path"] = relative.as_posix()
    result["evidence"] = "published_products"
    return result
