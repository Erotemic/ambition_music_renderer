"""Playback layers: the files a game plays when it mixes a cue from layers.

A score asks for them in its ``playback`` block::

    playback:
      layers:
        bed: [arpeggio, bass, organ, piano]
        drums: [drums]
      full: true
      sections:
        - {id: intro, form: [intro], tail: intro_ring}
        - {id: trail, form: [main_a, main_b], loop: true, lead_in: intro_ring, tail: trail_ring}

A layer is the sum of its stem groups. The groups are the stems after group
processing and before the master chain, so the sum of all layers is the
pre-master mix, and a game that plays fewer layers gets a quieter mix with no
compression from the layers it does not play.

``full: true`` also writes the mastered mix of each section as its ``full``
file: its share of one composition master. A score can ask for ``full`` with
no ``layers``.

A section is a span of consecutive form sections. Without ``sections``, each
form section is one playback section.

A section's ``tail`` is the form section right after its span, with no notes
in it: the notes and the reverb of the span ring into it. A looped section
adds its tail onto its head, so its ring sounds across the seam as it does
when the loop comes round again. Another section plays its tail after its end
(the game starts the next section at the end and fades this one out under
it). Make a tail longer than the longest ring.

A looped section's ``lead_in`` is the form section right before its span,
with no notes in it. Humanized notes on the first beat of the loop start a
few milliseconds early, in it. The loop adds the last beat of its lead-in
onto its end, so those starts sound before the seam. Make the lead-in longer
than the ring of the section before it plus one beat.

Give the tail the stem and section gains of the section that follows the
loop's end in the loop, and the lead-in the gains of the loop's last section:
then the gain ramps at both ends of the loop are the ramps of its seam.

A section with no tail and no lead-in starts and ends with a short fade, so a
loop does not click at its seam: a note that rings across the end of such a
loop stops there. A looped section with a tail or a lead-in has no fades: its
last sample runs on into its first.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..musicir.model import CompiledScore

# A layer with this name would publish to the path of the mastered section mix.
RESERVED_LAYER_IDS = {"full"}


def runtime_product_path(family: str, section: str, layer: str) -> Path:
    return Path(family) / section / f"{section}.{layer}.ogg"


def select_runtime_export_stems(
    native_stems: dict[str, np.ndarray],
    shared_gain_stems: dict[str, np.ndarray],
    gain_mode: str,
) -> dict[str, np.ndarray]:
    """Select one consistent gain domain for *all* exported runtime assets.

    Adaptive single-stem assets and grouped playback layers must share the
    same attenuation in ``shared`` mode. Otherwise decoding a layer group
    can clip even when individual adaptive stems have adequate headroom.
    """
    if gain_mode == "shared":
        return shared_gain_stems
    if gain_mode == "native":
        return native_stems
    raise ValueError(f"unknown runtime stem gain mode: {gain_mode!r}")


FADE_IN_SECONDS = 0.001
FADE_OUT_SECONDS = 0.004


def playback_layout(
    spec: dict[str, Any], form_ids: list[str], group_names: list[str]
) -> dict[str, Any] | None:
    """The layers and sections that ``spec`` asks for, or ``None`` if it asks for none.

    Raises ``ValueError`` when the block cannot give a complete mix: a group in
    two layers or in no layer, an unknown group, or a section that is not a
    span of consecutive form sections.
    """
    playback = spec.get("playback", {})
    if not isinstance(playback, dict):
        raise ValueError("playback must be a mapping")
    authored_layers = playback.get("layers", {})
    if not isinstance(authored_layers, dict):
        raise ValueError("playback.layers must map each layer id to a list of groups")
    full = playback.get("full", False)
    if not isinstance(full, bool):
        raise ValueError("playback.full must be true or false")
    if not authored_layers and not full:
        return None

    known = set(group_names)
    owner: dict[str, str] = {}
    layers: dict[str, list[str]] = {}
    for layer_id, groups in authored_layers.items():
        layer_id = str(layer_id)
        if not layer_id.strip():
            raise ValueError("playback.layers: layer ids must not be empty")
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
    if layers and missing:
        raise ValueError(f"playback.layers: these groups are in no layer: {missing}")

    if len(form_ids) != len(set(form_ids)):
        raise ValueError("playback: duplicate form section ids")
    authored_sections = playback.get("sections")
    if authored_sections is None:
        authored_sections = [{"id": fid, "form": [fid]} for fid in form_ids]
    if not isinstance(authored_sections, list) or not authored_sections:
        raise ValueError("playback.sections must be a non-empty list")
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in authored_sections:
        if not isinstance(row, dict) or "id" not in row:
            raise ValueError("playback.sections: each row needs an id")
        section_id = str(row["id"])
        if not section_id.strip():
            raise ValueError("playback.sections: section ids must not be empty")
        if not isinstance(row.get("loop", False), bool):
            raise ValueError(f"playback.sections.{section_id}.loop must be true or false")
        if section_id in seen:
            raise ValueError(f"playback.sections: the id {section_id!r} is there two times")
        seen.add(section_id)
        span = row.get("form", [section_id])
        if not isinstance(span, list) or not span:
            raise ValueError(f"playback.sections.{section_id}.form must be a non-empty list")
        span = [str(fid) for fid in span]
        unknown = [fid for fid in span if fid not in form_ids]
        if unknown:
            raise ValueError(
                f"playback.sections.{section_id}: unknown form sections {unknown}; the form is {form_ids}"
            )
        first = form_ids.index(span[0])
        if form_ids[first:first + len(span)] != span:
            raise ValueError(
                f"playback.sections.{section_id}: {span} is not a span of consecutive form sections; the form is {form_ids}"
            )
        lead_in = row.get("lead_in")
        if lead_in is not None:
            lead_in = str(lead_in)
            if not row.get("loop", False):
                raise ValueError(f"playback.sections.{section_id}: only a looped section has a lead_in")
            if first == 0 or form_ids[first - 1] != lead_in:
                raise ValueError(
                    f"playback.sections.{section_id}: the lead_in {lead_in!r} is not the form section right "
                    f"before {span[0]!r}; the form is {form_ids}"
                )
        ring = row.get("tail")
        if ring is not None:
            ring = str(ring)
            after = first + len(span)
            if after >= len(form_ids) or form_ids[after] != ring:
                raise ValueError(
                    f"playback.sections.{section_id}: the tail {ring!r} is not the form section right after "
                    f"{span[-1]!r}; the form is {form_ids}"
                )
        sections.append({
            "id": section_id,
            "form": span,
            "loop": bool(row.get("loop", False)),
            "tail": ring,
            "lead_in": lead_in,
        })
    return {"layers": layers, "full": full, "sections": sections}


def playback_layer_plan(compiled: CompiledScore) -> dict[str, Any] | None:
    """Resolve playback layout through the clock and events of one compiled score."""
    layout = playback_layout(compiled.normalized_spec,
                             [str(row["id"]) for row in compiled.sections],
                             list(compiled.group_names))
    if layout is None:
        return None
    by_id = {str(row["id"]): row for row in compiled.sections}
    clock = compiled.clock
    for row in layout["sections"]:
        head, last = by_id[row["form"][0]], by_id[row["form"][-1]]
        start, end = float(head["start_beat"]), float(last["end_beat"])
        if end <= start:
            raise ValueError(f"playback.sections.{row['id']}: musical span must be positive")
        lead = by_id.get(row["lead_in"])
        tail = by_id.get(row["tail"])
        row.update({
            "start_seconds": clock.time_at_beat(start),
            "end_seconds": clock.time_at_beat(end),
            "start_beat": start,
            "end_beat": end,
            "duration_beats": end - start,
            "lead_in_start_seconds": None if lead is None else clock.time_at_beat(max(float(lead["start_beat"]), start - 1.0)),
            "tail_end_seconds": None if tail is None else clock.time_at_beat(float(tail["end_beat"])),
        })
    pickups: dict[str, list[float]] = {}
    attacks = [event for event in compiled.note_events if event.get("event_type", "note") == "note"]
    for entry in layout["sections"]:
        ring = entry["lead_in"]
        if ring is None:
            continue
        for event in attacks:
            at = float(event["start_time"])
            if (event.get("section") in entry["form"]
                    and entry["lead_in_start_seconds"] <= at < entry["start_seconds"]):
                pickups.setdefault(ring, []).append(at)
    for row in layout["sections"]:
        for role in ("lead_in", "tail"):
            ring = row[role]
            if ring is None:
                continue
            for event in attacks:
                if event.get("section") != ring:
                    continue
                raise ValueError(f"playback.sections.{row['id']}: {role} {ring!r} owns note attacks")
    for row in layout["sections"]:
        # A shared spacer can hold an outgoing ring and an incoming pickup.
        # Keep the file span, but exclude the pickup from the outgoing tail.
        tail = by_id.get(row["tail"])
        foreign = [] if tail is None else [float(event["start_time"]) for event in attacks
            if event.get("section") not in [row["tail"], *row["form"]]
            and float(tail["start_seconds"]) <= float(event["start_time"]) < float(tail["end_seconds"])]
        exclusions = [*pickups.get(row["tail"], []), *foreign]
        row["tail_audio_end_seconds"] = min(exclusions) if exclusions else row["tail_end_seconds"]
    return layout


def _frame(seconds: float, sample_rate: int) -> int:
    return max(0, int(round(float(seconds) * sample_rate)))


def _cut(
    timeline: np.ndarray,
    first: int,
    last: int,
    ring_last: int,
    loop: bool,
    sample_rate: int,
    lead_first: int | None = None,
    ring_audio_last: int | None = None,
) -> np.ndarray:
    piece = np.array(timeline[first:last], dtype=np.float32, copy=True)
    stop = ring_last if ring_audio_last is None else min(ring_last, ring_audio_last)
    ring = np.array(timeline[last:max(last, stop)], dtype=np.float32, copy=True)
    if stop < ring_last:
        fade = min(len(ring), int(round(FADE_OUT_SECONDS * sample_rate)))
        if fade:
            ring[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32).reshape((-1,) + (1,) * (ring.ndim - 1))
        ring = np.pad(ring, ((0, ring_last - max(last, stop)),) + ((0, 0),) * (ring.ndim - 1))
    lead = np.asarray(timeline[min(first, first if lead_first is None else lead_first):first], dtype=np.float32)
    if loop and len(piece) and (len(ring) or len(lead)):
        n = min(len(lead), len(piece))
        if n:
            piece[len(piece) - n:] += lead[len(lead) - n:]
        for at in range(0, len(ring), len(piece)):
            part = ring[at:at + len(piece)]
            piece[:len(part)] += part
        return piece
    if len(ring):
        piece = np.concatenate([piece, ring])
    fade_in = min(len(piece), int(round(FADE_IN_SECONDS * sample_rate)))
    fade_out = min(len(piece), int(round(FADE_OUT_SECONDS * sample_rate)))
    shape = (-1,) + (1,) * (piece.ndim - 1)
    if fade_in:
        piece[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32).reshape(shape)
    if fade_out:
        piece[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32).reshape(shape)
    return piece


def cut_section(
    timeline: np.ndarray,
    sample_rate: int,
    start_seconds: float,
    end_seconds: float,
    *,
    tail_end_seconds: float | None = None,
    lead_in_start_seconds: float | None = None,
    tail_audio_end_seconds: float | None = None,
    loop: bool = False,
) -> np.ndarray:
    """The audio of one playback section from ``timeline``, with its tail and its seam fades.

    The tail is ``timeline`` from ``end_seconds`` to ``tail_end_seconds``, and
    the lead-in is ``timeline`` from ``lead_in_start_seconds`` to
    ``start_seconds``. A loop adds its tail onto its head (wrapped again if it
    is longer than the loop) and its lead-in onto its end, and has no fades;
    another section has its tail after its end.
    """
    first = _frame(start_seconds, sample_rate)
    last = max(first, _frame(end_seconds, sample_rate))
    ring_last = last if tail_end_seconds is None else _frame(tail_end_seconds, sample_rate)
    lead_first = None if lead_in_start_seconds is None else _frame(lead_in_start_seconds, sample_rate)
    ring_audio_last = None if tail_audio_end_seconds is None else _frame(tail_audio_end_seconds, sample_rate)
    return _cut(timeline, first, last, ring_last, loop, sample_rate, lead_first, ring_audio_last)


def layer_section_audio(
    stem_audio: dict[str, np.ndarray],
    groups: list[str],
    sample_rate: int,
    start_seconds: float,
    end_seconds: float,
    *,
    tail_end_seconds: float | None = None,
    lead_in_start_seconds: float | None = None,
    tail_audio_end_seconds: float | None = None,
    loop: bool = False,
) -> np.ndarray:
    """The sum of ``groups`` over one section (see :func:`cut_section`)."""
    first = _frame(start_seconds, sample_rate)
    last = max(first, _frame(end_seconds, sample_rate))
    ring_last = last if tail_end_seconds is None else _frame(tail_end_seconds, sample_rate)
    lead_first = first if lead_in_start_seconds is None else min(first, _frame(lead_in_start_seconds, sample_rate))
    window = sum(
        np.asarray(stem_audio[group][lead_first:max(last, ring_last)], dtype=np.float32) for group in groups
    )
    ring_audio_last = None if tail_audio_end_seconds is None else _frame(tail_audio_end_seconds, sample_rate) - lead_first
    return _cut(window, first - lead_first, last - lead_first, ring_last - lead_first, loop, sample_rate, 0, ring_audio_last)


def mastered_section_audio(
    plan: dict[str, Any],
    pre_master: np.ndarray,
    sample_rate: int,
    master: Callable[[np.ndarray], np.ndarray],
) -> dict[str, np.ndarray]:
    """The ``full`` audio of each section: its share of one composition master.

    ``master`` runs one time, over ``pre_master`` followed by each looped
    section two times (its tail on its head and its lead-in on its end). A loop's audio is its second
    pass, so the compressor and the reverb of the master are in the state they
    are in when the loop comes round again, and the seam needs no fades. Every
    other section is cut from the mastered timeline.
    """
    timeline = np.asarray(pre_master, dtype=np.float32)
    passes: list[np.ndarray] = [timeline]
    second_pass: dict[str, tuple[int, int]] = {}
    at = len(timeline)
    for section in plan["sections"]:
        if not section["loop"]:
            continue
        one_pass = cut_section(
            timeline, sample_rate, section["start_seconds"], section["end_seconds"],
            tail_end_seconds=section.get("tail_end_seconds"),
            tail_audio_end_seconds=section.get("tail_audio_end_seconds"),
            lead_in_start_seconds=section.get("lead_in_start_seconds"), loop=True,
        )
        second_pass[section["id"]] = (at + len(one_pass), len(one_pass))
        passes += [one_pass, one_pass]
        at += 2 * len(one_pass)
    mastered = np.asarray(master(np.concatenate(passes)), dtype=np.float32)
    out: dict[str, np.ndarray] = {}
    for section in plan["sections"]:
        if section["id"] in second_pass:
            first, length = second_pass[section["id"]]
            piece = np.array(mastered[first:first + length], dtype=np.float32, copy=True)
            if not (section.get("tail") or section.get("lead_in")):
                piece = cut_section(piece, sample_rate, 0.0, length / sample_rate)
            out[section["id"]] = piece
        else:
            out[section["id"]] = cut_section(
                mastered[: len(timeline)], sample_rate, section["start_seconds"], section["end_seconds"],
                tail_end_seconds=section.get("tail_end_seconds"),
                tail_audio_end_seconds=section.get("tail_audio_end_seconds"),
            )
    return out


def write_playback_layers(
    plan: dict[str, Any],
    stem_audio: dict[str, np.ndarray],
    sample_rate: int,
    outdir: Path,
    file_stem: str,
    write_audio: Callable[[np.ndarray, Path], Any],
    *,
    pre_master: np.ndarray | None = None,
    master: Callable[[np.ndarray], np.ndarray] | None = None,
) -> dict[str, dict[str, str]]:
    """Write ``playback/<section>/<file_stem>.<section>.<layer>.ogg`` for each pair.

    With ``plan["full"]``, also write each section's ``full`` file from
    ``pre_master`` and ``master`` (see :func:`mastered_section_audio`).
    Returns the paths relative to ``outdir``, for the manifest.
    """
    files: dict[str, dict[str, str]] = {}

    def put(section_id: str, layer_id: str, piece: np.ndarray) -> None:
        path = outdir / "playback" / section_id / f"{file_stem}.{section_id}.{layer_id}.ogg"
        write_audio(piece, path)
        files.setdefault(section_id, {})[layer_id] = str(path.relative_to(outdir))

    for section in plan["sections"]:
        for layer_id, groups in plan["layers"].items():
            piece = layer_section_audio(
                stem_audio, groups, sample_rate, section["start_seconds"], section["end_seconds"],
                tail_end_seconds=section.get("tail_end_seconds"),
                tail_audio_end_seconds=section.get("tail_audio_end_seconds"),
                lead_in_start_seconds=section.get("lead_in_start_seconds"), loop=section["loop"],
            )
            put(section["id"], layer_id, piece)
    if plan.get("full"):
        if pre_master is None or master is None:
            raise ValueError("playback.full needs the pre-master timeline and the master chain")
        for section_id, piece in mastered_section_audio(plan, pre_master, sample_rate, master).items():
            put(section_id, "full", piece)
    return files
