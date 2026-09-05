"""Pure model and probe renderer for the standalone Instrument Inspector.

The inspector is deliberately independent of Stem Lab.  It edits an isolated
instrument-definition document and optional group-processing document, then
renders disposable probes through the same instrument backend and post-process
code used by MusicIR renders.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

import numpy as np
import pretty_midi
import soundfile as sf
import yaml

from ._paths import agent_root
from .instrument_libraries import ALIASES, configured_sfz_roots, discover_sfz_files, resolve_sfz_reference
from .render.effects import post_process
from .render.group import render_group_audio
from .render.score_core import (
    CC_NUMBERS, DRUMS, GM_PROGRAMS, RenderContext, choose_soundfont, controller_number,
)
from .audit.sfz_measurement import sfz_regions, sfz_startup_cc
from .backends.sfizz_backend import sfz_key_span
from .render.score_events import add_instrument
from .render.score_theory import note_to_midi


_NEUTRAL_PROCESSING = {
    "gain_db": 0.0,
    "reverb_enabled": False,
    "stereo_width": 0.0,
    "limiter_enabled": False,
}

PITCHED_PROBE_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("major_scale", "Major scale + arpeggio"),
    ("minor_scale", "Natural minor scale + arpeggio"),
    ("single_note", "Single note"),
)

DRUM_PROBE_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("rock_groove", "Two-bar rock groove"),
    ("kit_essentials", "Kit essentials walk"),
    ("single_key", "Single drum key"),
)


def probe_template_options(*, is_drum: bool) -> tuple[tuple[str, str], ...]:
    return DRUM_PROBE_TEMPLATES if is_drum else PITCHED_PROBE_TEMPLATES


@dataclass(frozen=True)
class LibraryEntry:
    kind: str
    key: str
    label: str
    value: str
    group_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    request_hash: str
    outdir: Path
    dry_audio: Path
    processed_audio: Path
    report_path: Path
    report: dict[str, Any]


_GM_FAMILIES = (
    "Piano", "Chromatic percussion", "Organ", "Guitar", "Bass", "Strings",
    "Ensemble", "Brass", "Reed", "Pipe", "Synth lead", "Synth pad",
    "Synth effects", "Ethnic", "Percussive", "Sound effects",
)


def _gm_family(program: int) -> str:
    index = max(0, min(15, int(program) // 8))
    return _GM_FAMILIES[index]


def gm_library_entries() -> tuple[LibraryEntry, ...]:
    return tuple(
        LibraryEntry(
            "gm", name, name.replace("_", " ").title(), name,
            (_gm_family(program),),
        )
        for name, program in sorted(GM_PROGRAMS.items(), key=lambda item: item[1])
    )


def alias_library_entries() -> tuple[LibraryEntry, ...]:
    rows = []
    for name in sorted(ALIASES):
        parts = tuple(part.replace("_", " ").title() for part in name.split(".")[:-1])
        rows.append(LibraryEntry("sfz_alias", name, name.split(".")[-1].replace("_", " ").title(), name, parts))
    return tuple(rows)


def _installed_group_path(path: Path) -> tuple[str, ...]:
    path = path.resolve()
    candidates: list[tuple[int, Path, Path]] = []
    for root in configured_sfz_roots():
        try:
            resolved_root = root.expanduser().resolve()
            rel = path.relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        candidates.append((len(rel.parts), resolved_root, rel))
    if candidates:
        _depth, root, rel = min(candidates, key=lambda item: item[0])
        dirs = rel.parts[:-1]
        if dirs:
            return tuple(part.replace("_", " ").replace("-", " ") for part in dirs)
        return (root.name or str(root),)
    return tuple(part.replace("_", " ").replace("-", " ") for part in path.parts[-3:-1]) or ("Other",)


def installed_sfz_entries() -> tuple[LibraryEntry, ...]:
    return tuple(
        LibraryEntry("sfz_path", str(path), path.stem.replace("_", " ").replace("-", " "), str(path), _installed_group_path(path))
        for path in discover_sfz_files()
    )


def default_instrument_document() -> dict[str, Any]:
    return {
        "name": "audition",
        "group": "audition",
        "program": "acoustic_grand_piano",
        "volume": 100,
        "pan": 64,
        "expression": 100,
    }


def default_processing_document() -> dict[str, Any]:
    return dict(_NEUTRAL_PROCESSING)


def yaml_text(data: Mapping[str, Any]) -> str:
    return yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True, width=110)


def parse_yaml_mapping(text: str, *, label: str) -> dict[str, Any]:
    raw = yaml.safe_load(text) if text.strip() else {}
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} YAML must be a mapping")
    return raw


def normalize_instrument_document(data: Mapping[str, Any]) -> dict[str, Any]:
    inst = dict(data)
    inst["name"] = str(inst.get("name") or "audition")
    inst["group"] = str(inst.get("group") or "audition")
    if not inst.get("is_drum") and "program" not in inst:
        inst["program"] = "acoustic_grand_piano"
    return inst


def apply_library_entry(instrument: Mapping[str, Any], entry: LibraryEntry) -> dict[str, Any]:
    inst = normalize_instrument_document(instrument)
    if entry.kind == "gm":
        inst["program"] = entry.value
        inst.pop("instrument_backend", None)
        inst.pop("is_drum", None)
    elif entry.kind == "sfz_alias":
        inst.setdefault("program", "acoustic_grand_piano")
        inst["instrument_backend"] = {"kind": "sfz", "library_ref": entry.value}
        if entry.value.startswith("drums."):
            inst["is_drum"] = True
        elif entry.value.startswith(("guitar.", "bass.", "piano.", "strings.", "brass.", "winds.", "folk.")):
            inst.pop("is_drum", None)
    elif entry.kind == "sfz_path":
        inst.setdefault("program", "acoustic_grand_piano")
        inst["instrument_backend"] = {"kind": "sfz", "sfz": entry.value}
    else:
        raise ValueError(f"unsupported library entry kind {entry.kind!r}")
    return inst


def resolved_backend_path(instrument: Mapping[str, Any], *, base_dir: Path | None = None) -> Path | None:
    backend = instrument.get("instrument_backend")
    if not isinstance(backend, Mapping):
        return None
    explicit = backend.get("sfz") or backend.get("path") or backend.get("sfz_path") or backend.get("sfz_glob")
    library_ref = backend.get("library_ref") or backend.get("library")
    prefer = backend.get("prefer") or backend.get("prefer_keywords") or []
    return resolve_sfz_reference(
        explicit,
        library_ref=str(library_ref) if library_ref else None,
        prefer=[str(x) for x in prefer],
        base_dir=base_dir,
        roots=list(backend.get("library_roots") or []),
    )


def load_score_instrument(score_path: Path, instrument_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = yaml.safe_load(Path(score_path).read_text(encoding="utf8")) or {}
    if not isinstance(spec, dict):
        raise ValueError("score YAML is not a mapping")
    rows = spec.get("instruments") or []
    target = next(
        (dict(row) for row in rows if isinstance(row, dict) and str(row.get("name")) == instrument_name),
        None,
    )
    if target is None:
        raise ValueError(f"instrument {instrument_name!r} was not found")
    group = str(target.get("group") or target.get("name") or "audition")
    processing = dict((spec.get("group_postprocess") or {}).get(group) or {})
    if not processing:
        processing = default_processing_document()
    return target, processing


def score_instrument_names(score_path: Path) -> tuple[str, ...]:
    spec = yaml.safe_load(Path(score_path).read_text(encoding="utf8")) or {}
    rows = spec.get("instruments") or [] if isinstance(spec, dict) else []
    return tuple(str(row.get("name")) for row in rows if isinstance(row, dict) and row.get("name"))


def probe_request_hash(request: Mapping[str, Any]) -> str:
    payload = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str).encode("utf8")
    return hashlib.sha256(payload).hexdigest()[:20]


def build_probe_request(
    *,
    instrument: Mapping[str, Any],
    processing: Mapping[str, Any],
    probe: str | int,
    velocity: int = 108,
    duration_seconds: float = 1.4,
    backend: str = "auto",
    sample_rate: int = 48000,
    probe_template: str | None = None,
    tempo_bpm: float = 100.0,
) -> dict[str, Any]:
    return {
        "schema": "ambition.instrument_probe.v2",
        "instrument": normalize_instrument_document(instrument),
        "processing": dict(processing),
        "probe": probe,
        "probe_template": str(probe_template or ("single_key" if bool(instrument.get("is_drum")) else "single_note")),
        "velocity": max(1, min(127, int(velocity))),
        "duration_seconds": max(0.05, min(12.0, float(duration_seconds))),
        "tempo_bpm": max(30.0, min(260.0, float(tempo_bpm))),
        "backend": str(backend),
        "sample_rate": int(sample_rate),
    }


def _probe_pitch(value: str | int) -> int:
    if isinstance(value, str) and not value.strip().isdigit():
        pitch = note_to_midi(value.strip())
    else:
        pitch = int(value)
    return max(0, min(127, pitch))


def _probe_events(request: Mapping[str, Any], *, is_drum: bool) -> list[tuple[int, float, float, int]]:
    """Return canonical audition events as (pitch, start, end, velocity)."""
    velocity = int(request.get("velocity", 108))
    duration = float(request.get("duration_seconds", 1.4))
    bpm = float(request.get("tempo_bpm", 100.0))
    quarter = 60.0 / bpm
    eighth = quarter / 2.0
    start0 = 0.20
    template = str(request.get("probe_template") or ("single_key" if is_drum else "single_note"))
    probe = request.get("probe", "crash" if is_drum else "C4")

    if is_drum:
        def drum(name: str) -> int:
            return int(DRUMS[name])

        if template == "single_key":
            if isinstance(probe, str) and probe in DRUMS:
                pitch = drum(probe)
            else:
                pitch = max(0, min(127, int(probe)))
            return [(pitch, start0, start0 + min(duration, 0.30), velocity)]

        if template == "kit_essentials":
            names = ("kick", "snare", "closed_hat", "open_hat", "crash", "ride", "floor_tom", "mid_tom", "high_tom")
            return [
                (drum(name), start0 + i * quarter * 0.75, start0 + i * quarter * 0.75 + 0.12, velocity)
                for i, name in enumerate(names)
            ]

        if template != "rock_groove":
            raise ValueError(f"unknown drum probe template {template!r}")
        events: list[tuple[int, float, float, int]] = []
        # A deliberately plain two-bar backbeat: crash on the entrance, eighth-note
        # closed hats, kick on 1/3 with a small second-bar pickup, snare on 2/4.
        events.append((drum("crash"), start0, start0 + 0.16, min(127, velocity + 8)))
        for eighth_index in range(16):
            t = start0 + eighth_index * eighth
            events.append((drum("closed_hat"), t, t + 0.08, max(1, velocity - (24 if eighth_index % 2 else 16))))
        for beat in (0.0, 2.0, 4.0, 6.0, 6.5):
            t = start0 + beat * quarter
            events.append((drum("kick"), t, t + 0.10, velocity))
        for beat in (1.0, 3.0, 5.0, 7.0):
            t = start0 + beat * quarter
            events.append((drum("snare"), t, t + 0.10, min(127, velocity + 2)))
        return events

    root = _probe_pitch(probe)
    if template == "single_note":
        return [(root, start0, start0 + duration, velocity)]
    if template == "major_scale":
        scale = (0, 2, 4, 5, 7, 9, 11, 12, 11, 9, 7, 5, 4, 2, 0)
        arpeggio = (0, 4, 7, 12, 7, 4, 0)
    elif template == "minor_scale":
        scale = (0, 2, 3, 5, 7, 8, 10, 12, 10, 8, 7, 5, 3, 2, 0)
        arpeggio = (0, 3, 7, 12, 7, 3, 0)
    else:
        raise ValueError(f"unknown pitched probe template {template!r}")

    events = []
    t = start0
    note_len = min(duration, eighth * 0.88)
    for interval in scale:
        pitch = max(0, min(127, root + interval))
        events.append((pitch, t, t + note_len, velocity))
        t += eighth
    t += eighth
    for index, interval in enumerate(arpeggio):
        pitch = max(0, min(127, root + interval))
        final = index == len(arpeggio) - 1
        length = max(note_len, quarter * 1.5) if final else note_len
        events.append((pitch, t, t + length, velocity))
        t += eighth if not final else length
    return events




def _instrument_initial_cc(instrument: Mapping[str, Any]) -> dict[int, int]:
    """Return the MIDI CC state MusicIR sends at time zero for an instrument."""
    values = {
        7: int(instrument.get("volume", 100)),
        10: int(instrument.get("pan", 64)),
        11: int(instrument.get("expression", 100)),
    }
    for key, cc_num in CC_NUMBERS.items():
        if key in instrument and key not in {"volume", "pan", "expression"}:
            values[int(cc_num)] = int(instrument[key])
    for key, value in dict(instrument.get("controls") or {}).items():
        values[controller_number(key)] = int(value)
    return {cc: max(0, min(127, value)) for cc, value in values.items()}


def _sfz_bound(region: Mapping[str, Any], low: str, high: str, default_low: int, default_high: int) -> tuple[int, int]:
    key = region.get("key") if low == "lokey" else None
    lo = region.get(low, key if key is not None else default_low)
    hi = region.get(high, key if key is not None else default_high)
    try:
        return int(lo), int(hi)
    except (TypeError, ValueError):
        return default_low, default_high


def _cc_ranges(region: Mapping[str, Any]) -> dict[int, tuple[int, int]]:
    ranges: dict[int, list[int]] = {}
    for key, value in region.items():
        match = re.fullmatch(r"(lo|hi)cc(\d+)", str(key))
        if match is None or not isinstance(value, (int, float)):
            continue
        cc = int(match.group(2))
        pair = ranges.setdefault(cc, [0, 127])
        pair[0 if match.group(1) == "lo" else 1] = int(value)
    return {cc: (pair[0], pair[1]) for cc, pair in ranges.items()}


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    merged: list[list[int]] = []
    for lo, hi in sorted((max(0, lo), min(127, hi)) for lo, hi in ranges):
        if not merged or lo > merged[-1][1] + 1:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    return [(lo, hi) for lo, hi in merged]


def _suggest_for_ranges(ranges: list[tuple[int, int]], current: int) -> int | None:
    if not ranges:
        return None
    if any(lo <= current <= hi for lo, hi in ranges):
        return current
    # Prefer the nearest allowed interval, but choose its center rather than a
    # boundary because SFZ authors commonly use adjacent controller zones.
    lo, hi = min(ranges, key=lambda pair: min(abs(current - pair[0]), abs(current - pair[1])))
    return int(round((lo + hi) / 2.0))



def sfz_probe_preflight_from_census(
    request: Mapping[str, Any],
    census_row: Mapping[str, Any],
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Cheap SFZ preflight using a generated :mod:`instrument_usage_census` row.

    The census stores compact activation zones instead of every expanded SFZ
    region.  This is accurate for the key/velocity/controller gates needed by
    the inspector and avoids reparsing a large third-party program on every UI
    click.  The render subprocess still runs :func:`sfz_probe_preflight` as the
    authoritative check before synthesis.
    """
    instrument = normalize_instrument_document(request.get("instrument") or {})
    path = resolved_backend_path(instrument, base_dir=base_dir)
    backend = instrument.get("instrument_backend")
    if not isinstance(backend, Mapping) or path is None:
        return {"kind": "non_sfz", "status": "ok", "summary": "GM / non-SFZ backend; region preflight does not apply."}

    startup = {int(k): int(v) for k, v in dict(census_row.get("startup_cc") or {}).items()}
    authored = _instrument_initial_cc(instrument)
    controls = dict(startup)
    controls.update(authored)
    events = _probe_events(request, is_drum=bool(instrument.get("is_drum")))
    zones = [zone for zone in census_row.get("activation_zones") or [] if isinstance(zone, Mapping)]

    event_rows: list[dict[str, Any]] = []
    blocker_ranges: dict[int, list[tuple[int, int]]] = {}
    blocker_events: dict[int, int] = {}

    def zone_bounds(zone: Mapping[str, Any], key: str, default: tuple[int, int]) -> tuple[int, int]:
        raw = zone.get(key)
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            try:
                return int(raw[0]), int(raw[1])
            except (TypeError, ValueError):
                pass
        return default

    def zone_gates(zone: Mapping[str, Any]) -> dict[int, tuple[int, int]]:
        out: dict[int, tuple[int, int]] = {}
        for cc, raw in dict(zone.get("controllers") or {}).items():
            if isinstance(raw, (list, tuple)) and len(raw) == 2:
                try:
                    out[int(cc)] = (int(raw[0]), int(raw[1]))
                except (TypeError, ValueError):
                    pass
        return out

    for pitch, _start, _end, velocity in events:
        pitch_candidates: list[Mapping[str, Any]] = []
        candidates: list[Mapping[str, Any]] = []
        matched: list[Mapping[str, Any]] = []
        for zone in zones:
            klo, khi = zone_bounds(zone, "key_range", (0, 127))
            if not klo <= pitch <= khi:
                continue
            pitch_candidates.append(zone)
            vlo, vhi = zone_bounds(zone, "velocity_range", (1, 127))
            if not vlo <= velocity <= vhi:
                continue
            candidates.append(zone)
            gates = zone_gates(zone)
            if all(lo <= int(controls.get(cc, 0)) <= hi for cc, (lo, hi) in gates.items()):
                matched.append(zone)

        event_blockers: dict[int, list[tuple[int, int]]] = {}
        if candidates and not matched:
            all_ccs = sorted({cc for zone in candidates for cc in zone_gates(zone)})
            for cc in all_ccs:
                allowed: list[tuple[int, int]] = []
                every_zone_constrains = True
                for zone in candidates:
                    gates = zone_gates(zone)
                    if cc not in gates:
                        every_zone_constrains = False
                        break
                    allowed.append(gates[cc])
                merged = _merge_ranges(allowed)
                current = int(controls.get(cc, 0))
                if every_zone_constrains and merged and not any(lo <= current <= hi for lo, hi in merged):
                    event_blockers[cc] = merged
                    blocker_ranges.setdefault(cc, []).extend(merged)
                    blocker_events[cc] = blocker_events.get(cc, 0) + 1

        matched_regions = sum(int(zone.get("region_count") or 1) for zone in matched)
        event_rows.append({
            "pitch": int(pitch),
            "note": pretty_midi.note_number_to_name(int(pitch)),
            "velocity": int(velocity),
            "pitch_candidates": len(pitch_candidates),
            "velocity_candidates": len(candidates),
            "matched_regions": matched_regions,
            "blocking_cc": {str(cc): [list(pair) for pair in ranges] for cc, ranges in event_blockers.items()},
        })

    matched_events = sum(1 for row in event_rows if row["matched_regions"] > 0)
    suggestions: dict[int, int] = {}
    blockers: list[dict[str, Any]] = []
    for cc, raw_ranges in sorted(blocker_ranges.items()):
        ranges = _merge_ranges(raw_ranges)
        current = int(controls.get(cc, 0))
        suggestion = _suggest_for_ranges(ranges, current)
        if suggestion is not None:
            suggestions[cc] = suggestion
        blockers.append({
            "cc": cc,
            "current": current,
            "allowed_ranges": [list(pair) for pair in ranges],
            "suggested": suggestion,
            "affected_events": blocker_events.get(cc, 0),
        })

    if not zones:
        status = "no_regions"
        summary = f"Usage census contains zero playable regions for {path.name}."
    elif events and matched_events == 0:
        if blockers:
            details = ", ".join(
                f"CC{item['cc']}={item['current']} needs "
                + "/".join(f"{lo}-{hi}" for lo, hi in item["allowed_ranges"])
                for item in blockers
            )
            status = "blocked"
            summary = f"0/{len(events)} probe notes match the cached SFZ activation map; controller gate blocks them ({details})."
        elif not any(row["velocity_candidates"] for row in event_rows):
            status = "out_of_range"
            summary = f"0/{len(events)} probe notes match the cached SFZ key/velocity map."
        else:
            status = "no_match"
            summary = f"0/{len(events)} probe notes match an active cached SFZ zone."
    elif matched_events < len(events):
        status = "partial"
        summary = f"{matched_events}/{len(events)} probe notes match cached active SFZ zones; some notes may be dropped."
    else:
        status = "ok"
        summary = f"All {len(events)} probe notes match the cached SFZ activation map."

    return {
        "kind": "sfz",
        "source": "usage_census",
        "status": status,
        "summary": summary,
        "path": str(path),
        "key_span": census_row.get("key_span"),
        "region_count": int(census_row.get("region_count") or 0),
        "probe_event_count": len(events),
        "matched_event_count": matched_events,
        "startup_cc": {str(k): v for k, v in sorted(startup.items())},
        "authored_cc": {str(k): v for k, v in sorted(authored.items())},
        "effective_cc": {str(k): v for k, v in sorted(controls.items())},
        "blocking_controllers": blockers,
        "suggested_controls": {str(k): v for k, v in sorted(suggestions.items())},
        "candidate_sample_references": int(census_row.get("sample_references") or 0),
        "candidate_samples_found": int(census_row.get("samples_found") or 0),
        "active_sample_references": 0,
        "active_samples_found": 0,
        "events": event_rows,
    }


def sfz_probe_preflight(request: Mapping[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    """Explain whether an SFZ can respond to the current canonical probe.

    This is intentionally semantic rather than an audio heuristic.  It expands
    the SFZ regions, applies key/velocity/controller gates, checks referenced
    sample files, and reports controller values which would unblock an otherwise
    playable patch.  The actual renderer remains authoritative.
    """
    instrument = normalize_instrument_document(request.get("instrument") or {})
    path = resolved_backend_path(instrument, base_dir=base_dir)
    backend = instrument.get("instrument_backend")
    if not isinstance(backend, Mapping) or path is None:
        return {"kind": "non_sfz", "status": "ok", "summary": "GM / non-SFZ backend; region preflight does not apply."}

    regions = sfz_regions(path)
    startup = sfz_startup_cc(path)
    authored = _instrument_initial_cc(instrument)
    controls = dict(startup)
    controls.update(authored)
    events = _probe_events(request, is_drum=bool(instrument.get("is_drum")))
    event_rows: list[dict[str, Any]] = []
    blocker_ranges: dict[int, list[tuple[int, int]]] = {}
    blocker_events: dict[int, int] = {}
    candidate_samples: set[str] = set()
    candidate_samples_found: set[str] = set()
    active_samples: set[str] = set()
    active_samples_found: set[str] = set()

    for pitch, _start, _end, velocity in events:
        pitch_candidates = []
        candidates = []
        matched = []
        for region in regions:
            lo, hi = _sfz_bound(region, "lokey", "hikey", 0, 127)
            if not lo <= pitch <= hi:
                continue
            pitch_candidates.append(region)
            vlo, vhi = _sfz_bound(region, "lovel", "hivel", 1, 127)
            if not vlo <= velocity <= vhi:
                continue
            candidates.append(region)
            cc_ok = True
            for cc, (clo, chi) in _cc_ranges(region).items():
                actual = int(controls.get(cc, 0))
                if not clo <= actual <= chi:
                    cc_ok = False
                    break
            if cc_ok:
                matched.append(region)

        # A controller is a useful blocker only when *every* pitch/velocity
        # candidate constrains it away from the current value.  This avoids
        # suggesting articulation CCs when an unconstrained alternative exists.
        event_blockers: dict[int, list[tuple[int, int]]] = {}
        if candidates and not matched:
            all_ccs = sorted({cc for region in candidates for cc in _cc_ranges(region)})
            for cc in all_ccs:
                allowed: list[tuple[int, int]] = []
                every_region_constrains = True
                for region in candidates:
                    ranges = _cc_ranges(region)
                    if cc not in ranges:
                        every_region_constrains = False
                        break
                    allowed.append(ranges[cc])
                merged = _merge_ranges(allowed)
                actual = int(controls.get(cc, 0))
                if every_region_constrains and merged and not any(lo <= actual <= hi for lo, hi in merged):
                    event_blockers[cc] = merged
                    blocker_ranges.setdefault(cc, []).extend(merged)
                    blocker_events[cc] = blocker_events.get(cc, 0) + 1

        for region in candidates:
            sample = region.get("sample")
            if sample:
                candidate_samples.add(str(sample))
                sample_path = region.get("sample_path")
                if sample_path and Path(str(sample_path)).is_file():
                    candidate_samples_found.add(str(sample))
        for region in matched:
            sample = region.get("sample")
            if sample:
                active_samples.add(str(sample))
                sample_path = region.get("sample_path")
                if sample_path and Path(str(sample_path)).is_file():
                    active_samples_found.add(str(sample))

        event_rows.append({
            "pitch": int(pitch),
            "note": pretty_midi.note_number_to_name(int(pitch)),
            "velocity": int(velocity),
            "pitch_candidates": len(pitch_candidates),
            "velocity_candidates": len(candidates),
            "matched_regions": len(matched),
            "blocking_cc": {str(cc): [list(pair) for pair in ranges] for cc, ranges in event_blockers.items()},
        })

    matched_events = sum(1 for row in event_rows if row["matched_regions"] > 0)
    suggestions: dict[int, int] = {}
    blockers: list[dict[str, Any]] = []
    for cc, raw_ranges in sorted(blocker_ranges.items()):
        ranges = _merge_ranges(raw_ranges)
        current = int(controls.get(cc, 0))
        suggestion = _suggest_for_ranges(ranges, current)
        if suggestion is not None:
            suggestions[cc] = suggestion
        blockers.append({
            "cc": cc,
            "current": current,
            "allowed_ranges": [list(pair) for pair in ranges],
            "suggested": suggestion,
            "affected_events": blocker_events.get(cc, 0),
        })

    if not regions:
        status = "no_regions"
        summary = f"SFZ parsed with zero playable regions: {path.name}"
    elif events and matched_events == 0:
        if blockers:
            status = "blocked"
            details = ", ".join(
                f"CC{item['cc']}={item['current']} needs "
                + "/".join(f"{lo}-{hi}" for lo, hi in item["allowed_ranges"])
                for item in blockers
            )
            summary = f"0/{len(events)} probe notes match any SFZ region; controller gate blocks them ({details})."
        elif not any(row["velocity_candidates"] for row in event_rows):
            status = "out_of_range"
            summary = f"0/{len(events)} probe notes match the SFZ key/velocity map."
        else:
            status = "no_match"
            summary = f"0/{len(events)} probe notes match an active SFZ region."
    elif active_samples and not active_samples_found:
        status = "missing_samples"
        summary = (
            f"Probe notes match SFZ regions, but none of the {len(active_samples)} referenced active samples "
            "were found on disk."
        )
    elif matched_events < len(events):
        status = "partial"
        summary = f"{matched_events}/{len(events)} probe notes match active SFZ regions; some notes will be dropped."
    else:
        status = "ok"
        summary = f"All {len(events)} probe notes match at least one active SFZ region."

    span = sfz_key_span(str(path))
    return {
        "kind": "sfz",
        "status": status,
        "summary": summary,
        "path": str(path),
        "key_span": list(span) if span else None,
        "region_count": len(regions),
        "probe_event_count": len(events),
        "matched_event_count": matched_events,
        "startup_cc": {str(k): v for k, v in sorted(startup.items())},
        "authored_cc": {str(k): v for k, v in sorted(authored.items())},
        "effective_cc": {str(k): v for k, v in sorted(controls.items())},
        "blocking_controllers": blockers,
        "suggested_controls": {str(k): v for k, v in sorted(suggestions.items())},
        "candidate_sample_references": len(candidate_samples),
        "candidate_samples_found": len(candidate_samples_found),
        "active_sample_references": len(active_samples),
        "active_samples_found": len(active_samples_found),
        "events": event_rows,
    }


def format_probe_diagnostics(diagnostic: Mapping[str, Any]) -> str:
    """Compact human-readable SFZ preflight for the Qt inspector."""
    if diagnostic.get("kind") != "sfz":
        return str(diagnostic.get("summary") or "No SFZ region diagnostics.")
    lines = [str(diagnostic.get("summary") or "SFZ preflight")]
    path = diagnostic.get("path")
    if path:
        lines.append(f"SFZ: {path}")
    span = diagnostic.get("key_span")
    if isinstance(span, list) and len(span) == 2:
        lines.append(
            f"Parsed regions: {diagnostic.get('region_count', 0)} · key span MIDI {span[0]}–{span[1]} "
            f"({pretty_midi.note_number_to_name(int(span[0]))}–{pretty_midi.note_number_to_name(int(span[1]))})"
        )
    else:
        lines.append(f"Parsed regions: {diagnostic.get('region_count', 0)}")
    blockers = diagnostic.get("blocking_controllers") or []
    for item in blockers:
        ranges = " or ".join(f"{lo}–{hi}" for lo, hi in item.get("allowed_ranges") or [])
        suggestion = item.get("suggested")
        tail = f"; suggested CC{item['cc']}={suggestion}" if suggestion is not None else ""
        lines.append(
            f"BLOCKED: CC{item['cc']} is {item['current']}; matching regions require {ranges}" + tail
        )
    active_refs = int(diagnostic.get("active_sample_references") or 0)
    active_found = int(diagnostic.get("active_samples_found") or 0)
    if active_refs:
        lines.append(f"Active-region samples found on disk: {active_found}/{active_refs}")
    candidate_refs = int(diagnostic.get("candidate_sample_references") or 0)
    candidate_found = int(diagnostic.get("candidate_samples_found") or 0)
    if not active_refs and candidate_refs:
        lines.append(f"Pitch/velocity candidate samples found on disk: {candidate_found}/{candidate_refs}")
    startup = diagnostic.get("startup_cc") or {}
    if startup:
        lines.append("SFZ startup CCs: " + ", ".join(f"CC{k}={v}" for k, v in startup.items()))
    return "\n".join(lines)


def apply_probe_control_suggestions(instrument: Mapping[str, Any], diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with suggested controller gates added to ``controls``."""
    out = dict(instrument)
    suggestions = diagnostic.get("suggested_controls") or {}
    controls = dict(out.get("controls") or {})
    for key, value in suggestions.items():
        controls[int(key)] = int(value)
    if controls:
        out["controls"] = controls
    return out


def _make_probe_pm(request: Mapping[str, Any]) -> tuple[pretty_midi.PrettyMIDI, dict[str, str], str]:
    inst_spec = normalize_instrument_document(request["instrument"])
    name = str(inst_spec["name"])
    group = str(inst_spec["group"])
    bpm = float(request.get("tempo_bpm", 100.0))
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm, resolution=960)
    ctx = RenderContext(
        spec={"instruments": [inst_spec]},
        sample_rate=int(request["sample_rate"]),
        bpm=bpm,
        beats_per_bar=4.0,
        rng=np.random.default_rng(0),
        pm=pm,
        instruments={},
        groups={},
        section_starts={},
        motifs={},
    )
    add_instrument(ctx, inst_spec)
    inst = ctx.instruments[name]
    for pitch, start, end, velocity in _probe_events(request, is_drum=bool(inst_spec.get("is_drum"))):
        inst.notes.append(pretty_midi.Note(velocity=velocity, pitch=pitch, start=start, end=end))
    # render_group_audio reads the original instrument definitions from this
    # metadata so it can resolve SFZ/procedural backends and mix_gain_db.
    pm._ambition_instrument_specs = ctx.instrument_specs  # type: ignore[attr-defined]
    return pm, ctx.groups, group


def render_probe(request: Mapping[str, Any], *, output_root: Path | None = None) -> ProbeResult:
    request = dict(request)
    request_hash = probe_request_hash(request)
    root = Path(output_root or (agent_root() / "instrument_inspector" / "probes"))
    outdir = root / request_hash
    outdir.mkdir(parents=True, exist_ok=True)
    dry_path = outdir / "dry.wav"
    processed_path = outdir / "processed.wav"
    report_path = outdir / "report.json"
    request_path = outdir / "request.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True), encoding="utf8")
    if dry_path.is_file() and processed_path.is_file() and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf8"))
        return ProbeResult(request_hash, outdir, dry_path, processed_path, report_path, report)

    preflight = sfz_probe_preflight(request, base_dir=Path.cwd())
    if preflight.get("status") in {"blocked", "out_of_range", "no_regions", "no_match", "missing_samples"}:
        raise ValueError(format_probe_diagnostics(preflight))

    pm, groups, group = _make_probe_pm(request)
    sample_rate = int(request.get("sample_rate", 48000))
    backend = str(request.get("backend", "auto"))
    instrument = normalize_instrument_document(request["instrument"])
    resolved = resolved_backend_path(instrument)
    with tempfile.TemporaryDirectory(prefix="ambition-instrument-probe-") as temp:
        audio = render_group_audio(
            pm,
            groups,
            group,
            backend,
            choose_soundfont(None),
            sample_rate,
            Path(temp),
            minimum_duration=max(float(pm.get_end_time()) + 0.8, float(request.get("duration_seconds", 1.4)) + 0.8),
            bpm=100.0,
            base_dir=Path.cwd(),
            # Instrument Inspector must audition the selected backend exactly.
            # A GM fallback would make a broken SFZ appear healthy.
            render_cfg={"strict_backends": True},
        )
    dry = np.asarray(audio, dtype=np.float32)
    # Preserve MusicIR semantics exactly: the processing YAML is passed to
    # post_process as-authored. New inspector documents explicitly include
    # neutral settings; a loaded score group therefore keeps the renderer's
    # ordinary defaults for any fields it omits.
    processing = dict(request.get("processing") or {})
    processed = post_process(dry, sample_rate, processing, base_dir=Path.cwd())
    sf.write(dry_path, dry, sample_rate, subtype="PCM_16")
    sf.write(processed_path, processed, sample_rate, subtype="PCM_16")

    def stats(arr: np.ndarray) -> dict[str, float | bool | None]:
        if not arr.size:
            return {"peak": 0.0, "rms": 0.0, "peak_dbfs": None, "rms_dbfs": None, "effectively_silent": True}
        peak = float(np.max(np.abs(arr)))
        rms = float(np.sqrt(np.mean(np.square(arr), dtype=np.float64)))
        import math
        return {
            "peak": peak,
            "rms": rms,
            "peak_dbfs": 20.0 * math.log10(peak) if peak > 0 else None,
            "rms_dbfs": 20.0 * math.log10(rms) if rms > 0 else None,
            "effectively_silent": peak < 10 ** (-70.0 / 20.0),
        }

    report = {
        "schema": "ambition.instrument_probe_result.v2",
        "request_hash": request_hash,
        "resolved_backend_path": str(resolved) if resolved else None,
        "dry_audio": str(dry_path),
        "processed_audio": str(processed_path),
        "dry": stats(dry),
        "processed": stats(processed),
        "preflight": preflight,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf8")
    return ProbeResult(request_hash, outdir, dry_path, processed_path, report_path, report)


def render_probe_request_file(path: Path) -> ProbeResult:
    request = json.loads(Path(path).read_text(encoding="utf8"))
    if not isinstance(request, dict):
        raise ValueError("probe request JSON must be an object")
    return render_probe(request)


def write_export_document(
    path: Path,
    *,
    instrument: Mapping[str, Any],
    processing: Mapping[str, Any],
) -> Path:
    inst = normalize_instrument_document(instrument)
    group = str(inst.get("group") or inst.get("name") or "audition")
    payload = {
        "instrument": inst,
        "group_postprocess": {group: dict(processing)},
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text(payload), encoding="utf8")
    return path

EFFECT_TEMPLATES: dict[str, dict[str, Any]] = {
    "Gain": {"kind": "pedalboard", "effects": [{"effect": "gain", "gain_db": 3.0}]},
    "Distortion": {"kind": "pedalboard", "effects": [{"effect": "distortion", "drive_db": 12.0}]},
    "Compressor": {"kind": "pedalboard", "effects": [{"effect": "compressor", "threshold_db": -20.0, "ratio": 3.0, "attack_ms": 10.0, "release_ms": 100.0}]},
    "Reverb": {"kind": "pedalboard", "effects": [{"effect": "reverb", "room_size": 0.5, "wet_level": 0.25, "dry_level": 0.75}]},
    "Delay": {"kind": "pedalboard", "effects": [{"effect": "delay", "delay_ms": 120.0, "feedback": 0.25, "mix": 0.18}]},
    "LV2": {"kind": "lv2proc", "plugin_uri": "REPLACE_WITH_LV2_URI", "wet_mix": 1.0, "params": {}},
    "VST3": {"kind": "vst3", "plugin": "REPLACE_WITH_PLUGIN.vst3", "wet_mix": 1.0, "params": {}},
    "Command / Guitarix / NAM": {"kind": "command", "command": ["REPLACE_WITH_COMMAND", "{input}", "{output}"], "wet_mix": 1.0},
}


def append_effect_template(processing: Mapping[str, Any], template_name: str) -> dict[str, Any]:
    if template_name not in EFFECT_TEMPLATES:
        raise KeyError(template_name)
    import copy
    out = dict(processing)
    chain = list(out.get("effect_chain") or [])
    chain.append(copy.deepcopy(EFFECT_TEMPLATES[template_name]))
    out["effect_chain"] = chain
    return out
