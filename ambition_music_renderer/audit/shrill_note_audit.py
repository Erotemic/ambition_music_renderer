"""Score-level shrill-note audit for MusicIR cues.

This audit complements sour-note and spectrogram reports. It asks: which
individual rendered note events are high enough, loud enough, and isolated
enough to read as whistle / shrill standalone tones rather than ordinary
timbre?  It is intentionally conservative: it ignores drums and reports
candidates with source hints so authors can decide whether the high register is
intentional.
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

from .sour_note_audit import _events_for_spec, _section_for_bar, _section_starts, _source_hint

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

PRESENCE_HZ = 4000.0
PIERCING_HZ = 6000.0
WHISTLE_HZ = 8000.0
EXTREME_HZ = 10000.0


from ._common import round3 as _round3


@profile
def _is_unpitched_event(ev: dict[str, Any]) -> bool:
    group_name = str(ev.get("group") or ev.get("instrument") or "").lower()
    layer_name = str(ev.get("layer") or "").lower()
    layer_kind_name = str(ev.get("layer_kind") or "").lower()
    instrument_name = str(ev.get("instrument") or "").lower()
    return (
        layer_kind_name == "drums"
        or group_name in {"drums", "percussion"}
        or "drum" in group_name
        or "percussion" in group_name
        or "kit" in instrument_name
        or "drum" in layer_name
    )


@profile
def _severity_tier(freq_hz: float) -> str:
    if freq_hz >= EXTREME_HZ:
        return "extreme_10k_plus"
    if freq_hz >= WHISTLE_HZ:
        return "whistle_8k_plus"
    if freq_hz >= PIERCING_HZ:
        return "piercing_6k_plus"
    if freq_hz >= PRESENCE_HZ:
        return "presence_4k_plus"
    return "below_threshold"


@profile
def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


@profile
def _overlap_context(events: list[dict[str, Any]], ev: dict[str, Any]) -> dict[str, Any]:
    start = float(ev.get("start_beat", 0.0))
    end = float(ev.get("end_beat", start))
    if end <= start:
        end = start + 1e-6
    group = str(ev.get("group") or "")
    pitch = int(ev.get("pitch", 60))
    overlapping: list[int] = []
    lower_same_group: list[int] = []
    high_same_group: list[int] = []
    for other in events:
        if other is ev or _is_unpitched_event(other):
            continue
        if _overlap(start, end, float(other.get("start_beat", 0.0)), float(other.get("end_beat", 0.0))) <= 1e-4:
            continue
        op = int(other.get("pitch", 60))
        if str(other.get("group") or "") == group:
            overlapping.append(op)
            if op < pitch:
                lower_same_group.append(op)
            if op >= pitch - 7:
                high_same_group.append(op)
    nearest_lower_gap = None
    if lower_same_group:
        nearest_lower_gap = pitch - max(lower_same_group)
    return {
        "same_group_overlap_count": len(overlapping),
        "same_group_high_neighbor_count": len(high_same_group),
        "nearest_lower_gap_semitones": nearest_lower_gap,
    }


@profile
def _section_maps(spec: dict[str, Any]) -> tuple[dict[int, str], dict[int, int]]:
    section_by_bar: dict[int, str] = {}
    local_by_bar: dict[int, int] = {}
    cursor = 0
    for section in spec.get("sections", []) or []:
        bars = int(section.get("bars", 0) or 0)
        sid = str(section.get("id", ""))
        for local in range(bars):
            section_by_bar[cursor + local] = sid
            local_by_bar[cursor + local] = local
        cursor += bars
    return section_by_bar, local_by_bar


@profile
def audit_spec(
    spec: dict[str, Any],
    *,
    min_frequency_hz: float = PRESENCE_HZ,
    max_candidates: int = 120,
) -> dict[str, Any]:
    events, bpm, beats_per_bar = _events_for_spec(spec)
    section_starts = _section_starts(spec)
    section_by_bar, local_by_bar = _section_maps(spec)
    candidates: list[dict[str, Any]] = []
    layer_scores: Counter[str] = Counter()
    group_scores: Counter[str] = Counter()
    warnings: list[str] = []

    pitched_events = [ev for ev in events if not _is_unpitched_event(ev)]
    for ev in pitched_events:
        pitch = int(ev.get("pitch", 60))
        freq_hz = float(pretty_midi.note_number_to_hz(pitch))
        if freq_hz < min_frequency_hz:
            continue
        start_beat = float(ev.get("start_beat", 0.0))
        end_beat = float(ev.get("end_beat", start_beat))
        dur_beats = max(0.0, end_beat - start_beat)
        if dur_beats <= 0:
            continue
        velocity = int(ev.get("velocity", 64))
        ctx = _overlap_context(pitched_events, ev)
        tier = _severity_tier(freq_hz)
        tier_weight = {
            "presence_4k_plus": 1.0,
            "piercing_6k_plus": 1.6,
            "whistle_8k_plus": 2.4,
            "extreme_10k_plus": 3.2,
        }.get(tier, 0.0)
        duration_weight = math.sqrt(max(0.12, min(dur_beats, 2.5)))
        velocity_weight = (max(1.0, velocity) / 64.0) ** 0.65
        group = str(ev.get("group") or ev.get("instrument") or "?")
        layer = str(ev.get("layer") or "?")
        instrument = str(ev.get("instrument") or "?")
        # High notes that are the only high voice in a group, or that are far
        # above the nearest lower voice, are much more likely to read as
        # standalone whistles than normal distorted-guitar or cymbal timbre.
        high_neighbors = int(ctx["same_group_high_neighbor_count"])
        nearest_lower_gap = ctx["nearest_lower_gap_semitones"]
        if nearest_lower_gap is None:
            isolation_weight = 1.35
        elif nearest_lower_gap >= 24:
            isolation_weight = 1.25
        elif nearest_lower_gap >= 17:
            isolation_weight = 1.10
        else:
            isolation_weight = 0.82
        if high_neighbors > 1:
            isolation_weight *= 0.78
        # Distorted guitars can create real high harmonics, but a literal MIDI
        # note above C8 should still be reviewed. Pads/bells/mallets also get a
        # small boost because they sustain and pierce more readily.
        group_weight = 1.15 if group in {"guitars", "guitar_lead", "sparkle", "pads", "glimmer", "mallets"} else 1.0
        score = tier_weight * duration_weight * velocity_weight * isolation_weight * group_weight
        if score < 0.45:
            continue
        bar0 = int(start_beat // beats_per_bar)
        beat_in_bar = start_beat - bar0 * beats_per_bar
        source_hint, repeat_index, motif_index, motif_interval = _source_hint(spec, ev, section_starts, beats_per_bar)
        row = {
            "score": _round3(score),
            "severity": tier,
            "frequency_hz": _round3(freq_hz),
            "time_s": _round3(start_beat * 60.0 / bpm),
            "end_time_s": _round3(end_beat * 60.0 / bpm),
            "bar": bar0 + 1,
            "beat": _round3(beat_in_bar + 1.0),
            "section": ev.get("section") or section_by_bar.get(bar0),
            "local_bar": local_by_bar.get(bar0, _section_for_bar(spec, bar0)[1]) + 1,
            "note": ev.get("note") or pretty_midi.note_number_to_name(pitch),
            "pitch": pitch,
            "layer": layer,
            "layer_kind": ev.get("layer_kind"),
            "group": group,
            "instrument": instrument,
            "velocity": velocity,
            "duration_beats": _round3(dur_beats),
            "same_group_overlap_count": ctx["same_group_overlap_count"],
            "same_group_high_neighbor_count": ctx["same_group_high_neighbor_count"],
            "nearest_lower_gap_semitones": ctx["nearest_lower_gap_semitones"],
            "source_hint": source_hint,
            "repeat_index": repeat_index,
            "motif_index": motif_index,
            "motif_interval": motif_interval,
        }
        candidates.append(row)
        layer_scores[layer] += float(score)
        group_scores[group] += float(score)

    candidates.sort(key=lambda row: (float(row["score"]), float(row["frequency_hz"])), reverse=True)
    if any(str(row.get("severity")) in {"whistle_8k_plus", "extreme_10k_plus"} for row in candidates[:8]):
        warnings.append("one or more top candidates are in the 8 kHz+ whistle range")
    if any(str(row.get("group")) == "guitars" for row in candidates[:16]):
        warnings.append("guitar-group high-register candidates found; inspect whether they are notes or distortion/timbre")

    def counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
        return [{"name": k, "score": _round3(v)} for k, v in counter.most_common(16)]

    return {
        "schema": "ambition.music_shrill_note_audit.v1",
        "id": spec.get("id"),
        "title": spec.get("title"),
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "min_frequency_hz": min_frequency_hz,
        "thresholds_hz": {
            "presence": PRESENCE_HZ,
            "piercing": PIERCING_HZ,
            "whistle": WHISTLE_HZ,
            "extreme": EXTREME_HZ,
        },
        "note_count": len(events),
        "pitched_note_count": len(pitched_events),
        "candidate_count": len(candidates),
        "candidates": candidates[:max_candidates],
        "top_layers": counter_rows(layer_scores),
        "top_groups": counter_rows(group_scores),
        "warnings": warnings,
    }


@profile
def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "score",
        "severity",
        "frequency_hz",
        "time_s",
        "end_time_s",
        "bar",
        "beat",
        "section",
        "local_bar",
        "note",
        "pitch",
        "layer",
        "group",
        "instrument",
        "duration_beats",
        "velocity",
        "same_group_overlap_count",
        "same_group_high_neighbor_count",
        "nearest_lower_gap_semitones",
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
    if not _ensure_matplotlib():
        return False
    candidates = payload.get("candidates", [])
    if not candidates:
        return False
    fig, ax = plt.subplots(figsize=(11, 4.2))
    xs = [float(row["time_s"]) for row in candidates]
    ys = [float(row["frequency_hz"]) for row in candidates]
    sizes = [max(16.0, float(row["score"]) * 24.0) for row in candidates]
    ax.scatter(xs, ys, s=sizes, alpha=0.75)
    ax.axhline(PRESENCE_HZ, linestyle="--", linewidth=0.8, label="4 kHz review")
    ax.axhline(WHISTLE_HZ, linestyle=":", linewidth=0.9, label="8 kHz whistle")
    ax.set_yscale("log")
    ax.set_ylim(max(2500.0, min(ys) * 0.8), max(14000.0, max(ys) * 1.15))
    ax.set_title(f"Shrill-note candidates — {payload.get('id')}")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("frequency (Hz)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    for row in candidates[:10]:
        ax.annotate(
            f"b{row['bar']} {row['note']}",
            (float(row["time_s"]), float(row["frequency_hz"])),
            xytext=(0, 6),
            textcoords="offset points",
            fontsize=7,
        )
    _save_figure(fig, path, plot_format=plot_format, jpeg_quality=jpeg_quality)
    return True


@profile
def _write_layer_plot(payload: dict[str, Any], path: Path, *, plot_format: str, jpeg_quality: int) -> bool:
    if not _ensure_matplotlib():
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
    ax.set_xlabel("total shrill-note score")
    ax.set_title(f"Shrill-note score by layer — {payload.get('id')}")
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
    json_path = reports_dir / "shrill_note_candidates.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")
    paths["json"] = str(json_path)

    tsv_path = reports_dir / "shrill_note_candidates.tsv"
    _write_tsv(tsv_path, payload.get("candidates", []))
    paths["tsv"] = str(tsv_path)

    summary_path = reports_dir / "shrill_note_candidates_summary.txt"
    lines: list[str] = [
        f"cue: {payload.get('id')}",
        f"min_frequency_hz: {payload.get('min_frequency_hz')}",
        f"note_count: {payload.get('note_count')}",
        f"pitched_note_count: {payload.get('pitched_note_count')}",
        f"candidate_count: {payload.get('candidate_count')}",
        "",
        "thresholds:",
    ]
    for key, val in (payload.get("thresholds_hz") or {}).items():
        lines.append(f"  {key}: {val} Hz")
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("warnings:")
        lines.extend(f"  - {w}" for w in warnings)
    lines.append("")
    lines.append("top shrill-note candidates:")
    for row in payload.get("candidates", [])[:20]:
        lines.append(
            f"  {row['time_s']:>6.2f}-{row['end_time_s']:>6.2f}s "
            f"bar {row['bar']} beat {row['beat']} score {row['score']}: "
            f"{row['note']} ({row['frequency_hz']} Hz, {row['severity']}) "
            f"in {row['layer']} / {row['group']}; {row['source_hint']}"
        )
    lines.append("")
    lines.append("top layers:")
    for row in payload.get("top_layers", [])[:12]:
        lines.append(f"  {row['name']}: {row['score']}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf8")
    paths["summary"] = str(summary_path)

    md_path = reports_dir / "shrill_note_candidates.md"
    md: list[str] = [f"# Shrill-note Candidates — {payload.get('id')}", ""]
    if warnings:
        md.append("## Warnings")
        md.append("")
        md.extend(f"- {w}" for w in warnings)
        md.append("")
    md.extend(
        [
            "## Top Candidates",
            "",
            "| rank | score | severity | freq | time | bar | beat | note | layer | group | source hint |",
            "| ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for rank, row in enumerate(payload.get("candidates", [])[:32], start=1):
        md.append(
            f"| {rank} | {row['score']} | {row['severity']} | {row['frequency_hz']} | "
            f"{row['time_s']}–{row['end_time_s']} | {row['bar']} | {row['beat']} | "
            f"{row['note']} | {row['layer']} | {row['group']} | `{row['source_hint']}` |"
        )
    md.append("")
    md_path.write_text("\n".join(md), encoding="utf8")
    paths["markdown"] = str(md_path)

    if plots_dir is not None:
        plots_dir.mkdir(parents=True, exist_ok=True)
        suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
        timeline = plots_dir / f"shrill_note_timeline.{suffix}"
        if _write_timeline_plot(payload, timeline, plot_format=plot_format, jpeg_quality=jpeg_quality):
            paths["timeline_plot"] = str(timeline)
        layers = plots_dir / f"shrill_note_layers.{suffix}"
        if _write_layer_plot(payload, layers, plot_format=plot_format, jpeg_quality=jpeg_quality):
            paths["layer_plot"] = str(layers)
    return paths


@profile
def audit_file(path: Path, *, min_frequency_hz: float = PRESENCE_HZ, max_candidates: int = 120) -> dict[str, Any]:
    from ..render.score_core import load_yaml

    return audit_spec(load_yaml(path), min_frequency_hz=min_frequency_hz, max_candidates=max_candidates)


class ShrillNoteAuditConfig(kwconf.Config):
    """Audit notes that may be shrill or whistle-like."""


    score: Path = kwconf.Value(None, position=1, parser=Path)
    outdir: Path | None = kwconf.Value(None, parser=Path)
    plots: Path | None = kwconf.Value(None, parser=Path)
    min_frequency_hz: float = kwconf.Value(PRESENCE_HZ)
    max_candidates: int = kwconf.Value(120)
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"])
    json: bool = kwconf.Flag(False)

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return run(cls.cli(argv=argv, data=kwargs))


@profile
def run(args: ShrillNoteAuditConfig) -> int:
    payload = audit_file(
        args.score,
        min_frequency_hz=args.min_frequency_hz,
        max_candidates=args.max_candidates,
    )
    outdir = args.outdir or (args.score.parent / "reports")
    paths = write_reports(payload, outdir, plots_dir=args.plots, plot_format=args.plot_format)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(paths["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(ShrillNoteAuditConfig.main())
