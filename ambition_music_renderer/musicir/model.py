"""Canonical compiled-score representation shared by render consumers."""

from __future__ import annotations

import copy
import dataclasses as dc
import hashlib
import json
from typing import Any, Iterable, Mapping

import pretty_midi


COMPILED_SCORE_SCHEMA = "ambition.compiled_score.v1"


@dc.dataclass
class CompiledScore:
    """Semantic result of compiling either MusicIR frontend.

    ``PrettyMIDI`` remains the synthesis representation during the migration,
    but it no longer has to be the semantic message bus.  New consumers should
    read ``note_events``, ``instrument_specs``, ``groups``, ``sections``, and
    ``exact_metadata`` from this object.  Legacy private PrettyMIDI attributes
    remain attached until downstream callers have migrated and tests prove that
    removing them is safe.
    """

    source_schema: str | None
    canonical_schema: str
    normalized_spec: dict[str, Any]
    pm: pretty_midi.PrettyMIDI
    groups: dict[str, str]
    sections: list[dict[str, Any]]
    instrument_specs: dict[str, dict[str, Any]]
    note_events: list[dict[str, Any]]
    exact_metadata: dict[str, Any] | None = None
    normalization_warnings: tuple[str, ...] = ()

    def attach_legacy_metadata(self) -> None:
        """Populate compatibility attributes used by pre-migration consumers."""

        self.pm._ambition_note_events = self.note_events  # type: ignore[attr-defined]
        self.pm._ambition_instrument_specs = copy.deepcopy(self.instrument_specs)  # type: ignore[attr-defined]
        if self.exact_metadata is not None:
            self.pm._ambition_exact_score = copy.deepcopy(self.exact_metadata)  # type: ignore[attr-defined]

    def legacy_tuple(self) -> tuple[pretty_midi.PrettyMIDI, dict[str, str], list[dict[str, Any]]]:
        """Return the historical ``build_score`` tuple without losing metadata."""

        self.attach_legacy_metadata()
        return self.pm, self.groups, self.sections

    @property
    def group_names(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.groups.values())))

    @property
    def duration_seconds(self) -> float:
        candidates = [float(section.get("end_seconds", 0.0) or 0.0) for section in self.sections]
        candidates.extend(float(event.get("end_time", 0.0) or 0.0) for event in self.note_events)
        return max(candidates or [0.0])

    def assert_internal_consistency(self) -> None:
        """Check cross-object invariants expected by every downstream consumer."""

        instrument_names = [str(inst.name) for inst in self.pm.instruments]
        if len(instrument_names) != len(set(instrument_names)):
            raise ValueError("compiled score contains duplicate MIDI instrument names")
        missing_groups = [name for name in instrument_names if name not in self.groups]
        if missing_groups:
            raise ValueError(f"compiled score instruments missing groups: {missing_groups}")
        missing_specs = [name for name in instrument_names if name not in self.instrument_specs]
        if missing_specs:
            raise ValueError(f"compiled score instruments missing specs: {missing_specs}")
        known = set(instrument_names)
        bad_events = sorted(
            {
                str(event.get("instrument"))
                for event in self.note_events
                if str(event.get("instrument")) not in known
            }
        )
        if bad_events:
            raise ValueError(f"compiled score events reference unknown instruments: {bad_events}")
        if self.sections:
            starts = [float(row.get("start_seconds", 0.0) or 0.0) for row in self.sections]
            if starts != sorted(starts):
                raise ValueError("compiled score sections are not ordered by start time")


def _round_float(value: Any) -> float:
    return round(float(value), 9)


def _midi_instrument_payload(inst: pretty_midi.Instrument) -> dict[str, Any]:
    """Audio-semantic MIDI payload, independent of insertion ordering at t=0."""

    notes = sorted(
        (
            _round_float(note.start),
            _round_float(note.end),
            int(note.pitch),
            int(note.velocity),
        )
        for note in inst.notes
    )
    controls = sorted(
        (_round_float(cc.time), int(cc.number), int(cc.value))
        for cc in inst.control_changes
    )
    bends = sorted(
        (_round_float(pb.time), int(pb.pitch))
        for pb in inst.pitch_bends
    )
    return {
        "name": str(inst.name),
        "program": int(inst.program),
        "is_drum": bool(inst.is_drum),
        "notes": notes,
        "control_changes": controls,
        "pitch_bends": bends,
    }


def _canonical_event(event: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(event))
    out.setdefault("event_type", "note")
    return out


def compiled_score_payload(compiled: CompiledScore) -> dict[str, Any]:
    """Return a deterministic semantic snapshot suitable for migration checks."""

    return {
        "schema": COMPILED_SCORE_SCHEMA,
        "canonical_schema": compiled.canonical_schema,
        "midi_resolution": int(compiled.pm.resolution),
        "instruments": [_midi_instrument_payload(inst) for inst in compiled.pm.instruments],
        "groups": dict(sorted(compiled.groups.items())),
        "instrument_specs": copy.deepcopy(compiled.instrument_specs),
        "sections": copy.deepcopy(compiled.sections),
        "note_events": [_canonical_event(event) for event in compiled.note_events],
        "exact_metadata": copy.deepcopy(compiled.exact_metadata),
    }


def compiled_score_fingerprint(compiled: CompiledScore) -> str:
    """Hash the complete synthesis/form contract of a compiled score."""

    text = json.dumps(
        compiled_score_payload(compiled),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(text.encode("utf8")).hexdigest()
