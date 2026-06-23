"""Score-level dissonance hotspot analysis for MusicIR cues.

The renderer can make two individually reasonable layers sound wrong when their
notes overlap in dense seconds, sevenths, tritones, or close register clusters.
This module analyzes the expanded MIDI note events rather than the final audio,
so it can attribute hotspots back to bars, layers, instruments, and stem groups.

In addition to machine-readable JSON/TSV, this module writes a compact markdown
summary and optional plots so a human can quickly find the bars that deserve a
listening pass.
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

# Optional plotting dependency, loaded on first use so importing this module
# stays cheap (matplotlib is the single heaviest import in the audit package).
plt = None
HAS_MATPLOTLIB: bool | None = None


def _ensure_matplotlib() -> bool:
    """Import matplotlib lazily; return whether plotting is available."""
    global plt, HAS_MATPLOTLIB
    if HAS_MATPLOTLIB is not None:
        return HAS_MATPLOTLIB
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as _plt

        plt = _plt
        HAS_MATPLOTLIB = True
    except Exception:  # pragma: no cover - plotting is best-effort.
        plt = None
        HAS_MATPLOTLIB = False
    return HAS_MATPLOTLIB

INTERVAL_CLASS_NAMES = {
    0: "unison/octave",
    1: "minor second/major seventh",
    2: "major second/minor seventh",
    3: "minor third/major sixth",
    4: "major third/minor sixth",
    5: "perfect fourth/fifth",
    6: "tritone",
}

# Values are intentionally heuristic. The goal is to surface places a human
# should listen to, not to declare all dissonance invalid.
INTERVAL_CLASS_SEVERITY = {
    0: 0.00,
    1: 1.00,
    2: 0.48,
    3: 0.08,
    4: 0.04,
    5: 0.035,
    6: 0.72,
}


@profile
def _round3(value: float) -> float:
    return round(float(value), 3)


@profile
def _section_for_bar(spec: dict[str, Any], bar: int) -> tuple[dict[str, Any] | None, int]:
    cursor = 0
    for section in spec.get("sections", []):
        bars = int(section.get("bars", 0))
        if cursor <= bar < cursor + bars:
            return section, bar - cursor
        cursor += bars
    return None, bar


@profile
def _chord_for_abs_bar(spec: dict[str, Any], bar: int) -> str:
    from ..render.score_theory import chord_for_bar

    section, local = _section_for_bar(spec, bar)
    if not section:
        return ""
    return chord_for_bar(section, local)


@profile
def _fallback_events(pm: pretty_midi.PrettyMIDI, groups: dict[str, str], bpm: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
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
                    "nominal_bar": None,
                    "nominal_beat": None,
                    "nominal_duration_beats": None,
                    "start_time": float(note.start),
                    "end_time": float(note.end),
                    "start_beat": float(note.start / 60.0 * bpm),
                    "end_beat": float(note.end / 60.0 * bpm),
                }
            )
    return events


@profile
def _chord_pitch_classes(chord: str) -> set[int]:
    from ..render.score_theory import chord_intervals, note_to_midi

    try:
        root, intervals, slash_bass = chord_intervals(chord)
        root_pc = note_to_midi(f"{root}4") % 12
        pcs = {(root_pc + int(i)) % 12 for i in intervals}
        if slash_bass:
            bass_root = slash_bass.strip().split()[0]
            import re
            match = re.match(r"^([A-G](?:#|b)?)", bass_root)
            if match:
                pcs.add(note_to_midi(f"{match.group(1)}4") % 12)
        return pcs
    except Exception:
        return set()


@profile
def _pair_score(a: dict[str, Any], b: dict[str, Any], chord: str | None = None) -> tuple[float, dict[str, Any] | None]:
    pa = int(a["pitch"])
    pb = int(b["pitch"])
    if pa == pb:
        # Same pitch doubled across two timbres is usually not a clash. Keep a
        # tiny density score only when it is a cross-layer/instrument doubling.
        if a.get("instrument") == b.get("instrument"):
            return 0.0, None
    diff = abs(pa - pb)
    ic = min(diff % 12, 12 - (diff % 12))
    base = INTERVAL_CLASS_SEVERITY.get(ic, 0.0)
    if base <= 0.0:
        return 0.0, None

    # Close physical register matters more than pitch-class dissonance separated
    # by several octaves. Minor seconds within an octave are especially exposed.
    register_weight = 1.0
    if diff <= 2:
        register_weight = 1.85
    elif diff <= 6:
        register_weight = 1.25
    elif diff >= 24:
        register_weight = 0.38
    elif diff >= 18:
        register_weight = 0.62

    vel_weight = math.sqrt(max(1, int(a.get("velocity", 64))) * max(1, int(b.get("velocity", 64)))) / 96.0
    cross_layer = a.get("layer") != b.get("layer")
    cross_weight = 1.15 if cross_layer else 0.82
    score = base * register_weight * vel_weight * cross_weight

    # Consonance-aware discount: a dense pad containing legitimate chord tones
    # should not dominate the hotspot report merely because sustained chord
    # tones form seconds/sevenths across octaves. Keep close-register seconds
    # and tritones visible, but discount broad chord-tone color.
    if chord:
        pcs = _chord_pitch_classes(chord)
        if pcs:
            a_in = (pa % 12) in pcs
            b_in = (pb % 12) in pcs
            if a_in and b_in:
                if diff >= 12:
                    score *= 0.28
                elif diff >= 7:
                    score *= 0.45
                else:
                    score *= 0.75
            elif a_in or b_in:
                if diff >= 12:
                    score *= 0.70
                else:
                    score *= 0.85

    detail = {
        "score": score,
        "interval_semitones": diff,
        "interval_class": ic,
        "interval_name": INTERVAL_CLASS_NAMES.get(ic, str(ic)),
        "notes": [a.get("note"), b.get("note")],
        "pitches": [pa, pb],
        "instruments": [a.get("instrument"), b.get("instrument")],
        "groups": [a.get("group"), b.get("group")],
        "layers": [a.get("layer"), b.get("layer")],
        "velocities": [a.get("velocity"), b.get("velocity")],
    }
    return score, detail


@profile
def _active_events(events: list[dict[str, Any]], center_beat: float) -> list[dict[str, Any]]:
    return [ev for ev in events if float(ev["start_beat"]) <= center_beat < float(ev["end_beat"])]


@profile
def audit_spec(spec: dict[str, Any], *, bucket_beats: float = 0.25, max_hotspots: int = 40) -> dict[str, Any]:
    """Return JSON-serializable dissonance hotspot diagnostics."""
    from ..render.score_layers import build_score

    pm, groups, section_meta = build_score(spec)
    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    events = list(getattr(pm, "_ambition_note_events", []) or _fallback_events(pm, groups, bpm))
    if not events:
        return {
            "schema": "ambition.music_dissonance_audit.v1",
            "id": spec.get("id"),
            "hotspots": [],
            "warnings": ["score generated no note events"],
        }

    end_beat = max(float(ev["end_beat"]) for ev in events)
    bucket_count = int(math.ceil(end_beat / bucket_beats))
    hotspots: list[dict[str, Any]] = []
    layer_pair_scores: Counter[tuple[str, str]] = Counter()
    group_pair_scores: Counter[tuple[str, str]] = Counter()
    interval_scores: Counter[str] = Counter()

    for idx in range(bucket_count):
        start_beat = idx * bucket_beats
        end = min(end_beat, start_beat + bucket_beats)
        center = (start_beat + end) * 0.5
        active = _active_events(events, center)
        if len(active) < 2:
            continue
        abs_bar0 = int(center // beats_per_bar)
        beat_in_bar = center - abs_bar0 * beats_per_bar
        section, local_bar0 = _section_for_bar(spec, abs_bar0)
        chord = _chord_for_abs_bar(spec, abs_bar0)
        pair_details: list[dict[str, Any]] = []
        total_score = 0.0
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                score, detail = _pair_score(active[i], active[j], chord)
                if not detail:
                    continue
                total_score += score
                pair_details.append(detail)
                la, lb = sorted(str(x or "?") for x in detail["layers"])
                ga, gb = sorted(str(x or "?") for x in detail["groups"])
                layer_pair_scores[(la, lb)] += score
                group_pair_scores[(ga, gb)] += score
                interval_scores[str(detail["interval_name"])] += score
        if total_score <= 0.0:
            continue
        pair_details.sort(key=lambda row: float(row["score"]), reverse=True)
        hotspot = {
            "start_beat": _round3(start_beat),
            "end_beat": _round3(end),
            "center_beat": _round3(center),
            "bar": abs_bar0 + 1,
            "beat": _round3(beat_in_bar + 1.0),
            "section": (section or {}).get("id"),
            "local_bar": local_bar0 + 1,
            "chord": chord,
            "active_note_count": len(active),
            "score": _round3(total_score),
            "worst_pairs": [{**d, "score": _round3(float(d["score"]))} for d in pair_details[:8]],
            "active_notes": [
                {
                    "note": ev.get("note"),
                    "pitch": ev.get("pitch"),
                    "instrument": ev.get("instrument"),
                    "group": ev.get("group"),
                    "layer": ev.get("layer"),
                    "velocity": ev.get("velocity"),
                }
                for ev in sorted(active, key=lambda row: (int(row["pitch"]), str(row.get("instrument"))))
            ],
        }
        hotspots.append(hotspot)

    hotspots.sort(key=lambda row: (float(row["score"]), int(row["active_note_count"])), reverse=True)
    warnings: list[str] = []
    if hotspots and float(hotspots[0]["score"]) > 10.0:
        warnings.append("very strong dissonance hotspot found; inspect top bars for unintended clashes")
    dense_count = sum(1 for h in hotspots[:20] if int(h["active_note_count"]) >= 8)
    if dense_count >= 5:
        warnings.append("many top hotspots have 8+ simultaneous notes; reduce overlapping foreground layers or widen voicings")

    def _counter_rows(counter: Counter[tuple[str, str]] | Counter[str], limit: int = 16) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key, value in counter.most_common(limit):
            if isinstance(key, tuple):
                rows.append({"a": key[0], "b": key[1], "score": _round3(float(value))})
            else:
                rows.append({"name": key, "score": _round3(float(value))})
        return rows

    return {
        "schema": "ambition.music_dissonance_audit.v1",
        "id": spec.get("id"),
        "title": spec.get("title"),
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "bucket_beats": bucket_beats,
        "note_count": len(events),
        "section_count": len(section_meta),
        "hotspot_count": len(hotspots),
        "hotspots": hotspots[:max_hotspots],
        "top_layer_pairs": _counter_rows(layer_pair_scores),
        "top_group_pairs": _counter_rows(group_pair_scores),
        "top_interval_types": _counter_rows(interval_scores),
        "warnings": warnings,
    }


@profile
def _write_markdown_summary(payload: dict[str, Any], path: Path) -> None:
    lines: list[str] = [
        f"# Dissonance Hotspots — {payload.get('id')}",
        "",
        f"- bucket beats: `{payload.get('bucket_beats')}`",
        f"- note count: `{payload.get('note_count')}`",
        f"- hotspot count: `{payload.get('hotspot_count')}`",
        "",
    ]
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(
        [
            "## Top Hotspots",
            "",
            "| rank | score | bar | beat | chord | notes | layers | interval |",
            "| --- | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for rank, hotspot in enumerate(payload.get("hotspots", [])[:20], start=1):
        worst = (hotspot.get("worst_pairs") or [{}])[0]
        notes = " + ".join(str(x) for x in worst.get("notes", []) or [])
        layers = " + ".join(str(x) for x in worst.get("layers", []) or [])
        lines.append(
            f"| {rank} | {hotspot.get('score')} | {hotspot.get('bar')} | {hotspot.get('beat')} | "
            f"{hotspot.get('chord', '')} | {notes} | {layers} | {worst.get('interval_name', '')} |"
        )
    lines.append("")

    def add_pair_table(title: str, rows: list[dict[str, Any]], columns: tuple[str, str, str]) -> None:
        a, b, score = columns
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"| {a} | {b} | score |")
        lines.append("| --- | --- | ---: |")
        for row in rows[:12]:
            lines.append(f"| {row.get(a, '')} | {row.get(b, '')} | {row.get(score, '')} |")
        lines.append("")

    add_pair_table("Top Layer Pairs", payload.get("top_layer_pairs", []), ("a", "b", "score"))
    add_pair_table("Top Group Pairs", payload.get("top_group_pairs", []), ("a", "b", "score"))

    lines.append("## Top Interval Types")
    lines.append("")
    lines.append("| interval | score |")
    lines.append("| --- | ---: |")
    for row in payload.get("top_interval_types", [])[:12]:
        lines.append(f"| {row.get('name', '')} | {row.get('score', '')} |")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf8")


@profile
def _save_figure(fig: Any, path: Path, *, plot_format: str, jpeg_quality: int = 90) -> None:
    fmt = plot_format.lower()
    save_kwargs: dict[str, Any] = {"dpi": 180, "bbox_inches": "tight"}
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt in {"jpeg", "jpg"}:
        save_kwargs["format"] = "jpeg"
        save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality)}
    else:
        save_kwargs["format"] = fmt
    fig.savefig(path, **save_kwargs)
    plt.close(fig)


@profile
def _write_timeline_plot(payload: dict[str, Any], path: Path, *, plot_format: str, jpeg_quality: int) -> bool:
    if not _ensure_matplotlib():
        return False
    hotspots = payload.get("hotspots", [])
    if not hotspots:
        return False
    beats_per_bar = float(payload.get("beats_per_bar", 4.0))
    xs = [(float(h["center_beat"]) / beats_per_bar) + 1.0 for h in hotspots]
    ys = [float(h["score"]) for h in hotspots]
    fig, ax = plt.subplots(figsize=(10.5, 3.2))
    ax.plot(xs, ys)
    ax.set_title(f"Dissonance timeline — {payload.get('id')}")
    ax.set_xlabel("bar position")
    ax.set_ylabel("hotspot score")
    ax.grid(True, alpha=0.35)
    top = sorted(hotspots[:8], key=lambda row: float(row["score"]), reverse=True)
    for item in top[:6]:
        x = (float(item["center_beat"]) / beats_per_bar) + 1.0
        y = float(item["score"])
        ax.annotate(f"b{item['bar']}", (x, y), xytext=(0, 6), textcoords="offset points", fontsize=7)
    _save_figure(fig, path, plot_format=plot_format, jpeg_quality=jpeg_quality)
    return True


@profile
def _write_layer_pair_heatmap(payload: dict[str, Any], path: Path, *, plot_format: str, jpeg_quality: int) -> bool:
    if not _ensure_matplotlib():
        return False
    rows = payload.get("top_layer_pairs", [])
    if not rows:
        return False
    layer_totals: Counter[str] = Counter()
    for row in rows:
        layer_totals[str(row.get("a", "?"))] += float(row.get("score", 0.0))
        layer_totals[str(row.get("b", "?"))] += float(row.get("score", 0.0))
    labels = [name for name, _ in layer_totals.most_common(8)]
    if not labels:
        return False
    idx = {name: i for i, name in enumerate(labels)}
    size = len(labels)
    matrix = [[0.0 for _ in range(size)] for _ in range(size)]
    for row in rows:
        a = str(row.get("a", "?"))
        b = str(row.get("b", "?"))
        if a not in idx or b not in idx:
            continue
        i = idx[a]
        j = idx[b]
        value = float(row.get("score", 0.0))
        matrix[i][j] += value
        if i != j:
            matrix[j][i] += value
    fig, ax = plt.subplots(figsize=(5.4 + size * 0.35, 4.8))
    image = ax.imshow(matrix)
    ax.set_title(f"Layer pair clash heatmap — {payload.get('id')}")
    ax.set_xticks(range(size), labels=labels, rotation=45, ha="right")
    ax.set_yticks(range(size), labels=labels)
    for i in range(size):
        for j in range(size):
            value = matrix[i][j]
            if value > 0.001:
                ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(image, ax=ax, shrink=0.85)
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
    json_path = reports_dir / "dissonance_hotspots.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    tsv_path = reports_dir / "dissonance_hotspots.tsv"
    columns = [
        "rank",
        "score",
        "bar",
        "beat",
        "section",
        "local_bar",
        "chord",
        "active_note_count",
        "worst_interval",
        "worst_layers",
        "worst_groups",
        "worst_notes",
    ]
    lines = ["\t".join(columns)]
    for rank, hotspot in enumerate(payload.get("hotspots", []), start=1):
        worst = (hotspot.get("worst_pairs") or [{}])[0]
        row = {
            "rank": rank,
            "score": hotspot.get("score", ""),
            "bar": hotspot.get("bar", ""),
            "beat": hotspot.get("beat", ""),
            "section": hotspot.get("section", ""),
            "local_bar": hotspot.get("local_bar", ""),
            "chord": hotspot.get("chord", ""),
            "active_note_count": hotspot.get("active_note_count", ""),
            "worst_interval": worst.get("interval_name", ""),
            "worst_layers": " + ".join(str(x) for x in worst.get("layers", []) or []),
            "worst_groups": " + ".join(str(x) for x in worst.get("groups", []) or []),
            "worst_notes": " + ".join(str(x) for x in worst.get("notes", []) or []),
        }
        lines.append("\t".join(str(row.get(c, "")) for c in columns))
    tsv_path.write_text("\n".join(lines) + "\n", encoding="utf8")

    summary_path = reports_dir / "dissonance_hotspots_summary.txt"
    text: list[str] = [
        f"cue: {payload.get('id')}",
        f"bucket_beats: {payload.get('bucket_beats')}",
        f"note_count: {payload.get('note_count')}",
        f"hotspot_count: {payload.get('hotspot_count')}",
        "",
    ]
    warnings = list(payload.get("warnings") or [])
    if warnings:
        text.append("warnings:")
        text.extend(f"  - {w}" for w in warnings)
        text.append("")
    text.append("top hotspots:")
    for h in payload.get("hotspots", [])[:12]:
        worst = (h.get("worst_pairs") or [{}])[0]
        text.append(
            f"  bar {h.get('bar')} beat {h.get('beat')} score {h.get('score')} "
            f"notes {h.get('active_note_count')} chord {h.get('chord')} :: "
            f"{worst.get('interval_name', 'n/a')} "
            f"{'+'.join(str(x) for x in worst.get('notes', []) or [])} "
            f"layers {'+'.join(str(x) for x in worst.get('layers', []) or [])}"
        )
    text.append("")
    text.append("top layer pairs:")
    for row in payload.get("top_layer_pairs", [])[:10]:
        text.append(f"  {row.get('a')} + {row.get('b')}: {row.get('score')}")
    text.append("")
    text.append("top group pairs:")
    for row in payload.get("top_group_pairs", [])[:10]:
        text.append(f"  {row.get('a')} + {row.get('b')}: {row.get('score')}")
    text.append("")
    text.append("top interval types:")
    for row in payload.get("top_interval_types", [])[:10]:
        text.append(f"  {row.get('name')}: {row.get('score')}")
    summary_path.write_text("\n".join(text) + "\n", encoding="utf8")

    md_path = reports_dir / "dissonance_hotspots.md"
    _write_markdown_summary(payload, md_path)

    paths = {
        "json": str(json_path),
        "tsv": str(tsv_path),
        "summary": str(summary_path),
        "markdown": str(md_path),
    }

    if plots_dir is not None:
        plots_dir.mkdir(parents=True, exist_ok=True)
        ext = plot_format.lower()
        timeline_path = plots_dir / f"dissonance_timeline.{ext}"
        heatmap_path = plots_dir / f"dissonance_layer_pairs.{ext}"
        timeline_ok = _write_timeline_plot(payload, timeline_path, plot_format=plot_format, jpeg_quality=jpeg_quality)
        heatmap_ok = _write_layer_pair_heatmap(payload, heatmap_path, plot_format=plot_format, jpeg_quality=jpeg_quality)
        if timeline_ok:
            paths["timeline_plot"] = str(timeline_path)
        if heatmap_ok:
            paths["layer_pair_plot"] = str(heatmap_path)
        if plots_dir is not None and not _ensure_matplotlib():
            warnings = list(payload.get("warnings") or [])
            note = "matplotlib unavailable; skipped dissonance plot generation"
            if note not in warnings:
                warnings.append(note)
                payload["warnings"] = warnings
                json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")
                _write_markdown_summary(payload, md_path)
                summary_path.write_text("\n".join(text + ["", f"note: {note}"]) + "\n", encoding="utf8")

    return paths


@profile
def audit_file(path: Path, *, bucket_beats: float = 0.25, max_hotspots: int = 40) -> dict[str, Any]:
    from ..render.score_core import load_yaml

    spec = load_yaml(path)
    return audit_spec(spec, bucket_beats=bucket_beats, max_hotspots=max_hotspots)


class DissonanceAuditConfig(kwconf.Config):
    """Audit MusicIR harmonic dissonance hotspots."""


    score: Path = kwconf.Value(None, position=1, parser=Path, help="MusicIR YAML score to analyze")
    outdir: Path | None = kwconf.Value(None, parser=Path, help="directory for reports; defaults next to score")
    bucket_beats: float = kwconf.Value(0.25, help="analysis bucket size in beats")
    max_hotspots: int = kwconf.Value(40)
    json: bool = kwconf.Flag(False, help="also print JSON payload to stdout")
    plots: Path | None = kwconf.Value(None, parser=Path, help="optional directory for plot images")
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"], help="format for generated plots")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return run(cls.cli(argv=argv, data=kwargs))


@profile
def run(args: DissonanceAuditConfig) -> int:
    payload = audit_file(args.score, bucket_beats=args.bucket_beats, max_hotspots=args.max_hotspots)
    outdir = args.outdir or (args.score.parent / "reports")
    paths = write_reports(payload, outdir, plots_dir=args.plots, plot_format=args.plot_format)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(paths["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(DissonanceAuditConfig.main())
