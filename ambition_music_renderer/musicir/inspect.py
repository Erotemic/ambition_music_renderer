"""Inspect MusicIR derivation from authored v3 graph to compiled events.

These helpers are read-only.  They intentionally consume ``CompiledScore`` and
the canonical instrument resolver rather than reconstructing rendering rules.
The resulting JSON is designed for agents, debugging tools, and later DAW
reconciliation.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..instrument_resolution import backend_spec_from_instrument, resolve_instrument_backend
from ..render.exact_score import ScoreClock
from .graph import normalize_v3_score_graph
from .model import CompiledScore, compiled_score_fingerprint
from .transforms import clip_transform


INSPECTION_SCHEMA = "ambition.musicir_inspection.v1"


def _graph(compiled: CompiledScore):
    if compiled.canonical_schema != "ambition.musicir.v3" or not compiled.authoring_graph:
        return None
    # Normalize from the original v3 source so helper methods such as
    # ``chord_at_tick`` are available and the inspection follows the same
    # source-normalization authority as compilation.
    return normalize_v3_score_graph(compiled.normalized_spec)


def _clip_records(graph) -> list[dict[str, Any]]:
    if graph is None:
        return []
    result: list[dict[str, Any]] = []
    for part_index, part in enumerate(graph.parts):
        part_id = str(part["id"])
        for voice_index, voice in enumerate(part.get("voices", []) or []):
            voice_id = str(voice["id"])
            for clip_index, clip in enumerate(voice.get("clips", []) or []):
                source_kind = "events" if "events" in clip else "material" if "use" in clip else "generator"
                record = {
                    "part_id": part_id,
                    "voice_id": voice_id,
                    "clip_id": str(clip["id"]),
                    "path": f"parts[{part_index}].voices[{voice_index}].clips[{clip_index}]",
                    "source_kind": source_kind,
                    "instrument": str(clip.get("instrument", part.get("instrument", part_id))),
                    "at": copy.deepcopy(clip.get("at", {"bar": 1, "beat": 1})),
                    "transforms": clip_transform(clip).as_dict(),
                    "repeat": copy.deepcopy(clip.get("repeat", 1)),
                    "automation": copy.deepcopy(clip.get("automation") or []),
                    "source": copy.deepcopy(dict(clip)),
                }
                if "use" in clip:
                    material_id = str(clip["use"])
                    record["material_id"] = material_id
                    record["material"] = copy.deepcopy(graph.materials.get(material_id))
                if "generate" in clip:
                    record["generator"] = copy.deepcopy(dict(clip["generate"]))
                    record["generator_kind"] = str(clip["generate"].get("kind", ""))
                result.append(record)
    return result


def _matches_source_ref(
    source_ref: Mapping[str, Any] | None,
    *,
    clip_id: str | None = None,
    part_id: str | None = None,
    voice_id: str | None = None,
) -> bool:
    if not source_ref:
        return clip_id is None and part_id is None and voice_id is None
    if clip_id is not None and str(source_ref.get("clip_id")) != str(clip_id):
        return False
    if part_id is not None and str(source_ref.get("part_id")) != str(part_id):
        return False
    if voice_id is not None and str(source_ref.get("voice_id")) != str(voice_id):
        return False
    return True


def _instrument_plans(
    compiled: CompiledScore,
    names: Iterable[str],
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    render_cfg = dict(compiled.normalized_spec.get("render") or {})
    sfizz_cfg = dict(render_cfg.get("sfizz") or {})
    result: dict[str, Any] = {}
    for name in sorted(set(map(str, names))):
        spec = compiled.instrument_specs.get(name)
        if not spec:
            continue
        plan = resolve_instrument_backend(
            backend_spec_from_instrument(spec),
            base_dir=base_dir,
            sfizz_cfg=sfizz_cfg,
        )
        payload = plan.to_dict()
        payload["authored_instrument"] = copy.deepcopy(spec)
        result[name] = payload
    return result


def _harmony_for_event(graph, clock: ScoreClock | None, event: Mapping[str, Any]) -> str | None:
    if graph is None or clock is None or not graph.harmony:
        return None
    try:
        return str(graph.chord_at_tick(clock, int(event.get("start_tick", event.get("tick", 0)))))
    except Exception:
        return None


def expand_compiled_score(
    compiled: CompiledScore,
    *,
    clip_id: str | None = None,
    part_id: str | None = None,
    voice_id: str | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return source → expansion → realization evidence for a score or clip."""

    graph = _graph(compiled)
    clock = ScoreClock(graph.timing_score()) if graph is not None else None
    clip_records = _clip_records(graph)
    selected_clips = [
        row
        for row in clip_records
        if (clip_id is None or row["clip_id"] == clip_id)
        and (part_id is None or row["part_id"] == part_id)
        and (voice_id is None or row["voice_id"] == voice_id)
    ]
    if clip_id is not None and graph is not None and not selected_clips:
        known = sorted({row["clip_id"] for row in clip_records})
        raise KeyError(f"unknown MusicIR v3 clip {clip_id!r}; known clips: {known}")

    notes: list[dict[str, Any]] = []
    for event in compiled.note_events:
        source_ref = event.get("source_ref") if isinstance(event.get("source_ref"), Mapping) else None
        if not _matches_source_ref(source_ref, clip_id=clip_id, part_id=part_id, voice_id=voice_id):
            continue
        row = copy.deepcopy(dict(event))
        harmony = _harmony_for_event(graph, clock, row)
        if harmony is not None:
            row["harmony"] = harmony
        notes.append(row)

    controls: list[dict[str, Any]] = []
    for event in compiled.controller_events:
        source_ref = event.get("source_ref") if isinstance(event.get("source_ref"), Mapping) else None
        if not _matches_source_ref(source_ref, clip_id=clip_id, part_id=part_id, voice_id=voice_id):
            continue
        row = copy.deepcopy(dict(event))
        if graph is not None and clock is not None:
            try:
                row["position"] = clock.tick_to_position(int(row.get("tick", 0)))
                row["harmony"] = graph.chord_at_tick(clock, int(row.get("tick", 0)))
            except Exception:
                pass
        controls.append(row)

    instrument_names = [str(row.get("instrument")) for row in [*notes, *controls] if row.get("instrument")]
    if not instrument_names and clip_id is None:
        instrument_names = list(compiled.instrument_specs)

    return {
        "schema": INSPECTION_SCHEMA,
        "kind": "expansion",
        "score_id": str(compiled.normalized_spec.get("id", "")),
        "canonical_schema": compiled.canonical_schema,
        "compiled_score_fingerprint": compiled_score_fingerprint(compiled),
        "authoring_graph_fingerprint": compiled.authoring_graph_fingerprint,
        "selection": {
            "clip_id": clip_id,
            "part_id": part_id,
            "voice_id": voice_id,
        },
        "source_clips": selected_clips,
        "expanded_notes": notes,
        "expanded_controls": controls,
        "instrument_resolution": _instrument_plans(
            compiled,
            instrument_names,
            base_dir=Path(base_dir) if base_dir is not None else None,
        ),
        "counts": {
            "clips": len(selected_clips),
            "notes": len(notes),
            "controls": len(controls),
        },
    }


def _source_event_for_trace(source_clip: Mapping[str, Any] | None, source_ref: Mapping[str, Any]) -> Any:
    if not source_clip:
        return None
    rows = None
    if source_clip.get("material") and source_clip["material"].get("events") is not None:
        rows = source_clip["material"].get("events")
    elif source_clip.get("source", {}).get("events") is not None:
        rows = source_clip["source"].get("events")
    if not isinstance(rows, list):
        return None
    source_id = source_ref.get("source_event_id")
    if source_id is not None:
        for row in rows:
            if isinstance(row, Mapping) and str(row.get("id")) == str(source_id):
                return copy.deepcopy(row)
    try:
        index = int(source_ref.get("event_index", -1))
    except Exception:
        return None
    if 0 <= index < len(rows):
        return copy.deepcopy(rows[index])
    return None


def trace_compiled_event(
    compiled: CompiledScore,
    event_id: str,
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Trace one stable v3 event id back to source and forward to realization."""

    matches = [
        ("note", row)
        for row in compiled.note_events
        if str(row.get("event_id", "")) == str(event_id)
    ]
    matches.extend(
        ("control", row)
        for row in compiled.controller_events
        if str(row.get("event_id", "")) == str(event_id)
    )
    if not matches:
        sample = [str(row.get("event_id")) for row in compiled.note_events if row.get("event_id")][:8]
        raise KeyError(f"event id {event_id!r} was not compiled; example ids: {sample}")
    if len(matches) != 1:
        raise ValueError(f"event id {event_id!r} is not unique in CompiledScore")
    event_kind, event = matches[0]
    source_ref = event.get("source_ref") or {}
    expansion = expand_compiled_score(
        compiled,
        clip_id=str(source_ref.get("clip_id")) if source_ref.get("clip_id") else None,
        part_id=str(source_ref.get("part_id")) if source_ref.get("part_id") else None,
        voice_id=str(source_ref.get("voice_id")) if source_ref.get("voice_id") else None,
        base_dir=base_dir,
    )
    source_clip = next(
        (
            row
            for row in expansion["source_clips"]
            if row["clip_id"] == source_ref.get("clip_id")
            and row["part_id"] == source_ref.get("part_id")
            and row["voice_id"] == source_ref.get("voice_id")
        ),
        None,
    )
    instrument = str(event.get("instrument", ""))
    graph = _graph(compiled)
    harmony = None
    if graph is not None:
        clock = ScoreClock(graph.timing_score())
        harmony = _harmony_for_event(graph, clock, event)
    return {
        "schema": INSPECTION_SCHEMA,
        "kind": "event_trace",
        "score_id": str(compiled.normalized_spec.get("id", "")),
        "event_id": str(event_id),
        "event_kind": event_kind,
        "compiled_event": copy.deepcopy(dict(event)),
        "harmony": harmony,
        "source_ref": copy.deepcopy(dict(source_ref)),
        "source_clip": source_clip,
        "source_event": _source_event_for_trace(source_clip, source_ref),
        "generator_output_index": (
            int(source_ref.get("event_index", 0))
            if source_ref.get("generator_kind") is not None
            else None
        ),
        "instrument_resolution": copy.deepcopy(expansion["instrument_resolution"].get(instrument)),
        "compiled_score_fingerprint": compiled_score_fingerprint(compiled),
        "authoring_graph_fingerprint": compiled.authoring_graph_fingerprint,
    }


def authoring_graph_report(compiled: CompiledScore) -> dict[str, Any]:
    """Return a compact graph/edge view of v3 compositional structure."""

    graph = _graph(compiled)
    if graph is None:
        return {
            "schema": INSPECTION_SCHEMA,
            "kind": "graph",
            "score_id": str(compiled.normalized_spec.get("id", "")),
            "canonical_schema": compiled.canonical_schema,
            "authoring_graph": None,
            "message": "this score has no MusicIR v3 authoring graph; v1/v2 remain renderable compatibility frontends",
        }

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    score_node = f"score:{graph.score_id}"
    nodes.append({"id": score_node, "kind": "score", "label": graph.score_id})
    for material_id, material in graph.materials.items():
        node_id = f"material:{material_id}"
        nodes.append({"id": node_id, "kind": "material", "label": material_id, "material_kind": material.get("kind")})
        edges.append({"from": score_node, "to": node_id, "kind": "defines"})
    for record in _clip_records(graph):
        part_node = f"part:{record['part_id']}"
        voice_node = f"voice:{record['part_id']}/{record['voice_id']}"
        clip_node = f"clip:{record['part_id']}/{record['voice_id']}/{record['clip_id']}"
        if not any(node["id"] == part_node for node in nodes):
            nodes.append({"id": part_node, "kind": "part", "label": record["part_id"]})
            edges.append({"from": score_node, "to": part_node, "kind": "contains"})
        if not any(node["id"] == voice_node for node in nodes):
            nodes.append({"id": voice_node, "kind": "voice", "label": record["voice_id"]})
            edges.append({"from": part_node, "to": voice_node, "kind": "contains"})
        nodes.append(
            {
                "id": clip_node,
                "kind": "clip",
                "label": record["clip_id"],
                "source_kind": record["source_kind"],
                "instrument": record["instrument"],
                "path": record["path"],
            }
        )
        edges.append({"from": voice_node, "to": clip_node, "kind": "contains"})
        if record.get("material_id"):
            edges.append({"from": clip_node, "to": f"material:{record['material_id']}", "kind": "uses"})
        if record.get("generator_kind"):
            generator_node = f"generator:{record['generator_kind']}"
            if not any(node["id"] == generator_node for node in nodes):
                nodes.append({"id": generator_node, "kind": "generator", "label": record["generator_kind"]})
            edges.append({"from": clip_node, "to": generator_node, "kind": "generates"})
    return {
        "schema": INSPECTION_SCHEMA,
        "kind": "graph",
        "score_id": graph.score_id,
        "canonical_schema": compiled.canonical_schema,
        "authoring_graph_fingerprint": compiled.authoring_graph_fingerprint,
        "nodes": nodes,
        "edges": edges,
        "harmony": copy.deepcopy(graph.harmony),
        "form": copy.deepcopy(graph.form),
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "materials": len(graph.materials),
            "clips": len(_clip_records(graph)),
        },
    }
