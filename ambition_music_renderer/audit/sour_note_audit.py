"""Score-level sour-note audit for MusicIR cues.

The dissonance audit ranks overlapping note pairs. This module answers a
slightly different composing question: "which individual note events look wrong
for the harmony/key at their timestamp, and where in the YAML did they come
from?"

It expands the MusicIR score into MIDI note events, compares each event against
its active chord plus an inferred section key, and writes JSON/TSV/Markdown
reports that include layer, group, bar/beat/time, and best-effort YAML source
hints such as ``layer_templates.answer_phrase.roots[2]``.
"""

from __future__ import annotations

from ..profiler import profile

import kwconf
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import pretty_midi

from ..render.score_core import load_yaml
from ..render.score_layers import build_score
from ..render.score_theory import chord_for_bar, chord_intervals, chord_pitches, note_to_midi

try:  # Optional plotting dependency.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except Exception:  # pragma: no cover - plotting is best-effort.
    plt = None
    HAS_MATPLOTLIB = False

PC_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAJOR_SCALE = {0, 2, 4, 5, 7, 9, 11}
NATURAL_MINOR_SCALE = {0, 2, 3, 5, 7, 8, 10}

INTERVAL_CLASS_NAMES = {
    0: "unison/octave",
    1: "minor second/major seventh",
    2: "major second/minor seventh",
    3: "minor third/major sixth",
    4: "major third/minor sixth",
    5: "perfect fourth/fifth",
    6: "tritone",
}

# Tuned for triadic chamber/folk material. These weights deliberately make
# minor seconds, major sevenths, and tritones prominent while still letting
# diatonic passing tones remain lower priority.
INTERVAL_PRESSURE = {
    0: 0.00,
    1: 1.00,
    2: 0.36,
    3: 0.08,
    4: 0.04,
    5: 0.08,
    6: 0.78,
}


@profile
def _round3(value: float) -> float:
    return round(float(value), 3)


@profile
def _pc_name(pc: int) -> str:
    return PC_NAMES[int(pc) % 12]


@profile
def _section_starts(spec: dict[str, Any]) -> dict[str, int]:
    starts: dict[str, int] = {}
    cursor = 0
    for section in spec.get("sections", []):
        starts[str(section.get("id", ""))] = cursor
        cursor += int(section.get("bars", 0))
    return starts


@profile
def _section_for_bar(spec: dict[str, Any], bar0: int) -> tuple[dict[str, Any] | None, int]:
    cursor = 0
    for section in spec.get("sections", []):
        bars = int(section.get("bars", 0))
        if cursor <= bar0 < cursor + bars:
            return section, bar0 - cursor
        cursor += bars
    return None, bar0


@profile
def _chord_for_abs_bar(spec: dict[str, Any], bar0: int) -> str:
    section, local = _section_for_bar(spec, bar0)
    if not section:
        return ""
    return chord_for_bar(section, local)


@profile
def _chord_pcs(chord: str) -> set[int]:
    try:
        return {int(p) % 12 for p in chord_pitches(chord, octave=4, voicing="closed")}
    except Exception:
        return set()


@profile
def _chord_root_pc(chord: str) -> int | None:
    try:
        root, _intervals, _slash = chord_intervals(chord)
        return note_to_midi(f"{root}4") % 12
    except Exception:
        return None


@profile
def _infer_section_keys(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keys: dict[str, dict[str, Any]] = {}
    for section in spec.get("sections", []):
        sid = str(section.get("id", ""))
        harmony = [str(ch) for ch in (section.get("harmony") or [])]
        chord_pcs = [_chord_pcs(ch) for ch in harmony]
        chord_roots = [_chord_root_pc(ch) for ch in harmony]
        best: tuple[float, int, str, set[int]] | None = None
        for tonic in range(12):
            for mode, intervals in (("major", MAJOR_SCALE), ("minor", NATURAL_MINOR_SCALE)):
                pcs = {(tonic + i) % 12 for i in intervals}
                score = 0.0
                for cps, root_pc in zip(chord_pcs, chord_roots):
                    if cps:
                        score += sum(1.0 for pc in cps if pc in pcs) / len(cps)
                    if root_pc is not None and root_pc in pcs:
                        score += 0.35
                    if root_pc == tonic:
                        score += 0.25
                candidate = (score, tonic, mode, pcs)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if best is None:
            keys[sid] = {"name": "unknown", "pcs": set()}
        else:
            _score, tonic, mode, pcs = best
            keys[sid] = {
                "name": f"{_pc_name(tonic)} {mode}",
                "tonic_pc": tonic,
                "mode": mode,
                "pcs": pcs,
            }
    return keys


@profile
def _state_weights(spec: dict[str, Any], state: str = "default") -> dict[str, float]:
    states = spec.get("state_map") or {}
    if not isinstance(states, dict):
        return {}
    data = states.get(state) or next(iter(states.values()), {}) if states else {}
    if not isinstance(data, dict):
        return {}
    stems = data.get("stems") or {}
    return {str(k): float(v) for k, v in stems.items()} if isinstance(stems, dict) else {}


@profile
def _events_for_spec(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], float, float]:
    pm, groups, _section_meta = build_score(spec)
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    events = list(getattr(pm, "_ambition_note_events", []) or [])
    if not events:
        for inst in pm.instruments:
            name = inst.name or f"program_{inst.program}"
            for note in inst.notes:
                events.append(
                    {
                        "instrument": name,
                        "group": groups.get(name, name),
                        "section": None,
                        "layer": None,
                        "layer_kind": None,
                        "pitch": int(note.pitch),
                        "note": pretty_midi.note_number_to_name(int(note.pitch)),
                        "velocity": int(note.velocity),
                        "start_time": float(note.start),
                        "end_time": float(note.end),
                        "start_beat": float(note.start / 60.0 * bpm),
                        "end_beat": float(note.end / 60.0 * bpm),
                    }
                )
    return events, bpm, beats_per_bar


@profile
def _interval_class_to_chord(pc: int, chord_pcs: set[int]) -> tuple[int | None, float, str]:
    if not chord_pcs:
        return None, 0.0, ""
    best_ic: int | None = None
    best_pressure = -1.0
    for cpc in chord_pcs:
        diff = abs((pc - cpc) % 12)
        ic = min(diff, 12 - diff)
        pressure = INTERVAL_PRESSURE.get(ic, 0.0)
        if pressure > best_pressure:
            best_ic = ic
            best_pressure = pressure
    return best_ic, max(0.0, best_pressure), INTERVAL_CLASS_NAMES.get(best_ic or 0, "")


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
    layer: dict[str, Any],
    section_starts: dict[str, int],
    beats_per_bar: float,
) -> tuple[str, int | None, int | None, Any]:
    """Return a best-effort YAML source hint for a motif note event."""
    layer_name = str(ev.get("layer") or "?")
    section_id = str(ev.get("section") or "")
    section_start = section_starts.get(section_id, 0)
    local_bar = float(ev.get("nominal_bar", ev.get("start_beat", 0.0) / beats_per_bar)) - section_start
    nominal_beat = float(ev.get("nominal_beat", 0.0))
    roots = layer.get("roots") or None
    root = layer.get("root")
    starts = layer.get("starts") or [[0, 0.0]]
    every_bars = float(layer.get("every_bars", 2.0))
    repeats = int(layer.get("repeats", 1))
    best_rep: int | None = None
    best_start: list[Any] | None = None
    best_distance = 1e9
    for rep in range(repeats):
        for start in starts:
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
def _source_hint(
    spec: dict[str, Any],
    ev: dict[str, Any],
    section_starts: dict[str, int],
    beats_per_bar: float,
) -> tuple[str, int | None, int | None, Any]:
    templates = _layer_templates(spec)
    layer_name = str(ev.get("layer") or "?")
    layer = templates.get(layer_name, {})
    kind = str(layer.get("kind") or ev.get("layer_kind") or "")
    if kind == "motif":
        return _motif_source_hint(spec, ev, layer, section_starts, beats_per_bar)
    bar0 = int(float(ev.get("start_beat", 0.0)) // beats_per_bar)
    section, local_bar = _section_for_bar(spec, bar0)
    chord = chord_for_bar(section, local_bar) if section else ""
    section_id = str((section or {}).get("id") or ev.get("section") or "?")
    return (
        f"sections.{section_id}.harmony[{local_bar}]={chord}; layer_templates.{layer_name}",
        None,
        None,
        None,
    )


@profile
def _sample_contexts(
    spec: dict[str, Any],
    ev: dict[str, Any],
    beats_per_bar: float,
    section_keys: dict[str, dict[str, Any]],
    bucket_beats: float,
) -> list[dict[str, Any]]:
    start = float(ev.get("start_beat", 0.0))
    end = float(ev.get("end_beat", start))
    if end <= start:
        end = start + 1e-3
    sample_count = max(1, int(math.ceil((end - start) / bucket_beats)))
    contexts: list[dict[str, Any]] = []
    for idx in range(sample_count):
        beat = min(end - 1e-6, start + (idx + 0.5) * (end - start) / sample_count)
        bar0 = int(beat // beats_per_bar)
        section, local_bar = _section_for_bar(spec, bar0)
        sid = str((section or {}).get("id") or ev.get("section") or "")
        chord = chord_for_bar(section, local_bar) if section else ""
        key = section_keys.get(sid, {"name": "unknown", "pcs": set()})
        contexts.append(
            {
                "bar0": bar0,
                "local_bar0": local_bar,
                "beat": beat,
                "section": sid,
                "chord": chord,
                "chord_pcs": _chord_pcs(chord),
                "chord_root_pc": _chord_root_pc(chord),
                "key_name": key.get("name", "unknown"),
                "key_pcs": key.get("pcs", set()),
            }
        )
    return contexts


@profile
def audit_spec(
    spec: dict[str, Any],
    *,
    bucket_beats: float = 0.25,
    max_candidates: int = 80,
    min_score: float = 0.28,
) -> dict[str, Any]:
    events, bpm, beats_per_bar = _events_for_spec(spec)
    section_keys = _infer_section_keys(spec)
    section_starts = _section_starts(spec)
    default_weights = _state_weights(spec, "default")
    candidates: list[dict[str, Any]] = []
    layer_scores: Counter[str] = Counter()
    group_scores: Counter[str] = Counter()
    warnings: list[str] = []

    if not events:
        return {
            "schema": "ambition.music_sour_note_audit.v1",
            "id": spec.get("id"),
            "warnings": ["score generated no note events"],
            "candidates": [],
            "top_layers": [],
            "top_groups": [],
            "section_keys": {},
        }

    for ev in events:
        group_name = str(ev.get("group") or ev.get("instrument") or "").lower()
        layer_name = str(ev.get("layer") or "").lower()
        layer_kind_name = str(ev.get("layer_kind") or "").lower()
        instrument_name = str(ev.get("instrument") or "").lower()
        # Drum/percussion MIDI notes are control symbols for kit pieces, not
        # pitched harmony. Treating kick/snare/hat note numbers as melody
        # produced hundreds of false sour-note candidates in otherwise useful
        # bundle reports. Dissonance and amplitude reports still cover drum
        # loudness/clutter; this audit is intentionally pitch-harmony only.
        if (
            layer_kind_name == "drums"
            or group_name in {"drums", "percussion"}
            or "drum" in group_name
            or "percussion" in group_name
            or "kit" in instrument_name
            or "drum" in layer_name
        ):
            continue

        pitch = int(ev.get("pitch", 60))
        pc = pitch % 12
        contexts = _sample_contexts(spec, ev, beats_per_bar, section_keys, bucket_beats)
        if not contexts:
            continue
        out_chord = 0
        out_key = 0
        out_key_and_chord = 0
        safe_extension = 0
        pressures: list[float] = []
        intervals: list[str] = []
        chord_names: Counter[str] = Counter()
        key_names: Counter[str] = Counter()
        for ctx in contexts:
            chord_names[str(ctx["chord"])] += 1
            key_names[str(ctx["key_name"])] += 1
            chord_pcs = set(ctx.get("chord_pcs") or set())
            key_pcs = set(ctx.get("key_pcs") or set())
            in_chord = bool(chord_pcs and pc in chord_pcs)
            if chord_pcs and not in_chord:
                out_chord += 1
            if key_pcs and pc not in key_pcs:
                out_key += 1
                # Secondary dominants, diminished chords, and altered chords
                # often contain chromatic chord tones. Those are harmonic
                # intent, not sour notes. Only score out-of-key pressure when
                # the pitch is also outside the current chord.
                if not in_chord:
                    out_key_and_chord += 1
            root_pc = ctx.get("chord_root_pc")
            if key_pcs and pc in key_pcs and root_pc is not None:
                # Diatonic 9ths, 4ths/sus notes, 6ths, and b7ths are common
                # folk/chamber color. They are still non-chord tones, but they
                # should not outrank genuinely out-of-key notes merely because
                # a sustained chord contains a neighboring chord tone.
                if ((pc - int(root_pc)) % 12) in {2, 5, 9, 10}:
                    safe_extension += 1
            _ic, pressure, iname = _interval_class_to_chord(pc, chord_pcs)
            pressures.append(pressure)
            if iname:
                intervals.append(iname)
        out_chord_frac = out_chord / len(contexts)
        out_key_frac = out_key / len(contexts)
        out_key_and_chord_frac = out_key_and_chord / len(contexts)
        safe_extension_frac = safe_extension / len(contexts)
        worst_pressure = max(pressures) if pressures else 0.0
        if out_chord_frac <= 0.0 and out_key_frac <= 0.0 and worst_pressure < 0.5:
            continue

        dur = max(0.0, float(ev.get("end_beat", 0.0)) - float(ev.get("start_beat", 0.0)))
        velocity = int(ev.get("velocity", 64))
        group = str(ev.get("group") or ev.get("instrument") or "?")
        layer = str(ev.get("layer") or "?")
        layer_kind = str(ev.get("layer_kind") or "")
        default_weight = float(default_weights.get(group, 1.0))
        duration_weight = math.sqrt(max(0.18, min(dur, 4.0)))
        velocity_weight = math.sqrt(max(1.0, velocity) / 64.0)
        state_weight = 0.25 + 0.75 * max(0.0, min(default_weight, 1.0))
        support_weight = 1.18 if layer_kind in {"bassline", "pad_chords", "chord_hits", "pedal", "root_hits"} else 1.0
        register_weight = 1.15 if pitch < 48 or pitch >= 72 else 1.0
        # Penalize out-of-key non-chord tones more heavily than diatonic passing
        # tones. The pressure term catches b2/maj7/tritone color against the
        # current chord even when the section key is ambiguous.
        extension_discount = 1.0 - 0.55 * safe_extension_frac
        base = (0.65 * out_chord_frac + 0.90 * worst_pressure) * extension_discount + 0.80 * out_key_and_chord_frac
        score = base * duration_weight * velocity_weight * state_weight * support_weight * register_weight
        if score < min_score:
            continue
        start_beat = float(ev.get("start_beat", 0.0))
        bar0 = int(start_beat // beats_per_bar)
        beat_in_bar = start_beat - bar0 * beats_per_bar
        source_hint, repeat_index, motif_index, motif_interval = _source_hint(spec, ev, section_starts, beats_per_bar)
        chord = chord_names.most_common(1)[0][0] if chord_names else ""
        key_name = key_names.most_common(1)[0][0] if key_names else "unknown"
        worst_interval = Counter(intervals).most_common(1)[0][0] if intervals else ""
        row = {
            "score": _round3(score),
            "time_s": _round3(start_beat * 60.0 / bpm),
            "end_time_s": _round3(float(ev.get("end_beat", start_beat)) * 60.0 / bpm),
            "bar": bar0 + 1,
            "beat": _round3(beat_in_bar + 1.0),
            "section": ev.get("section"),
            "local_bar": _section_for_bar(spec, bar0)[1] + 1,
            "chord": chord,
            "inferred_key": key_name,
            "note": ev.get("note"),
            "pitch": pitch,
            "pc": _pc_name(pc),
            "layer": layer,
            "layer_kind": layer_kind,
            "group": group,
            "instrument": ev.get("instrument"),
            "velocity": velocity,
            "duration_beats": _round3(dur),
            "default_state_weight": _round3(default_weight),
            "out_of_chord_fraction": _round3(out_chord_frac),
            "out_of_key_fraction": _round3(out_key_frac),
            "out_of_key_and_chord_fraction": _round3(out_key_and_chord_frac),
            "safe_extension_fraction": _round3(safe_extension_frac),
            "worst_chord_interval": worst_interval,
            "source_hint": source_hint,
            "repeat_index": repeat_index,
            "motif_index": motif_index,
            "motif_interval": motif_interval,
        }
        candidates.append(row)
        layer_scores[layer] += float(score)
        group_scores[group] += float(score)

    candidates.sort(key=lambda row: (float(row["score"]), float(row["duration_beats"])), reverse=True)
    if candidates and float(candidates[0]["score"]) > 2.0:
        top = candidates[0]
        warnings.append(
            f"strong sour-note candidate at bar {top['bar']} beat {top['beat']}: {top['note']} in layer {top['layer']}"
        )
    if len(candidates) > 20:
        warnings.append("many sour-note candidates found; inspect source_hint clusters before editing individual notes")

    def counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
        return [{"name": k, "score": _round3(v)} for k, v in counter.most_common(16)]

    return {
        "schema": "ambition.music_sour_note_audit.v1",
        "id": spec.get("id"),
        "title": spec.get("title"),
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "bucket_beats": bucket_beats,
        "note_count": len(events),
        "candidate_count": len(candidates),
        "section_keys": {
            sid: {k: v for k, v in data.items() if k != "pcs"} | {"pcs": sorted(_pc_name(pc) for pc in data.get("pcs", set()))}
            for sid, data in section_keys.items()
        },
        "candidates": candidates[:max_candidates],
        "top_layers": counter_rows(layer_scores),
        "top_groups": counter_rows(group_scores),
        "warnings": warnings,
    }


@profile
def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "score",
        "time_s",
        "end_time_s",
        "bar",
        "beat",
        "local_bar",
        "chord",
        "inferred_key",
        "note",
        "layer",
        "group",
        "duration_beats",
        "velocity",
        "out_of_chord_fraction",
        "out_of_key_fraction",
        "out_of_key_and_chord_fraction",
        "worst_chord_interval",
        "source_hint",
    ]
    lines = ["\t".join(columns)]
    for row in rows:
        lines.append("\t".join(str(row.get(c, "")) for c in columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf8")


@profile
def _save_figure(fig: Any, path: Path, *, plot_format: str, jpeg_quality: int = 90) -> None:
    fmt = plot_format.lower()
    save_kwargs: dict[str, Any] = {"dpi": 150, "bbox_inches": "tight"}
    if fmt in {"jpg", "jpeg"}:
        save_kwargs["format"] = "jpeg"
        save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality), "optimize": True}
    else:
        save_kwargs["format"] = fmt
    fig.savefig(path, **save_kwargs)
    plt.close(fig)


@profile
def _write_timeline_plot(payload: dict[str, Any], path: Path, *, plot_format: str, jpeg_quality: int) -> bool:
    if not HAS_MATPLOTLIB:
        return False
    candidates = payload.get("candidates", [])
    if not candidates:
        return False
    fig, ax = plt.subplots(figsize=(11, 3.8))
    xs = [float(row["time_s"]) for row in candidates]
    ys = [float(row["score"]) for row in candidates]
    ax.scatter(xs, ys, s=18)
    ax.set_title(f"Sour-note candidates — {payload.get('id')}")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("candidate score")
    ax.grid(True, alpha=0.3)
    for row in candidates[:8]:
        ax.annotate(
            f"b{row['bar']} {row['note']}",
            (float(row["time_s"]), float(row["score"])),
            xytext=(0, 6),
            textcoords="offset points",
            fontsize=7,
        )
    _save_figure(fig, path, plot_format=plot_format, jpeg_quality=jpeg_quality)
    return True


@profile
def _write_layer_plot(payload: dict[str, Any], path: Path, *, plot_format: str, jpeg_quality: int) -> bool:
    if not HAS_MATPLOTLIB:
        return False
    rows = payload.get("top_layers", [])[:12]
    if not rows:
        return False
    labels = [str(row["name"]) for row in rows]
    values = [float(row["score"]) for row in rows]
    fig, ax = plt.subplots(figsize=(8.5, max(3.0, 0.38 * len(labels) + 1.5)))
    positions = list(range(len(labels)))
    ax.barh(positions, values)
    ax.set_yticks(positions, labels=labels)
    ax.invert_yaxis()
    ax.set_xlabel("total sour-note score")
    ax.set_title(f"Sour-note score by layer — {payload.get('id')}")
    ax.grid(True, axis="x", alpha=0.3)
    _save_figure(fig, path, plot_format=plot_format, jpeg_quality=jpeg_quality)
    return True


@profile
def write_reports(
    payload: dict[str, Any],
    reports_dir: Path,
    *,
    plots_dir: Path | None = None,
    plot_format: str = "jpg",
    jpeg_quality: int = 90,
) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    json_path = reports_dir / "sour_note_candidates.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")
    paths["json"] = str(json_path)

    tsv_path = reports_dir / "sour_note_candidates.tsv"
    _write_tsv(tsv_path, payload.get("candidates", []))
    paths["tsv"] = str(tsv_path)

    summary_path = reports_dir / "sour_note_candidates_summary.txt"
    lines: list[str] = [
        f"cue: {payload.get('id')}",
        f"bucket_beats: {payload.get('bucket_beats')}",
        f"note_count: {payload.get('note_count')}",
        f"candidate_count: {payload.get('candidate_count')}",
        "",
        "inferred section keys:",
    ]
    for sid, data in (payload.get("section_keys") or {}).items():
        lines.append(f"  {sid}: {data.get('name')} ({', '.join(data.get('pcs', []))})")
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("warnings:")
        lines.extend(f"  - {w}" for w in warnings)
    lines.append("")
    lines.append("top sour-note candidates:")
    for row in payload.get("candidates", [])[:16]:
        lines.append(
            f"  {row['time_s']:>6.2f}-{row['end_time_s']:>6.2f}s "
            f"bar {row['bar']} beat {row['beat']} score {row['score']}: "
            f"{row['note']} in {row['layer']} over {row['chord']} "
            f"({row['worst_chord_interval']}); {row['source_hint']}"
        )
    lines.append("")
    lines.append("top layers:")
    for row in payload.get("top_layers", [])[:12]:
        lines.append(f"  {row['name']}: {row['score']}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf8")
    paths["summary"] = str(summary_path)

    md_path = reports_dir / "sour_note_candidates.md"
    md: list[str] = [f"# Sour-note Candidates — {payload.get('id')}", ""]
    if warnings:
        md.append("## Warnings")
        md.append("")
        md.extend(f"- {w}" for w in warnings)
        md.append("")
    md.extend(
        [
            "## Top Candidates",
            "",
            "| rank | score | time | bar | beat | chord | note | layer | source hint |",
            "| ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for rank, row in enumerate(payload.get("candidates", [])[:24], start=1):
        md.append(
            f"| {rank} | {row['score']} | {row['time_s']}–{row['end_time_s']} | "
            f"{row['bar']} | {row['beat']} | {row['chord']} | {row['note']} | "
            f"{row['layer']} | `{row['source_hint']}` |"
        )
    md.append("")
    md_path.write_text("\n".join(md), encoding="utf8")
    paths["markdown"] = str(md_path)

    if plots_dir is not None:
        plots_dir.mkdir(parents=True, exist_ok=True)
        suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
        timeline = plots_dir / f"sour_note_timeline.{suffix}"
        if _write_timeline_plot(payload, timeline, plot_format=plot_format, jpeg_quality=jpeg_quality):
            paths["timeline_plot"] = str(timeline)
        layers = plots_dir / f"sour_note_layers.{suffix}"
        if _write_layer_plot(payload, layers, plot_format=plot_format, jpeg_quality=jpeg_quality):
            paths["layer_plot"] = str(layers)
    return paths


@profile
def audit_file(path: Path, *, bucket_beats: float = 0.25, max_candidates: int = 80, min_score: float = 0.28) -> dict[str, Any]:
    return audit_spec(load_yaml(path), bucket_beats=bucket_beats, max_candidates=max_candidates, min_score=min_score)


class SourNoteAuditConfig(kwconf.Config):
    """Audit likely sour-note candidates."""


    score: Path = kwconf.Value(None, position=1, parser=Path)
    outdir: Path | None = kwconf.Value(None, parser=Path)
    plots: Path | None = kwconf.Value(None, parser=Path)
    bucket_beats: float = kwconf.Value(0.25)
    max_candidates: int = kwconf.Value(80)
    min_score: float = kwconf.Value(0.28)
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"])
    json: bool = kwconf.Flag(False)




@profile
def main(argv: list[str] | None = None) -> int:
    args = SourNoteAuditConfig.cli(argv=argv)
    payload = audit_file(
        args.score,
        bucket_beats=args.bucket_beats,
        max_candidates=args.max_candidates,
        min_score=args.min_score,
    )
    outdir = args.outdir or (args.score.parent / "reports")
    paths = write_reports(payload, outdir, plots_dir=args.plots, plot_format=args.plot_format)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(paths["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
