"""Pure semantic comparison helpers for Stem Lab's read-only inspector."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .music_timeline import MusicTimeline, TimelineDocument, TimelineNote, live_score_candidate


@dataclass(frozen=True)
class NoteChange:
    before: TimelineNote
    after: TimelineNote


@dataclass(frozen=True)
class StemDiffReport:
    group: str
    before_notes: tuple[TimelineNote, ...]
    after_notes: tuple[TimelineNote, ...]
    unchanged: tuple[TimelineNote, ...]
    changed: tuple[NoteChange, ...]
    removed: tuple[TimelineNote, ...]
    added: tuple[TimelineNote, ...]
    before_instruments: tuple[str, ...]
    after_instruments: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.changed or self.removed or self.added or self.before_instruments != self.after_instruments)


def _anchor(value: float | None, fallback: float) -> tuple[str, float]:
    if value is not None:
        return ("beat", round(float(value), 6))
    return ("time", round(float(fallback), 4))


def _slot_key(note: TimelineNote) -> tuple[Any, ...]:
    return (
        _anchor(note.start_beat, note.start_seconds),
        note.section,
        note.layer,
        note.layer_kind,
    )


def _semantic_key(note: TimelineNote) -> tuple[Any, ...]:
    return (
        _slot_key(note),
        _anchor(note.end_beat, note.end_seconds),
        int(note.pitch),
        int(note.velocity),
    )


def _sort_key(note: TimelineNote) -> tuple[Any, ...]:
    return (
        round(note.start_seconds, 6),
        note.section or "",
        note.layer or "",
        note.pitch,
        round(note.end_seconds, 6),
        note.velocity,
    )


def compare_stem_timelines(before: MusicTimeline, after: MusicTimeline, group: str) -> StemDiffReport:
    """Compare one rendered stem semantically, ignoring instrument identity for note equality.

    Instrument swaps are reported separately so changing a patch does not make
    an otherwise identical performance appear as a rewrite of every note.
    """
    before_notes = tuple(sorted((n for n in before.notes if n.group == group), key=_sort_key))
    after_notes = tuple(sorted((n for n in after.notes if n.group == group), key=_sort_key))

    after_exact: dict[tuple[Any, ...], deque[TimelineNote]] = defaultdict(deque)
    for note in after_notes:
        after_exact[_semantic_key(note)].append(note)

    unchanged: list[TimelineNote] = []
    remaining_before: list[TimelineNote] = []
    matched_after_ids: set[int] = set()
    for note in before_notes:
        bucket = after_exact.get(_semantic_key(note))
        if bucket:
            matched = bucket.popleft()
            unchanged.append(matched)
            matched_after_ids.add(id(matched))
        else:
            remaining_before.append(note)

    remaining_after = [note for note in after_notes if id(note) not in matched_after_ids]

    before_slots: dict[tuple[Any, ...], list[TimelineNote]] = defaultdict(list)
    after_slots: dict[tuple[Any, ...], list[TimelineNote]] = defaultdict(list)
    for note in remaining_before:
        before_slots[_slot_key(note)].append(note)
    for note in remaining_after:
        after_slots[_slot_key(note)].append(note)

    changed: list[NoteChange] = []
    removed: list[TimelineNote] = []
    added: list[TimelineNote] = []
    for slot in sorted(set(before_slots) | set(after_slots), key=repr):
        left = sorted(before_slots.get(slot, ()), key=_sort_key)
        right = sorted(after_slots.get(slot, ()), key=_sort_key)
        paired = min(len(left), len(right))
        for index in range(paired):
            changed.append(NoteChange(left[index], right[index]))
        removed.extend(left[paired:])
        added.extend(right[paired:])

    return StemDiffReport(
        group=group,
        before_notes=before_notes,
        after_notes=after_notes,
        unchanged=tuple(sorted(unchanged, key=_sort_key)),
        changed=tuple(changed),
        removed=tuple(sorted(removed, key=_sort_key)),
        added=tuple(sorted(added, key=_sort_key)),
        before_instruments=tuple(sorted({note.instrument for note in before_notes})),
        after_instruments=tuple(sorted({note.instrument for note in after_notes})),
    )


def score_source_for_version(version: Any) -> tuple[Path | None, bool]:
    """Return a score suitable for instrument inspection and whether it is immutable render provenance."""
    snapshot = getattr(version, "score_snapshot_path", None)
    if snapshot and Path(snapshot).is_file():
        return Path(snapshot).resolve(), True
    run_dir = getattr(version, "run_dir", None)
    if run_dir is None:
        return None, False
    candidate = live_score_candidate(Path(run_dir), str(getattr(version, "label", "")))
    return candidate, False


def _compact(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return str(value)


def instrument_definition_lines(version: Any, document: TimelineDocument | None, group: str) -> tuple[str, ...]:
    """Describe authored instrument definitions for one stem, with timeline fallback."""
    score_path, exact_score = score_source_for_version(version)
    if score_path is not None:
        try:
            spec = yaml.safe_load(score_path.read_text(encoding="utf8")) or {}
        except (OSError, yaml.YAMLError):
            spec = {}
        rows = spec.get("instruments", []) if isinstance(spec, Mapping) else []
        lines: list[str] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping) or str(row.get("group") or "") != group:
                    continue
                name = str(row.get("name") or "instrument")
                attrs = [
                    f"{key}={_compact(value)}"
                    for key, value in row.items()
                    if key not in {"name", "group"}
                ]
                suffix = ", ".join(attrs) if attrs else "no extra configuration"
                lines.append(f"{name}: {suffix}")
        if lines:
            provenance = "render snapshot" if exact_score else "live source fallback"
            return tuple([f"[{provenance}]", *lines])

    if document is None:
        return ("No instrument metadata available.",)
    names = sorted({note.instrument for note in document.timeline.notes if note.group == group})
    if not names:
        return ("No instrument metadata available.",)
    return tuple(["[expanded note timeline only]", *names])


def format_note(note: TimelineNote) -> str:
    start = f"beat {note.start_beat:.3f}" if note.start_beat is not None else f"{note.start_seconds:.3f}s"
    return f"{start}: {note.note} vel {note.velocity} ({note.layer or '-'})"
