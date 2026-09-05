"""Read-only semantic note timelines for rendered music variants.

The renderer already expands authored scores into exact note events before audio
synthesis.  This module turns that expansion into a small stable artifact that
human tools can visualize without parsing authoring YAML or reverse engineering
rendered audio.
"""

from __future__ import annotations

import dataclasses as dc
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import shutil
from typing import Any, Iterable, Mapping

import yaml


TIMELINE_SCHEMA = "ambition.music_note_timeline.v1"


@dc.dataclass(frozen=True)
class TimelineNote:
    group: str
    instrument: str
    section: str | None
    layer: str | None
    layer_kind: str | None
    pitch: int
    note: str
    velocity: int
    start_seconds: float
    end_seconds: float
    start_beat: float | None = None
    end_beat: float | None = None


@dc.dataclass(frozen=True)
class TimelineGridLine:
    time_seconds: float
    bar: int
    beat: int
    major: bool


@dc.dataclass(frozen=True)
class TimelineSection:
    id: str
    label: str
    start_seconds: float
    end_seconds: float


@dc.dataclass(frozen=True)
class MusicTimeline:
    cue_id: str
    title: str
    render_hash: str
    duration_seconds: float
    notes: tuple[TimelineNote, ...]
    grid: tuple[TimelineGridLine, ...]
    sections: tuple[TimelineSection, ...]

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(sorted({note.group for note in self.notes}))


@dc.dataclass(frozen=True)
class TimelineDocument:
    timeline: MusicTimeline
    provenance: str
    source_path: Path
    exact_for_render: bool

    @property
    def provenance_label(self) -> str:
        labels = {
            "render_timeline": "render timeline",
            "render_snapshot": "render score snapshot",
            "live_score": "live score fallback",
        }
        return labels.get(self.provenance, self.provenance.replace("_", " "))


@dc.dataclass(frozen=True)
class RenderAuthoringArtifacts:
    """Immutable semantic artifacts stored beside one audio render."""

    score_snapshot: Path
    note_timeline: Path
    source_score_sha256: str

    def manifest_files(self, run_dir: Path) -> dict[str, str]:
        root = Path(run_dir).resolve()
        return {
            "score_snapshot": str(self.score_snapshot.resolve().relative_to(root)),
            "note_timeline": str(self.note_timeline.resolve().relative_to(root)),
        }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timeline_note(row: Mapping[str, Any]) -> TimelineNote | None:
    if str(row.get("event_type", "note")) == "keyswitch":
        return None
    try:
        pitch = int(row["pitch"])
        start = float(row["start_time"])
        end = float(row["end_time"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= pitch <= 127) or not math.isfinite(start) or not math.isfinite(end):
        return None
    if end <= start:
        return None
    return TimelineNote(
        group=str(row.get("group") or row.get("instrument") or "unknown"),
        instrument=str(row.get("instrument") or "unknown"),
        section=str(row["section"]) if row.get("section") is not None else None,
        layer=str(row["layer"]) if row.get("layer") is not None else None,
        layer_kind=str(row["layer_kind"]) if row.get("layer_kind") is not None else None,
        pitch=pitch,
        note=str(row.get("note") or pitch),
        velocity=max(1, min(127, int(row.get("velocity", 80)))),
        start_seconds=max(0.0, start),
        end_seconds=max(0.0, end),
        start_beat=_optional_float(row.get("start_beat")),
        end_beat=_optional_float(row.get("end_beat")),
    )


def _section_rows(section_meta: Iterable[Mapping[str, Any]]) -> tuple[TimelineSection, ...]:
    rows: list[TimelineSection] = []
    for section in section_meta:
        start = _safe_float(section.get("start_seconds"))
        end = _safe_float(section.get("end_seconds"), start)
        rows.append(
            TimelineSection(
                id=str(section.get("id") or "section"),
                label=str(section.get("label") or section.get("id") or "section"),
                start_seconds=start,
                end_seconds=max(start, end),
            )
        )
    return tuple(rows)


def _v1_grid(spec: Mapping[str, Any], section_meta: Iterable[Mapping[str, Any]]) -> tuple[TimelineGridLine, ...]:
    from .render.score_core import TempoMap

    beats_per_bar = float((spec.get("meter") or {}).get("beats_per_bar", 4))
    if beats_per_bar <= 0:
        return ()
    sections = list(section_meta)
    if not sections:
        return ()
    total_beats = max(_safe_float(row.get("end_beat")) for row in sections)
    tempo = TempoMap.from_spec(dict(spec))
    count = max(0, int(math.ceil(total_beats - 1e-9)))
    rows: list[TimelineGridLine] = []
    for beat_index in range(count + 1):
        bar_zero = int(math.floor(beat_index / beats_per_bar))
        beat_zero = int(round(beat_index - bar_zero * beats_per_bar))
        rows.append(
            TimelineGridLine(
                time_seconds=float(tempo.beat_to_time(float(beat_index))),
                bar=bar_zero + 1,
                beat=beat_zero + 1,
                major=beat_zero == 0,
            )
        )
    return tuple(rows)


def _v2_grid(
    spec: Mapping[str, Any],
    pm: Any,
    *,
    exact_metadata: Mapping[str, Any] | None = None,
) -> tuple[TimelineGridLine, ...]:
    from .render.exact_score import ExactTempoMap, ScoreClock

    score = dict(spec.get("score") or {})
    clock = ScoreClock(score)
    tempo = ExactTempoMap(score, clock).bind_ppq(clock.ppq)
    exact_meta = dict(exact_metadata or getattr(pm, "_ambition_exact_score", {}) or {})
    end_tick = int(exact_meta.get("end_tick", 0))
    if end_tick <= 0:
        return ()
    last_position = clock.tick_to_position(max(0, end_tick - 1))
    last_bar = int(last_position.get("bar", 1))
    rows: list[TimelineGridLine] = []
    for bar in range(1, last_bar + 1):
        change = clock.meter_at_bar(bar)
        beat_ticks = clock.ppq * 4 / change.denominator
        bar_start = clock.bar_start_tick(bar)
        for beat_zero in range(change.numerator):
            tick = bar_start + int(round(beat_zero * beat_ticks))
            if tick > end_tick:
                break
            rows.append(
                TimelineGridLine(
                    time_seconds=float(tempo.tick_to_time(tick)),
                    bar=bar,
                    beat=beat_zero + 1,
                    major=beat_zero == 0,
                )
            )
    return tuple(rows)


def build_timeline(
    spec: Mapping[str, Any],
    pm: Any,
    section_meta: Iterable[Mapping[str, Any]],
    *,
    render_hash: str = "",
    note_events: Iterable[Mapping[str, Any]] | None = None,
    exact_metadata: Mapping[str, Any] | None = None,
) -> MusicTimeline:
    """Build a compact semantic timeline from expanded score semantics.

    ``note_events`` / ``exact_metadata`` are the canonical CompiledScore path.
    Private PrettyMIDI metadata remains a compatibility fallback for callers
    that have not migrated yet.
    """
    events = (
        tuple(note_events)
        if note_events is not None
        else (getattr(pm, "_ambition_note_events", ()) or ())
    )
    notes = tuple(
        note
        for row in events
        if isinstance(row, Mapping)
        if (note := _timeline_note(row)) is not None
    )
    sections = _section_rows(section_meta)
    duration = max(
        [section.end_seconds for section in sections]
        + [note.end_seconds for note in notes]
        + [0.0]
    )
    if spec.get("schema") == "ambition.musicir.v2":
        grid = _v2_grid(spec, pm, exact_metadata=exact_metadata)
    else:
        grid = _v1_grid(spec, section_meta)
    cue_id = str(spec.get("id") or "cue")
    return MusicTimeline(
        cue_id=cue_id,
        title=str(spec.get("title") or cue_id.replace("_", " ").title()),
        render_hash=str(render_hash),
        duration_seconds=float(duration),
        notes=notes,
        grid=grid,
        sections=sections,
    )


def timeline_to_dict(timeline: MusicTimeline) -> dict[str, Any]:
    return {
        "schema": TIMELINE_SCHEMA,
        "cue_id": timeline.cue_id,
        "title": timeline.title,
        "render_hash": timeline.render_hash,
        "duration_seconds": timeline.duration_seconds,
        "sections": [dc.asdict(row) for row in timeline.sections],
        "grid": [dc.asdict(row) for row in timeline.grid],
        "notes": [dc.asdict(row) for row in timeline.notes],
    }


def timeline_from_dict(data: Mapping[str, Any]) -> MusicTimeline:
    if data.get("schema") != TIMELINE_SCHEMA:
        raise ValueError(f"unsupported note timeline schema: {data.get('schema')!r}")
    return MusicTimeline(
        cue_id=str(data.get("cue_id") or "cue"),
        title=str(data.get("title") or data.get("cue_id") or "Cue"),
        render_hash=str(data.get("render_hash") or ""),
        duration_seconds=_safe_float(data.get("duration_seconds")),
        sections=tuple(TimelineSection(**row) for row in data.get("sections", []) or []),
        grid=tuple(TimelineGridLine(**row) for row in data.get("grid", []) or []),
        notes=tuple(TimelineNote(**row) for row in data.get("notes", []) or []),
    )


def write_timeline(timeline: MusicTimeline, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timeline_to_dict(timeline), indent=2), encoding="utf8")
    return path


def read_timeline(path: Path) -> MusicTimeline:
    data = json.loads(Path(path).read_text(encoding="utf8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"note timeline must contain a JSON object: {path}")
    return timeline_from_dict(data)


def compile_score_timeline(score_path: Path, *, render_hash: str = "") -> MusicTimeline:
    """Compile a score into note events without synthesizing audio."""
    from .musicir.compile import compile_score

    score_path = Path(score_path).resolve()
    spec = yaml.safe_load(score_path.read_text(encoding="utf8")) or {}
    if not isinstance(spec, Mapping):
        raise ValueError(f"score must contain a YAML mapping: {score_path}")
    compiled = compile_score(dict(spec))
    return build_timeline(
        compiled.normalized_spec,
        compiled.pm,
        compiled.sections,
        render_hash=render_hash,
        note_events=compiled.note_events,
        exact_metadata=compiled.exact_metadata,
    )


def score_text_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_render_authoring_artifacts(
    *,
    score_path: Path,
    spec: Mapping[str, Any],
    pm: Any,
    section_meta: Iterable[Mapping[str, Any]],
    render_hash: str,
    run_dir: Path,
    compiled: Any | None = None,
) -> RenderAuthoringArtifacts:
    """Persist immutable score provenance and exact expanded note data.

    These files describe a render. They are deliberately separate from any
    future editable working document.
    """
    run_dir = Path(run_dir).resolve()
    authoring_dir = run_dir / "authoring"
    authoring_dir.mkdir(parents=True, exist_ok=True)
    cue_id = str(spec.get("id") or "cue")
    snapshot = authoring_dir / f"{cue_id}_{render_hash}.source.music.yaml"
    shutil.copy2(Path(score_path), snapshot)
    timeline_path = authoring_dir / f"{cue_id}_{render_hash}.note_timeline.json"
    write_timeline(
        build_timeline(
            compiled.normalized_spec if compiled is not None else spec,
            pm,
            section_meta,
            render_hash=render_hash,
            note_events=(compiled.note_events if compiled is not None else None),
            exact_metadata=(compiled.exact_metadata if compiled is not None else None),
        ),
        timeline_path,
    )
    return RenderAuthoringArtifacts(
        score_snapshot=snapshot,
        note_timeline=timeline_path,
        source_score_sha256=score_text_sha256(snapshot),
    )


def _regen_score_path(run_dir: Path) -> Path | None:
    regen = Path(run_dir) / "regen.sh"
    if not regen.is_file():
        return None
    try:
        text = regen.read_text(encoding="utf8")
    except OSError:
        return None
    for line in text.splitlines():
        if not re.match(r"^spec=", line):
            continue
        raw = line.split("=", 1)[1].strip()
        try:
            tokens = shlex.split(raw)
        except ValueError:
            return None
        if len(tokens) == 1:
            path = Path(tokens[0]).expanduser()
            return path.resolve() if path.is_file() else None
    return None


def live_score_candidate(run_dir: Path, label: str) -> Path | None:
    """Best-effort source lookup for pre-timeline renders.

    This fallback is intentionally marked non-exact because the source file may
    have changed after the render.  New renders should use the immutable render
    snapshot/timeline recorded in the manifest instead.
    """
    run_dir = Path(run_dir).resolve()
    bank_score = run_dir.parent.parent / "scores" / f"{label}.music.yaml"
    if bank_score.is_file():
        return bank_score.resolve()
    return _regen_score_path(run_dir)


def version_timeline_status(version: Any) -> str:
    """Describe the strongest note-timeline evidence available for a version.

    Keep this provenance lookup outside the Qt layer so the GUI does not need
    to duplicate the live-score fallback contract.
    """
    timeline_path = getattr(version, "timeline_path", None)
    if timeline_path and Path(timeline_path).is_file():
        return "exact"

    snapshot = getattr(version, "score_snapshot_path", None)
    if snapshot and Path(snapshot).is_file():
        return "snapshot"

    run_dir = getattr(version, "run_dir", None)
    if run_dir is None:
        return "—"
    candidate = live_score_candidate(
        Path(run_dir), str(getattr(version, "label", ""))
    )
    return "live source" if candidate is not None else "—"


def load_version_timeline(version: Any) -> TimelineDocument | None:
    """Load the strongest available timeline evidence for a rendered version."""
    timeline_path = getattr(version, "timeline_path", None)
    if timeline_path and Path(timeline_path).is_file():
        timeline = read_timeline(Path(timeline_path))
        expected_hash = str(getattr(version, "render_hash", "") or "")
        exact = not expected_hash or timeline.render_hash == expected_hash
        return TimelineDocument(
            timeline=timeline,
            provenance="render_timeline",
            source_path=Path(timeline_path).resolve(),
            exact_for_render=exact,
        )

    snapshot = getattr(version, "score_snapshot_path", None)
    if snapshot and Path(snapshot).is_file():
        timeline = compile_score_timeline(
            Path(snapshot), render_hash=str(getattr(version, "render_hash", "") or "")
        )
        return TimelineDocument(
            timeline=timeline,
            provenance="render_snapshot",
            source_path=Path(snapshot).resolve(),
            exact_for_render=True,
        )

    candidate = live_score_candidate(
        Path(getattr(version, "run_dir")), str(getattr(version, "label", ""))
    )
    if candidate is None:
        return None
    timeline = compile_score_timeline(
        candidate, render_hash=str(getattr(version, "render_hash", "") or "")
    )
    return TimelineDocument(
        timeline=timeline,
        provenance="live_score",
        source_path=candidate,
        exact_for_render=False,
    )
