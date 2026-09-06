"""Normalized authoring graph for MusicIR v3.

MusicIR v1 and v2 are source frontends with different abstraction levels.  V3
introduces a representation that can hold both exact material and procedural
clips in the same score.  The graph intentionally remains *authoring semantic*:
it preserves stable source identities and generator intent before expansion to
:class:`~ambition_music_renderer.musicir.model.CompiledScore`.
"""

from __future__ import annotations

import copy
import dataclasses as dc
import hashlib
import json
from collections import Counter
from fractions import Fraction
from typing import Any, Iterable, Mapping


AUTHORING_GRAPH_SCHEMA = "ambition.musicir.authoring_graph.v1"


@dc.dataclass(frozen=True)
class SourceRef:
    """Stable source coordinates carried from v3 authoring into compiled events."""

    score_id: str
    part_id: str
    voice_id: str
    clip_id: str
    material_id: str | None = None
    material_chain: tuple[str, ...] | None = None
    generator_kind: str | None = None
    repeat_index: int = 0
    event_index: int = 0
    source_event_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in dc.asdict(self).items()
            if value is not None
        }

    def event_id(self, *, pitch_index: int = 0) -> str:
        """Return a deterministic event identity suitable for DAW sidecars."""

        parts = [
            self.score_id,
            self.part_id,
            self.voice_id,
            self.clip_id,
            f"r{self.repeat_index:03d}",
            self.source_event_id or f"e{self.event_index:04d}",
            f"p{pitch_index:02d}",
        ]
        return "/".join(_id_piece(part) for part in parts)


def _id_piece(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("MusicIR v3 source ids must not be empty")
    return text.replace("/", "_")


def _copy_rows(value: Any, *, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"MusicIR v3 {field} must be a list")
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise TypeError(f"MusicIR v3 {field}[{idx}] must be a mapping")
        out.append(copy.deepcopy(dict(row)))
    return out


def _require_unique_ids(rows: Iterable[Mapping[str, Any]], *, field: str) -> None:
    ids = [str(row.get("id", "")).strip() for row in rows]
    if any(not item for item in ids):
        raise ValueError(f"every MusicIR v3 {field} entry needs a stable `id`")
    dupes = sorted(key for key, count in Counter(ids).items() if count > 1)
    if dupes:
        raise ValueError(f"duplicate MusicIR v3 {field} ids: {dupes}")


def _normalize_meter(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return [{"bar": 1, "signature": "4/4"}]
    if isinstance(value, str):
        return [{"bar": 1, "signature": value}]
    if isinstance(value, Mapping):
        row = copy.deepcopy(dict(value))
        if "beats_per_bar" in row:
            beats = int(row["beats_per_bar"])
            beat_unit = int(row.get("beat_unit", 4))
            return [{"bar": 1, "signature": f"{beats}/{beat_unit}"}]
        if "map" in row:
            return _copy_rows(row.get("map"), field="meter.map")
        row.setdefault("bar", 1)
        return [row]
    return _copy_rows(value, field="meter")


def _normalize_tempo(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return [{"tick": 0, "bpm": 120.0}]
    if isinstance(value, (int, float)):
        return [{"tick": 0, "bpm": float(value)}]
    if isinstance(value, Mapping):
        row = copy.deepcopy(dict(value))
        if "events" in row:
            events = _copy_rows(row.get("events"), field="tempo.events")
            initial = row.get("initial", row.get("bpm"))
            if initial is not None:
                events.insert(0, {"tick": 0, "bpm": float(initial)})
            return events
        row.setdefault("tick", 0)
        return [row]
    return _copy_rows(value, field="tempo")


def _normalize_materials(value: Any) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    rows: list[dict[str, Any]]
    if isinstance(value, Mapping):
        rows = []
        for material_id, raw in value.items():
            if not isinstance(raw, Mapping):
                raise TypeError(f"MusicIR v3 material {material_id!r} must be a mapping")
            row = copy.deepcopy(dict(raw))
            row.setdefault("id", str(material_id))
            rows.append(row)
    else:
        rows = _copy_rows(value, field="materials")
    _require_unique_ids(rows, field="materials")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        material_id = str(row["id"])
        if "kind" not in row:
            row["kind"] = "events" if "events" in row else "motif"
        kind = str(row["kind"])
        if kind not in {"events", "motif", "sequence"}:
            raise ValueError(
                f"MusicIR v3 material {material_id!r} has unsupported kind {kind!r}; "
                "expected 'events', 'motif', or 'sequence'"
            )
        if kind == "events" and not isinstance(row.get("events", []), list):
            raise TypeError(f"MusicIR v3 event material {material_id!r} needs an events list")
        if kind == "sequence":
            items = row.get("items", [])
            if not isinstance(items, list):
                raise TypeError(f"MusicIR v3 sequence material {material_id!r} needs an items list")
            for item_index, item in enumerate(items):
                if not isinstance(item, Mapping) or not item.get("use"):
                    raise TypeError(
                        f"MusicIR v3 sequence material {material_id!r} items[{item_index}] "
                        "needs a mapping with `use`"
                    )
        out[material_id] = row
    return out


def _normalize_key(value: Any) -> dict[str, Any] | None:
    """Normalize optional score-level tonal context for v3 pitch semantics."""

    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        parts = text.replace("-", " ").split()
        tonic = parts[0]
        mode = parts[1] if len(parts) > 1 else "major"
        return {"tonic": tonic, "mode": mode.lower().replace("-", "_")}
    if not isinstance(value, Mapping):
        raise TypeError("MusicIR v3 key must be a string or mapping")
    row = copy.deepcopy(dict(value))
    tonic = row.get("tonic", row.get("root"))
    if tonic is None:
        raise ValueError("MusicIR v3 key mapping needs `tonic`")
    return {
        "tonic": str(tonic),
        "mode": str(row.get("mode", "major")).lower().replace("-", "_"),
    }


def normalize_v3_harmony(value: Any) -> dict[str, Any]:
    if value is None:
        return {"events": []}
    if isinstance(value, list):
        return {"start_bar": 1, "every_bars": 1, "progression": copy.deepcopy(value)}
    if not isinstance(value, Mapping):
        raise TypeError("MusicIR v3 harmony must be a progression list or mapping")
    row = copy.deepcopy(dict(value))
    if "progression" not in row and "events" not in row:
        raise ValueError("MusicIR v3 harmony needs `progression` or `events`")
    return row


def _normalize_clip(clip: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    row = copy.deepcopy(dict(clip))
    clip_id = str(row.get("id", "")).strip()
    if not clip_id:
        raise ValueError(
            f"MusicIR v3 {path} needs a stable `id`; clip ids are the future DAW/source mapping key"
        )
    row["id"] = clip_id
    source_fields = [key for key in ("events", "use", "generate") if key in row]
    if len(source_fields) != 1:
        raise ValueError(
            f"MusicIR v3 clip {clip_id!r} must define exactly one of events/use/generate; "
            f"found {source_fields}"
        )
    if "generate" in row and not isinstance(row["generate"], Mapping):
        raise TypeError(f"MusicIR v3 clip {clip_id!r} generate must be a mapping")
    if "events" in row and not isinstance(row["events"], list):
        raise TypeError(f"MusicIR v3 clip {clip_id!r} events must be a list")
    return row


def chord_for_bar_from_harmony(harmony: Mapping[str, Any], bar: int) -> str:
    """Resolve a one-based bar from normalized v3 harmony configuration.

    This is shared by the authoring graph and compatibility audit helpers so
    v3 harmony has one interpretation even where an older audit still works in
    bar coordinates.
    """

    bar = int(bar)
    cfg = harmony
    progression = cfg.get("progression")
    if progression:
        start_bar = int(cfg.get("start_bar", 1))
        every = max(1, int(cfg.get("every_bars", 1)))
        idx = (bar - start_bar) // every
        if idx >= 0:
            vals = list(progression)
            if bool(cfg.get("cycle", False)) and vals:
                return str(vals[idx % len(vals)])
            if idx < len(vals):
                return str(vals[idx])
    best: tuple[int, str] | None = None
    for event in cfg.get("events", []) or []:
        if isinstance(event, Mapping):
            raw_at = event.get("at")
            if isinstance(raw_at, Mapping):
                event_bar = int(raw_at.get("bar", event.get("bar", 1)))
            else:
                event_bar = int(event.get("bar", raw_at if raw_at is not None else 1))
            chord = str(event.get("chord", event.get("harmony", "")))
        elif isinstance(event, (list, tuple)) and len(event) >= 2:
            event_bar = int(event[0])
            chord = str(event[1])
        else:
            raise ValueError(f"invalid MusicIR v3 harmony event {event!r}")
        if event_bar <= bar and chord and (best is None or event_bar >= best[0]):
            best = (event_bar, chord)
    if best is None:
        raise KeyError(f"MusicIR v3 has no harmony defined for bar {bar}")
    return best[1]


def form_region_for_bar(form: Sequence[Mapping[str, Any]], bar: int) -> tuple[dict[str, Any] | None, int]:
    """Map a one-based v3 score bar to ``(form region, zero-based local bar)``."""

    bar = int(bar)
    for row in form:
        raw_from = row.get("from")
        if isinstance(raw_from, Mapping):
            start_bar = int(raw_from.get("bar", 1))
        else:
            start_bar = int(row.get("start_bar", 1))
        raw_to = row.get("to")
        if isinstance(raw_to, Mapping):
            end_bar = int(raw_to.get("bar", start_bar))
        elif row.get("bars") is not None:
            end_bar = start_bar + int(row["bars"])
        else:
            continue
        if start_bar <= bar < end_bar:
            return copy.deepcopy(dict(row)), bar - start_bar
    return None, max(0, bar - 1)


@dc.dataclass
class NormalizedScoreGraph:
    """Canonical authoring graph for one MusicIR v3 source file."""

    score_id: str
    seed: int
    ppq: int
    meter: list[dict[str, Any]]
    tempo: list[dict[str, Any]]
    form: list[dict[str, Any]]
    end: Any
    instruments: list[dict[str, Any]]
    harmony: dict[str, Any]
    key_context: dict[str, Any] | None
    materials: dict[str, dict[str, Any]]
    parts: list[dict[str, Any]]
    source_spec: dict[str, Any]

    def timing_score(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "timebase": {"ppq": self.ppq},
            "meter": copy.deepcopy(self.meter),
            "tempo": copy.deepcopy(self.tempo),
            "form": copy.deepcopy(self.form),
        }
        if self.end is not None:
            out["end"] = copy.deepcopy(self.end)
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": AUTHORING_GRAPH_SCHEMA,
            "score_id": self.score_id,
            "seed": self.seed,
            "ppq": self.ppq,
            "meter": copy.deepcopy(self.meter),
            "tempo": copy.deepcopy(self.tempo),
            "form": copy.deepcopy(self.form),
            "end": copy.deepcopy(self.end),
            "instruments": copy.deepcopy(self.instruments),
            "harmony": copy.deepcopy(self.harmony),
            "key": copy.deepcopy(self.key_context),
            "materials": copy.deepcopy(self.materials),
            "parts": copy.deepcopy(self.parts),
        }

    def form_region_at_tick(self, clock: Any, tick: int) -> dict[str, Any] | None:
        """Return the authored form region containing ``tick`` when available."""

        for row in self.form:
            if row.get("start_tick") is not None:
                start = int(row["start_tick"])
            elif row.get("from") is not None:
                start = int(clock.position_to_tick(row["from"]))
            else:
                continue
            if row.get("end_tick") is not None:
                end = int(row["end_tick"])
            elif row.get("to") is not None:
                end = int(clock.position_to_tick(row["to"]))
            elif row.get("bars") is not None and isinstance(row.get("from"), Mapping):
                pos = copy.deepcopy(dict(row["from"]))
                pos["bar"] = int(pos.get("bar", 1)) + int(row["bars"])
                end = int(clock.position_to_tick(pos))
            else:
                continue
            if start <= int(tick) < end:
                return copy.deepcopy(dict(row))
        return None

    def chord_for_bar(self, bar: int) -> str:
        """Resolve one-based score bar to its authored harmony symbol."""

        return chord_for_bar_from_harmony(self.harmony, bar)

    def chord_at_tick(self, clock: Any, tick: int) -> str:
        """Resolve harmony at an exact score tick, including mid-bar changes."""

        tick = int(tick)
        best: tuple[int, str] | None = None
        for event in self.harmony.get("events", []) or []:
            if isinstance(event, Mapping):
                chord = str(event.get("chord", event.get("harmony", "")))
                if "tick" in event:
                    event_tick = int(event["tick"])
                elif event.get("at") is not None:
                    event_tick = int(clock.position_to_tick(event["at"]))
                else:
                    event_tick = int(clock.position_to_tick({"bar": int(event.get("bar", 1)), "beat": float(event.get("beat", 1))}))
            elif isinstance(event, (list, tuple)) and len(event) >= 2:
                chord = str(event[1])
                event_tick = int(clock.position_to_tick({"bar": int(event[0]), "beat": 1}))
            else:
                raise ValueError(f"invalid MusicIR v3 harmony event {event!r}")
            if chord and event_tick <= tick and (best is None or event_tick >= best[0]):
                best = (event_tick, chord)
        if best is not None:
            return best[1]
        position = clock.tick_to_position(tick)
        return self.chord_for_bar(int(position["bar"]))


def normalize_v3_score_graph(spec: Mapping[str, Any]) -> NormalizedScoreGraph:
    """Validate and normalize a canonical ``ambition.musicir.v3`` mapping."""

    source = copy.deepcopy(dict(spec))
    score_id = str(source.get("id", "")).strip()
    if not score_id:
        raise ValueError("MusicIR v3 score needs a stable top-level `id`")
    ppq = int((source.get("timebase") or {}).get("ppq", source.get("ppq", 960)))
    if ppq <= 0:
        raise ValueError("MusicIR v3 timebase.ppq must be > 0")
    instruments = _copy_rows(source.get("instruments") or [], field="instruments")
    _require_unique_ids(
        [{"id": row.get("name")} for row in instruments],
        field="instrument names",
    )
    materials = _normalize_materials(source.get("materials"))
    parts = _copy_rows(source.get("parts") or [], field="parts")
    _require_unique_ids(parts, field="parts")
    for part_idx, part in enumerate(parts):
        part_id = str(part["id"])
        voices = _copy_rows(part.get("voices") or [], field=f"parts[{part_idx}].voices")
        _require_unique_ids(voices, field=f"part {part_id!r} voices")
        part["voices"] = voices
        for voice in voices:
            voice_id = str(voice["id"])
            clips_raw = voice.get("clips") or []
            if not isinstance(clips_raw, list):
                raise TypeError(f"MusicIR v3 voice {part_id}/{voice_id} clips must be a list")
            clips = [
                _normalize_clip(
                    clip,
                    path=f"part {part_id!r} voice {voice_id!r} clip[{idx}]",
                )
                for idx, clip in enumerate(clips_raw)
            ]
            _require_unique_ids(clips, field=f"voice {part_id}/{voice_id} clips")
            voice["clips"] = clips
            for clip in clips:
                if "use" in clip and str(clip["use"]) not in materials:
                    raise KeyError(
                        f"MusicIR v3 clip {clip['id']!r} references unknown material {clip['use']!r}"
                    )

    return NormalizedScoreGraph(
        score_id=score_id,
        seed=int(source.get("seed", 1)),
        ppq=ppq,
        meter=_normalize_meter(source.get("meter")),
        tempo=_normalize_tempo(source.get("tempo")),
        form=_copy_rows(source.get("form") or [], field="form"),
        end=copy.deepcopy(source.get("end")),
        instruments=instruments,
        harmony=normalize_v3_harmony(source.get("harmony")),
        key_context=_normalize_key(source.get("key")),
        materials=materials,
        parts=parts,
        source_spec=source,
    )


def authoring_graph_fingerprint(graph: NormalizedScoreGraph | Mapping[str, Any]) -> str:
    """Hash authoring structure including stable source ids and generator intent."""

    payload = graph.as_dict() if isinstance(graph, NormalizedScoreGraph) else copy.deepcopy(dict(graph))
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def fraction_to_ticks(value: Any, *, ppq: int) -> int:
    """Convert a v3 local musical duration to integer ticks.

    Integers remain exact ticks for DAW/import friendliness.  Fraction strings
    are fractions of a whole note (``1/4`` = quarter note).  ``{beats: N}``
    means quarter-note beats and ``{ticks: N}`` is explicit.
    """

    if isinstance(value, bool):
        raise TypeError("boolean is not a MusicIR duration")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, Mapping):
        if "ticks" in value:
            return int(value["ticks"])
        if "beats" in value:
            ticks = Fraction(str(value["beats"])) * ppq
        else:
            raise ValueError(f"unsupported MusicIR v3 local duration {value!r}")
    else:
        if isinstance(value, float):
            frac = Fraction(value).limit_denominator(15360)
        else:
            frac = Fraction(str(value))
        ticks = frac * (4 * ppq)
    if ticks.denominator != 1:
        raise ValueError(f"duration {value!r} is not exact at ppq={ppq}")
    return int(ticks)
