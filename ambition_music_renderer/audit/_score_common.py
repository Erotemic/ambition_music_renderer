"""Shared score-structure helpers for the audit tools.

The score-level audits (arrangement, dissonance, sour-note, shrill-note) all
expand a MusicIR spec into note events and reason about sections, chords,
state weights, and YAML source hints. Each of them had grown its own copy of
these helpers (and the copies had drifted — one ``_state_weights`` crashed on
non-dict state entries, one events expansion hardcoded bpm=120). They live
here now so there is a single definition of each judgment.

Numeric/audio helpers (dB, RMS, peak, figure saving) live in ``_common``.
"""

from __future__ import annotations

from typing import Any

from ..profiler import profile


@profile
def events_for_spec(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], float, float]:
    """Expand ``spec`` into note events; return ``(events, bpm, beats_per_bar)``.

    ``build_score`` always attaches the expanded events as
    ``pm._ambition_note_events`` (``score_events.add_note`` is the only place
    notes enter the score, and it records an event for each one), so an empty
    list here means the score genuinely produced no notes.
    """
    from ..render.score_layers import build_score

    pm, _groups, _section_meta = build_score(spec)
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    events = list(getattr(pm, "_ambition_note_events", []) or [])
    return events, bpm, beats_per_bar


@profile
def section_starts(spec: dict[str, Any]) -> dict[str, int]:
    """Absolute start bar (0-based) of each section id."""
    starts: dict[str, int] = {}
    cursor = 0
    for section in spec.get("sections", []):
        starts[str(section.get("id", ""))] = cursor
        cursor += int(section.get("bars", 0))
    return starts


@profile
def section_for_bar(spec: dict[str, Any], bar0: int) -> tuple[dict[str, Any] | None, int]:
    """Map an absolute 0-based bar to ``(section, local_bar)``."""
    cursor = 0
    for section in spec.get("sections", []):
        bars = int(section.get("bars", 0))
        if cursor <= bar0 < cursor + bars:
            return section, bar0 - cursor
        cursor += bars
    return None, bar0


@profile
def chord_for_abs_bar(spec: dict[str, Any], bar0: int) -> str:
    """The chord symbol sounding at an absolute 0-based bar ('' past the end)."""
    from ..render.score_theory import chord_for_bar

    section, local = section_for_bar(spec, bar0)
    if not section:
        return ""
    return chord_for_bar(section, local)


@profile
def chord_pitch_classes(chord: str) -> set[int]:
    """Pitch classes of ``chord``, including any slash bass; empty on parse failure.

    ``chord_pitches`` with the ``closed`` voicing keeps every extension from
    the lead-sheet symbol and inserts the slash bass, so this matches both the
    interval-based and pitch-based variants the audits used to carry.
    """
    from ..render.score_theory import chord_pitches

    try:
        return {int(p) % 12 for p in chord_pitches(chord, octave=4, voicing="closed")}
    except Exception:
        return set()


@profile
def state_weights(spec: dict[str, Any], state: str = "default") -> dict[str, float]:
    """Per-group stem weights for ``state`` (first state as fallback)."""
    states = spec.get("state_map") or {}
    if not isinstance(states, dict):
        return {}
    data = states.get(state) or next(iter(states.values()), {}) if states else {}
    if not isinstance(data, dict):
        return {}
    stems = data.get("stems") or {}
    return {str(k): float(v) for k, v in stems.items()} if isinstance(stems, dict) else {}


@profile
def _layer_templates(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    templates = spec.get("layer_templates") or {}
    return {str(k): v for k, v in templates.items() if isinstance(v, dict)} if isinstance(templates, dict) else {}


@profile
def _motifs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for motif in spec.get("motifs", []) or []:
        if isinstance(motif, dict) and "id" in motif:
            out[str(motif["id"])] = motif
    return out


@profile
def _motif_source_hint(
    spec: dict[str, Any],
    ev: dict[str, Any],
    starts: dict[str, int],
    beats_per_bar: float,
) -> tuple[str, int | None, int | None, Any]:
    """Return a best-effort YAML source hint for a motif note event."""
    layer_name = str(ev.get("layer") or "?")
    section_id = str(ev.get("section") or "")
    section_start = starts.get(section_id, 0)
    local_bar = float(ev.get("nominal_bar", ev.get("start_beat", 0.0) / beats_per_bar)) - section_start
    nominal_beat = float(ev.get("nominal_beat", 0.0))
    layer = _layer_templates(spec).get(layer_name, {})
    roots = layer.get("roots") or None
    root = layer.get("root")
    layer_starts = layer.get("starts") or [[0, 0.0]]
    every_bars = float(layer.get("every_bars", 2.0))
    repeats = int(layer.get("repeats", 1))
    best_rep: int | None = None
    best_start: list[Any] | None = None
    best_distance = 1e9
    for rep in range(repeats):
        for start in layer_starts:
            start_bar = float(start[0]) + rep * every_bars
            start_beat = float(start[1])
            # Compare in absolute beats inside section.
            distance = abs(((local_bar - start_bar) * beats_per_bar + nominal_beat) - start_beat)
            if local_bar >= start_bar - 1e-6 and distance < best_distance:
                best_distance = distance
                best_rep = rep
                best_start = start
    motif_index: int | None = None
    motif_interval: Any = None
    motif_id = str(layer.get("motif", ""))
    motif = _motifs(spec).get(motif_id, {})
    if best_rep is not None and best_start is not None and motif:
        start_bar = float(best_start[0]) + best_rep * every_bars
        start_beat = float(best_start[1])
        rel_beat = (local_bar - start_bar) * beats_per_bar + nominal_beat - start_beat
        rhythm = [float(x) for x in motif.get("rhythm", [1.0])]
        cursor = 0.0
        for idx, dur in enumerate(rhythm):
            scaled = dur * float(layer.get("rhythm_scale", 1.0))
            if cursor - 1e-4 <= rel_beat < cursor + scaled - 1e-4:
                motif_index = idx
                break
            cursor += scaled
        if motif_index is not None:
            intervals = motif.get("intervals")
            notes = motif.get("notes")
            if isinstance(intervals, list) and intervals:
                motif_interval = intervals[motif_index % len(intervals)]
            elif isinstance(notes, list) and notes:
                motif_interval = notes[motif_index % len(notes)]
    if roots and best_rep is not None:
        root_idx = best_rep % len(roots)
        root_val = roots[root_idx]
        hint = f"layer_templates.{layer_name}.roots[{root_idx}]={root_val}"
    elif root is not None:
        hint = f"layer_templates.{layer_name}.root={root}"
    else:
        hint = f"layer_templates.{layer_name}"
    if motif_index is not None:
        hint += f"; motifs.{motif_id}.intervals[{motif_index}]={motif_interval}"
    return hint, best_rep, motif_index, motif_interval


@profile
def source_hint(
    spec: dict[str, Any],
    ev: dict[str, Any],
    starts: dict[str, int],
    beats_per_bar: float,
) -> tuple[str, int | None, int | None, Any]:
    """Best-effort YAML source hint for a note event.

    Returns ``(hint, repeat_index, motif_index, motif_interval)``; the indices
    are only populated for motif layers.
    """
    from ..render.score_theory import chord_for_bar

    templates = _layer_templates(spec)
    layer_name = str(ev.get("layer") or "?")
    layer = templates.get(layer_name, {})
    kind = str(layer.get("kind") or ev.get("layer_kind") or "")
    if kind == "motif":
        return _motif_source_hint(spec, ev, starts, beats_per_bar)
    bar0 = int(float(ev.get("start_beat", 0.0)) // beats_per_bar)
    section, local_bar = section_for_bar(spec, bar0)
    chord = chord_for_bar(section, local_bar) if section else ""
    section_id = str((section or {}).get("id") or ev.get("section") or "?")
    return (
        f"sections.{section_id}.harmony[{local_bar}]={chord}; layer_templates.{layer_name}",
        None,
        None,
        None,
    )
