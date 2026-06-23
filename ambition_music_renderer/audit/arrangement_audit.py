"""Pure-Python arrangement preflight for MusicIR cues.

This is a score/MIDI-level audit, not an audio render. It catches common
composition and orchestration problems before spending time on synthesis:

* stem groups that are present but likely buried in the default state,
* one group dominating the arrangement,
* low-register density that can make bass lines muddy or clash-prone,
* long/high-velocity non-chord tones that may sound like wrong notes,
* sparse or overly similar state mixes.

The report is intentionally heuristic. It should point a composer/agent to
places that deserve listening, not replace listening.
"""

from __future__ import annotations

from ..profiler import profile

import lazy_loader as lazy

import kwconf
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

pretty_midi = lazy.load("pretty_midi")


@profile
def _round3(value: float) -> float:
    return round(float(value), 3)


@profile
def _events_for_spec(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], float, float]:
    from ..render.score_layers import build_score

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
                        "start_beat": float(note.start / 60.0 * bpm),
                        "end_beat": float(note.end / 60.0 * bpm),
                    }
                )
    return events, bpm, beats_per_bar


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
def _chord_pcs(spec: dict[str, Any], bar0: int) -> set[int]:
    from ..render.score_theory import chord_for_bar, chord_pitches

    section, local_bar = _section_for_bar(spec, bar0)
    if not section:
        return set()
    chord = chord_for_bar(section, local_bar)
    return {int(p) % 12 for p in chord_pitches(chord, octave=4, voicing="closed")}


@profile
def _state_weights(spec: dict[str, Any], state: str = "default") -> dict[str, float]:
    states = spec.get("state_map") or {}
    data = states.get(state) or next(iter(states.values()), {}) if states else {}
    return {str(k): float(v) for k, v in (data.get("stems") or {}).items()}


@profile
def _weighted_event_value(ev: dict[str, Any]) -> float:
    dur = max(0.0, float(ev.get("end_beat", 0.0)) - float(ev.get("start_beat", 0.0)))
    return dur * max(1.0, float(ev.get("velocity", 64)))


@profile
def _active_events(events: list[dict[str, Any]], beat: float) -> list[dict[str, Any]]:
    return [ev for ev in events if float(ev.get("start_beat", 0.0)) <= beat < float(ev.get("end_beat", 0.0))]


@profile
def audit_spec(spec: dict[str, Any], *, bucket_beats: float = 0.25, max_rows: int = 40) -> dict[str, Any]:
    events, bpm, beats_per_bar = _events_for_spec(spec)
    warnings: list[str] = []
    if not events:
        return {
            "schema": "ambition.music_arrangement_audit.v1",
            "id": spec.get("id"),
            "warnings": ["score generated no note events"],
            "groups": [],
            "bar_density": [],
            "bass_collision_candidates": [],
            "harmonic_outliers": [],
        }

    default_weights = _state_weights(spec, "default")
    group_raw: Counter[str] = Counter()
    group_weighted: Counter[str] = Counter()
    group_note_counts: Counter[str] = Counter()
    group_pitch_min: dict[str, int] = {}
    group_pitch_max: dict[str, int] = {}
    for ev in events:
        group = str(ev.get("group") or ev.get("instrument") or "?")
        value = _weighted_event_value(ev)
        group_raw[group] += value
        group_weighted[group] += value * float(default_weights.get(group, 1.0))
        group_note_counts[group] += 1
        pitch = int(ev.get("pitch", 60))
        group_pitch_min[group] = min(group_pitch_min.get(group, pitch), pitch)
        group_pitch_max[group] = max(group_pitch_max.get(group, pitch), pitch)

    total_weighted = sum(group_weighted.values()) or 1.0
    total_raw = sum(group_raw.values()) or 1.0
    group_rows: list[dict[str, Any]] = []
    for group in sorted(group_raw):
        row = {
            "group": group,
            "note_count": int(group_note_counts[group]),
            "raw_share": _round3(group_raw[group] / total_raw),
            "default_state_weight": _round3(default_weights.get(group, 1.0)),
            "default_weighted_share": _round3(group_weighted[group] / total_weighted),
            "pitch_min": pretty_midi.note_number_to_name(group_pitch_min[group]),
            "pitch_max": pretty_midi.note_number_to_name(group_pitch_max[group]),
        }
        group_rows.append(row)
    group_rows.sort(key=lambda row: float(row["default_weighted_share"]), reverse=True)

    for row in group_rows:
        group = row["group"]
        share = float(row["default_weighted_share"])
        state_weight = float(row["default_state_weight"])
        if state_weight >= 0.50 and share < 0.06:
            warnings.append(
                f"group {group!r} is enabled in default state but has only {share:.1%} weighted score presence; it may be hard to hear"
            )
        if share > 0.68:
            warnings.append(f"group {group!r} contributes {share:.1%} of weighted score presence; it may dominate the arrangement")

    end_beat = max(float(ev.get("end_beat", 0.0)) for ev in events)
    bucket_count = int(math.ceil(end_beat / bucket_beats))
    low_density_rows: list[dict[str, Any]] = []
    bass_collision_rows: list[dict[str, Any]] = []
    bar_density_counter: Counter[int] = Counter()
    bar_velocity_weight: Counter[int] = Counter()
    harmonic_outliers: list[dict[str, Any]] = []
    high_register_rows: list[dict[str, Any]] = []

    for ev in events:
        dur = max(0.0, float(ev.get("end_beat", 0.0)) - float(ev.get("start_beat", 0.0)))
        bar0 = int(float(ev.get("start_beat", 0.0)) // beats_per_bar)
        bar_density_counter[bar0] += 1
        bar_velocity_weight[bar0] += _weighted_event_value(ev)
        pitch = int(ev.get("pitch", 60))
        pcs = _chord_pcs(spec, bar0)
        if pcs and (pitch % 12) not in pcs and dur >= 0.7 and int(ev.get("velocity", 64)) >= 34:
            layer_kind = str(ev.get("layer_kind") or "")
            # Motif notes are often passing/neighbor tones. Still report them,
            # but with a lower severity so the list prioritizes sustained pads,
            # basses, and harmonic support that accidentally leave the chord.
            severity = dur * float(ev.get("velocity", 64)) / (48.0 if layer_kind == "motif" else 32.0)
            harmonic_outliers.append(
                {
                    "bar": bar0 + 1,
                    "beat": _round3(float(ev.get("start_beat", 0.0)) - bar0 * beats_per_bar + 1.0),
                    "note": ev.get("note"),
                    "layer": ev.get("layer"),
                    "group": ev.get("group"),
                    "duration_beats": _round3(dur),
                    "velocity": int(ev.get("velocity", 64)),
                    "severity": _round3(severity),
                }
            )
        group = str(ev.get("group") or "")
        layer_kind = str(ev.get("layer_kind") or "")
        if group not in {"drums", "percussion"} and layer_kind != "drums" and pitch >= 96:
            # MIDI 96 is C7.  Guitar/pad/brass content here is often a sign of
            # a voicing generator escaping into whistle-tone territory, even
            # when the pitch class is technically harmonic.
            start = float(ev.get("start_beat", 0.0))
            high_register_rows.append(
                {
                    "bar": bar0 + 1,
                    "beat": _round3(start - bar0 * beats_per_bar + 1.0),
                    "time_s": _round3(start * 60.0 / bpm),
                    "note": ev.get("note"),
                    "pitch": int(pitch),
                    "layer": ev.get("layer"),
                    "group": ev.get("group"),
                    "instrument": ev.get("instrument"),
                    "section": ev.get("section"),
                    "duration_beats": _round3(dur),
                    "velocity": int(ev.get("velocity", 64)),
                    "severity": _round3((pitch - 95) * max(1.0, dur) * max(1.0, float(ev.get("velocity", 64))) / 96.0),
                }
            )

    for idx in range(bucket_count):
        beat = idx * bucket_beats + bucket_beats * 0.5
        active = _active_events(events, beat)
        low = [ev for ev in active if int(ev.get("pitch", 60)) < 48]
        if len(low) >= 3:
            bar0 = int(beat // beats_per_bar)
            low_density_rows.append(
                {
                    "bar": bar0 + 1,
                    "beat": _round3(beat - bar0 * beats_per_bar + 1.0),
                    "low_note_count": len(low),
                    "notes": "+".join(str(ev.get("note")) for ev in sorted(low, key=lambda row: int(row.get("pitch", 60)))[:8]),
                    "layers": "+".join(sorted({str(ev.get("layer")) for ev in low})),
                }
            )
        lows = [ev for ev in active if int(ev.get("pitch", 60)) < 48]
        highs = [ev for ev in active if int(ev.get("pitch", 60)) >= 72]
        for low_ev in lows:
            for hi_ev in highs:
                diff = abs(int(low_ev.get("pitch", 60)) - int(hi_ev.get("pitch", 60)))
                ic = min(diff % 12, 12 - (diff % 12))
                if ic in {1, 2, 6}:
                    bar0 = int(beat // beats_per_bar)
                    score = (1.0 if ic == 1 else 0.65 if ic == 6 else 0.42)
                    score *= math.sqrt(float(low_ev.get("velocity", 64)) * float(hi_ev.get("velocity", 64))) / 96.0
                    bass_collision_rows.append(
                        {
                            "bar": bar0 + 1,
                            "beat": _round3(beat - bar0 * beats_per_bar + 1.0),
                            "score": _round3(score),
                            "low_note": low_ev.get("note"),
                            "high_note": hi_ev.get("note"),
                            "low_layer": low_ev.get("layer"),
                            "high_layer": hi_ev.get("layer"),
                            "interval_class": ic,
                        }
                    )

    bar_rows: list[dict[str, Any]] = []
    for bar0, count in sorted(bar_density_counter.items()):
        bar_rows.append(
            {
                "bar": bar0 + 1,
                "note_count": int(count),
                "weighted_note_beats": _round3(float(bar_velocity_weight[bar0])),
            }
        )
    bar_rows.sort(key=lambda row: float(row["weighted_note_beats"]), reverse=True)
    bass_collision_rows.sort(key=lambda row: float(row["score"]), reverse=True)
    harmonic_outliers.sort(key=lambda row: float(row["severity"]), reverse=True)
    high_register_rows.sort(key=lambda row: float(row["severity"]), reverse=True)
    low_density_rows = low_density_rows[:max_rows]

    if bass_collision_rows and float(bass_collision_rows[0]["score"]) > 0.45:
        top = bass_collision_rows[0]
        warnings.append(
            f"bass/melody collision candidate at bar {top['bar']} beat {top['beat']}: {top['low_note']} vs {top['high_note']}"
        )
    if low_density_rows:
        top = low_density_rows[0]
        warnings.append(f"low-register density reaches {top['low_note_count']} simultaneous notes near bar {top['bar']} beat {top['beat']}")
    if harmonic_outliers and float(harmonic_outliers[0]["severity"]) > 2.5:
        top = harmonic_outliers[0]
        warnings.append(
            f"long/high non-chord tone candidate at bar {top['bar']} beat {top['beat']}: {top['note']} in layer {top['layer']}"
        )
    if high_register_rows and float(high_register_rows[0]["severity"]) > 1.5:
        top = high_register_rows[0]
        warnings.append(
            f"piercing high-register candidate at bar {top['bar']} beat {top['beat']}: {top['note']} in layer {top['layer']} group {top['group']}"
        )

    return {
        "schema": "ambition.music_arrangement_audit.v1",
        "id": spec.get("id"),
        "title": spec.get("title"),
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "note_count": len(events),
        "default_state_weights": default_weights,
        "groups": group_rows,
        "bar_density": bar_rows[:max_rows],
        "low_register_density": low_density_rows,
        "bass_collision_candidates": bass_collision_rows[:max_rows],
        "harmonic_outliers": harmonic_outliers[:max_rows],
        "high_register_candidates": high_register_rows[:max_rows],
        "warnings": warnings,
    }


@profile
def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf8")
        return
    columns = list(rows[0].keys())
    lines = ["\t".join(columns)]
    for row in rows:
        lines.append("\t".join(str(row.get(c, "")) for c in columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf8")


@profile
def write_reports(payload: dict[str, Any], reports_dir: Path) -> dict[str, str]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "arrangement_audit.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")
    _write_tsv(reports_dir / "arrangement_group_presence.tsv", payload.get("groups", []))
    _write_tsv(reports_dir / "arrangement_bass_collisions.tsv", payload.get("bass_collision_candidates", []))
    _write_tsv(reports_dir / "arrangement_harmonic_outliers.tsv", payload.get("harmonic_outliers", []))
    _write_tsv(reports_dir / "arrangement_high_register_candidates.tsv", payload.get("high_register_candidates", []))

    summary_path = reports_dir / "arrangement_audit_summary.txt"
    lines: list[str] = [
        f"cue: {payload.get('id')}",
        f"note_count: {payload.get('note_count')}",
        "",
    ]
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("warnings:")
        lines.extend(f"  - {w}" for w in warnings)
        lines.append("")
    lines.append("default-state group presence:")
    for row in payload.get("groups", []):
        lines.append(
            f"  {row['group']}: weighted {float(row['default_weighted_share']):.1%}, "
            f"raw {float(row['raw_share']):.1%}, state {row['default_state_weight']}, "
            f"range {row['pitch_min']}-{row['pitch_max']}"
        )
    lines.append("")
    lines.append("top bass collision candidates:")
    for row in payload.get("bass_collision_candidates", [])[:10]:
        lines.append(
            f"  bar {row['bar']} beat {row['beat']} score {row['score']}: "
            f"{row['low_note']}({row['low_layer']}) + {row['high_note']}({row['high_layer']})"
        )
    lines.append("")
    lines.append("top harmonic outliers:")
    for row in payload.get("harmonic_outliers", [])[:10]:
        lines.append(
            f"  bar {row['bar']} beat {row['beat']} severity {row['severity']}: "
            f"{row['note']} layer {row['layer']} group {row['group']} dur {row['duration_beats']}"
        )
    lines.append("")
    lines.append("top high-register candidates (C7+):")
    for row in payload.get("high_register_candidates", [])[:10]:
        lines.append(
            f"  {row['time_s']:>6.2f}s bar {row['bar']} beat {row['beat']} severity {row['severity']}: "
            f"{row['note']} layer {row['layer']} group {row['group']} instrument {row['instrument']}"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf8")

    md_path = reports_dir / "arrangement_audit.md"
    md: list[str] = [f"# Arrangement Audit — {payload.get('id')}", ""]
    if warnings:
        md.append("## Warnings")
        md.append("")
        md.extend(f"- {w}" for w in warnings)
        md.append("")
    md.extend(["## Default-state group presence", "", "| group | weighted share | raw share | state weight | pitch range |", "| --- | ---: | ---: | ---: | --- |"])
    for row in payload.get("groups", []):
        md.append(
            f"| {row['group']} | {float(row['default_weighted_share']):.1%} | {float(row['raw_share']):.1%} | "
            f"{row['default_state_weight']} | {row['pitch_min']}–{row['pitch_max']} |"
        )
    md.extend(["", "## Bass collision candidates", "", "| bar | beat | score | notes | layers |", "| ---: | ---: | ---: | --- | --- |"])
    for row in payload.get("bass_collision_candidates", [])[:20]:
        md.append(
            f"| {row['bar']} | {row['beat']} | {row['score']} | {row['low_note']} + {row['high_note']} | "
            f"{row['low_layer']} + {row['high_layer']} |"
        )
    md.extend(["", "## Harmonic outliers", "", "| bar | beat | severity | note | layer | duration |", "| ---: | ---: | ---: | --- | --- | ---: |"])
    for row in payload.get("harmonic_outliers", [])[:20]:
        md.append(
            f"| {row['bar']} | {row['beat']} | {row['severity']} | {row['note']} | {row['layer']} | {row['duration_beats']} |"
        )
    md.extend(["", "## High-register candidates", "", "| time | bar | beat | severity | note | group | layer | instrument |", "| ---: | ---: | ---: | ---: | --- | --- | --- | --- |"] )
    for row in payload.get("high_register_candidates", [])[:20]:
        md.append(
            f"| {row['time_s']} | {row['bar']} | {row['beat']} | {row['severity']} | {row['note']} | {row['group']} | {row['layer']} | {row['instrument']} |"
        )
    md_path.write_text("\n".join(md) + "\n", encoding="utf8")

    return {
        "json": str(json_path),
        "summary": str(summary_path),
        "markdown": str(md_path),
    }


@profile
def audit_file(path: Path, *, bucket_beats: float = 0.25, max_rows: int = 40) -> dict[str, Any]:
    from ..render.score_core import load_yaml

    return audit_spec(load_yaml(path), bucket_beats=bucket_beats, max_rows=max_rows)


class ArrangementAuditConfig(kwconf.Config):
    """Audit MusicIR arrangement density and event overlap."""


    score: Path = kwconf.Value(None, position=1, parser=Path)
    outdir: Path | None = kwconf.Value(None, parser=Path)
    bucket_beats: float = kwconf.Value(0.25)
    max_rows: int = kwconf.Value(40)
    json: bool = kwconf.Flag(False)

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return run(cls.cli(argv=argv, data=kwargs))


@profile
def run(args: ArrangementAuditConfig) -> int:
    payload = audit_file(args.score, bucket_beats=args.bucket_beats, max_rows=args.max_rows)
    outdir = args.outdir or (args.score.parent / "reports")
    paths = write_reports(payload, outdir)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(paths["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(ArrangementAuditConfig.main())
