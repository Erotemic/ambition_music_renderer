"""Playback layers: the files a game plays when it mixes a cue from layers.

A score asks for them in its ``playback`` block::

    playback:
      layers:
        bed: [arpeggio, bass, organ, piano]
        drums: [drums]
      sections:
        - {id: intro, form: [intro]}
        - {id: trail, form: [main_a, main_b], loop: true}

A layer is the sum of its stem groups. The groups are the stems after group
processing and before the master chain, so the sum of all layers is the
pre-master mix, and a game that plays fewer layers gets a quieter mix with no
compression from the layers it does not play.

A section is a span of consecutive form sections. Without ``sections``, each
form section is one playback section.

Each file starts and ends with a short fade, so a loop does not click at its
seam. A note that rings across the end of a looped section stops there: keep
long notes inside the loop.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

# A layer with this name would publish to the path of the mastered section mix.
RESERVED_LAYER_IDS = {"full"}
FADE_IN_SECONDS = 0.001
FADE_OUT_SECONDS = 0.004


def playback_layer_plan(
    spec: dict[str, Any], section_meta: list[dict[str, Any]], group_names: list[str]
) -> dict[str, Any] | None:
    """The layers and sections that ``spec`` asks for, or ``None`` if it asks for none.

    Raises ``ValueError`` when the block cannot give a complete mix: a group in
    two layers or in no layer, an unknown group, or a section that is not a
    span of consecutive form sections.
    """
    playback = spec.get("playback") or {}
    authored_layers = playback.get("layers")
    if not authored_layers:
        return None
    if not isinstance(authored_layers, dict):
        raise ValueError("playback.layers must map each layer id to a list of groups")

    known = set(group_names)
    owner: dict[str, str] = {}
    layers: dict[str, list[str]] = {}
    for layer_id, groups in authored_layers.items():
        layer_id = str(layer_id)
        if layer_id in RESERVED_LAYER_IDS:
            raise ValueError(f"playback.layers: the layer id {layer_id!r} is reserved")
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"playback.layers.{layer_id} must be a list of one or more groups")
        for group in map(str, groups):
            if group not in known:
                raise ValueError(
                    f"playback.layers.{layer_id}: unknown group {group!r}; the groups are {sorted(known)}"
                )
            if group in owner:
                raise ValueError(
                    f"playback.layers: group {group!r} is in layer {owner[group]!r} and in layer {layer_id!r}"
                )
            owner[group] = layer_id
        layers[layer_id] = [str(group) for group in groups]
    missing = sorted(known - set(owner))
    if missing:
        raise ValueError(f"playback.layers: these groups are in no layer: {missing}")

    form_ids = [str(sec["id"]) for sec in section_meta]
    by_id = {str(sec["id"]): sec for sec in section_meta}
    authored_sections = playback.get("sections") or [{"id": fid, "form": [fid]} for fid in form_ids]
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in authored_sections:
        if not isinstance(row, dict) or "id" not in row:
            raise ValueError("playback.sections: each row needs an id")
        section_id = str(row["id"])
        if section_id in seen:
            raise ValueError(f"playback.sections: the id {section_id!r} is there two times")
        seen.add(section_id)
        span = [str(fid) for fid in (row.get("form") or [section_id])]
        unknown = [fid for fid in span if fid not in by_id]
        if unknown:
            raise ValueError(
                f"playback.sections.{section_id}: unknown form sections {unknown}; the form is {form_ids}"
            )
        first = form_ids.index(span[0])
        if form_ids[first:first + len(span)] != span:
            raise ValueError(
                f"playback.sections.{section_id}: {span} is not a span of consecutive form sections; the form is {form_ids}"
            )
        head, tail = by_id[span[0]], by_id[span[-1]]
        sections.append({
            "id": section_id,
            "form": span,
            "loop": bool(row.get("loop", False)),
            "start_seconds": float(head["start_seconds"]),
            "end_seconds": float(tail["end_seconds"]),
            "start_beat": float(head["start_beat"]),
            "end_beat": float(tail["end_beat"]),
            "duration_beats": float(tail["end_beat"]) - float(head["start_beat"]),
        })
    return {"layers": layers, "sections": sections}


def layer_section_audio(
    stem_audio: dict[str, np.ndarray],
    groups: list[str],
    sample_rate: int,
    start_seconds: float,
    end_seconds: float,
) -> np.ndarray:
    """The sum of ``groups`` from ``start_seconds`` to ``end_seconds``, with the seam fades."""
    first = max(0, int(round(start_seconds * sample_rate)))
    last = max(first, int(round(end_seconds * sample_rate)))
    piece = sum(np.asarray(stem_audio[group][first:last], dtype=np.float32) for group in groups)
    piece = np.array(piece, dtype=np.float32, copy=True)
    fade_in = min(len(piece), int(round(FADE_IN_SECONDS * sample_rate)))
    fade_out = min(len(piece), int(round(FADE_OUT_SECONDS * sample_rate)))
    shape = (-1,) + (1,) * (piece.ndim - 1)
    if fade_in:
        piece[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32).reshape(shape)
    if fade_out:
        piece[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32).reshape(shape)
    return piece


def write_playback_layers(
    plan: dict[str, Any],
    stem_audio: dict[str, np.ndarray],
    sample_rate: int,
    outdir: Path,
    file_stem: str,
    write_audio: Callable[[np.ndarray, Path], Any],
) -> dict[str, dict[str, str]]:
    """Write ``playback/<section>/<file_stem>.<section>.<layer>.ogg`` for each pair.

    Returns the paths relative to ``outdir``, for the manifest.
    """
    files: dict[str, dict[str, str]] = {}
    for section in plan["sections"]:
        for layer_id, groups in plan["layers"].items():
            piece = layer_section_audio(
                stem_audio, groups, sample_rate, section["start_seconds"], section["end_seconds"]
            )
            path = outdir / "playback" / section["id"] / f"{file_stem}.{section['id']}.{layer_id}.ogg"
            write_audio(piece, path)
            files.setdefault(section["id"], {})[layer_id] = str(path.relative_to(outdir))
    return files
